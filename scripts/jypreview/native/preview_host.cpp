// preview_host.cpp — isolated Jianying DLL preview host (IPC v1).
//
// Loads the version-locked videoeditor.dll from the installed JianyingPro
// directory only after verifying version + SHA-256, and serves two render
// paths over a length-prefixed JSON protocol (RGBA bytes follow the metadata):
//   * playerwin          — Server/Session/VeWrapper/PlayerWin timeline frames
//   * frame-reader-compositor — lvve::FrameReaderWin source frames
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

// Finds `"key"` at any nesting depth and returns the scalar that follows.
// Strings are returned unquoted with \" \\ \n \r \t and \uXXXX decoded.
bool find_scalar(const std::string& json, const std::string& key, std::string* out) {
  const std::string needle = "\"" + key + "\"";
  size_t pos = 0;
  while ((pos = json.find(needle, pos)) != std::string::npos) {
    size_t i = pos + needle.size();
    while (i < json.size() && (json[i] == ' ' || json[i] == '\t' || json[i] == '\n' || json[i] == '\r')) ++i;
    if (i < json.size() && json[i] == ':') {
      ++i;
      while (i < json.size() && (json[i] == ' ' || json[i] == '\t' || json[i] == '\n' || json[i] == '\r')) ++i;
      if (i >= json.size()) return false;
      if (json[i] == '"') {
        std::string value;
        ++i;
        while (i < json.size() && json[i] != '"') {
          if (json[i] == '\\' && i + 1 < json.size()) {
            char n = json[i + 1];
            if (n == 'u') {
              size_t j = i + 2;
              uint32_t cp = 0;
              int digits = 0;
              for (; digits < 4 && j < json.size(); ++digits, ++j) {
                char h = json[j];
                int d;
                if (h >= '0' && h <= '9') d = h - '0';
                else if (h >= 'a' && h <= 'f') d = h - 'a' + 10;
                else if (h >= 'A' && h <= 'F') d = h - 'A' + 10;
                else break;
                cp = cp * 16 + static_cast<uint32_t>(d);
              }
              if (digits == 4) {
                if (cp >= 0xD800 && cp <= 0xDBFF && j + 6 <= json.size() && json[j] == '\\' &&
                    json[j + 1] == 'u') {
                  size_t k = j + 2;
                  uint32_t lo = 0;
                  int low_digits = 0;
                  for (; low_digits < 4 && k < json.size(); ++low_digits, ++k) {
                    char h = json[k];
                    int d;
                    if (h >= '0' && h <= '9') d = h - '0';
                    else if (h >= 'a' && h <= 'f') d = h - 'a' + 10;
                    else if (h >= 'A' && h <= 'F') d = h - 'A' + 10;
                    else break;
                    lo = lo * 16 + static_cast<uint32_t>(d);
                  }
                  if (low_digits == 4 && lo >= 0xDC00 && lo <= 0xDFFF) {
                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    j = k;
                  }
                }
                append_utf8(cp, &value);
                i = j;
                continue;
              }
            }
            if (n == 'n') value += '\n';
            else if (n == 'r') value += '\r';
            else if (n == 't') value += '\t';
            else value += n;
            i += 2;
          } else {
            value += json[i++];
          }
        }
        *out = value;
        return true;
      }
      size_t start = i;
      while (i < json.size() && json[i] != ',' && json[i] != '}' && json[i] != ']' && json[i] != ' ') ++i;
      *out = json.substr(start, i - start);
      return true;
    }
    pos = pos + needle.size();
  }
  return false;
}

std::string find_string(const std::string& json, const std::string& key, const std::string& fallback = "") {
  std::string v;
  return find_scalar(json, key, &v) ? v : fallback;
}

