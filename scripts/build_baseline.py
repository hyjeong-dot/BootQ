"""
정규화 C단계: 매핑표만으로 캠프를 새 어휘로 옮긴 기준 프로파일을 만든다 (LLM 없음, 표준 라이브러리만 사용).
D단계(LLM) 결과와 비교할 기준선이다. 기준선과 LLM 결과가 다른 캠프만 검수한다.

규칙
- job_ids       : 원래 (대분류, 중분류) → 대표 직무 (data/private/job_map.csv)
- industry_ids  : 원래 산업 → 대표 산업 (data/private/industry_map.csv).
                  상세분류가 산업 성격(예: 2차전지, 회계법인)이면 산업에 더한다. 산업이 ANY였다면 그 값으로 바꾼다
- sub_jobs, skills : 상세분류 → 분류표(data/private/detail_map.csv)의 sub_job, skill
- job 성격의 상세분류(예: PM)와 버린 상세분류는 매칭에 쓰지 않고 job_hint, detail_dropped 칸에 남긴다 (D단계 참고용)
- 캠프 하나가 여러 행이면(코드만 다른 같은 캠프) 값을 합친다
- camp_type은 캠프명을 읽어야 해서 여기서는 비워 둔다 (D단계)

실행 (prepare_camps.py를 먼저 실행):
    python scripts/build_baseline.py
출력: data/derived/camp_baseline.csv (git 제외)
"""
import csv
import sys
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAMPS = ROOT / 'data' / 'derived' / 'camp_raw.csv'
JOB_MAP = ROOT / 'data' / 'private' / 'job_map.csv'
INDUSTRY_MAP = ROOT / 'data' / 'private' / 'industry_map.csv'
DETAIL_MAP = ROOT / 'data' / 'private' / 'detail_map.csv'
OVERRIDES = ROOT / 'data' / 'private' / 'camp_overrides.csv'
JOBS = ROOT / 'data' / 'vocab' / 'jobs.csv'
INDUSTRIES = ROOT / 'data' / 'vocab' / 'industries.csv'
SKILLS = ROOT / 'data' / 'vocab' / 'skills.csv'
OUT = ROOT / 'data' / 'derived' / 'camp_baseline.csv'

ANY = 'ANY'
NO_DETAIL = ('', 'N/A')
SEP = '|'
COLUMNS = ['source_camp_id', '캠프명', 'job_ids', 'job_families', 'sub_jobs', 'skills', 'industry_ids',
           'camp_type', 'job_hint', 'detail_dropped', 'orig_job', 'orig_industry', 'orig_detail', 'override']


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def add(values: list, value: str) -> None:
    if value and value not in values:
        values.append(value)


