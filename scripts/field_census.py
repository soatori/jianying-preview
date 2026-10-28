"""Census the three panel-conversion families this round adjudicated.

Reads only content keys listed in temp/corpus-scan/manifest.json, so the stale plain/ leftovers
(F-030) cannot enter a count. Emits:

  shadow_style_keys.csv   materials.texts[].content -> styles[].shadows[]  key census + value ranges,
                          with the panel/600 fit test for the blur-family keys
  video_crop_census.csv   materials.videos[].crop shape census, per-corner ranges, crop_ratio
                          histogram, crop_scale, corner_pin structure
  fill_alpha_pairing.csv  styles[].fill.alpha vs styles[].fill.content.solid.alpha co-occurrence

Usage: python scripts/field_census.py
"""
import argparse
import collections
import csv
import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'temp' / 'corpus-scan' / 'manifest.json'
PLAIN = ROOT / 'temp' / 'corpus-scan' / 'plain'
OUT = ROOT / 'docs' / 'evidence' / 'tables'

CORNER_KEYS = ['upper_left_x', 'upper_left_y', 'upper_right_x', 'upper_right_y',
               'lower_left_x', 'lower_left_y', 'lower_right_x', 'lower_right_y']
FULL_CROP = {'upper_left_x': 0.0, 'upper_left_y': 0.0, 'upper_right_x': 1.0, 'upper_right_y': 0.0,
             'lower_left_x': 0.0, 'lower_left_y': 1.0, 'lower_right_x': 1.0, 'lower_right_y': 1.0}