long long find_int(const std::string& json, const std::string& key, long long fallback = -1) {
  std::string v;
  if (!find_scalar(json, key, &v)) return fallback;
  char* end = nullptr;
  long long n = std::strtoll(v.c_str(), &end, 10);
  return end && *end == 0 ? n : fallback;
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

// Returns the raw JSON scalar token (quoted string or number/bool/null) for a
// key so request_id round-trips with the caller's original type.
bool find_raw_token(const std::string& json, const std::string& key, std::string* out) {
  const std::string needle = "\"" + key + "\"";
  size_t pos = 0;
  while ((pos = json.find(needle, pos)) != std::string::npos) {
    size_t i = pos + needle.size();
    while (i < json.size() && (json[i] == ' ' || json[i] == '\t' || json[i] == '\n' || json[i] == '\r')) ++i;
    if (i < json.size() && json[i] == ':') {
      ++i;
      while (i < json.size() && (json[i] == ' ' || json[i] == '\t' || json[i] == '\n' || json[i] == '\r')) ++i;
      size_t start = i;
      if (i < json.size() && json[i] == '"') {
        ++i;
        while (i < json.size() && json[i] != '"') {
          if (json[i] == '\\') ++i;
          ++i;
        }
        if (i < json.size()) ++i;
      } else {
        while (i < json.size() && json[i] != ',' && json[i] != '}' && json[i] != ']' && json[i] != ' ' &&
               json[i] != '\n' && json[i] != '\r' && json[i] != '\t')
          ++i;
      }
      *out = json.substr(start, i - start);
      return !out->empty();
    }
    pos = pos + needle.size();
  }
  return false;
}

std::string make_meta(const std::string& request_id_token, long long generation, const std::string& op, bool ok) {
  std::string meta = "{\"protocol_version\":1,\"request_id\":" + request_id_token +
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

  // playerwin path state
  void* player = nullptr;
  std::string player_failure_step;
  std::string player_failure_detail;
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
  if (g_state.best_pixels.empty()) {
    err->code = "frame_unavailable";
    err->message = "no frame was delivered for the requested time";
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
// PlayerWin path: Server/Session/VeWrapper/PlayerWin
// --------------------------------------------------------------------------
struct SharedPtr2 {
  void* ptr;
  void* ctrl;
};

unsigned char g_adapter[8192];
unsigned char g_global[8192];
void* g_server = nullptr;
long g_sid = -1;
void* g_session_slot = nullptr;
void* g_wrapper_slot = nullptr;
void* g_editor_slot = nullptr;
char g_step_name[64] = "resolve_exports";
char g_step_detail[256];

LONG WINAPI log_exception(EXCEPTION_POINTERS* ex, const char* step) {
  const auto* r = ex->ExceptionRecord;
  const auto* c = ex->ContextRecord;
  HMODULE mod = nullptr;
  wchar_t path[MAX_PATH] = {};
  char utf8[MAX_PATH * 4] = {};
  std::snprintf(g_step_detail, sizeof(g_step_detail),
                "exception=0x%08lx rva=0x%llx av_addr=%p", r->ExceptionCode,
                0ull, r->ExceptionAddress);
  if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                         reinterpret_cast<LPCWSTR>(r->ExceptionAddress), &mod) &&
      GetModuleFileNameW(mod, path, MAX_PATH)) {
    WideCharToMultiByte(CP_UTF8, 0, path, -1, utf8, sizeof(utf8), nullptr, nullptr);
    std::snprintf(g_step_detail, sizeof(g_step_detail),
                  "exception=0x%08lx module=%s rva=0x%llx av_addr=%p", r->ExceptionCode, utf8,
                  static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(r->ExceptionAddress) -
                                                  reinterpret_cast<uintptr_t>(mod)),
                  r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2
                      ? reinterpret_cast<void*>(r->ExceptionInformation[1])
                      : nullptr);
  }
  logf("playerwin_av step=%s %s rcx=%p rdx=%p r8=%p r9=%p\n", step, g_step_detail,
       reinterpret_cast<void*>(c->Rcx), reinterpret_cast<void*>(c->Rdx), reinterpret_cast<void*>(c->R8),
       reinterpret_cast<void*>(c->R9));
  return EXCEPTION_EXECUTE_HANDLER;
}

