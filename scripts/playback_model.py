"""Draft JSON -> playback model (L1 of the verification plan).

Read-only. Reads a decrypted draft_content.json and emits the per-segment model a
player needs (geometry, timing, material, resolved media path) plus the L1
assertions: reference integrity, track overlap, duration consistency, and
target == source / speed. Feature counts say what the renderer must support for
this project, so a playback test is never scored against an empty feature set.

Usage:
  python scripts/playback_model.py <plain.json> --draft-root <draft dir> [--out <temp path>]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent / "jy_crypto"))

MACRO = re.compile(r"^##_draftpath_placeholder_[0-9A-Fa-f-]+_##[/\\]")

VIDEO_SHAPE = ("clip", "transform", "scale", "rotation", "alpha", "flip")

BOX_HEADS = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"styp", b"pssh", b"smhd"}


def probe_container(path: str | None) -> dict:
    """Can a demuxer open this at all? JianYing encrypts more than draft_content.json: the
    composite renders under Resources/combination/ have no box header, while their sibling
    *.alpha.mp4 files are plaintext. This reads 12 bytes and reports; it never guesses an algo."""
    if not path or not os.path.isfile(path):
        return {"readable": False, "why": "missing"}
    with open(path, "rb") as fh:
        head = fh.read(12)
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return {"readable": True, "container": "matroska"}
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return {"readable": True, "container": "mpeg-audio"}
    # Still-image materials (videos[].type == 'photo') are PNG/JPEG, not ISO-BMFF: without
    # this the probe called a logo PNG 'no-box-header' and both render chains skipped it.
    png = bytes([0x89]) + b'PNG' + bytes([0x0D, 0x0A, 0x1A, 0x0A])
    jpeg = bytes([0xFF, 0xD8, 0xFF])
    for magic, name in ((png, 'png'), (jpeg, 'jpeg'), (b'GIF8', 'gif'), (b'BM', 'bmp')):
        if head.startswith(magic):
            return {'readable': True, 'container': name}
    if head[:4] == b'RIFF' and head[8:12] == b'WEBP':
        return {'readable': True, 'container': 'webp'}
    typ = head[4:8]
    if typ in BOX_HEADS:
        return {"readable": True, "container": "iso-bmff", "first_atom": typ.decode("latin1"),
                "atom_size": int.from_bytes(head[:4], "big")}
    return {"readable": False, "why": "no-box-header", "head_hex": head.hex()}


def scratch_out(path: Path) -> Path:
    """Confine every artifact to the repo temp/ - same fence as the crypto worker."""
    from cache import assert_scratch_target

    return assert_scratch_target(path)


def resolve_path(raw: str | None, draft_root: Path) -> str | None:
    if not raw:
        return None
    p = MACRO.sub("", raw.replace("\\", "/"))
    if p != raw.replace("\\", "/"):
        p = (draft_root / p).as_posix()
    return p


def load_json_string(blob: str):
    """texts.content is a JSON string that carries its own styles[] (spec/text.yaml)."""
    try:
        return json.loads(blob)
    except (TypeError, json.JSONDecodeError):
        return None


def style_of(s: dict, fonts: dict) -> dict:
    """One styles[] entry, flattened to what a renderer needs.

    range is UTF-16 code units (U-01); solid.alpha is the authority with fill.alpha as the
    fallback (U-02); shadow diffuse is panel-blur / 600 (U-03); the font travels as an absolute
    path into the resource cache, so the preview can load the very face JianYing used (F-036).
    """
    fill = s.get("fill") or {}
    content = fill.get("content") or {}
    solid = content.get("solid") or {}
    grad = content.get("gradient") or {}
    font = s.get("font") or {}
    path = (font.get("path") or "").replace("\\", "/") or None
    if path:
        fonts.setdefault(path, {"path": path, "id": font.get("id"), "exists": os.path.isfile(path)})
    shadow = (s.get("shadows") or [None])[0]
    sh = None
    if shadow:
        sc = ((shadow.get("content") or {}).get("solid") or {})
        sh = {"alpha": shadow.get("alpha"), "angle": shadow.get("angle"),
              "distance": shadow.get("distance"), "diffuse": shadow.get("diffuse"),
              "color": sc.get("color")}
    return {
        "range": s.get("range"), "size": s.get("size"),
        "font_id": font.get("id"), "font_path": path,
        "render_type": content.get("render_type"),
        "color": solid.get("color"),
        "alpha": solid.get("alpha", fill.get("alpha", 1.0)),
        "gradient": None if not grad.get("color") else {"mode": grad.get("mode"),
                                                        "angle": grad.get("angle"),
                                                        "colors": grad.get("color")},
        "strokes": [{"color": (st.get("content") or {}).get("color"), "width": st.get("width"),
                     "alpha": st.get("alpha")} for st in (s.get("strokes") or [])],
        "shadow": sh,
        "useLetterColor": s.get("useLetterColor"),
        "bold": s.get("bold"), "italic": s.get("italic"),
    }


class Model:
    MAX_COMPOSITE_DEPTH = 3

    def __init__(self, draft: dict, draft_root: Path, depth: int = 0):
        self.draft = draft
        self.draft_root = draft_root
        self.depth = depth
        mats = draft.get("materials") or {}
        self.buckets: dict[str, dict] = {}
        for name, items in mats.items():
            if not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and it.get("id"):
                    self.buckets[it["id"]] = (name, it)
        self.speeds = {
            s["id"]: s for s in mats.get("speeds") or [] if isinstance(s, dict) and s.get("id")
        }
        self.fonts: dict[str, dict] = {}
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def material_of(self, mid: str | None):
        return self.buckets.get(mid) if mid else None

    def speed_for(self, seg: dict) -> float:
        if seg.get("speed"):
            return float(seg["speed"])
        for ref in seg.get("extra_material_refs") or []:
            bucket, item = self.material_of(ref) or (None, None)
            if bucket == "speeds":
                return float(item.get("speed") or 1.0)
        return 1.0

    def segment(self, seg: dict, track: dict) -> dict:
        sid = seg.get("id")
        bucket, mat = self.material_of(seg.get("material_id"))
        if mat is None:
            self.errors.append(f"dangling material_id {seg.get('material_id')} in segment {sid}")
        refs, missing = [], []
        for ref in seg.get("extra_material_refs") or []:
            if ref in self.buckets:
                refs.append({"id": ref, "bucket": self.buckets[ref][0], "type": self.buckets[ref][1].get("type")})
            else:
                missing.append(ref)
                self.errors.append(f"dangling extra_material_ref {ref} in segment {sid}")

        tgt, src = seg.get("target_timerange") or {}, seg.get("source_timerange") or {}
        t_start, t_dur = int(tgt.get("start") or 0), int(tgt.get("duration") or 0)
        s_start, s_dur = int(src.get("start") or 0), int(src.get("duration") or 0)
        speed = self.speed_for(seg)
        if s_dur and t_dur and abs(t_dur - s_dur / speed) > 1000:
            self.warnings.append(
                f"target != source/speed on {sid}: {t_dur} vs {s_dur / speed:.0f} (us)"
            )

        # `clip` is a SEGMENT field in this schema (segments[].clip = transform/scale/rotation).
        # Reading it off the material made every geometry channel null, which is why the player
        # and channel 2 both painted subtitles dead-centre while the draft says y=-0.4427
        # (found 2026-10-22 while chasing the cover-caption offset, Q-4).
        clip = seg.get("clip") or (mat.get("clip") if mat else None)
        out = {
            "id": sid,
            "track": {"type": track.get("type"), "flag": track.get("flag"), "attribute": track.get("attribute")},
            "material": {"bucket": bucket, "id": seg.get("material_id"), "type": (mat or {}).get("type")},
            "target": {"start_us": t_start, "duration_us": t_dur},
            "source": {"start_us": s_start, "duration_us": s_dur},
            "speed": speed,
            "render_index": seg.get("render_index"),
            # 轨道级叠序键。语料里 1412/2218 份草稿带它（`render_index_track_mode_on` 为 true 的 1576 份），
            # 以前 L1 根本不复制 ⇒ 下面的叠序哨兵会恒等通过（我第一次的负样本测试就是这么暴露的）。
            # 值按剪映的写法**继承轨上第一个非空值**：它挂在段上，但语义是轨级的。
            "track_render_index": seg.get("track_render_index"),
            # Segment-level level control. `materials.audios[].volume` is null on all 37 clips of
            # this draft, so reading only the material's volume silently drops the real attenuation:
            # 4 of 104 segments write a non-default one here, three of them the music bed at
            # 0.3981 = exactly -8 dB (F-076). Absent means 1.0.
            "volume": seg.get("volume"),
            # Absent on 102 of this draft's 104 segments; the two that carry it are hidden
            # overlays at t=0 that both renderers were painting (F-071, found by the export).
            "visible": seg.get("visible", True),
            "clip": None,
            "media": None,
            "text": None,
            "features": {},
            "extra_refs": refs,
            # 混合模式以 effects 资源实现（F-049/U-12）：语料里没有 blend_mode/mix_mode 段键，
            # 判别是 extra_material_refs -> materials.effects[type=="mix_mode"]，包身份是 path 尾段的 md5。
            "mix_mode": None,
            "animations": [],
        }
        if clip:
            tf = clip.get("transform") or {}
            out["clip"] = {
                "x": tf.get("x", 0.0), "y": tf.get("y", 0.0),
                "scale_x": (clip.get("scale") or {}).get("x", 1.0),
                "scale_y": (clip.get("scale") or {}).get("y", 1.0),
                "rotation": clip.get("rotation", 0.0),
                "alpha": clip.get("alpha", 1.0),
                "flip": clip.get("flip"),
            }
        an = self.animations_for(refs)
        if an:
            out["animations"] = an

        for r in refs:
            if r["bucket"] != "effects":
                continue
            item = self.buckets[r["id"]][1]
            if item.get("type") != "mix_mode":
                continue
            pkg = str(item.get("path") or "").replace("\\", "/").rstrip("/").split("/")[-1]
            out["mix_mode"] = {"name": item.get("name"), "package_md5": pkg, "ref": r["id"]}
            break

        if mat and mat.get("path"):
            p = resolve_path(mat["path"], self.draft_root)
            out["media"] = {
                "raw_path": mat.get("path"),
                "path": p,
                "exists": bool(p) and os.path.isfile(p),
                "width": mat.get("width"), "height": mat.get("height"),
                "duration_us": mat.get("duration"),
                "material_type": mat.get("type"),
                "container": probe_container(p),
            }
        if bucket == "audios" and mat:
            out["audio"] = {
                "volume": mat.get("volume"),
                "duration_us": mat.get("duration"),
                "channel_layout": mat.get("channel_layout"),
                "type": mat.get("type"),
                "loudness": self.ref_of(refs, "loudnesses"),
                "fade": self.ref_of(refs, "audio_fades"),
            }
        # 视频段也引用 loudnesses / audio_fades：剪映对**烘焙进组合缓存**的那条音轨做响度归一
        # （实测一条 `enable:true, target_loudness:-12.0, avg_loudness:-9.26`，且它的
        # time_range.duration=6.6 s 正等于主轨第一段的长度 ⇒ 归一对象就是组合音频）。
        # 原来只在 audios 桶建 `audio`，视频段的归一信息整个不落模型，于是口播的替换音源
        # 按满增益进混音：peak_fs 1.30→2.05、满刻度窗 33→458（P-88）。
        if bucket == "videos" and mat:
            loud = self.ref_of(refs, "loudnesses")
            fade = self.ref_of(refs, "audio_fades")
            if loud or fade:
                out["audio"] = {
                    "volume": mat.get("volume"),
                    "duration_us": mat.get("duration"),
                    "channel_layout": mat.get("channel_layout"),
                    "type": mat.get("type"),
                    "loudness": loud,
                    "fade": fade,
                }
        if bucket == "texts" and mat:
            content = load_json_string(mat.get("content") or "")
            styles = (content or {}).get("styles") or []
            out["text"] = {
                "text": (content or {}).get("text"),
                "alignment": mat.get("alignment"),
                "font_size": mat.get("font_size"),
                "text_color": mat.get("text_color"),
                "style_count": len(styles),
                "styles": [style_of(s, self.fonts) for s in styles],
                "strokes": sum(len(s.get("strokes") or []) for s in styles),
                "shadows": sum(len(s.get("shadows") or []) for s in styles),
                "effect_style": sorted({s.get("effect_style_id") for s in styles if s.get("effect_style_id")}),
                "check_flag": mat.get("check_flag"),
            }
        # A composite is identified by its drafts[] reference, not by an unreadable file:
        # this draft's track 6 segment carries a combination ref and **no media at all**, so a
        # readability-only predicate silently dropped a five-track child timeline (cover
        # caption and logo layer included). Prefer the render cache when it decodes; recurse
        # whenever there is no readable cache.
        has_draft = any(r["bucket"] == "drafts" for r in refs)
        cache_ok = bool(out.get("media")) and out["media"].get("container", {}).get("readable")
        if has_draft and not cache_ok:
            comp = self.expand_composite(refs)
            if comp is not None:
                out["composite"] = comp
        out["features"] = self.features(seg, mat, refs)
        return out

    def expand_composite(self, refs: list[dict]) -> dict | None:
        """Rebuild a composite segment from the child timeline embedded in materials.drafts[].

        JianYing encrypts the composite render cache (Resources/combination/*_video.mp4 has no
        box header), but the draft entry carries the child's tracks *and its own materials*
        inline - measured on this draft: 0 of 1 .. 0 of 97 child material ids resolve against
        the parent's bucket set. So the picture is rebuildable without reading subdraft/.
        """
        if self.depth >= self.MAX_COMPOSITE_DEPTH:
            return None
        for r in refs:
            if r["bucket"] != "drafts":
                continue
            entry = self.buckets[r["id"]][1]
            child = entry.get("draft")
            if not isinstance(child, dict) or not child.get("tracks"):
                continue
            built = Model(child, self.draft_root, self.depth + 1).build()
            built["composite_type"] = entry.get("type")
            built["child_id"] = child.get("id")
            return built
        return None

    def ref_of(self, refs: list[dict], bucket: str) -> dict | None:
        """First extra_material_ref resolving into `bucket`, as the raw entry."""
        for r in refs:
            if r["bucket"] == bucket:
                return self.buckets[r["id"]][1]
        return None

    def _tw_tables(self, path: str, name: str | None):
        """把「打字光标」那两张**写死的**节奏表塞进模型条目（F-087）。

        浏览器读不了包内 lua（网关只按 id 发媒体/字体），而这条律的表是常量不是随机数，
        所以随模型带 28 个浮点是让两通道共用**同一条律**的最小代价——比在页面里另抄一份强。
        """
        if name != "打字光标" or not path:
            return None
        cache = self.__dict__.setdefault("_tw_cache", {})
        if path not in cache:
            try:
                import animation_curve as ac
                cache[path] = ac.load_typewriter(path)
            except Exception:                               # noqa: BLE001
                cache[path] = None
        return cache[path]

    def animations_for(self, refs: list[dict]) -> list[dict]:
        """把 extra_material_refs -> materials.material_animations[] 解成渲染可用的条目。

        两种形状都收（版本差异未判，所以不许按形状丢弃）：
          A. `material_animations[] = {type:"sticker_animation", animations:[{type:"in",duration,path,...}]}`
             —— 本测试草稿 65 段全走这条（P-29：「向上闪入」0.3 s 就是这样丢的）。
          B. `{in/out/loop: {actions:[...]}}` —— 规格 F-012 记的形，语料里是否仍存在未在本轮复核。
        """
        out = []
        for r in refs:
            if r["bucket"] != "material_animations":
                continue
            item = self.buckets[r["id"]][1]
            for a in item.get("animations") or []:
                if not isinstance(a, dict):
                    continue
                path = str(a.get("path") or "")
                out.append({
                    "kind": a.get("type"),
                    "name": a.get("name"),
                    "duration_us": a.get("duration"),
                    # `start` 是该动画在片段内的起始偏移（animations.yaml:15/:33）；
                    # 缺席时按 kind 推：in 从段头起，out 从段尾倒推（F-078：窗口算错=动画常驻或永不生效）
                    "start_us": a.get("start"),
                    "resource_id": a.get("resource_id"),
                    "category_name": a.get("category_name"),
                    "panel": a.get("panel"),
                    "material_type": a.get("material_type"),
                    "path": path or None,
                    "package_exists": bool(path) and os.path.isdir(path),
                    "tw": self._tw_tables(path, a.get("name")),
                    "anim_material_id": item.get("id"),
                })
            for k in ("in", "out", "loop"):
                block = item.get(k) or {}
                for a in (block.get("actions") or []) if isinstance(block, dict) else []:
                    if not isinstance(a, dict):
                        continue
                    out.append({"kind": k, "name": a.get("name"), "duration_us": a.get("duration"),
                                "resource_id": a.get("resource_id"), "category_name": None,
                                "panel": None, "material_type": None, "path": a.get("path") or None,
                                "package_exists": bool(a.get("path")) and os.path.isdir(a["path"]),
                                "anim_material_id": item.get("id")})
        return out

    def features(self, seg: dict, mat: dict | None, refs: list[dict]) -> dict:
        present = {r["bucket"] for r in refs}
        fx = {}
        if "material_animations" in present:
            fx["animation"] = sorted({a["kind"] for a in self.animations_for(refs)})
        if "transitions" in present:
            names = [self.buckets[r["id"]][1].get("name") for r in refs if r["bucket"] == "transitions"]
            fx["transition"] = names
        if seg.get("common_mask") or seg.get("masks"):
            cfg = (seg.get("common_mask") or {}).get("config") or {}
            fx["mask"] = {"invert": cfg.get("invert"), "feather": cfg.get("feather"), "type": cfg.get("type")}
        if seg.get("common_keyframes"):
            fx["keyframes"] = sorted({k.get("property_type", "").split("_")[-1] for k in seg["common_keyframes"]})
        effect_types = set()
        for r in refs:
            if r["bucket"] == "effects":
                b, item = self.buckets[r["id"]]
                if item.get("type"):
                    effect_types.add(item["type"])
        if effect_types:
            fx["effects"] = sorted(effect_types)
        crop = (mat or {}).get("crop") or {}
        if crop and not (
            crop.get("upper_left_x", 0) == 0 and crop.get("upper_left_y", 0) == 0
            and crop.get("lower_right_x", 1) == 1 and crop.get("lower_right_y", 1) == 1
        ):
            fx["crop_non_identity"] = True
        if (mat or {}).get("chroma") or (mat or {}).get("bright"):
            fx["grade_present"] = True
        return fx

    def build(self) -> dict:
        draft = self.draft
        canvas = draft.get("canvas_config") or {}
        tracks_out = []
        seg_count = 0
        max_end = 0
        for ti, track in enumerate(draft.get("tracks") or []):
            segs = []
            spans = []
            for seg in track.get("segments") or []:
                m = self.segment(seg, track)
                segs.append(m)
                s, d = m["target"]["start_us"], m["target"]["duration_us"]
                spans.append((s, s + d, m["id"]))
                max_end = max(max_end, s + d)
                seg_count += 1
            spans.sort()
            for (a0, a1, aid), (b0, b1, bid) in zip(spans, spans[1:]):
                if b0 < a1:
                    self.errors.append(f"track {ti} ({track.get('type')}) overlap: {aid} [{a0},{a1}) vs {bid} [{b0},{b1})")
            tracks_out.append({
                "index": ti, "type": track.get("type"), "flag": track.get("flag"),
                "attribute": track.get("attribute"), "is_master": track.get("is_master"),
                "name": track.get("name"), "segments": segs,
            })

        declared = int(draft.get("duration") or 0)
        if declared and abs(declared - max_end) > 1000:
            self.warnings.append(f"top duration {declared} != last segment end {max_end} (us)")

        feats: dict[str, int] = {}
        media: dict[str, dict] = {}
        for t in tracks_out:
            for s in t["segments"]:
                for k in s["features"]:
                    feats[k] = feats.get(k, 0) + 1
                mm = s["media"]
                if mm and mm.get("path"):
                    readable = bool(mm.get("container", {}).get("readable"))
                    e = media.setdefault(mm["path"], {"exists": mm["exists"], "readable": readable,
                                                      "segments": 0, "type": mm.get("material_type"),
                                                      "container": mm.get("container")})
                    e["segments"] += 1
                    e["exists"] = e["exists"] and mm["exists"]
                    e["readable"] = e["readable"] and readable
        missing = sorted(p for p, e in media.items() if not e["exists"])
        unreadable = sorted(p for p, e in media.items() if e["exists"] and not e["readable"])

        def merge(sub: dict) -> None:
            for f in sub.get("fonts", []):
                self.fonts.setdefault(f["path"], f)
            for e in sub.get("media", []):
                cur = media.setdefault(e["path"], dict(e, segments=0))
                cur["segments"] += e["segments"]
                cur["exists"] = cur["exists"] and e["exists"]
                cur["readable"] = cur["readable"] and e["readable"]
            for t in sub.get("tracks", []):
                for s in t["segments"]:
                    if s.get("composite"):
                        merge(s["composite"])

        for t in tracks_out:
            for s in t["segments"]:
                if s.get("composite"):
                    merge(s["composite"])
        missing = sorted(p for p, e in media.items() if not e["exists"])
        unreadable = sorted(p for p, e in media.items() if e["exists"] and not e["readable"])

        def count_geometry(nodes):
            """How many segments (composites included) carry a clip, how many are hidden, and how
            many set a level. The clip count is the guard against reading `clip` off the wrong
            object again: that mistake silently produced 0/136."""
            hit = tot = hidden = vol = 0
            for tr in nodes:
                for sg in tr["segments"]:
                    tot += 1
                    hit += 1 if sg.get("clip") else 0
                    hidden += 1 if sg.get("visible") is False else 0
                    v = sg.get("volume")
                    vol += 1 if v is not None and abs(v - 1.0) > 1e-6 else 0
                    if sg.get("composite"):
                        h2, t2, x2, v2 = count_geometry(sg["composite"]["tracks"])
                        hit += h2
                        tot += t2
                        hidden += x2
                        vol += v2
            return hit, tot, hidden, vol

        # 叠序归属（U-15）的**发现器**，不是新律：语料 2218 份草稿里 `render_index_track_mode_on`
        # 为 true 的有 1576 份、带 `track_render_index` 的 1412 份，但"按 tri 排"与"按轨道列表位置排"
        # 在两律之间**从未在任何瞬间产生过不同次序**（temp/playback-test/u15_corpus_scan.py：可判对象 0 例，
        # 唯一一例次序不一致也只是两条轨并列同一个值，不是反转）⇒ 不凭推断改渲染次序，只留哨兵：
        # 真出现反转的草稿必须拿成片重判，而不是让渲染器按一个未证的律走。
        def _first_tri(tr):
            for sg in tr["segments"]:
                if sg.get("track_render_index") is not None:
                    return sg["track_render_index"]
            return None

        _keys = [(_first_tri(tr) if _first_tri(tr) is not None else -1, i)
                 for i, tr in enumerate(tracks_out)]
        if [i for _, i in sorted(_keys, key=lambda p: p[0])] != list(range(len(tracks_out))):
            self.warnings.append(
                "track_render_index order != track list order "
                f"(mode_on={draft.get('render_index_track_mode_on')}) ⇒ 叠序两律在此草稿上会分叉，"
                "U-15 需按成片重判，别照现行律出图")

        geo_hit, geo_tot, geo_hidden, geo_vol = count_geometry(tracks_out)
        # 轨类型的**覆盖分母**（U-98）：画面腿只走 video/text，声音腿只走 audio/video，
        # 于是 mixed / sticker / effect / adjust / filter 这几类轨被静默丢掉——语料尺度上
        # mixed 有 930 条轨 / 355 份草稿（其中材料桶是 videos 1723 + texts 848，是真内容），
        # sticker 280 条。不报错的丢失最难发现，所以先把"没被任何腿路由的段数"变成数。
        _rendered = ("video", "text", "audio")
        type_segs: dict = {}
        unrouted = 0
        for tr in tracks_out:
            ty = tr.get("type") or "?"
            n = len(tr.get("segments") or [])
            type_segs[ty] = type_segs.get(ty, 0) + n
            if ty not in _rendered:
                unrouted += n
        return {
            "timeline_id": draft.get("id"),
            "duration_us": declared,
            "last_segment_end_us": max_end,
            "canvas": canvas,
            "render_index_track_mode_on": draft.get("render_index_track_mode_on"),
            "platform": draft.get("platform"),
            "version": {"version": draft.get("version"), "new_version": draft.get("new_version")},
            "tracks": tracks_out,
            "fonts": list(self.fonts.values()),
            "stats": {
                "track_count": len(tracks_out),
                "segment_count": seg_count,
                "media_count": len(media),
                "media_missing": len(missing),
                "media_unreadable": len(unreadable),
                "geometry_segments": geo_hit,
                "geometry_total": geo_tot,
                "invisible_segments": geo_hidden,
                "volume_segments": geo_vol,
                "track_type_segments": type_segs,
                "unrouted_track_segments": unrouted,
                "mix_mode_segments": sum(1 for tr in tracks_out for s in tr["segments"]
                                         if s.get("mix_mode")),
                "animation_segments": sum(1 for tr in tracks_out for s in tr["segments"]
                                          if s.get("animations")),
                "feature_counts": dict(sorted(feats.items(), key=lambda kv: -kv[1])),
            },
            "media": [{"path": p, **e} for p, e in sorted(media.items())],
            "missing_media": missing,
            "unreadable_media": unreadable,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("plain", help="decrypted draft_content.json")
    ap.add_argument("--draft-root", required=True)
    ap.add_argument("--out", default="temp/playback-test/model.json")
    ap.add_argument("--timeline", help="check the decoded content-id against this timeline id")
    args = ap.parse_args()

    raw = Path(args.plain).read_bytes()
    if not raw.lstrip(b"\xef\xbb\xbf").startswith(b"{"):
        print("not plaintext - decrypt first via scripts/jy_crypto/worker.py", file=sys.stderr)
        return 2
    draft = json.loads(raw.decode("utf-8-sig"))
    if args.timeline and draft.get("id") != args.timeline:
        print(f"content-id {draft.get('id')} != requested timeline {args.timeline}", file=sys.stderr)
        return 2

    model = Model(draft, Path(args.draft_root)).build()
    out = scratch_out(Path(args.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, ensure_ascii=False, indent=1), encoding="utf-8")

    s = model["stats"]
    print(f"timeline {model['timeline_id']}  {model['duration_us']/1e6:.2f} s  "
          f"{model['canvas'].get('width')}x{model['canvas'].get('height')}")
    print(f"tracks {s['track_count']}  segments {s['segment_count']}  "
          f"media {s['media_count']} (missing {s['media_missing']}, unreadable {s['media_unreadable']})  "
          f"geometry {s['geometry_segments']}/{s['geometry_total']}  "
          f"hidden {s['invisible_segments']}  level-set {s['volume_segments']}")
    print("features:", json.dumps(s["feature_counts"], ensure_ascii=False))
    for t in model["tracks"]:
        segs = t["segments"]
        kinds = sorted({x["material"]["bucket"] for x in segs if x["material"]["bucket"]})
        print(f"  T{t['index']:02d} {t['type']:<6} flag={t['flag']} segs={len(segs):>3} buckets={kinds}")
    print(f"errors {len(model['errors'])}  warnings {len(model['warnings'])}")
    for e in model["errors"][:10]:
        print("  E", e)
    for w in model["warnings"][:10]:
        print("  W", w)
    return 0 if not model["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
