"""SP-02：素材索引形状清点器——GOP、moov 位置、elst/ctts 条目、首帧取数需求。

为什么自研这一支而不是复用：docs/ 此前对 GOP/关键帧间距零清点（U-55 的「走关键帧索引还是
代理片」全压在这个量上），而播放器侧的索引由 mediabunny 负责，本脚本只服务**离线清点与服务端
通道**，两者不重叠。分工：结构层（stss/stts/ctts/elst/moov）用标准库自己走 box；编码语义
（codec/profile/pix_fmt/码率/音轨）用已装的 PyAV（docs/evidence/toolchain.md:57 已备案）。

口径纪律：只读，不写源文件；读数必须带文件绝对路径与单次/多次；`stss` 缺失 = 无同步样本表
（多为全 I 帧或写工具省略），与「关键帧很多」是两回事，不得混记。

用法：
    python scripts/media_probe.py <文件或目录>... [--json-out temp/media-probe/out.json]
                                   [--quiet]
输出：stdout 表格 + 可选 JSON（供入 docs/evidence/tables/）。
"""
from __future__ import annotations

import argparse
import json
import statistics
import struct
import sys
from pathlib import Path

CONTAINER_ATOMS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"edts", b"udta", b"mvex", b"dinf"}


def walk(f, lo, hi, path=""):
    """扁平化 box 列表：(path, box_start, payload_start, payload_end)。"""
    out = []
    p = lo
    while p + 8 <= hi:
        f.seek(p)
        hdr = f.read(8)
        if len(hdr) < 8:
            break
        size = int.from_bytes(hdr[:4], "big")
        typ = hdr[4:8]
        head = 8
        if size == 1:
            size = int.from_bytes(f.read(8), "big")
            head = 16
        elif size == 0:
            size = hi - p
        if size < head or p + size > hi:
            break
        ps, pe = p + head, p + size
        out.append((f"{path}.{typ.decode('latin1', 'replace')}", p, ps, pe))
        if typ in CONTAINER_ATOMS:
            out.extend(walk(f, ps, pe, f"{path}.{typ.decode('latin1', 'replace')}"))
        p += size
    return out


def rd(f, at, n):
    f.seek(at)
    return f.read(n)


def u32(b, o):
    return int.from_bytes(b[o:o + 4], "big")