def main() -> int:
    job_map = {(r['원래대분류'], r['원래중분류']): (r['대표대분류'], r['대표직무']) for r in read_csv(JOB_MAP)}
    industry_map = {r['원래산업']: r['대표산업'] for r in read_csv(INDUSTRY_MAP)}
    detail_map = {r['원래상세분류']: (r['분류'], r['정규값']) for r in read_csv(DETAIL_MAP)}
    overrides = {}
    for r in read_csv(OVERRIDES):
        overrides.setdefault(r['source_camp_id'], []).append(r['지시'])

    camps: 'OrderedDict[str, dict]' = OrderedDict()
    for row in read_csv(CAMPS):
        camp = camps.setdefault(row['source_camp_id'], {
            '캠프명': row['캠프명'], 'families': [], 'jobs': [], 'sub_jobs': [], 'skills': [], 'industries': [],
            'detail_industries': [], 'job_hint': [], 'dropped': [], 'orig_job': [], 'orig_industry': [], 'orig_detail': [],
        })
        family, job = job_map[(row['직무대분류'], row['직무중분류'])]
        add(camp['families'], family)
        add(camp['jobs'], job)
        add(camp['industries'], industry_map[row['산업']])
        add(camp['orig_job'], f"{row['직무대분류']}/{row['직무중분류']}")
        add(camp['orig_industry'], row['산업'])
        detail = row['상세분류']
        if detail in NO_DETAIL:
            continue
        add(camp['orig_detail'], detail)
        kind, value = detail_map[detail]
        if kind == 'sub_job':
            add(camp['sub_jobs'], value)
        elif kind == 'skill':
            add(camp['skills'], value)
        elif kind == 'industry':
            add(camp['detail_industries'], value)
        elif kind == 'job':
            add(camp['job_hint'], value)
        else:
            add(camp['dropped'], detail)

    out_rows = []
    for camp_id, c in camps.items():
        industries = c['industries']
        for value in c['detail_industries']:
            if industries == [ANY]:
                industries = []
            add(industries, value)
        out_rows.append({
            'source_camp_id': camp_id, '캠프명': c['캠프명'],
            'job_ids': SEP.join(c['jobs']), 'job_families': SEP.join(c['families']),
            'sub_jobs': SEP.join(c['sub_jobs']), 'skills': SEP.join(c['skills']),
            'industry_ids': SEP.join(industries), 'camp_type': '',
            'job_hint': SEP.join(c['job_hint']), 'detail_dropped': SEP.join(c['dropped']),
            'orig_job': SEP.join(c['orig_job']), 'orig_industry': SEP.join(c['orig_industry']),
            'orig_detail': SEP.join(c['orig_detail']), 'override': ' / '.join(overrides.get(camp_id, [])),
        })

    jobs = {r['job'] for r in read_csv(JOBS)}
    industries_vocab = {r['industry'] for r in read_csv(INDUSTRIES)}
    skills_vocab = {r['skill'] for r in read_csv(SKILLS)}
    errors = []
    for r in out_rows:
        errors += [f'{r["캠프명"][:30]}: jobs.csv에 없는 직무 {j}' for j in r['job_ids'].split(SEP) if j not in jobs]
        errors += [f'{r["캠프명"][:30]}: industries.csv에 없는 산업 {i}' for i in r['industry_ids'].split(SEP) if i not in industries_vocab]
        errors += [f'{r["캠프명"][:30]}: skills.csv에 없는 스킬 {s}' for s in r['skills'].split(SEP) if s and s not in skills_vocab]
        if not r['job_ids'] or not r['industry_ids']:
            errors.append(f'{r["캠프명"][:30]}: 직무 또는 산업이 비어 있음')
    unknown_overrides = set(overrides) - set(camps)
    errors += [f'camp_overrides에 없는 캠프 ID: {i}' for i in unknown_overrides]
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1

    with OUT.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)

    n = len(out_rows)
    multi_job = sum(1 for r in out_rows if SEP in r['job_ids'])
    multi_ind = sum(1 for r in out_rows if SEP in r['industry_ids'])
    print(f'기준 프로파일 {n}개 캠프 → {OUT.relative_to(ROOT)}')
    print(f'직무 여러 개: {multi_job}개 / 산업 여러 개: {multi_ind}개 / 산업 ANY만: {sum(1 for r in out_rows if r["industry_ids"] == ANY)}개')
    print(f'sub_job 있음: {sum(1 for r in out_rows if r["sub_jobs"])}개 ({sum(1 for r in out_rows if r["sub_jobs"]) * 100 // n}%) / '
          f'skills 있음: {sum(1 for r in out_rows if r["skills"])}개 / job_hint: {sum(1 for r in out_rows if r["job_hint"])}개 / '
          f'버린 상세분류: {sum(1 for r in out_rows if r["detail_dropped"])}개 / 예외 지시: {sum(1 for r in out_rows if r["override"])}개')
    job_counts = Counter(j for r in out_rows for j in r['job_ids'].split(SEP))
    print(f'직무 {len(job_counts)}개 중 캠프 1개뿐인 직무 {sum(1 for v in job_counts.values() if v == 1)}개')
    return 0


if __name__ == '__main__':
    sys.exit(main())
