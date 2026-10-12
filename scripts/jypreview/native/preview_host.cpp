// preview_host.cpp — isolated Jianying DLL preview host (IPC v1).
//
// Loads the version-locked videoeditor.dll from the installed JianyingPro
// directory only after verifying version + SHA-256. It fails PlayerWin closed
// until its private configuration, project-open, and frame-output contracts
// are evidenced; FrameReader source frames use the length-prefixed JSON
// protocol (RGBA bytes follow the metadata).
// Failure modes are explicit {code,message,detail}; there is no silent
// fallback to any other renderer, and no JianyingPro UI is ever started.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <bcrypt.h>

#include <io.h>
#include <fcntl.h>

#include <cctype>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#pragma comment(lib, "bcrypt.lib")

namespace {

void logf(const char* fmt, ...) {
  va_list args;
  va_start(args, fmt);
  vfprintf(stderr, fmt, args);
  va_end(args);
  fflush(stderr);
}

// --------------------------------------------------------------------------
// Minimal JSON helpers (only the scalar fields this host consumes).
// --------------------------------------------------------------------------
std::string json_escape(const std::string& in) {
  std::string out;
  out.reserve(in.size() + 8);
  for (unsigned char c : in) {
    switch (c) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (c < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof(buf), "\\u%04x", c);
          out += buf;
        } else {
          out += static_cast<char>(c);
        }
    }
  }
  return out;
}

void append_utf8(uint32_t cp, std::string* out) {
  if (cp < 0x80) {
    *out += static_cast<char>(cp);
  } else if (cp < 0x800) {
    *out += static_cast<char>(0xC0 | (cp >> 6));
    *out += static_cast<char>(0x80 | (cp & 0x3F));
  } else if (cp < 0x10000) {
    *out += static_cast<char>(0xE0 | (cp >> 12));
    *out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
    *out += static_cast<char>(0x80 | (cp & 0x3F));
  } else {
    *out += static_cast<char>(0xF0 | (cp >> 18));
    *out += static_cast<char>(0x80 | ((cp >> 12) & 0x3F));
    *out += static_cast<char>(0x80 | ((cp >> 6) & 0x3F));
    *out += static_cast<char>(0x80 | (cp & 0x3F));
  }
}

// Reads one JSON string literal. `*i` must point at the opening quote and is
// advanced past the closing quote. Only RFC 8259 escapes are accepted
// (\" \\ \/ \b \f \n \r \t \uXXXX with a valid surrogate pair), raw control
// characters are rejected, and the input must end with the closing quote.
bool read_json_string(const std::string& json, size_t* i, std::string* out) {
  if (*i >= json.size() || json[*i] != '"') return false;
  size_t k = *i + 1;
  out->clear();
  while (k < json.size() && json[k] != '"') {
    if (static_cast<unsigned char>(json[k]) < 0x20) return false;  // raw control char
    if (json[k] == '\\') {
      if (k + 1 >= json.size()) return false;
      char n = json[k + 1];
      if (n == 'u') {
        size_t j = k + 2;
        uint32_t cp = 0;
        int digits = 0;
        for (; digits < 4; ++digits, ++j) {
          if (j >= json.size()) return false;
          char h = json[j];
          int d;
          if (h >= '0' && h <= '9') d = h - '0';
          else if (h >= 'a' && h <= 'f') d = h - 'a' + 10;
          else if (h >= 'A' && h <= 'F') d = h - 'A' + 10;
          else return false;  // \u must be followed by exactly four hex digits
          cp = cp * 16 + static_cast<uint32_t>(d);
        }
        if (cp >= 0xD800 && cp <= 0xDBFF) {
          // High surrogate: a matching low surrogate must follow.
          if (j + 6 > json.size() || json[j] != '\\' || json[j + 1] != 'u') return false;
          size_t lo_i = j + 2;
          uint32_t lo = 0;
          int low_digits = 0;
          for (; low_digits < 4; ++low_digits, ++lo_i) {
            if (lo_i >= json.size()) return false;
            char h = json[lo_i];
            int d;
            if (h >= '0' && h <= '9') d = h - '0';
            else if (h >= 'a' && h <= 'f') d = h - 'a' + 10;
            else if (h >= 'A' && h <= 'F') d = h - 'A' + 10;
            else return false;
            lo = lo * 16 + static_cast<uint32_t>(d);
          }
          if (lo < 0xDC00 || lo > 0xDFFF) return false;
          cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
          j = lo_i;
        } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
          return false;  // lone low surrogate
        }
        append_utf8(cp, out);
        k = j;
        continue;
      }
      if (n == '"') *out += '"';
      else if (n == '\\') *out += '\\';
      else if (n == '/') *out += '/';
      else if (n == 'b') *out += '\b';
      else if (n == 'f') *out += '\f';
      else if (n == 'n') *out += '\n';
      else if (n == 'r') *out += '\r';
      else if (n == 't') *out += '\t';
      else return false;  // invalid escape sequence (e.g. \x, \q)
      k += 2;
    } else {
      *out += json[k++];
    }
  }
  if (k >= json.size()) return false;  // unterminated string literal
  *i = k + 1;
  return true;
}

// find_scalar/find_string/find_int were removed on review: a depth-blind
// search is exactly the confusion this host must not have. Envelope fields use
// scan_object_level(); payload fields use payload_string()/payload_int().

// --------------------------------------------------------------------------
// Scoped JSON readers
//
// The IPC envelope (protocol_version / request_id / generation / op) is read
// with scan_object_level(), which walks exactly one object level and never
// descends, so a key that only exists inside `payload` can never drive the
// host. Payload fields use payload_string()/payload_int(), which read the
// payload object at its own top level — never the whole request.
// --------------------------------------------------------------------------

struct JsonField {
  std::string key;
  std::string value;  // decoded for strings, raw token otherwise
  std::string raw;    // raw token (quoted for strings)
  std::string span;   // raw span for object/array values
  bool is_string = false;
  bool scalar = false;
};

