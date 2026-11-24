"""
상세분류 분류표(data/private/detail_map.csv, git 제외) 검사와 요약.

- 캠프 원본의 상세분류 값(N/A 제외)이 분류표에 빠짐없이 있는지, 분류표에 원본에 없는 값이 있는지
- 분류가 sub_job / skill / job / industry / drop 중 하나인지, drop이 아니면 정규값이 있는지
- skill 정규값이 data/vocab/skills.csv와 같은지, industry 정규값이 industries.csv에 있는지

실행 (prepare_camps.py를 먼저 실행):
    python scripts/check_detail_map.py
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPS = ROOT / 'data' / 'derived' / 'camp_raw.csv'
DETAIL_MAP = ROOT / 'data' / 'private' / 'detail_map.csv'
SKILLS = ROOT / 'data' / 'vocab' / 'skills.csv'
INDUSTRIES = ROOT / 'data' / 'vocab' / 'industries.csv'
KINDS = ('sub_job', 'skill', 'job', 'industry', 'drop')
NO_DETAIL = ('', 'N/A')


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def main() -> int:
    counts = Counter(c['상세분류'] for c in read_csv(CAMPS) if c['상세분류'] not in NO_DETAIL)
    table = {r['원래상세분류']: r for r in read_csv(DETAIL_MAP)}
    errors = [f'분류표에 없음: {k}' for k in counts if k not in table]
    errors += [f'원본에 없는 값: {k}' for k in table if k not in counts]

    skills_in_map = defaultdict(set)
    for key, r in table.items():
        if r['분류'] not in KINDS:
            errors.append(f'알 수 없는 분류: {key} {r["분류"]}')
        elif r['분류'] != 'drop' and not r['정규값']:
            errors.append(f'정규값 없음: {key}')
        if r['분류'] == 'skill':
            skills_in_map['skill'].add(r['정규값'])
    skills = {r['skill'] for r in read_csv(SKILLS)}
    if skills_in_map['skill'] != skills:
        errors.append(f'skills.csv와 분류표의 skill이 다름: {sorted(skills ^ skills_in_map["skill"])}')
    industries = {r['industry'] for r in read_csv(INDUSTRIES)}
    errors += [f'industries.csv에 없는 산업: {k} → {r["정규값"]}' for k, r in table.items()
               if r['분류'] == 'industry' and r['정규값'] not in industries]

    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1

    total = sum(counts.values())
    print(f'상세분류 값 {len(counts)}개, 채워진 행 {total}개')
    for kind in KINDS:
        keys = [k for k in counts if table[k]['분류'] == kind]
        print(f'{kind}: 값 {len(keys)}개, 행 {sum(counts[k] for k in keys)}개, 정규값 {len({table[k]["정규값"] for k in keys} - {""})}개')
    return 0


if __name__ == '__main__':
    sys.exit(main())
