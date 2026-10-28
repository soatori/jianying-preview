"""Rebuild the track / segment / material-type matrices from the frozen r3 scan.

Reads only the content keys listed in temp/corpus-scan/manifest.json, so the stale plain/ leftovers
(F-030) cannot enter any count. Writes docs/evidence/tables/{track_types,segment_shapes,
track_material_map,material_type_enums,render_index_bands_by_type}.csv and prints a short report.

Usage: python scripts/track_matrix.py [--json-out temp/track-probe/matrix.json]
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

BANDS = [(0, 999, '0-999'), (1000, 9999, '1000-9999'), (10000, 10999, '10000-10999'),
         (11000, 13999, '11000-13999'), (14000, 14999, '14000-14999'),
         (15000, 15999, '15000-15999'), (16000, 18999, '16000-18999'),
         (19000, 10 ** 9, '19000+')]
TRACK_KEYS = ['id', 'type', 'segments', 'is_default_name', 'flag', 'attribute', 'name']


def band_name(v):
    for lo, hi, name in BANDS:
        if lo <= v <= hi:
            return name
    return '<other>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json-out')
    args = ap.parse_args()

    valid = set(r['key'] for r in json.loads(MANIFEST.read_text(encoding='utf-8')) if r.get('key'))

    n_tracks = collections.Counter()
    track_key = collections.defaultdict(collections.Counter)
    track_flag = collections.defaultdict(collections.Counter)
    track_attr = collections.defaultdict(collections.Counter)
    idn = collections.Counter()
    idn_ty = collections.defaultdict(collections.Counter)
    segs = collections.Counter()
    keysets = collections.defaultdict(collections.Counter)
    bands = collections.defaultdict(collections.Counter)
    refs = collections.Counter()
    mat_enum = collections.defaultdict(collections.Counter)
    unresolved = collections.Counter()
    n_contents = 0

    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        if os.path.basename(path)[:-5] not in valid:
            continue
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        n_contents += 1
        mats = d.get('materials') or {}
        index = {}
        for bname, bval in mats.items():
            if not isinstance(bval, list):
                continue
            for item in bval:
                if isinstance(item, dict) and isinstance(item.get('id'), str):
                    t = item.get('type')
                    if isinstance(t, str):
                        mat_enum[bname][t or '<empty-string>'] += 1
                        index[item['id']] = (bname, t)
        for t in d.get('tracks') or []:
            if not isinstance(t, dict):
                continue
            ty = str(t.get('type', '<absent>'))
            n_tracks[ty] += 1
            for k in TRACK_KEYS:
                if k in t:
                    track_key[ty][k] += 1
            idn_ty[ty][repr(t.get('is_default_name', '<absent>'))] += 1
            idn[repr(t.get('is_default_name', '<absent>'))] += 1
            track_flag[ty][repr(t.get('flag', '<absent>'))] += 1
            track_attr[ty][repr(t.get('attribute', '<absent>'))] += 1
            for s in t.get('segments') or []:
                if not isinstance(s, dict):
                    continue
                segs[ty] += 1
                keysets[ty][tuple(sorted(s.keys()))] += 1
                ri = s.get('render_index')
                if isinstance(ri, int):
                    bands[ty][band_name(ri)] += 1
                ref = s.get('material_id')
                if isinstance(ref, str):
                    if ref in index:
                        b, bt = index[ref]
                        refs['%s|%s.%s' % (ty, b, bt)] += 1
                    else:
                        unresolved[ty] += 1

    OUT.mkdir(parents=True, exist_ok=True)

    def write(name, header, rows):
        with (OUT / name).open('w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)
        print('wrote %s/%s (%d rows)' % (OUT.name, name, len(rows)))

    order = [ty for ty, _ in n_tracks.most_common()]
    write('track_types.csv',
          ['track_type', 'n_tracks', 'n_segments', 'has_id', 'has_type', 'has_segments',
           'has_name', 'has_attribute', 'has_flag', 'is_default_name_true', 'is_default_name_false',
           'flag_values', 'attribute_values'],
          [[ty, n_tracks[ty], segs[ty], track_key[ty]['id'], track_key[ty]['type'],
            track_key[ty]['segments'], track_key[ty]['name'], track_key[ty]['attribute'],
            track_key[ty]['flag'], idn_ty[ty]['True'], idn_ty[ty]['False'],
            ' '.join('%s:%s' % (v, c) for v, c in track_flag[ty].most_common()),
            ' '.join('%s:%s' % (v, c) for v, c in track_attr[ty].most_common())] for ty in order])

    rows = []
    for ty in order:
        dist = keysets[ty]
        tot = segs[ty]
        for ks, c in dist.most_common(6):
            rows.append([ty, tot, len(dist), len(ks), c, '%.1f' % (100.0 * c / tot), ','.join(ks)])
    write('segment_shapes.csv',
          ['track_type', 'n_segments', 'distinct_keysets', 'n_keys', 'segments', 'share_pct', 'keys'], rows)

    write('track_material_map.csv', ['track_type', 'bucket', 'bucket_type', 'segments_referencing'],
          [[k.split('|')[0], k.split('|')[1].split('.')[0], k.split('|')[1].split('.', 1)[1], c]
           for k, c in sorted(refs.items(), key=lambda kv: (-kv[1], kv[0]))])

    write('material_type_enums.csv', ['bucket', 'type_value', 'entries'],
          [[b, v, c] for b in sorted(mat_enum) for v, c in mat_enum[b].most_common()])

    names = [n for _, _, n in BANDS]
    write('render_index_bands_by_type.csv', ['track_type'] + names + ['total_with_render_index'],
          [[ty] + [bands[ty].get(n, 0) for n in names] + [sum(bands[ty].values())] for ty in order])

    print('\ncontents=%d  tracks=%d  segments=%d' % (n_contents, sum(n_tracks.values()), sum(segs.values())))
    print('is_default_name:', dict(idn))
    print('unresolved material_id refs:', dict(unresolved))
    for ty in order:
        top = keysets[ty].most_common(1)[0]
        print('  %-7s tracks=%-6d segments=%-6d keysets=%-4d top=%d keys @%.1f%%' %
              (ty, n_tracks[ty], segs[ty], len(keysets[ty]), len(top[0]), 100.0 * top[1] / segs[ty]))
    fortyfive = collections.Counter()
    for ty in order:
        for ks, c in keysets[ty].items():
            if len(ks) == 45:
                fortyfive[ty] += c
    print('45-key segments:', sum(fortyfive.values()), dict(fortyfive))

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out), exist_ok=True)
        json.dump({'n_contents': n_contents,
                   'n_tracks': n_tracks.most_common(), 'segs': segs.most_common(),
                   'track_key': {k: v.most_common() for k, v in track_key.items()},
                   'flag': {k: v.most_common() for k, v in track_flag.items()},
                   'attribute': {k: v.most_common() for k, v in track_attr.items()},
                   'is_default_name': idn.most_common(),
                   'bands': {k: v.most_common() for k, v in bands.items()},
                   'refs': refs.most_common(), 'mat_enum': {k: v.most_common() for k, v in mat_enum.items()},
                   'unresolved': unresolved.most_common()},
                  open(args.json_out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