// Strict JSON number (RFC 8259): -?(0|[1-9]\d*)(\.\d+)?([eE][+-]?\d+)?
// No leading '+', no leading zeros, no bare '.', no trailing '.'.
bool is_json_number(const std::string& text) {
  size_t i = 0;
  if (i < text.size() && text[i] == '-') ++i;
  if (i >= text.size() || text[i] < '0' || text[i] > '9') return false;
  if (text[i] == '0') {
    ++i;
  } else {
    while (i < text.size() && text[i] >= '0' && text[i] <= '9') ++i;
  }
  if (i < text.size() && text[i] == '.') {
    ++i;
    if (i >= text.size() || text[i] < '0' || text[i] > '9') return false;
    while (i < text.size() && text[i] >= '0' && text[i] <= '9') ++i;
  }
  if (i < text.size() && (text[i] == 'e' || text[i] == 'E')) {
    ++i;
    if (i < text.size() && (text[i] == '+' || text[i] == '-')) ++i;
    if (i >= text.size() || text[i] < '0' || text[i] > '9') return false;
    while (i < text.size() && text[i] >= '0' && text[i] <= '9') ++i;
  }
  return i == text.size();
}

// A primitive JSON value: number, true, false or null — nothing else. Tokens
// such as `not_json`, `NaN`, `Infinity` or `0x10` are rejected.
bool is_json_literal(const std::string& text) {
  return text == "true" || text == "false" || text == "null" || is_json_number(text);
}

// Parses and validates one complete JSON value starting at json[i] (skipping
// leading whitespace). On success *i is advanced past the value.
//
// Unlike a bracket counter this validates the *contents*: nested objects and
// arrays are walked recursively, so `"payload":{"a":not_json}` is rejected
// even though its braces balance.
bool parse_value_strict(const std::string& json, size_t* i) {
  auto ws = [&]() {
    while (*i < json.size() && std::isspace(static_cast<unsigned char>(json[*i]))) ++(*i);
  };
  ws();
  if (*i >= json.size()) return false;
  const char c = json[*i];
  if (c == '{') {
    ++(*i);
    ws();
    if (*i < json.size() && json[*i] == '}') {
      ++(*i);
      return true;
    }
    for (;;) {
      ws();
      if (*i >= json.size() || json[*i] != '"') return false;
      std::string key;
      if (!read_json_string(json, i, &key)) return false;
      ws();
      if (*i >= json.size() || json[*i] != ':') return false;
      ++(*i);
      if (!parse_value_strict(json, i)) return false;
      ws();
      if (*i >= json.size()) return false;
      if (json[*i] == ',') {
        ++(*i);
        continue;
      }
      if (json[*i] == '}') {
        ++(*i);
        return true;
      }
      return false;
    }
  }
  if (c == '[') {
    ++(*i);
    ws();
    if (*i < json.size() && json[*i] == ']') {
      ++(*i);
      return true;
    }
    for (;;) {
      if (!parse_value_strict(json, i)) return false;
      ws();
      if (*i >= json.size()) return false;
      if (json[*i] == ',') {
        ++(*i);
        continue;
      }
      if (json[*i] == ']') {
        ++(*i);
        return true;
      }
      return false;
    }
  }
  if (c == '"') {
    std::string text;
    return read_json_string(json, i, &text);
  }
  const size_t start = *i;
  while (*i < json.size() && json[*i] != ',' && json[*i] != '}' && json[*i] != ']' &&
         !std::isspace(static_cast<unsigned char>(json[*i])))
    ++(*i);
  if (*i == start) return false;
  return is_json_literal(json.substr(start, *i - start));
}

// Scans exactly one JSON object level (nested values are not extracted, but
// their *contents* are validated by parse_value_strict — a balanced document
// with invalid JSON inside is still rejected). Returns false on malformed input.
bool scan_object_level(const std::string& json, std::vector<JsonField>* out) {
  size_t i = 0;
  auto ws = [&]() {
    while (i < json.size() && std::isspace(static_cast<unsigned char>(json[i]))) ++i;
  };
  ws();
  if (i >= json.size() || json[i] != '{') return false;
  ++i;
  ws();
  if (i < json.size() && json[i] == '}') {
    ++i;
    ws();
    return i == json.size();
  }
  for (;;) {
    ws();
    if (i >= json.size() || json[i] != '"') return false;
    JsonField field;
    if (!read_json_string(json, &i, &field.key)) return false;
    ws();
    if (i >= json.size() || json[i] != ':') return false;
    ++i;
    ws();
    if (i >= json.size()) return false;
    const size_t vstart = i;
    if (json[i] == '"') {
      if (!read_json_string(json, &i, &field.value)) return false;
      field.raw = json.substr(vstart, i - vstart);
      field.is_string = true;
      field.scalar = true;
    } else if (json[i] == '{' || json[i] == '[') {
      size_t vend = i;
      if (!parse_value_strict(json, &vend)) return false;
      field.span = json.substr(vstart, vend - vstart);
      i = vend;
      field.scalar = false;
    } else {
      size_t j = i;
      while (j < json.size() && json[j] != ',' && json[j] != '}' && json[j] != ']' &&
             !std::isspace(static_cast<unsigned char>(json[j])))
        ++j;
      if (j == i) return false;
      field.raw = field.value = json.substr(i, j - i);
      if (!is_json_literal(field.value)) return false;  // reject not_json / NaN / 0x10
      field.scalar = true;
      i = j;
    }
    out->push_back(field);
    ws();
    if (i >= json.size()) return false;
    if (json[i] == ',') {
      ++i;
      continue;
    }
    if (json[i] == '}') {
      ++i;
      break;
    }
    return false;
  }
  ws();
  return i == json.size();
}

// First occurrence of `key` at the scanned level plus its occurrence count.
const JsonField* find_field(const std::vector<JsonField>& fields, const std::string& key, int* count) {
  const JsonField* first = nullptr;
  *count = 0;
  for (const JsonField& field : fields) {
    if (field.key == key) {
      if (!first) first = &field;
      ++*count;
    }
  }
  return first;
}

