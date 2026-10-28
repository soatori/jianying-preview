"""Census tracks[].flag against track position and the material kinds each track carries.

This is what closes U-61: the enum is readable from the canvas_agent chunks
(FlagNone=0, FlagTextSubtitle=1, FlagSubVideo=2, FlagTextLyric=3, FlagVideoSubtitle=4,
FlagAudioSubtitle=5, FlagAiScriptSubtitle=6), and the corpus says the desktop writer uses it as
"first video track never gets 2" plus "flag 1 on a text track means it carries subtitle material".

Reads only content keys listed in temp/corpus-scan/manifest.json.
Writes docs/evidence/tables/track_flag_semantics.csv.

Usage: python scripts/track_flag_census.py
"""
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

BUCKETS = ['texts', 'videos', 'audios', 'effects', 'stickers', 'video_effects', 'placeholders',
            'text_templates', 'audio_effects', 'captions', 'video_trackings']
# enum values read out of app/static/js/*.js (Name=digit reverse-mapping form)
FLAG_ENUM = {'FlagNone': 0, 'FlagTextSubtitle': 1, 'FlagSubVideo': 2, 'FlagTextLyric': 3,
             'FlagVideoSubtitle': 4, 'FlagAudioSubtitle': 5, 'FlagAiScriptSubtitle': 6}


def main():
    valid = {r['key'] for r in json.loads(MANIFEST.read_text(encoding='utf-8')) if r.get('key')}

    video_pos = collections.Counter()          # (is_first_video, flag) -> count
    kind_flag = collections.defaultdict(collections.Counter)  # track_type -> (flag, kindset) -> count
    tracks_total = 0
    contents = 0

    for path in sorted(glob.glob(str(PLAIN / '*.json'))):
        key = os.path.basename(path)[:-5]
        if key not in valid:
            continue
        contents += 1
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        mat = doc.get('materials') or {}
        mtype = {}
        for b in BUCKETS:
            for m in mat.get(b) or []:
                if isinstance(m, dict) and 'id' in m:
                    mtype[m['id']] = f'{b}.{m.get("type")}'
        tracks = doc.get('tracks') or []
        video_idx = [i for i, t in enumerate(tracks) if t.get('type') == 'video']
        first = set(video_idx[:1])
        for i, t in enumerate(tracks):
            tracks_total += 1
            ty = t.get('type')
            fl = 'absent' if 'flag' not in t else t['flag']
            if ty == 'video':
                video_pos[('first' if i in first else 'other', str(fl))] += 1
                continue
            kinds = collections.Counter(mtype.get(s.get('material_id'), 'unresolved')
                                        for s in (t.get('segments') or []))
            present = tuple(sorted({k for k, v in kinds.items() if v}))
            kind_flag[ty][(str(fl), present)] += 1

    rows = [['section', 'a', 'b', 'count']]
    for (posi, fl), c in sorted(video_pos.items()):
        rows.append(['video_flag_by_position', posi, fl, c])
    for ty in sorted(kind_flag):
        for (fl, present), c in sorted(kind_flag[ty].items(), key=lambda x: -x[1]):
            rows.append(['flag_by_carried_materials', ty, f'flag={fl} kinds={";".join(present)}', c])
    rows.append(['enum_source', 'tracks[].flag',
                 ' '.join(f'{k}={v}' for k, v in sorted(FLAG_ENUM.items(), key=lambda x: x[1])), ''])
    rows.append(['totals', f'contents={contents}', f'tracks={tracks_total}', ''])

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / 'track_flag_semantics.csv').open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, lineterminator='\n')
        w.writerows(rows)

    print(json.dumps({'contents': contents, 'tracks': tracks_total,
                      'video_flag_by_position': {f'{k[0]}/{k[1]}': v for k, v in sorted(video_pos.items())}},
                     ensure_ascii=False, indent=1))
    for ty in ('text', 'mixed'):
        print(f'--- {ty}')
        tot = collections.Counter()
        with_sub = collections.Counter()
        for (fl, present), c in kind_flag[ty].items():
            tot[fl] += c
            if 'texts.subtitle' in present:
                with_sub[fl] += c
        for fl in sorted(tot, key=lambda x: -tot[x]):
            print(f'   flag={fl:<7} tracks={tot[fl]:<5} carrying texts.subtitle={with_sub[fl]} '
                  f'({with_sub[fl] / tot[fl] * 100:.1f}%)')
        for (fl, present), c in sorted(kind_flag[ty].items(), key=lambda x: -x[1])[:8]:
            print(f'      flag={fl:<7} n={c:<5} kinds={present}')


if __name__ == '__main__':
    main()
