"""
산업 매핑표(data/private/industry_map.csv, git 제외) 검사와 요약.

- 캠프 원본의 산업 값이 매핑표에 빠짐없이 있는지, 매핑표에 원본에 없는 값이 있는지
- 대표 산업이 industries.csv에 있는지(원래 값에서 오지 않는 '신설' 산업은 매핑표에서 안 써도 됨), 계열 파일(industry_family.csv)의 산업이 목록에 있는지
- 계열 파일에 같은 (계열, 산업) 행이 중복되지 않는지 (한 산업이 여러 계열에 속하는 것은 허용)
- 매핑 후 대표 산업별 캠프 행 수

실행 (prepare_camps.py를 먼저 실행):
    python scripts/check_industry_map.py
"""
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPS = ROOT / 'data' / 'derived' / 'camp_raw.csv'
INDUSTRY_MAP = ROOT / 'data' / 'private' / 'industry_map.csv'
INDUSTRIES = ROOT / 'data' / 'vocab' / 'industries.csv'
FAMILIES = ROOT / 'data' / 'vocab' / 'industry_family.csv'


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def main() -> int:
    camps = read_csv(CAMPS)
    mapping = {}
    errors = []
    for row in read_csv(INDUSTRY_MAP):
        if row['원래산업'] in mapping:
            errors.append(f'매핑표 중복 행: {row["원래산업"]}')
        mapping[row['원래산업']] = row['대표산업']

    counts = Counter(c['산업'] for c in camps)
    errors += [f'매핑표에 없음: {k}' for k in counts if k not in mapping]
    errors += [f'원본에 없는 값: {k}' for k in mapping if k not in counts]

    vocab_rows = read_csv(INDUSTRIES)
    vocab = {r['industry'] for r in vocab_rows}
    new_industries = {r['industry'] for r in vocab_rows if r['note'].startswith('신설')}
    errors += [f'industries.csv에 없는 대표 산업: {v}' for v in set(mapping.values()) if v not in vocab]
    errors += [f'매핑표에서 안 쓰는 산업: {v}' for v in vocab if v not in set(mapping.values()) and v not in new_industries]

    seen = set()
    for r in read_csv(FAMILIES):
        if r['industry'] not in vocab:
            errors.append(f'계열 파일의 산업이 industries.csv에 없음: {r["industry"]}')
        key = (r['family'], r['industry'])
        if key in seen:
            errors.append(f'계열 파일 중복 행: {key}')
        seen.add(key)

    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1

    after = Counter()
    for k, n in counts.items():
        after[mapping[k]] += n
    print(f'원래 산업 {len(counts)}개 → 대표 산업 {len(after) - 1}개 + ANY')
    print('행 수 1~2개뿐인 산업: ' + ', '.join(f'{k}({n})' for k, n in sorted(after.items(), key=lambda x: x[1]) if n <= 2 and k != 'ANY') or '없음')
    print(', '.join(f'{k}({n})' for k, n in after.most_common()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