bool parse_ll(const std::string& text, long long* out) {
  if (text.empty()) return false;
  char* end = nullptr;
  const long long value = std::strtoll(text.c_str(), &end, 10);
  if (!end || *end != 0) return false;
  *out = value;
  return true;
}

// Payload lookups: the payload object's own top level only, so a same-named
// envelope key or a deeper nested key can never be picked up by mistake.
// `count` reports how often the key occurred, so callers can reject duplicates
// on consumed fields instead of silently taking the first match.
std::string payload_string(const std::vector<JsonField>& payload, const std::string& key,
                           const std::string& fallback, int* count) {
  const JsonField* field = find_field(payload, key, count);
  if (!field || !field->is_string) return fallback;
  return field->value;
}

long long payload_int(const std::vector<JsonField>& payload, const std::string& key,
                      long long fallback, int* count) {
  const JsonField* field = find_field(payload, key, count);
  if (!field) return fallback;
  long long value = 0;
  return parse_ll(field->value, &value) ? value : fallback;
}

// --------------------------------------------------------------------------
// IPC v1 framing
// --------------------------------------------------------------------------
bool read_exact(void* buf, size_t size) {
  auto* p = static_cast<unsigned char*>(buf);
  size_t done = 0;
  while (done < size) {
    size_t n = fread(p + done, 1, size - done, stdin);
    if (n == 0) return false;
    done += n;
  }
  return true;
}

// Protocol stream: the DLL prints its own banners to the process stdout when
// it is loaded, so the real IPC stdout handle is captured here and fd1 is
// re-pointed at stderr before any library loads.
HANDLE g_protocol_out = nullptr;

void write_exact(const void* buf, size_t size) {
  if (g_protocol_out && g_protocol_out != INVALID_HANDLE_VALUE) {
    const char* p = static_cast<const char*>(buf);
    size_t done = 0;
    while (done < size) {
      DWORD wrote = 0;
      DWORD chunk = static_cast<DWORD>(size - done > 0x7fffffff ? 0x7fffffff : size - done);
      if (!WriteFile(g_protocol_out, p + done, chunk, &wrote, nullptr) || wrote == 0) return;
      done += wrote;
    }
    return;
  }
  fwrite(buf, 1, size, stdout);
  fflush(stdout);
}

void send_json(const std::string& body) {
  unsigned len = static_cast<unsigned>(body.size());
  unsigned char header[4] = {
      static_cast<unsigned char>(len & 0xff), static_cast<unsigned char>((len >> 8) & 0xff),
      static_cast<unsigned char>((len >> 16) & 0xff), static_cast<unsigned char>((len >> 24) & 0xff)};
  write_exact(header, 4);
  write_exact(body.data(), body.size());
}

struct ErrorSpec {
  std::string code;
  std::string message;
  std::string detail;
};

constexpr long long kProtocolVersion = 1;

// IPC envelope: read from the top level only, every field exactly once.
struct Envelope {
  bool ok = false;
  std::string request_id = "0";  // raw JSON token, echoed verbatim
  long long generation = 0;
  std::string op;
  std::string payload;  // raw payload object span ("" when absent)
  bool has_payload = false;
  ErrorSpec error;
};

// Validates the envelope before any op runs. Nested copies of envelope keys
// inside `payload` are ignored by construction (scan_object_level never
// descends), so payload {"op":"close"} can never close a ping, and a missing
// or duplicated envelope field is rejected instead of silently resolved.
Envelope parse_envelope(const std::string& raw) {
  Envelope env;
  std::vector<JsonField> top;
  if (!scan_object_level(raw, &top)) {
    env.error = {"bad_request", "request must be one well-formed top-level JSON object",
                 "malformed_request"};
    return env;
  }

  int count = 0;
  // request_id is read first so later rejections can still echo the caller's
  // id — the Python client checks request_id before the error code.
  const JsonField* request_id = find_field(top, "request_id", &count);
  if (count == 0) {
    env.error = {"bad_request", "missing envelope field: request_id", "request_id"};
    return env;
  }
  if (count > 1) {
    env.error = {"bad_request", "duplicate envelope field: request_id", "request_id"};
    return env;
  }
  if (request_id->is_string) {
    env.request_id = "\"" + json_escape(request_id->value) + "\"";
  } else if (request_id->value == "true" || request_id->value == "false" ||
             request_id->value == "null" || is_json_number(request_id->value)) {
    env.request_id = request_id->value;
  } else {
    env.error = {"bad_request", "invalid envelope field: request_id must be a string or number",
                 "request_id"};
    return env;
  }

  count = 0;
  const JsonField* proto = find_field(top, "protocol_version", &count);
  if (count == 0) {
    env.error = {"unsupported_protocol_version", "protocol_version is missing",
                 "protocol_version=-1 supported=" + std::to_string(kProtocolVersion)};
    return env;
  }
  if (count > 1) {
    env.error = {"bad_request", "duplicate envelope field: protocol_version", "protocol_version"};
    return env;
  }
  long long version = -1;
  const std::string proto_raw = proto->raw.empty() ? std::string("<non-scalar>") : proto->raw;
  if (proto->is_string || !parse_ll(proto->value, &version) || version != kProtocolVersion) {
    env.error = {"unsupported_protocol_version", "unsupported protocol_version",
                 "protocol_version=" + proto_raw + " supported=" + std::to_string(kProtocolVersion)};
    return env;
  }

  count = 0;
  const JsonField* generation = find_field(top, "generation", &count);
  if (count == 0) {
    env.error = {"bad_request", "missing envelope field: generation", "generation"};
    return env;
  }
  if (count > 1) {
    env.error = {"bad_request", "duplicate envelope field: generation", "generation"};
    return env;
  }
  if (generation->is_string || !parse_ll(generation->value, &env.generation)) {
    env.error = {"bad_request", "invalid envelope field: generation must be an integer", "generation"};
    return env;
  }

  count = 0;
  const JsonField* op = find_field(top, "op", &count);
  if (count == 0) {
    env.error = {"bad_request", "missing envelope field: op", "op"};
    return env;
  }
  if (count > 1) {
    env.error = {"bad_request", "duplicate envelope field: op", "op"};
    return env;
  }
  if (!op->is_string) {
    env.error = {"bad_request", "invalid envelope field: op must be a string", "op"};
    return env;
  }
  env.op = op->value;

  count = 0;
  const JsonField* payload = find_field(top, "payload", &count);
  if (count > 1) {
    env.error = {"bad_request", "duplicate envelope field: payload", "payload"};
    return env;
  }
  if (count == 1) {
    if (payload->scalar) {
      env.error = {"bad_request", "invalid envelope field: payload must be a JSON object", "payload"};
      return env;
    }
    env.payload = payload->span;
    env.has_payload = true;
  }
  env.ok = true;
  return env;
}
// Set by the close op: the response is flushed, then the main loop stops and
// the short-lived host exits normally — private DLL destructors are never
// invoked.
bool g_close_and_exit = false;

