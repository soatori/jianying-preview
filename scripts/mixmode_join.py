"""Join the corpus's mix_mode effect entries against the installed MixMode resource index.

Reads only content keys listed in temp/corpus-scan/manifest.json (so the stale plain/ leftovers
cannot enter a count), joins each materials.effects[type=="mix_mode"] entry on resource_id /
effect_id / path-md5 against <install>/Resources/MixMode/MixMode.json, and attaches the GLSL
blend function from docs/evidence/tables/mixmode_glsl.csv.

Writes docs/evidence/tables/{mixmode_packages,mixmode_draft_paths}.csv.

Usage: python scripts/mixmode_join.py [--install "<剪映安装目录>"]   # 缺省自动检测
"""
import argparse
import collections
import csv
import glob
import json
import os
import re
from pathlib import Path

import jy_paths

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / 'temp' / 'corpus-scan' / 'manifest.json'
PLAIN = ROOT / 'temp' / 'corpus-scan' / 'plain'
OUT = ROOT / 'docs' / 'evidence' / 'tables'
MD5_RE = re.compile(r'[0-9a-f]{32}$')


def load_glsl():
    fn = OUT / 'mixmode_glsl.csv'
    if not fn.exists():
        return {}
    with fn.open(encoding='utf-8-sig') as fh:
        return {r['package_md5']: r['blend_function'] for r in csv.DictReader(fh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--install', default=None,
                    help='剪映安装目录（版本目录）；缺省由 scripts/jy_paths.py 自动检测')
    args = ap.parse_args()

    install = Path(args.install) if args.install else jy_paths.install_dir()
    index_path = install / 'Resources' / 'MixMode' / 'MixMode.json'
    index = json.loads(index_path.read_text(encoding='utf-8-sig'))['resourceList']
    by_rid = {str(e['resourceId']): e for e in index}
    by_eid = {str(e['effectId']): e for e in index}
    by_md5 = {e['path']: e for e in index}
    glsl = load_glsl()

    valid = {r['key'] for r in json.loads(MANIFEST.read_text(encoding='utf-8')) if r.get('key')}

    # per package: distinct draft names, occurrence count, contents touched
    pkg_names = collections.defaultdict(collections.Counter)
    pkg_occ = collections.Counter()
    pkg_contents = collections.Counter()
    unmatched = collections.Counter()
    unmatched_contents = collections.Counter()
    path_rows = collections.Counter()
    contents_scanned = 0
    contents_with_mixmode = 0
    contents_joined = 0
    total_occ = 0

    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        key = os.path.basename(path)[:-5]
        if key not in valid:
            continue
        contents_scanned += 1
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        effects = ((doc.get('materials') or {}).get('effects')) or []
        hit = False
        seen_here = collections.Counter()
        joined_here = False
        for e in effects:
            if e.get('type') != 'mix_mode':
                continue
            hit = True
            total_occ += 1
            raw_path = str(e.get('path') or '')
            tail = raw_path.replace('\\', '/').rstrip('/').split('/')[-1].lower()
            md5 = tail if MD5_RE.match(tail) else ''
            rid = str(e.get('resource_id') or '')
            eid = str(e.get('effect_id') or '')
            rec = by_md5.get(md5) or by_rid.get(rid) or by_eid.get(eid)
            name = str(e.get('name') or '')
            if rec is None:
                unmatched[f'rid={rid}|eid={eid}|md5={md5 or tail}|name={name}'] += 1
                unmatched_contents[key] += 1
                continue
            joined_here = True
            pkg = rec['path']
            pkg_occ[pkg] += 1
            pkg_names[pkg][name] += 1
            seen_here[pkg] += 1
            path_rows[(pkg, raw_path if raw_path else '<empty>')] += 1
        if hit:
            contents_with_mixmode += 1
            if joined_here:
                contents_joined += 1
            for pkg in seen_here:
                pkg_contents[pkg] += 1

    OUT.mkdir(parents=True, exist_ok=True)

    with (OUT / 'mixmode_packages.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['package_md5', 'name_id', 'effect_id', 'resource_id', 'glsl_blend_function',
                    'draft_names_occurrences', 'draft_name_set', 'occurrences', 'contents',
                    'index_only'])
        for rec in index:
            pkg = rec['path']
            names = pkg_names.get(pkg, {})
            w.writerow([pkg, rec['nameId'], rec['effectId'], rec['resourceId'],
                        glsl.get(pkg, ''),
                        ' '.join(f'{n}={c}' for n, c in sorted(names.items(), key=lambda x: -x[1])),
                        '|'.join(sorted(names)), pkg_occ.get(pkg, 0), pkg_contents.get(pkg, 0),
                        'no' if pkg_occ.get(pkg) else 'index_only_never_referenced'])
        for pkg in sorted(set(glsl) - {r['path'] for r in index}):
            w.writerow([pkg, '', '', '', glsl[pkg], '', '', 0, 0, 'glsl_only_not_in_index'])

    with (OUT / 'mixmode_draft_paths.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerow(['package_md5', 'draft_path_as_stored', 'occurrences'])
        for (pkg, p), c in sorted(path_rows.items(), key=lambda x: -x[1]):
            w.writerow([pkg, p, c])

    summary = {
        'install': str(index_path),
        'index_entries': len(index),
        'contents_scanned': contents_scanned,
        'contents_with_mix_mode': contents_with_mixmode,
        'mix_mode_occurrences': total_occ,
        'joined_occurrences': sum(pkg_occ.values()),
        'contents_joined': contents_joined,
        'unmatched_occurrences': sum(unmatched.values()),
        'unmatched_shapes': dict(unmatched),
        'packages_referenced': len(pkg_occ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for pkg, rec in sorted(((r['path'], r) for r in index)):
        print(f"{pkg} {rec['nameId']:<22} {glsl.get(pkg,''):<26} "
              f"names={dict(pkg_names.get(pkg, {}))} occ={pkg_occ.get(pkg,0)} contents={pkg_contents.get(pkg,0)}")


if __name__ == '__main__':
    main()