def is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def parse_content(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
        except Exception:
            return None
        return v if isinstance(v, dict) else None
    return None


def write_rows(name, header, rows):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / name).open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--blur-divisor', type=float, default=600.0,
                    help='candidate panel->engine divisor from the xmldraft shadow-blur range (0..1/6)')
    args = ap.parse_args()

    valid = {r['key'] for r in json.loads(MANIFEST.read_text(encoding='utf-8')) if r.get('key')}

    sh_present = collections.Counter()          # shadow key -> occurrences
    sh_contents = collections.defaultdict(set)  # shadow key -> content keys
    sh_vals = collections.defaultdict(collections.Counter)
    fill_keys = collections.Counter()
    content_keys = collections.Counter()
    styles_total = 0
    shadow_total = 0
    pair = collections.Counter()
    pair_diff = []

    crop_shape = collections.Counter()
    crop_vals = collections.defaultdict(list)
    crop_contents = collections.defaultdict(set)
    crop_ratio = collections.Counter()
    crop_scale = collections.Counter()
    corner_pin_shape = collections.Counter()
    corner_pin_vals = collections.defaultdict(list)
    seg_keys = collections.Counter()
    seg_contents = collections.defaultdict(set)
    videos_total = 0

    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        key = os.path.basename(path)[:-5]
        if key not in valid:
            continue
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        mat = doc.get('materials') or {}

        for t in mat.get('texts') or []:
            content = parse_content(t.get('content'))
            if not content:
                continue
            for st in content.get('styles') or []:
                if not isinstance(st, dict):
                    continue
                fill = st.get('fill')
                if isinstance(fill, dict):
                    styles_total += 1
                    fill_keys.update(fill.keys())
                    fc = fill.get('content')
                    if isinstance(fc, dict):
                        content_keys.update(fc.keys())
                        solid = fc.get('solid')
                        if isinstance(solid, dict):
                            content_keys.update('solid.' + k for k in solid)
                    has_a = 'alpha' in fill
                    has_b = isinstance(solid, dict) and 'alpha' in solid
                    if has_a and has_b:
                        pair['both_present'] += 1
                        a, b = fill['alpha'], solid['alpha']
                        if not (is_num(a) and is_num(b)) or abs(a - b) > 1e-9:
                            pair['both_differ_gt_1e-9'] += 1
                            pair_diff.append((a, b))
                        else:
                            pair['both_equal'] += 1
                    elif has_a:
                        pair['fill_alpha_only'] += 1
                    elif has_b:
                        pair['solid_alpha_only'] += 1
                    else:
                        pair['neither'] += 1
                for s in (st.get('shadows') or []) if isinstance(st.get('shadows'), list) else []:
                    if not isinstance(s, dict):
                        continue
                    shadow_total += 1
                    for k, v in s.items():
                        sh_present[k] += 1
                        sh_contents[k].add(key)
                        if is_num(v):
                            sh_vals[k][round(v, 6)] += 1

        for tr in doc.get('tracks') or []:
            for sg in tr.get('segments') or []:
                if isinstance(sg, dict):
                    seg_keys.update(k for k in sg)
                    for k in ('render_index', 'track_render_index', 'track_attribute',
                              'group_id', 'template_id', 'visible'):
                        if k in sg:
                            seg_contents[k].add(key)

        for v in mat.get('videos') or []:
            videos_total += 1
            c = v.get('crop')
            if isinstance(c, dict):
                crop_shape[f'dict_keys_{len(c)}'] += 1
                if len(c) == 8:
                    if all(is_num(c.get(k)) and abs(c[k] - FULL_CROP[k]) < 1e-12 for k in CORNER_KEYS):
                        crop_shape['dict_keys_8_equal_full_frame_identity'] += 1
                    else:
                        crop_shape['dict_keys_8_actual_crop'] += 1
                for ck, cv in c.items():
                    if is_num(cv):
                        crop_vals[ck].append(cv)
                        crop_contents[ck].add(key)
            elif 'crop' in v:
                crop_shape[f'not_a_dict_{type(c).__name__}'] += 1
            else:
                crop_shape['absent'] += 1
            if 'crop_ratio' in v:
                crop_ratio[f'{type(v["crop_ratio"]).__name__}:{v["crop_ratio"]}'] += 1
            if 'crop_scale' in v:
                crop_scale[round(v['crop_scale'], 6) if is_num(v['crop_scale'])
                          else f'non-num:{v["crop_scale"]}'] += 1
            cp = v.get('corner_pin')
            if 'corner_pin' in v:
                if isinstance(cp, dict):
                    corner_pin_shape['dict:' + ','.join(sorted(cp))] += 1
                    info = cp.get('corner_pin_info')
                    if isinstance(info, dict):
                        for ck, cv in info.items():
                            if is_num(cv):
                                corner_pin_vals[ck].append(cv)
                else:
                    corner_pin_shape[f'{type(cp).__name__}'] += 1

    blur = args.blur_divisor
    rows = []
    for k in sorted(sh_present, key=lambda x: -sh_present[x]):
        vals = sorted(sh_vals.get(k, {}))
        fit = ''
        if k in ('diffuse', 'feather') and vals:
            hits = sum(c for v, c in sh_vals[k].items() if abs(v * blur - round(v * blur)) < 1e-3)
            fit = f'{hits}/{sum(sh_vals[k].values())} land on an integer panel value at panel/{blur:g}'
        rows.append([k, sh_present[k], len(sh_contents[k]), len(vals),
                     vals[0] if vals else '', vals[-1] if vals else '',
                     ' '.join(f'{v}:{c}' for v, c in sh_vals[k].most_common(5)), fit])
    write_rows('shadow_style_keys.csv',
               ['shadow_key', 'occurrences', 'contents', 'distinct_numeric_values', 'min', 'max',
                'top_values', 'panel_divisor_fit'], rows)

    rows = []
    for ck in CORNER_KEYS:
        vs = crop_vals.get(ck, [])
        rows.append(['crop.' + ck, len(vs), len(crop_contents.get(ck, ())),
                     min(vs) if vs else '', max(vs) if vs else ''])
    for shape, cnt in crop_shape.most_common():
        rows.append([f'videos[].crop {shape}', cnt, '', '', ''])
    for r, cnt in crop_ratio.most_common():
        rows.append([f'videos[].crop_ratio {r}', cnt, '', '', ''])
    for s, cnt in crop_scale.most_common(8):
        rows.append([f'videos[].crop_scale {s}', cnt, '', '', ''])
    for shape, cnt in corner_pin_shape.most_common():
        rows.append([f'videos[].corner_pin {shape}', cnt, '', '', ''])
    for ck, vs in sorted(corner_pin_vals.items()):
        rows.append([f'corner_pin.corner_pin_info.{ck}', len(vs), '', min(vs), max(vs)])
    write_rows('video_crop_census.csv', ['field', 'count', 'contents', 'min', 'max'], rows)

    write_rows('fill_alpha_pairing.csv', ['case', 'styles_count'],
               [[k, pair[k]] for k in sorted(pair)] +
               [['styles_with_fill', styles_total], ['shadow_entries', shadow_total],
                ['threshold', ''] ])

    seg_index_rows = [[k, seg_keys[k], len(seg_contents[k])]
                      for k in ['render_index', 'track_render_index', 'track_attribute',
                                'group_id', 'template_id', 'visible'] if k in seg_keys]
    write_rows('segment_index_keys.csv', ['segment_key', 'occurrences', 'contents'], seg_index_rows)

    summary = {
        'contents_scanned': len(valid),
        'video_materials': videos_total,
        'styles_with_fill': styles_total,
        'shadow_entries': shadow_total,
        'fill_alpha_pairing': dict(pair),
        'blur_divisor': blur,
        'diffuse_top': sh_vals['diffuse'].most_common(6),
        'feather_top': sh_vals['feather'].most_common(6),
        'crop_shape': dict(crop_shape),
        'crop_ratio': dict(crop_ratio.most_common(10)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