std::string make_meta(const std::string& request_id_token, long long generation, const std::string& op, bool ok) {
  std::string meta = "{\"protocol_version\":" + std::to_string(kProtocolVersion) +
                     ",\"request_id\":" + request_id_token +
                     ",\"generation\":" + std::to_string(generation) + ",\"op\":\"" + json_escape(op) +
                     "\",\"ok\":" + (ok ? "true" : "false");
  return meta;
}

void send_ok(const std::string& request_id, long long generation, const std::string& op,
             const std::string& extra_fields) {
  send_json(make_meta(request_id, generation, op, true) + extra_fields + "}");
}

void send_error(const std::string& request_id, long long generation, const std::string& op,
                const ErrorSpec& err, bool dll_loaded) {
  std::string body = make_meta(request_id, generation, op, false);
  body += ",\"error\":{\"code\":\"" + json_escape(err.code) + "\",\"message\":\"" + json_escape(err.message) +
          "\",\"detail\":{\"reason\":\"" + json_escape(err.detail) + "\",\"dll_loaded\":" +
          (dll_loaded ? "true" : "false") + "}}}";
  send_json(body);
}

void send_frame(const std::string& request_id, long long generation, const std::string& op, long long pts_us,
                unsigned width, unsigned height, const unsigned char* pixels) {
  unsigned long long byte_length = static_cast<unsigned long long>(width) * height * 4ull;
  std::string meta = make_meta(request_id, generation, op, true);
  meta += ",\"pts_us\":" + std::to_string(pts_us) + ",\"width\":" + std::to_string(width) +
          ",\"height\":" + std::to_string(height) + ",\"format\":\"RGBA\",\"byte_length\":" +
          std::to_string(byte_length) + "}";
  send_json(meta);
  write_exact(pixels, static_cast<size_t>(byte_length));
}

// --------------------------------------------------------------------------
// Fail-closed verification: version, SHA-256 (Windows CNG), dependency load
// --------------------------------------------------------------------------
std::string basename_of(const std::string& path) {
  size_t slash = path.find_last_of("/\\");
  return slash == std::string::npos ? path : path.substr(slash + 1);
}

std::string dir_of(const std::string& path) {
  size_t slash = path.find_last_of("/\\");
  return slash == std::string::npos ? std::string() : path.substr(0, slash);
}

bool sha256_hex(const std::wstring& path, std::string* hex, std::string* why) {
  HANDLE file = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING,
                            FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    *why = "CreateFile failed: " + std::to_string(GetLastError());
    return false;
  }
  bool ok = false;
  do {
    LARGE_INTEGER size{};
    if (!GetFileSizeEx(file, &size) || size.QuadPart <= 0 || size.QuadPart > 1024ll * 1024 * 1024) {
      *why = "unexpected file size";
      break;
    }
    std::vector<unsigned char> data(static_cast<size_t>(size.QuadPart));
    DWORD got = 0;
    if (!ReadFile(file, data.data(), static_cast<DWORD>(data.size()), &got, nullptr) ||
        got != data.size()) {
      *why = "ReadFile failed: " + std::to_string(GetLastError());
      break;
    }
    // Windows CNG one-shot hash: BCryptCreateHash is rejected with
    // STATUS_INVALID_PARAMETER on this host, BCryptHash is the supported entry.
    BCRYPT_ALG_HANDLE alg = nullptr;
    NTSTATUS status = BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, nullptr, 0);
    if (status) {
      *why = "BCryptOpenAlgorithmProvider status=" + std::to_string(static_cast<long>(status));
      break;
    }
    unsigned char digest[32] = {};
    status = BCryptHash(alg, nullptr, 0, data.data(), static_cast<ULONG>(data.size()), digest,
                        static_cast<ULONG>(sizeof(digest)));
    BCryptCloseAlgorithmProvider(alg, 0);
    if (status) {
      *why = "BCryptHash status=" + std::to_string(static_cast<long>(status));
      break;
    }
    char hexbuf[65] = {};
    for (int i = 0; i < 32; ++i) std::snprintf(hexbuf + i * 2, 3, "%02x", digest[i]);
    *hex = hexbuf;
    ok = true;
  } while (false);
  CloseHandle(file);
  return ok;
}

std::string to_lower(std::string s) {
  for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
  return s;
}

struct HostState {
  std::string install_dir;
  std::string expect_version;
  std::string expect_sha256;
  std::string dll_path;
  HMODULE dll = nullptr;
  bool verified = false;
  std::string verify_code;
  std::string verify_message;
  std::string verify_detail;

  // reader path state
  void* reader = nullptr;
  void* reader_object = nullptr;  // crafted callback object storage
  long long last_pts = -1;
  long long best_pts = -1;
  long long best_dist = -1;
  unsigned width = 0;
  unsigned height = 0;
  std::vector<unsigned char> best_pixels;
  bool stop_batch = false;
  long long target_pts = -1;
  double source_fps = 0.0;
  std::string source_path;
};

