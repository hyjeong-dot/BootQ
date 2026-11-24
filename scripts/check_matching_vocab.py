"""
매칭용 어휘 검사와 요약 (#8).

- job_relation.csv가 입력 파일(jobs, job_family_policy, job_relation_manual)로 다시 만든 결과와 같은지
- category_camp_type.csv: camp_type 값
- (git 제외) job_alias.csv: 직무·산업이 어휘에 있는지
- (git 제외) company_industry.csv: 산업이 어휘에 있는지
- (git 제외, 원본이 있을 때) 유저 원본의 target_job·target_company·category가 빠짐없이 변환되는지
- 상태별 개수와 '확인필요' 목록

실행:
    uv run python scripts/check_matching_vocab.py
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.normalize_v2 import CAMP_TYPES  # noqa: E402
from app.sources.qna import find_raw_qna, read_xlsx_rows  # noqa: E402
from app.sources.vocab import (PRIVATE_DIR, VOCAB_DIR, _read, load_category_camp_type, load_company_industry,  # noqa: E402
                               load_industries, load_job_alias, load_job_families, load_job_relations)
from scripts.build_job_relation import build  # noqa: E402

ALL_JOBS, ALL_COMPANIES = '모든 직무', '모든 회사'
STATUSES = ('확정', '초안', '확인필요', '제외')


def main() -> int:
    jobs, industries = load_job_families(), load_industries()
    errors: list[str] = []

    relations, build_errors = build()
    errors += build_errors
    rebuilt = [(r.job_a, r.job_b, r.relation) for r in relations]
    if rebuilt != load_job_relations():
        errors.append('job_relation.csv가 입력 파일과 다름: scripts/build_job_relation.py를 다시 실행')

    categories = load_category_camp_type()
    errors += [f'category_camp_type 값 오류: {c}={t}' for c, t in categories.items() if t and t not in CAMP_TYPES]

    private = {'job_alias': PRIVATE_DIR / 'job_alias.csv', 'company_industry': PRIVATE_DIR / 'company_industry.csv'}
    has_private = all(p.exists() for p in private.values())
    if has_private:
        alias, companies = load_job_alias(), load_company_industry()
        for term, (alias_jobs, alias_industries) in alias.items():
            errors += [f'job_alias 직무가 어휘에 없음: {term} → {j}' for j in alias_jobs if j not in jobs]
            errors += [f'job_alias 산업이 어휘에 없음: {term} → {i}' for i in alias_industries if i not in industries]
            if term in jobs:
                errors.append(f'job_alias에 대표 직무와 같은 표기가 있음 (변환 불필요): {term}')
        for company, company_industries in companies.items():
            errors += [f'company_industry 산업이 어휘에 없음: {company} → {i}' for i in company_industries
                       if i not in industries]
        for name, path in private.items():
            errors += [f'{name} 상태 값 오류: {r}' for r in _read(path) if r['status'] not in STATUSES]
    else:
        print('git 제외 파일이 없어 job_alias·company_industry 검사를 건너뜀')

    raw_qna = find_raw_qna()
    if has_private and raw_qna is not None:
        rows = read_xlsx_rows(raw_qna)
        user_jobs = Counter(r['question_target_job'] for r in rows if r['question_target_job'] not in ('', ALL_JOBS))
        user_companies = Counter(r['question_target_company'] for r in rows if r['question_target_company'] not in ('', ALL_COMPANIES))
        user_categories = Counter(r['question_category'] for r in rows if r['question_category'])
        errors += [f'target_job 변환 누락: {t} ({n}건)' for t, n in user_jobs.items() if t not in jobs and t not in alias]
        errors += [f'target_company 변환 누락: {c} ({n}건)' for c, n in user_companies.items() if c not in companies]
        errors += [f'category 누락: {c} ({n}건)' for c, n in user_categories.items() if c not in categories]
        direct = sum(n for t, n in user_jobs.items() if t in jobs)
        print(f'유저 target_job {len(user_jobs)}종 {sum(user_jobs.values())}건: 대표 직무와 같은 표기 '
              f'{sum(1 for t in user_jobs if t in jobs)}종 {direct}건, 별칭 변환 {sum(1 for t in user_jobs if t in alias)}종')
        print(f'유저 target_company {len(user_companies)}종 {sum(user_companies.values())}건')

    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1

    print(f'job_relation: {len(relations)}쌍 ' + str(Counter((r.relation, r.source) for r in relations)))
    for name, path in [('job_relation_manual', VOCAB_DIR / 'job_relation_manual.csv'),
                       ('job_family_policy', VOCAB_DIR / 'job_family_policy.csv'),
                       ('category_camp_type', VOCAB_DIR / 'category_camp_type.csv'), *private.items()]:
        if path.exists():
            print(f'{name}: ' + ', '.join(f'{s} {n}' for s, n in Counter(r['status'] for r in _read(path)).most_common()))
    if has_private:
        for name, path, key in [('job_alias', private['job_alias'], 'user_term'),
                                ('company_industry', private['company_industry'], 'company')]:
            todo = [r[key] for r in _read(path) if r['status'] == '확인필요']
            print(f'{name} 확인필요 {len(todo)}: ' + ', '.join(todo))
    return 0


if __name__ == '__main__':
    sys.exit(main())
