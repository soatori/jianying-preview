"""Extract the render_index allocator rules from the canvas_agent chunks, and cross-tab
track.type against platform.app_version.

Two separate questions answered by one pass:

1. `render_index` bands are not semantics -- they are the constants inside a class the vendor
   calls RenderIndexUtils (nextVideo / nextFilter / nextAdjust / nextVideoEffect /
   nextPluginEffect / nextTextAndSticker). The bodies are readable in the shipped chunks.
2. `mixed` is not a generic "multi-content track" concept; it is a track type that only exists in
   a closed app_version range, and the 11.6 TrackType enum does not contain the strings "mixed"
   or "adjust" at all.

Read-only over the install dir; reads the corpus only through temp/corpus-scan/manifest.json keys.
Writes docs/evidence/tables/{render_index_allocators,track_type_by_app_version}.csv.

Usage: python scripts/render_index_allocators.py
"""
import collections
import csv
import glob
import json
import os
import re
from pathlib import Path

import jy_paths

ROOT = Path(__file__).resolve().parent.parent
APP_JS = jy_paths.app_js_dir()
MANIFEST = ROOT / 'temp' / 'corpus-scan' / 'manifest.json'
PLAIN = ROOT / 'temp' / 'corpus-scan' / 'plain'
OUT = ROOT / 'docs' / 'evidence' / 'tables'
ALLOC_CHUNK = 'ai-creation~15.f6ca3ef2.js'
ENUM_CHUNKS = None  # None = scan every chunk


def body(text, start):
    depth, i = 1, start
    while i < len(text) and depth:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
        i += 1
    return text[start:i - 1]


def extract_allocators():
    text = (APP_JS / ALLOC_CHUNK).read_text(encoding='utf-8', errors='replace')
    rows = []
    for m in re.finditer(r't\.(next[A-Za-z]*RenderIndex(?:WithTimeRange)?)=function\(([^)]*)\)\{', text):
        code = body(text, m.end()).replace('\n', '')
        consts = sorted({int(float(c)) for c in re.findall(r'\d+(?:e\d)?', code)})
        rows.append([m.group(1), m.group(2), str(consts), 'free mode' if 'freeRenderIndexModeOn' in code else '',
                     '+2' if re.search(r'\+2\}', code) or code.count('+2') else '', code[:400]])
    return rows


def extract_enums():
    names = {}
    counts = {}
    files = sorted(APP_JS.rglob('*.js')) if ENUM_CHUNKS is None else [APP_JS / f for f in ENUM_CHUNKS]
    for p in files:
        if not p.exists():
            continue
        text = p.read_text(encoding='utf-8', errors='replace')
        for m in re.finditer(r'(TrackType[A-Za-z]*|Flag[A-Za-z]*)\s*[:=]\s*"([^"]+)"', text):
            names.setdefault(m.group(1), set()).add(m.group(2))
        for m in re.finditer(r'(Flag[A-Za-z]*)\s*=\s*(\d+)', text):
            names.setdefault(m.group(1), set()).add(m.group(2))
    return names


def version_key(v):
    parts = re.findall(r'\d+', v)
    return tuple(int(x) for x in parts[:3]) if parts else (999,)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = extract_allocators()
    enums = extract_enums()

    valid = {r['key'] for r in json.loads(MANIFEST.read_text(encoding='utf-8')) if r.get('key')}
    tab = {}
    totals = {}
    contents = 0
    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        if os.path.basename(path)[:-5] not in valid:
            continue
        contents += 1
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        av = str(((doc.get('platform') or {}).get('app_version')) or 'NO_PLATFORM')
        for t in doc.get('tracks') or []:
            ty = str(t.get('type'))
            totals[ty] = totals.get(ty, 0) + 1
            tab.setdefault(ty, {})
            tab[ty][av] = tab[ty].get(av, 0) + 1

    with (OUT / 'render_index_allocators.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['allocator', 'args', 'numeric_constants', 'free_mode_branch', 'step_plus_2', 'body'])
        w.writerows(rows)
        for name in sorted(enums):
            w.writerow(['ENUM ' + name, '', '', '', '', '|'.join(sorted(enums[name]))])

    # sub-band shape: which allocator branch could have produced 15000+ values, and the
    # root flag that selects the branch
    sub_rows = []
    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        if os.path.basename(path)[:-5] not in valid:
            continue
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        flag = doc.get('free_render_index_mode_on')
        sub_rows.append(('root_flag', repr(flag), 1))
        parity = {}
        for t in doc.get('tracks') or []:
            ty = str(t.get('type'))
            for sg in t.get('segments') or []:
                ri = sg.get('render_index')
                if isinstance(ri, int) and 15000 <= ri <= 19999:
                    parity.setdefault((ty, str(ri // 1000 * 1000)), collections.Counter())
                    parity[(ty, str(ri // 1000 * 1000))]['even' if ri % 2 == 0 else 'odd'] += 1
        for (ty, base_k), c in parity.items():
            sub_rows.append(('sub_band', f'type={ty} base={base_k}', f'even={c["even"]} odd={c["odd"]}'))

    sub_counter = collections.Counter()
    for kind, a_, b_ in sub_rows:
        if kind == 'root_flag':
            sub_counter[a_] += 1
    with (OUT / 'render_index_subbands.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['section', 'key', 'value'])
        for k, v in sorted(sub_counter.items()):
            w.writerow(['free_render_index_mode_on_per_content', k, v])
        for kind, a_, b_ in sub_rows:
            if kind == 'sub_band':
                w.writerow([kind, a_, b_])

    versions = sorted({v for d in tab.values() for v in d}, key=version_key)
    with (OUT / 'track_type_by_app_version.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['app_version'] + sorted(tab, key=lambda x: -totals[x]))
        for v in versions:
            w.writerow([v] + [tab.get(t, {}).get(v, 0) for t in sorted(tab, key=lambda x: -totals[x])])

    print(f'contents={contents} tracks_by_type={totals}')
    for t in sorted(tab, key=lambda x: -totals[x]):
        vs = sorted(tab[t], key=version_key)
        print(f'  {t:<9} versions {len(vs)}: {vs[0]} .. {vs[-1]}  '
              f'range=[{",".join(f"{v}:{tab[t][v]}" for v in vs if version_key(v) >= (11, 0, 0))}]')
    print('allocators:')
    for r in rows:
        print(f'  {r[0]:<38} consts={r[2]:<22} free={r[3]:<9} body={r[5][:130]}')
    print('enums:', {k: sorted(v) for k, v in enums.items() if k.startswith('TrackType')})


if __name__ == '__main__':
    main()