HostState g_state;

// --------------------------------------------------------------------------
// Verification + load
// --------------------------------------------------------------------------
bool verify_and_load(ErrorSpec* err) {
  if (g_state.verified) {
    if (!g_state.verify_code.empty()) {
      err->code = g_state.verify_code;
      err->message = g_state.verify_message;
      err->detail = g_state.verify_detail;
      return false;
    }
    return true;
  }
  g_state.verified = true;

  std::string dir_name = basename_of(g_state.install_dir);
  if (dir_name != g_state.expect_version) {
    g_state.verify_code = "version_mismatch";
    g_state.verify_message = "install directory version does not match the expected version";
    g_state.verify_detail = "install_dir_version=" + dir_name + " expected=" + g_state.expect_version;
    err->code = g_state.verify_code;
    err->message = g_state.verify_message;
    err->detail = g_state.verify_detail;
    return false;
  }

  g_state.dll_path = g_state.install_dir + "\\videoeditor.dll";
  DWORD attrs = GetFileAttributesA(g_state.dll_path.c_str());
  if (attrs == INVALID_FILE_ATTRIBUTES) {
    g_state.verify_code = "dll_missing";
    g_state.verify_message = "videoeditor.dll not found in the install directory";
    g_state.verify_detail = g_state.dll_path;
    err->code = g_state.verify_code;
    err->message = g_state.verify_message;
    err->detail = g_state.verify_detail;
    return false;
  }

  std::wstring wpath(g_state.dll_path.begin(), g_state.dll_path.end());
  std::string digest, why;
  if (!sha256_hex(wpath, &digest, &why)) {
    g_state.verify_code = "dll_hash_unreadable";
    g_state.verify_message = "cannot hash videoeditor.dll";
    g_state.verify_detail = why;
    err->code = g_state.verify_code;
    err->message = g_state.verify_message;
    err->detail = g_state.verify_detail;
    return false;
  }
  if (to_lower(digest) != to_lower(g_state.expect_sha256)) {
    g_state.verify_code = "dll_hash_mismatch";
    g_state.verify_message = "videoeditor.dll SHA-256 does not match the pinned build";
    g_state.verify_detail = "actual=" + digest + " expected=" + g_state.expect_sha256;
    err->code = g_state.verify_code;
    err->message = g_state.verify_message;
    err->detail = g_state.verify_detail;
    return false;
  }

  SetDllDirectoryA(g_state.install_dir.c_str());
  g_state.dll = LoadLibraryExA(g_state.dll_path.c_str(), nullptr, LOAD_WITH_ALTERED_SEARCH_PATH);
  if (!g_state.dll) {
    DWORD code = GetLastError();
    bool missing = (code == ERROR_MOD_NOT_FOUND || code == ERROR_DLL_NOT_FOUND || code == ERROR_PROC_NOT_FOUND);
    g_state.verify_code = missing ? "dependency_missing" : "dll_load_failed";
    g_state.verify_message = missing ? "videoeditor.dll or one of its dependencies is missing"
                                     : "LoadLibraryEx failed";
    g_state.verify_detail = "win32_error=" + std::to_string(code) + " install_dir=" + g_state.install_dir;
    err->code = g_state.verify_code;
    err->message = g_state.verify_message;
    err->detail = g_state.verify_detail;
    return false;
  }
  logf("dll_loaded base=%p sha256=%s\n", g_state.dll, digest.c_str());
  return true;
}

// --------------------------------------------------------------------------
// Reader path: lvve::FrameReaderWin arbitrary-time source frames
// --------------------------------------------------------------------------
using CreateFrameReader = void* (__cdecl*)();

// Frame result layout recovered from FrameReaderWin slot-2 callback arguments:
//   +0x18 path ptr, +0x20 status, +0x28 pts_us, +0x30 frame_duration_us,
//   +0x38 RGBA ptr, +0x40 byte size, +0x44 stride, +0x48 width, +0x4c height
struct FakeBase {
  void** vtable;
  int id;
  int called;
};

FakeBase g_reader_obj = {};
void* g_reader_vtable[8] = {};
void* g_slot2_ret = reinterpret_cast<void*>(1);

bool readable_ptr(const void* p) {
  uintptr_t v = reinterpret_cast<uintptr_t>(p);
  if (v < 0x10000) return false;
  MEMORY_BASIC_INFORMATION mbi{};
  if (!VirtualQuery(p, &mbi, sizeof(mbi))) return false;
  return mbi.State == MEM_COMMIT &&
         (mbi.Protect & (PAGE_READWRITE | PAGE_READONLY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE)) != 0;
}

void capture_frame(const void* a1) {
  if (!readable_ptr(a1)) return;
  const unsigned char* b = static_cast<const unsigned char*>(a1);
  unsigned bytes = *reinterpret_cast<const unsigned*>(b + 0x40);
  unsigned width = *reinterpret_cast<const unsigned*>(b + 0x48);
  unsigned height = *reinterpret_cast<const unsigned*>(b + 0x4c);
  void* pixels = *reinterpret_cast<void* const*>(b + 0x38);
  long long pts = *reinterpret_cast<const long long*>(b + 0x28);
  long long fd = *reinterpret_cast<const long long*>(b + 0x30);
  if (!readable_ptr(pixels) || width == 0 || height == 0 || width > 8192 || height > 8192) return;
  if (bytes != width * height * 4) return;
  if (pts < 0) return;  // negative/invalid PTS: never record (stale-frame guard)
  g_state.last_pts = pts;
  long long dist = pts - (g_state.target_pts >= 0 ? g_state.target_pts : 0);
  long long ad = dist < 0 ? -dist : dist;
  if (g_state.target_pts < 0 || ad < (g_state.best_dist < 0 ? std::numeric_limits<long long>::max()
                                                            : g_state.best_dist)) {
    g_state.best_dist = g_state.target_pts < 0 ? -1 : ad;
    g_state.best_pts = pts;
    g_state.width = width;
    g_state.height = height;
    g_state.best_pixels.assign(static_cast<const unsigned char*>(pixels),
                               static_cast<const unsigned char*>(pixels) + bytes);
  }
  if (fd > 0 && g_state.target_pts >= 0 && ad * 2 <= fd) {
    g_state.stop_batch = true;
    g_slot2_ret = nullptr;  // tell the DLL to stop consuming the batch
  }
}

