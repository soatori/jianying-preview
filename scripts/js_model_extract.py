"""Extract JianYing's own draft-JSON model layer out of the canvas_agent editor chunks and diff it
against the r3 corpus key set.

Target A finding: `app/static/js/ai-creation~10.js` and `ai-creation~11.js` carry a generated
per-class field table `{common:[...], bigint:{...}, array:{...}, object:{...}}` plus a constructor
that assigns a default to every key. That is the vendor's own field inventory and default set.

Read-only over the install dir; reads the corpus only through temp/corpus-scan/manifest.json keys.
Writes docs/evidence/tables/js_model_keys.csv and temp/rea/js_model_diff.json.

Usage: python temp/rea/js_schema.py [--corpus]
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / 'temp' / '_js'          # placeholder, replaced below
APP_JS = Path('D:/Program Files/JianyingPro/11.6.0.14552/Resources/canvas_agent/app/static/js')
MANIFEST = ROOT / 'temp' / 'corpus-scan' / 'manifest.json'
PLAIN = ROOT / 'temp' / 'corpus-scan' / 'plain'
OUT = ROOT / 'docs' / 'evidence' / 'tables'
TEMP = ROOT / 'temp' / 'rea'

TARGETS = ['ai-creation~10.0176e5c4.js', 'ai-creation~11.aa2812ea.js']
NOISE = {'type', 'clsName', 'nullable', 'common', 'bigint', 'array', 'object', 'items', 'key'}
CLASS_MARKERS = [
    ('draft_root', 'render_index_track_mode_on'),
    ('segment', 'track_render_index'),
    ('material_video', 'duration_sec'),
    ('text_material', 'text_overlap'),
]


def match_obj(text, start):
    depth = 0
    i = start
    n = len(text)
    in_str = None
    while i < n:
        ch = text[i]
        if in_str:
            if ch == '\\':
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in '"\'':
            in_str = ch
        elif ch in '{[(':
            depth += 1
        elif ch in '}])':
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def list_field(block, section):
    m = re.search(r'\b' + section + r':\[', block)
    if not m:
        return []
    j = block.index('[', m.end() - 1)
    k = block.index(']', j)
    return re.findall(r'"([^"]+)"', block[j:k])


def map_keys(block, section):
    m = re.search(r'\b' + section + r':\{', block)
    if not m:
        return []
    j = block.index('{', m.end() - 1)
    k = match_obj(block, j)
    return [x for x in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)\s*:', block[j:k]) if x not in NOISE]


def snake(name):
    return re.sub(r'([A-Z])', lambda x: '_' + x.group(1).lower(), name)


def defaults_after(text, pos, span=5200):
    tail = text[pos:pos + span]
    out = {}
    for m in re.finditer(r'\be\.([A-Za-z][A-Za-z0-9_]*)=([^,;)]{1,48})', tail):
        key = snake(m.group(1))
        val = m.group(2).strip()
        out.setdefault(key, val)
    return out


def corpus_key_set():
    valid = {r['key'] for r in json.loads(MANIFEST.read_text(encoding='utf-8')) if r.get('key')}
    found = collections.Counter()

    def walk(node, depth):
        if depth > 12:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                found[k] += 1
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node:
                walk(v, depth + 1)

    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        if os.path.basename(path)[:-5] not in valid:
            continue
        walk(json.loads(Path(path).read_text(encoding='utf-8')), 0)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--corpus', action='store_true', help='also diff against the full corpus key set')
    args = ap.parse_args()

    recs = {}
    for fname in TARGETS:
        text = (APP_JS / fname).read_text(encoding='utf-8', errors='replace')
        for m in re.finditer(r'\{common:\[', text):
            end = match_obj(text, m.start())
            block = text[m.start():end]
            common = list_field(block, 'common')
            if len(common) < 3:
                continue
            bigint = map_keys(block, 'bigint')
            array = map_keys(block, 'array')
            object_ = map_keys(block, 'object')
            keys = common + bigint + array + object_
            sig = '|'.join(sorted(keys))
            dflt = {k: v for k, v in defaults_after(text, end).items() if k in keys}
            cls = 'other'
            for name, marker in CLASS_MARKERS:
                if marker in keys:
                    cls = name
                    break
            prev = recs.get(sig)
            if prev is None:
                recs[sig] = {'signature': sig, 'class_hint': cls, 'n_keys': len(keys),
                             'common': common, 'bigint': bigint, 'array': array, 'object': object_,
                             'defaults': dflt, 'chunks': {fname: 1}, 'offsets': [m.start()]}
            else:
                prev['chunks'][fname] = prev['chunks'].get(fname, 0) + 1
                if len(dflt) > len(prev['defaults']):
                    prev['defaults'] = dflt

    rows = []
    for sig, r in sorted(recs.items(), key=lambda x: -x[1]['n_keys']):
        rows.append({
            'class_hint': r['class_hint'], 'n_keys': r['n_keys'],
            'chunks': ';'.join(f'{k}={v}' for k, v in sorted(r['chunks'].items())),
            'common_keys': '|'.join(r['common']), 'bigint_keys': '|'.join(r['bigint']),
            'array_keys': '|'.join(r['array']), 'object_keys': '|'.join(r['object']),
            'defaults': ' '.join(f'{k}={v}' for k, v in sorted(r['defaults'].items())),
            'all_keys': '|'.join(sorted(set(sig.split('|')))),
        })
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'js_model_keys.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)

    js_keys = set()
    for r in recs.values():
        js_keys |= set(r['signature'].split('|'))
    summary = {'chunks': TARGETS, 'raw_records': sum(sum(v['chunks'].values()) for v in recs.values()),
               'distinct_records': len(recs), 'distinct_model_keys': len(js_keys)}

    if args.corpus:
        ck = corpus_key_set()
        corpus_keys = set(ck)
        summary['corpus_distinct_keys'] = len(corpus_keys)
        summary['model_only_count'] = len(js_keys - corpus_keys)
        summary['corpus_only_count'] = len(corner := (corpus_keys - js_keys))
        summary['model_only'] = sorted(js_keys - corpus_keys)
        (TEMP / 'js_model_diff.json').write_text(
            json.dumps({'model_only': sorted(js_keys - corpus_keys),
                        'counts': summary,
                        'corpus_only_top': [k for k, _ in ck.most_common() if k in (corpus_keys - js_keys)][:400]},
                       ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, list)}, ensure_ascii=False, indent=1))
    print(f'\ntop records: ')
    for r in rows[:8]:
        print(f"  {r['class_hint']:<16} n={r['n_keys']:<4} {r['chunks']}")
    print(f"  ... {len(rows)} distinct records total")


if __name__ == '__main__':
    main()