def probe_structure(path: Path):
    n = path.stat().st_size
    r = {"file": str(path), "bytes": n}
    with open(path, "rb") as f:
        boxes = walk(f, 0, n)
        brands = rd(f, 8, 4) if any(b[0] == ".ftyp" for b in boxes) else b""
        r["brand"] = brands.decode("latin1", "replace").strip() or None
        moov = next((b for b in boxes if b[0] == ".moov"), None)
        if moov is None:
            r["error"] = "no top-level moov (fragmented or unparseable)"
            return r
        r["moov"] = {"offset": moov[1], "size": moov[3] - moov[1],
                     "position": "tail" if moov[1] > n * 0.5 else "head"}
        # 播放器实际取的是 `bytes=<moov起点>-`（开区间到文件尾），所以尾读成本 = to_eof 而非 moov 本体
        r["moov"]["to_eof_bytes"] = n - moov[1]
        mdat = [b for b in boxes if b[0] == ".mdat"]
        if mdat:
            r["mdat_first_offset"] = mdat[0][1]
        # 尾部读需求：moov 在尾时，起播前必须把整段 moov（含 udta）读进来
        r["tail_read_bytes"] = (moov[3] - moov[1]) if r["moov"]["position"] == "tail" else 0

        tracks = []
        for tr in [b for b in boxes if b[0].endswith(".trak")]:
            sub = [b for b in boxes if b[0].startswith(tr[0] + ".") and tr[1] < b[1] < tr[3] and b[3] <= tr[3]]

            def one(*sfx):
                for b in sub:
                    if any(b[0].endswith(s) for s in sfx):
                        return b
                return None

            hdlr = one(".hdlr")
            if hdlr is None:
                continue
            kind = rd(f, hdlr[2] + 8, 4).decode("latin1", "replace")
            md = one(".mdhd")
            b = rd(f, md[2], 32)
            if b[0] == 1:
                ts, dur = u32(b, 20), int.from_bytes(b[24:32], "big")
            else:
                ts, dur = u32(b, 12), u32(b, 16)
            tk = {"handler": kind, "timescale": ts, "duration": dur,
                  "seconds": round(dur / ts, 3) if ts else None}

            st = one(".stsd")
            if st:
                b = rd(f, st[2], 96)
                tk["fourcc"] = b[12:16].decode("latin1", "replace")
                if kind == "vide":
                    tk["coded_w"] = int.from_bytes(b[40:42], "big")
                    tk["coded_h"] = int.from_bytes(b[42:44], "big")

            stts = one(".stts")
            if stts:
                b = rd(f, stts[2], 8)
                cnt = u32(b, 4)
                seen = min(cnt, 200_000)
                b = rd(f, stts[2], 8 + 8 * seen)
                ent = [struct.unpack(">II", b[8 + 8 * i:16 + 8 * i]) for i in range(seen)]
                tk["stts_entries"] = cnt
                tk["frames"] = sum(a for a, _ in ent) if seen == cnt else None
                first_delta = ent[0][1] or 1
                tk["nominal_fps"] = round(ts / first_delta, 3) if ts else None
                tk["sample_delta_units"] = first_delta
                tk["vfr"] = cnt > 1 and len({d for _, d in ent}) > 1
                # 变帧率时第一条 delta 不代表平均帧率（F-038 的分母教训）：另给平均口径
                tk["avg_fps"] = round(tk["frames"] / dur * ts, 3) if tk["frames"] and dur and ts else None

            stss = one(".stss")
            sizes = []
            zs = one(".stsz")
            if zs:
                b = rd(f, zs[2], 16)
                unif, sc = u32(b, 4), u32(b, 8)
                if unif:
                    sizes = [unif] * sc
                else:
                    b = rd(f, zs[2], 16 + 4 * sc)
                    sizes = [u32(b, 16 + 4 * i) for i in range(sc)]
                tk["sample_sizes_mean"] = round(sum(sizes) / len(sizes)) if sizes else None
            if stss:
                b = rd(f, stss[2], 8)
                cnt = u32(b, 4)
                b = rd(f, stss[2], 8 + 4 * cnt)
                ks = [u32(b, 8 + 4 * i) - 1 for i in range(cnt)]
                tk["keyframes"] = cnt
                tk["seek_index_bytes"] = 8 + 4 * cnt
                if len(ks) > 1 and sizes:
                    gaps = [y - x for x, y in zip(ks, ks[1:])]
                    spans = [sum(sizes[x:y]) for x, y in zip(ks, ks[1:])]
                    fps = (tk.get("avg_fps") or tk.get("nominal_fps")) if tk.get("vfr") \
                        else (tk.get("nominal_fps") or tk.get("avg_fps")) or 1
                    tk["gop_frames"] = [min(gaps), max(gaps), round(statistics.mean(gaps), 1)]
                    tk["gop_ms"] = [round(min(gaps) * 1000 / fps), round(max(gaps) * 1000 / fps)]
                    tk["gop_ms_fps_basis"] = "avg_fps" if tk.get("vfr") else "nominal_fps"
                    tk["gop_bytes"] = [min(spans), max(spans), round(statistics.mean(spans))]
            elif kind == "vide":
                tk["keyframes"] = None  # 无 stss：全 I 帧，或写工具省略
            ctts = one(".ctts")
            if ctts:
                b = rd(f, ctts[2], 8)
                cnt = u32(b, 4)
                seen = min(cnt, 200_000)
                b = rd(f, ctts[2], 8 + 8 * seen)
                ent = [struct.unpack(">II", b[8 + 8 * i:16 + 8 * i]) for i in range(seen)]
                offs = [int.from_bytes(struct.pack(">i", d), "big", signed=True) for _, d in ent]
                tk["ctts_entries"] = cnt
                tk["reorder_offset_units"] = [min(offs), max(offs)]
                d = tk.get("sample_delta_units") or 0
                if d:
                    tk["reorder_frames"] = [round(min(offs) / d, 2), round(max(offs) / d, 2)]
            el = one(".elst")
            if el:
                b = rd(f, el[2], 8)
                cnt = u32(b, 4)
                ver = b[0]
                sz = 20 if ver == 1 else 12
                b = rd(f, el[2], 8 + sz * min(cnt, 64))
                rows = []
                for i in range(cnt):
                    o = 8 + sz * i
                    if ver == 1:
                        seg = int.from_bytes(b[o:o + 8], "big")
                        mt = int.from_bytes(b[o + 8:o + 16], "big", signed=True)
                    else:
                        seg = u32(b, o)
                        mt = int.from_bytes(b[o + 4:o + 8], "big", signed=True)
                    rate = struct.unpack(">i", b[o + sz - 4:o + sz])[0] / 65536.0
                    rows.append({"segment_duration": seg, "media_time": mt, "media_rate": round(rate, 3)})
                tk["elst_entries"] = cnt
                tk["elst"] = rows
            tracks.append(tk)
        r["tracks"] = tracks
    return r