template <int N>
void* slot_fn(void* self, void* a1, void* a2, void* a3) {
  (void)a2;
  (void)a3;
  if (N == 2) capture_frame(a1);
  if (N == 2) return g_slot2_ret;
  return self;
}

LONG WINAPI log_reader_av(EXCEPTION_POINTERS* ex) {
  const auto* r = ex->ExceptionRecord;
  const auto* c = ex->ContextRecord;
  HMODULE mod = nullptr;
  wchar_t wpath[MAX_PATH] = {};
  char utf8[MAX_PATH * 4] = {};
  if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                         reinterpret_cast<LPCWSTR>(r->ExceptionAddress), &mod) &&
      GetModuleFileNameW(mod, wpath, MAX_PATH)) {
    WideCharToMultiByte(CP_UTF8, 0, wpath, -1, utf8, sizeof(utf8), nullptr, nullptr);
  }
  logf("reader_av code=0x%08lx addr=%p module=%s rva=0x%llx av_addr=%p rcx=%p rdx=%p r8=%p r9=%p\n",
       r->ExceptionCode, r->ExceptionAddress, utf8,
       mod ? static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(r->ExceptionAddress) -
                                             reinterpret_cast<uintptr_t>(mod))
           : 0ull,
       r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2
           ? reinterpret_cast<void*>(r->ExceptionInformation[1])
           : nullptr,
       reinterpret_cast<void*>(c->Rcx), reinterpret_cast<void*>(c->Rdx), reinterpret_cast<void*>(c->R8),
       reinterpret_cast<void*>(c->R9));
  return EXCEPTION_EXECUTE_HANDLER;
}

long long pts_of_frame(long long frame) {  // C0308-style 60000/1001 grid
  return (frame * 1001LL * 1000 + 30) / 60;
}

long long frame_of_time(long long t_us) {
  return (t_us * 60000LL) / (1001LL * 1000000LL);
}

struct RequestFn {
  using Type = int(__fastcall*)(void*, const std::string&, const std::vector<std::int64_t>&, int, int, bool,
                                const void*, bool);
};

int call_slot1(RequestFn::Type fn, void* reader, const std::string* path,
               const std::vector<std::int64_t>* times, const void* cb) {
  __try {
    return fn(reader, *path, *times, 1920, 1080, true, cb, true);
  } __except (log_reader_av(GetExceptionInformation())) {
    return -1;
  }
}

bool open_reader(ErrorSpec* err) {
  auto create = reinterpret_cast<CreateFrameReader>(
      GetProcAddress(g_state.dll, "?create@FrameReader@lvve@@SAPEAV12@XZ"));
  if (!create) {
    err->code = "init_rejected";
    err->message = "FrameReader::create export missing";
    err->detail = "videoeditor.dll build does not expose the frame reader factory";
    return false;
  }
  g_reader_obj.vtable = g_reader_vtable;
  g_reader_obj.id = 1;
  for (int i = 0; i < 8; ++i) g_reader_vtable[i] = nullptr;
  g_reader_vtable[0] = reinterpret_cast<void*>(&slot_fn<0>);
  g_reader_vtable[1] = reinterpret_cast<void*>(&slot_fn<1>);
  g_reader_vtable[2] = reinterpret_cast<void*>(&slot_fn<2>);
  g_reader_vtable[3] = reinterpret_cast<void*>(&slot_fn<3>);
  g_reader_vtable[4] = reinterpret_cast<void*>(&slot_fn<4>);
  g_reader_vtable[5] = reinterpret_cast<void*>(&slot_fn<5>);
  g_reader_vtable[6] = reinterpret_cast<void*>(&slot_fn<6>);
  g_reader_vtable[7] = reinterpret_cast<void*>(&slot_fn<7>);
  void* reader = create();
  if (!reader) {
    err->code = "init_rejected";
    err->message = "FrameReader::create returned null";
    err->detail = "the DLL refused to create a frame reader in this process";
    return false;
  }
  g_state.reader = reader;
  return true;
}

bool render_reader_at(long long t_us, ErrorSpec* err) {
  void** vtable = *static_cast<void***>(g_state.reader);
  auto request = reinterpret_cast<RequestFn::Type>(vtable[1]);
  if (!request) {
    err->code = "frame_unavailable";
    err->message = "FrameReaderWin slot 1 missing";
    err->detail = "unexpected vtable layout";
    return false;
  }
  long long frame = frame_of_time(t_us);
  long long key = frame - (frame % 250);
  if (key < 0) key = 0;
  g_state.target_pts = pts_of_frame(frame);
  g_state.best_dist = -1;
  g_state.best_pts = -1;
  g_state.stop_batch = false;
  g_slot2_ret = reinterpret_cast<void*>(1);

  std::vector<std::int64_t> times;
  // One duplicate of the GOP anchor lets the first request perform the seek;
  // every later entry moves the decoder forward by exactly one frame, and
  // one trailing entry covers the observed one-frame delivery lag.
  times.push_back(pts_of_frame(key));
  for (long long j = key; j <= frame + 1; ++j) times.push_back(pts_of_frame(j));

  unsigned char cb[64];
  std::memset(cb, 0, sizeof(cb));
  *reinterpret_cast<void**>(cb + 0) = &g_reader_obj;
  *reinterpret_cast<void**>(cb + 0x38) = &g_reader_obj;

  std::string path = g_state.source_path;
  int rc = call_slot1(request, g_state.reader, &path, &times, cb);
  logf("slot1_rc=%d last_pts=%lld best_pts=%lld target=%lld bytes=%zu\n", rc, g_state.last_pts,
       g_state.best_pts, g_state.target_pts, g_state.best_pixels.size());
  if (rc < 0) {
    err->code = "frame_unavailable";
    err->message = "FrameReaderWin request raised a structured exception or error code";
    err->detail = "slot1 rc=" + std::to_string(rc);
    return false;
  }
  if (g_state.best_pixels.empty() || g_state.best_pts < 0) {
    err->code = "frame_unavailable";
    err->message = "no frame with a valid pts was delivered for the requested time";
    err->detail = "deliveries=" + std::to_string(g_state.last_pts) + " target_pts=" +
                  std::to_string(g_state.target_pts) + " key_frame=" + std::to_string(key);
    return false;
  }
  long long dev = g_state.best_pts - g_state.target_pts;
  if (dev < 0) dev = -dev;
  if (dev > 16684) {
    err->code = "pts_out_of_range";
    err->message = "native decoder did not reach the requested time";
    err->detail = "pts=" + std::to_string(g_state.best_pts) + " requested_pts=" +
                  std::to_string(g_state.target_pts) + " deviation_us=" + std::to_string(dev) +
                  " key_frame=" + std::to_string(key) + " (decoder stalls after certain GOP anchors)";
    return false;
  }
  return true;
}

