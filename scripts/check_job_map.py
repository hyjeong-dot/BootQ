"""
직무 매핑표(data/private/job_map.csv, git 제외) 검사와 요약.

- 캠프 원본의 (대분류, 중분류) 쌍이 매핑표에 빠짐없이 있는지, 매핑표에 원본에 없는 쌍이 있는지
- 대표 직무 하나가 대표 대분류 두 개에 걸치지 않는지
- 대표 직무 목록(data/vocab/jobs.csv)과 매핑표가 맞는지, 수동 관계 파일의 직무가 목록에 있는지
- 대표 직무별 캠프 수 (캠프 1개뿐인 직무 수의 변화)

실행 (prepare_camps.py를 먼저 실행):
    python scripts/check_job_map.py
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPS = ROOT / 'data' / 'derived' / 'camp_raw.csv'
JOB_MAP = ROOT / 'data' / 'private' / 'job_map.csv'
JOBS = ROOT / 'data' / 'vocab' / 'jobs.csv'
RELATIONS = ROOT / 'data' / 'vocab' / 'job_relation_manual.csv'


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def main() -> int:
    camps = read_csv(CAMPS)
    job_map = read_csv(JOB_MAP)
    errors = []

    mapping = {}
    for row in job_map:
        key = (row['원래대분류'], row['원래중분류'])
        if key in mapping:
            errors.append(f'매핑표 중복 행: {key}')
        mapping[key] = (row['대표대분류'], row['대표직무'])

    camp_pairs = Counter((c['직무대분류'], c['직무중분류']) for c in camps)
    errors += [f'매핑표에 없음: {k}' for k in camp_pairs if k not in mapping]
    errors += [f'원본에 없는 쌍: {k}' for k in mapping if k not in camp_pairs]

    families = defaultdict(set)
    for family, job in mapping.values():
        families[job].add(family)
    errors += [f'대표 직무가 대분류 여러 개에 걸침: {j} {sorted(f)}' for j, f in families.items() if len(f) > 1]

    vocab = {r['job']: r for r in read_csv(JOBS)}
    for job, fams in families.items():
        if job not in vocab:
            errors.append(f'jobs.csv에 없는 대표 직무: {job}')
        elif vocab[job]['family'] not in fams:
            errors.append(f'jobs.csv 대분류 불일치: {job} {vocab[job]["family"]} vs {sorted(fams)}')
    errors += [f'매핑표에서 안 쓰는데 신설 표시가 없음: {j}' for j, r in vocab.items()
               if j not in families and r['status'] != '신설']

    for r in read_csv(RELATIONS):
        errors += [f'관계 파일의 직무가 jobs.csv에 없음: {j}' for j in (r['job_a'], r['job_b']) if j not in vocab]
        if r['relation'] not in ('CLOSE', 'FAMILY', 'NONE'):
            errors.append(f'알 수 없는 관계: {r}')

    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1

    before = defaultdict(set)
    after = defaultdict(set)
    for c in camps:
        key = (c['직무대분류'], c['직무중분류'])
        before[key].add(c['캠프명'])
        after[mapping[key]].add(c['캠프명'])

    types = Counter(row['유형'] for row in job_map)
    print(f'원래 직무 {len(before)}개 → 대표 직무 {len(after)}개, 대표 대분류 {len({f for f, _ in after})}개')
    print('유형: ' + ', '.join(f'{t} {n}' for t, n in types.most_common()))
    print(f'검토 표시: {sum(1 for r in job_map if r["검토"] == "Y")}행')
    print(f'캠프 1개뿐인 직무: {sum(1 for v in before.values() if len(v) == 1)}개 → {sum(1 for v in after.values() if len(v) == 1)}개')
    print()
    for family in sorted({f for f, _ in after}):
        jobs = sorted(((j, len(after[(f, j)])) for f, j in after if f == family), key=lambda x: -x[1])
        print(f'[{family}] ' + ', '.join(f'{j}({n})' for j, n in jobs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