def probe_codec(path: Path):
    """编码语义交给 PyAV（已装、已备案）：codec/profile/pix_fmt/码率/帧率/音轨布局。"""
    try:
        import av
    except Exception as exc:  # pragma: no cover
        return {"codec_error": f"PyAV unavailable: {exc}"}
    out = {"streams": []}
    try:
        with av.open(str(path)) as c:
            out["container"] = c.format.name
            out["duration_s"] = round(float(c.duration) / av.time_base, 3) if c.duration else None
            for s in c.streams:
                d = {"type": s.type, "codec": s.codec_context.name if s.codec_context else None}
                if s.type == "video":
                    cc = s.codec_context
                    d.update(profile=getattr(cc, "profile", None), pix_fmt=getattr(cc, "pix_fmt", None),
                             w=s.width, h=s.height, coded_w=getattr(cc, "coded_width", None),
                             coded_h=getattr(cc, "coded_height", None),
                             fps=round(float(s.average_rate), 3) if s.average_rate else None,
                             rotation=getattr(s, "rotation", None), frames=s.frames,
                             bit_rate=getattr(cc, "bit_rate", None))
                elif s.type == "audio":
                    cc = s.codec_context
                    d.update(sample_rate=getattr(cc, "sample_rate", None),
                             channels=getattr(cc, "channels", None),
                             layout=str(getattr(cc, "layout", None)), frames=s.frames)
                out["streams"].append(d)
    except Exception as exc:
        out["codec_error"] = f"{type(exc).__name__}: {exc}"
    return out


def collect(inputs):
    files = []
    for s in inputs:
        p = Path(s)
        if p.is_dir():
            files.extend(sorted(x for x in p.rglob("*")
                                if x.is_file() and x.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"!! 不存在：{s}", file=sys.stderr)
    return files


def main():
    ap = argparse.ArgumentParser(description="素材索引形状清点（GOP / moov / elst / ctts）")
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--json-out")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    rows = []
    for p in collect(args.inputs):
        rec = probe_structure(p)
        rec.update({"codec": probe_codec(p)})
        rows.append(rec)
        if not args.quiet:
            v = [t for t in rec.get("tracks", []) if t.get("handler") == "vide"]
            a = [t for t in rec.get("tracks", []) if t.get("handler") == "soun"]
            print(f"== {rec['file']} {rec['bytes']/1e6:.1f}MB brand={rec.get('brand')} "
                  f"container={rec['codec'].get('container')} moov@{rec['moov']['offset']} "
                  f"{rec['moov']['position']} size={rec['moov']['size']/1000:.0f}KB "
                  f"尾读到文件尾={rec['moov'].get('to_eof_bytes', 0)/1000:.0f}KB")
            for t in v:
                g = t.get("gop_frames")
                print(f"   [V] {t.get('fourcc')} {t.get('coded_w')}x{t.get('coded_h')} ts={t['timescale']} "
                      f"{t['seconds']}s frames={t.get('frames')} fps={t.get('nominal_fps')}/{t.get('avg_fps')} "
                      f"vfr={t.get('vfr')} "
                      f"stts={t.get('stts_entries')} kf={t.get('keyframes')} "
                      f"GOP={g} ms={t.get('gop_ms')}({t.get('gop_ms_fps_basis')}) GOPbytes={t.get('gop_bytes')} "
                      f"帧均值={t.get('sample_sizes_mean')} seek索引={t.get('seek_index_bytes')}B "
                      f"ctts={t.get('ctts_entries')} 重排帧={t.get('reorder_frames')} "
                      f"elst条目={t.get('elst_entries')} {t.get('elst') or ''}")
            for t in a:
                print(f"   [A] {t.get('fourcc')} ts={t['timescale']} {t['seconds']}s frames={t.get('frames')} "
                      f"elst条目={t.get('elst_entries')}")
            st = rec["codec"].get("streams", [])
            for s in st:
                if s.get("type") == "video":
                    print(f"   [codec] {s.get('codec')} profile={s.get('profile')} pix={s.get('pix_fmt')} "
                          f"{s.get('w')}x{s.get('h')} coded={s.get('coded_w')}x{s.get('coded_h')} "
                          f"fps={s.get('fps')} rot={s.get('rotation')} bitrate={s.get('bit_rate')}")
                else:
                    print(f"   [acodec] {s.get('codec')} {s.get('sample_rate')}Hz ch={s.get('channels')} "
                          f"layout={s.get('layout')}")
            if rec["codec"].get("codec_error"):
                print(f"   [codec] ERROR {rec['codec']['codec_error']}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nJSON → {out}（{len(rows)} 份）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