// --------------------------------------------------------------------------
// PlayerWin path: fail closed until a legal ABI contract is recovered
// --------------------------------------------------------------------------
// Evidence (temp/dll-native-preview/evidence.md section 2 and
// probes/initveabconfig-body.asm):
//  * InitVEAbConfig(cfg) dereferences [cfg+0xb70], i.e. a live config tree;
//    a zeroed config faults (0xc0000005, av_addr=0x0) at rva=0x156573b.
//  * 34 exports mentioning VEAdapterConfig were reviewed: the DLL exposes no
//    factory to construct VEAdapterConfig/VEGlobalConfig, and openSession
//    with a zeroed config faults at +0x8.
//  * PlayerWin's ctor
//    (??0PlayerWin@lvve@@QEAA@PEAXPEBUVEAdapterConfig@adapter@1@J@Z) requires
//    caller-provided storage ("this") whose contract is not evidenced;
//    draft_root/timeline_id have no recovered load path and no render op
//    (GetSpecificTimeImage) is wired.
// Fabricating a config or passing a null "this" would be guessing a private
// ABI, so no PlayerWin call is executed: the gate reports the blocker
// explicitly instead of AV-ing or falling back to another renderer.
bool open_player(const std::string& draft_root, const std::string& timeline_id, ErrorSpec* err) {
  err->code = "init_rejected";
  err->message = "PlayerWin initialization blocked: no legal ABI contract recovered";
  err->detail = "step=VEAdapterConfig-construction "
                "evidence=temp/dll-native-preview/evidence.md#2 draft_root=" + draft_root +
                " timeline_id=" + timeline_id + " render_path=not-wired";
  return false;
}

// --------------------------------------------------------------------------
// Dispatch
// --------------------------------------------------------------------------
// Per-request frame state: cleared before every render_at so a failed or
// near-zero seek can never emit a previous request's pixels.
void clear_frame_state() {
  g_state.best_pixels.clear();
  g_state.width = 0;
  g_state.height = 0;
  g_state.best_pts = -1;
  g_state.best_dist = -1;
  g_state.last_pts = -1;
  g_state.stop_batch = false;
  g_state.target_pts = -1;
}

// Lifecycle: at most one render path is attached. `open` detaches the current
// path *before* any attempt, so a failed path switch leaves the host with no
// render path instead of silently serving the previous source's frames.
// Private DLL destructors are never called (same rule as close): a detached
// object is reclaimed at process exit.
void clear_render_state() {
  clear_frame_state();
  g_state.reader = nullptr;
  g_state.source_path.clear();
}