enum PlayerStep {
  kInitVeAbConfig = 1,
  kServerInstance = 2,
  kServerStartup = 3,
  kOpenSession = 4,
  kGetSession = 5,
  kInitVeWrapper = 6,
  kGetVeWrapper = 7,
  kOpenTimelineEditor = 8,
  kTimelineEditor = 9,
  kPlayerCtor = 10,
  kSetOffscreen = 11,
  kPrepare = 12,
};

struct PlayerCtx {
  int which;
  int arg;
  long ret;
  void* ptr;
  bool use_two_strings;
};

void run_player_step(PlayerCtx* ctx) {
  switch (ctx->which) {
    case kInitVeAbConfig: {
      using Fn = void(__fastcall*)(const void*);
      auto fn = reinterpret_cast<Fn>(
          GetProcAddress(g_state.dll, "?InitVEAbConfig@lvve@@YAXPEBUVEAdapterConfig@adapter@1@@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      fn(g_adapter);
      ctx->ret = 0;
      break;
    }
    case kServerInstance: {
      using Fn = void* (__cdecl*)();
      auto fn = reinterpret_cast<Fn>(GetProcAddress(g_state.dll, "?instance@Server@lyra@@SAPEAU12@XZ"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      ctx->ptr = fn();
      g_server = ctx->ptr;
      ctx->ret = ctx->ptr ? 0 : -2;
      if (!ctx->ptr) std::snprintf(g_step_detail, sizeof(g_step_detail), "Server::instance returned null");
      break;
    }
    case kServerStartup: {
      using Fn = void(__fastcall*)(void*, const void*);
      auto fn = reinterpret_cast<Fn>(
          GetProcAddress(g_state.dll, "?startup@Server@lyra@@QEAAXPEBUVEGlobalConfig@lvve@@@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      fn(g_server, g_global);
      ctx->ret = 0;
      break;
    }
    case kOpenSession: {
      std::string name = "jypreview-preview-host";
      std::string addr;
      if (ctx->use_two_strings) {
        using Fn = long(__fastcall*)(void*, const void*, const std::string*, const std::string*);
        auto fn = reinterpret_cast<Fn>(GetProcAddress(
            g_state.dll,
            "?openSession@Server@lyra@@QEAAJPEBUVEAdapterConfig@adapter@lvve@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@1@Z"));
        if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
        ctx->ret = fn(g_server, g_adapter, &name, &addr);
      } else {
        using Fn = long(__fastcall*)(void*, const void*, const std::string*);
        auto fn = reinterpret_cast<Fn>(GetProcAddress(
            g_state.dll,
            "?openSession@Server@lyra@@QEAAJPEBUVEAdapterConfig@adapter@lvve@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z"));
        if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
        ctx->ret = fn(g_server, g_adapter, &name);
      }
      g_sid = ctx->ret;
      break;
    }
    case kGetSession: {
      using Fn = SharedPtr2(__fastcall*)(void*, void*, long);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(
          g_state.dll, "?getSession@Server@lyra@@QEAA?AV?$shared_ptr@USession@lyra@@@std@@J@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      fn(g_session_slot, g_server, ctx->arg);
      ctx->ptr = *reinterpret_cast<void**>(g_session_slot);
      ctx->ret = ctx->ptr ? 0 : -2;
      if (!ctx->ptr) std::snprintf(g_step_detail, sizeof(g_step_detail), "getSession returned null");
      break;
    }
    case kInitVeWrapper: {
      using Fn = bool(__fastcall*)(void*, const void*);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(
          g_state.dll, "?initVeWrapper@Session@lyra@@QEAA_NPEBUVEAdapterConfig@adapter@lvve@@@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      void* session = *reinterpret_cast<void**>(g_session_slot);
      if (!session) { std::snprintf(g_step_detail, sizeof(g_step_detail), "no session"); ctx->ret = -2; return; }
      bool ok = fn(session, g_adapter);
      ctx->ret = ok ? 0 : -3;
      if (!ok) std::snprintf(g_step_detail, sizeof(g_step_detail), "initVeWrapper returned false");
      break;
    }
    case kGetVeWrapper: {
      using Fn = SharedPtr2(__fastcall*)(void*, void*);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(
          g_state.dll, "?getVeWrapper@Session@lyra@@QEAA?AV?$shared_ptr@UVeWrapper@wrapper@lyra@@@std@@XZ"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      void* session = *reinterpret_cast<void**>(g_session_slot);
      fn(g_wrapper_slot, session);
      ctx->ptr = *reinterpret_cast<void**>(g_wrapper_slot);
      ctx->ret = ctx->ptr ? 0 : -2;
      if (!ctx->ptr) std::snprintf(g_step_detail, sizeof(g_step_detail), "getVeWrapper returned null");
      break;
    }
    case kOpenTimelineEditor: {
      using Fn = void(__fastcall*)(void*, long, bool);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(
          g_state.dll, "?openTimelineEditor@VeWrapper@wrapper@lyra@@QEAAXJ_N@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      void* wrapper = *reinterpret_cast<void**>(g_wrapper_slot);
      if (!wrapper) { std::snprintf(g_step_detail, sizeof(g_step_detail), "no wrapper"); ctx->ret = -2; return; }
      fn(wrapper, ctx->arg, true);
      ctx->ret = 0;
      break;
    }
    case kTimelineEditor: {
      using Fn = SharedPtr2(__fastcall*)(void*, void*, long);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(
          g_state.dll,
          "?timelineEditor@VeWrapper@wrapper@lyra@@QEAA?AV?$shared_ptr@VVeTimelineEditor@wrapper@lyra@@@std@@J@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      void* wrapper = *reinterpret_cast<void**>(g_wrapper_slot);
      fn(g_editor_slot, wrapper, ctx->arg);
      ctx->ptr = *reinterpret_cast<void**>(g_editor_slot);
      ctx->ret = ctx->ptr ? 0 : -2;
      if (!ctx->ptr) std::snprintf(g_step_detail, sizeof(g_step_detail), "timelineEditor returned null");
      break;
    }
    case kPlayerCtor: {
      using Fn = void* (__fastcall*)(void*, void*, const void*, long);
      auto fn = reinterpret_cast<Fn>(
          GetProcAddress(g_state.dll, "??0PlayerWin@lvve@@QEAA@PEAXPEBUVEAdapterConfig@adapter@1@J@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      void* editor = *reinterpret_cast<void**>(g_editor_slot);
      ctx->ptr = fn(nullptr, editor, g_adapter, ctx->arg);
      g_state.player = ctx->ptr;
      ctx->ret = ctx->ptr ? 0 : -2;
      if (!ctx->ptr) std::snprintf(g_step_detail, sizeof(g_step_detail), "PlayerWin ctor returned null");
      break;
    }
    case kSetOffscreen: {
      using Fn = void(__fastcall*)(void*, bool);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(g_state.dll, "?SetOffscreen@PlayerWin@lvve@@UEAAAX_N@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      fn(g_state.player, true);
      ctx->ret = 0;
      break;
    }
    case kPrepare: {
      using Fn = void(__fastcall*)(void*, bool);
      auto fn = reinterpret_cast<Fn>(GetProcAddress(g_state.dll, "?Prepare@PlayerWin@lvve@@UEAAAX_N@Z"));
      if (!fn) { std::snprintf(g_step_detail, sizeof(g_step_detail), "export missing"); ctx->ret = -1; return; }
      fn(g_state.player, true);
      ctx->ret = 0;
      break;
    }
    default:
      ctx->ret = -999;
      std::snprintf(g_step_detail, sizeof(g_step_detail), "unknown step");
  }
}

bool guarded_player(PlayerCtx* ctx, const char* step) {
  std::snprintf(g_step_name, sizeof(g_step_name), "%s", step);
  g_step_detail[0] = 0;
  __try {
    run_player_step(ctx);
    return true;
  } __except (log_exception(GetExceptionInformation(), g_step_name)) {
    ctx->ret = -1000;
    return false;
  }
}

bool open_player(ErrorSpec* err) {
  std::memset(g_adapter, 0, sizeof(g_adapter));
  std::memset(g_global, 0, sizeof(g_global));
  g_session_slot = std::calloc(2, sizeof(void*));
  g_wrapper_slot = std::calloc(2, sizeof(void*));
  g_editor_slot = std::calloc(2, sizeof(void*));
  g_sid = -1;

  struct {
    int which;
    const char* step;
    bool two_strings;
  } plan[] = {
      {kInitVeAbConfig, "InitVEAbConfig", false},
      {kServerInstance, "Server::instance", false},
      {kServerStartup, "Server::startup", false},
      {kOpenSession, "Server::openSession", true},
      {kGetSession, "Server::getSession", false},
      {kInitVeWrapper, "Session::initVeWrapper", false},
      {kGetVeWrapper, "Session::getVeWrapper", false},
      {kOpenTimelineEditor, "VeWrapper::openTimelineEditor", false},
      {kTimelineEditor, "VeWrapper::timelineEditor", false},
      {kPlayerCtor, "PlayerWin ctor", false},
      {kSetOffscreen, "PlayerWin::SetOffscreen", false},
      {kPrepare, "PlayerWin::Prepare", false},
  };
  for (auto& p : plan) {
    PlayerCtx ctx{};
    ctx.which = p.which;
    ctx.arg = g_sid;
    ctx.use_two_strings = p.two_strings;
    bool ok = guarded_player(&ctx, p.step);
    if (!ok) {
      err->code = "init_rejected";
      err->message = std::string("PlayerWin initialization failed at ") + p.step;
      err->detail = std::string("step=") + p.step + " " + g_step_detail +
                    " (VEAdapterConfig/VEGlobalConfig construction contract is not exposed by the DLL)";
      g_state.player_failure_step = p.step;
      g_state.player_failure_detail = err->detail;
      return false;
    }
    if (ctx.ret != 0) {
      err->code = "init_rejected";
      err->message = std::string("PlayerWin initialization rejected at ") + p.step;
      err->detail = std::string("step=") + p.step + " ret=" + std::to_string(ctx.ret) + " " + g_step_detail;
      g_state.player_failure_step = p.step;
      g_state.player_failure_detail = err->detail;
      return false;
    }
  }
  return true;
}

// --------------------------------------------------------------------------
// Dispatch
// --------------------------------------------------------------------------
std::string read_all_payload(const std::string& request, size_t* payload_pos) {
  (void)request;
  (void)payload_pos;
  return std::string();
}

void handle(const std::string& raw) {
  std::string request_id = "0";
  if (!find_raw_token(raw, "request_id", &request_id) ||
      !(request_id == "0" || (request_id[0] == '"') || (request_id[0] >= '0' && request_id[0] <= '9') ||
        request_id[0] == '-' || request_id[0] == 't' || request_id[0] == 'f' || request_id[0] == 'n')) {
    request_id = "0";
  }
  long long generation = find_int(raw, "generation", 0);
  std::string op = find_string(raw, "op", "");

  if (op == "ping") {
    send_ok(request_id, generation, op, ",\"protocol_version\":1");
    return;
  }

  if (op == "open") {
    std::string render_path = find_string(raw, "render_path", "");
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
      if (!open_player(&err)) {
        send_error(request_id, generation, op, err, true);
        return;
      }
      send_ok(request_id, generation, op, ",\"render_path\":\"playerwin\"");
      return;
    }
    if (render_path == "frame-reader-compositor") {
      g_state.source_path = find_string(raw, "source_path", "");
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
    long long t_us = find_int(raw, "t_us", -1);
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
    if (g_state.player) {
      err = {"init_rejected", "PlayerWin path produced no frame", "player present but GetSpecificTimeImage is not wired"};
      send_error(request_id, generation, op, err, true);
      return;
    }
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
    g_state.reader = nullptr;
    g_state.player = nullptr;
    g_state.best_pixels.clear();
    send_ok(request_id, generation, op, "");
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
  }
  logf("preview_host exiting\n");
  return 0;
}