void handle(const std::string& raw) {
  // Envelope first: protocol_version/request_id/generation/op are read from
  // the top level only and must each appear exactly once; `payload` is scanned
  // separately, so a nested op/generation/request_id can never drive the host
  // (payload {"op":"close"} on a ping must not close the host).
  Envelope env = parse_envelope(raw);
  std::vector<JsonField> payload;
  if (env.ok && env.has_payload && !scan_object_level(env.payload, &payload)) {
    env.ok = false;
    env.error = {"bad_request", "payload must be one well-formed JSON object", "payload"};
  }
  if (!env.ok) {
    send_error(env.request_id, env.generation, "", env.error, g_state.dll != nullptr);
    return;
  }
  const std::string& request_id = env.request_id;
  const long long generation = env.generation;
  const std::string& op = env.op;

  if (op == "ping") {
    send_ok(request_id, generation, op, "");  // make_meta already emits protocol_version
    return;
  }

  if (op == "open") {
    // Any open attempt detaches the current render path first: a failed path
    // switch must not leave the previous source reachable through render_at.
    clear_render_state();
    int render_count = 0;
    std::string render_path = payload_string(payload, "render_path", "", &render_count);
    if (render_count > 1) {
      // A consumed payload field must be unambiguous: never pick by order.
      send_error(request_id, generation, op,
                 {"bad_request", "duplicate payload field: render_path", "render_path"},
                 g_state.dll != nullptr);
      return;
    }
    if (render_path.empty()) {
      send_error(request_id, generation, op,
                 {"bad_request", "render_path is required", "render_path"}, g_state.dll != nullptr);
      return;
    }
    ErrorSpec err;
    if (!verify_and_load(&err)) {
      send_error(request_id, generation, op, err, false);
      return;
    }
    if (render_path == "playerwin") {
      int draft_count = 0;
      int timeline_count = 0;
      std::string draft_root = payload_string(payload, "draft_root", "", &draft_count);
      std::string timeline_id = payload_string(payload, "timeline_id", "", &timeline_count);
      if (draft_count > 1 || timeline_count > 1) {
        const char* dup = draft_count > 1 ? "draft_root" : "timeline_id";
        send_error(request_id, generation, op,
                   {"bad_request", std::string("duplicate payload field: ") + dup, dup}, true);
        return;
      }
      if (!open_player(draft_root, timeline_id, &err)) {
        send_error(request_id, generation, op, err, true);
        return;
      }
      send_ok(request_id, generation, op, ",\"render_path\":\"playerwin\"");
      return;
    }
    if (render_path == "frame-reader-compositor") {
      int source_count = 0;
      const std::string source_path = payload_string(payload, "source_path", "", &source_count);
      if (source_count > 1) {
        send_error(request_id, generation, op,
                   {"bad_request", "duplicate payload field: source_path", "source_path"}, true);
        return;
      }
      g_state.source_path = source_path;
      if (g_state.source_path.empty()) {
        send_error(request_id, generation, op,
                   {"bad_request", "source_path is required for the frame reader path", "source_path"}, true);
        return;
      }
      if (!open_reader(&err)) {
        send_error(request_id, generation, op, err, true);
        return;
      }
      send_ok(request_id, generation, op, ",\"render_path\":\"frame-reader-compositor\"");
      return;
    }
    send_error(request_id, generation, op,
               {"bad_request", "unknown render_path", render_path}, true);
    return;
  }

  if (op == "render_at") {
    int t_us_count = 0;
    long long t_us = payload_int(payload, "t_us", -1, &t_us_count);
    if (t_us_count > 1) {
      // Checked before any state is touched: a duplicate t_us must never
      // resolve to "whichever came first".
      send_error(request_id, generation, op,
                 {"bad_request", "duplicate payload field: t_us", "t_us"},
                 g_state.dll != nullptr);
      return;
    }
    ErrorSpec err;
    if (!g_state.dll) {
      err = {"host_not_open", "open must succeed before render_at", "no dll"};
      send_error(request_id, generation, op, err, false);
      return;
    }
    if (t_us < 0) {
      err = {"bad_request", "t_us is required", "t_us"};
      send_error(request_id, generation, op, err, true);
      return;
    }
    // Clear per-request frame state before any delivery so a failed or
    // near-zero seek can never emit a previous request's pixels.
    clear_frame_state();
    if (!g_state.reader) {
      err = {"host_not_open", "no render path is open", "open first"};
      send_error(request_id, generation, op, err, true);
      return;
    }
    if (!render_reader_at(t_us, &err)) {
      send_error(request_id, generation, op, err, true);
      return;
    }
    send_frame(request_id, generation, op, g_state.best_pts, g_state.width, g_state.height,
               g_state.best_pixels.data());
    return;
  }

  if (op == "close") {
    // Reviewed close behaviour: private DLL destructors (~FrameReader,
    // ~PlayerWin) are deliberately never called — their contracts are not
    // evidenced and must not be guessed. Objects are reclaimed only at
    // process exit; the render path is detached and frame state cleared so a
    // later open cannot observe stale pixels.
    clear_render_state();
    send_ok(request_id, generation, op, "");
    // Response sent: end the process instead of guessing ~FrameReader/
    // ~PlayerWin contracts.
    g_close_and_exit = true;
    return;
  }

  send_error(request_id, generation, op, {"bad_request", "unknown op", op}, g_state.dll != nullptr);
}

}  // namespace

int main(int argc, char** argv) {
  _setmode(_fileno(stdin), _O_BINARY);
  std::setvbuf(stderr, nullptr, _IONBF, 0);

  // Keep the caller's stdout as the protocol channel, then point process-wide
  // stdout (CRT fd1 and Win32 STD_OUTPUT_HANDLE) at stderr so videoeditor.dll
  // banners cannot corrupt the length-prefixed framing.
  HANDLE raw_out = GetStdHandle(STD_OUTPUT_HANDLE);
  DuplicateHandle(GetCurrentProcess(), raw_out, GetCurrentProcess(), &g_protocol_out, 0, FALSE,
                  DUPLICATE_SAME_ACCESS);
  fflush(stdout);
  _dup2(_fileno(stderr), _fileno(stdout));
  SetStdHandle(STD_OUTPUT_HANDLE, GetStdHandle(STD_ERROR_HANDLE));

  g_state.install_dir = R"(D:\Program Files\JianyingPro\11.5.3.14501)";
  g_state.expect_version = "11.5.3.14501";
  g_state.expect_sha256 =
      "E5E4020BD5B37EB19968473E19D7246CA5EFE80064A039136341A27B1FD5D8B7";
  auto value_of = [&](int& i, const char* name) -> std::string {
    std::string arg = argv[i];
    size_t n = std::strlen(name);
    if (arg.rfind(name, 0) != 0) return std::string();
    if (arg.size() == n) {
      if (i + 1 >= argc) return std::string();
      return argv[++i];
    }
    if (arg[n] == '=') return arg.substr(n + 1);
    return std::string();
  };
  for (int i = 1; i < argc; ++i) {
    std::string v = value_of(i, "--install-dir");
    if (!v.empty()) { g_state.install_dir = v; continue; }
    v = value_of(i, "--expect-version");
    if (!v.empty()) { g_state.expect_version = v; continue; }
    v = value_of(i, "--expect-sha256");
    if (!v.empty()) { g_state.expect_sha256 = v; continue; }
  }

  for (;;) {
    unsigned char header[4];
    if (!read_exact(header, 4)) break;
    unsigned len = static_cast<unsigned>(header[0]) | (static_cast<unsigned>(header[1]) << 8) |
                   (static_cast<unsigned>(header[2]) << 16) | (static_cast<unsigned>(header[3]) << 24);
    if (len == 0 || len > 512u * 1024u * 1024u) {
      logf("bad_frame_length=%u\n", len);
      break;
    }
    std::string raw(len, '\0');
    if (!read_exact(&raw[0], len)) break;
    handle(raw);
    if (g_close_and_exit) break;
  }
  logf("preview_host exiting\n");
  return 0;
}
