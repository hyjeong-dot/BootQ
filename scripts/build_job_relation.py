"""
직무 관계(data/vocab/job_relation.csv) 생성. 입력은 모두 커밋된 어휘 파일이라 결과도 커밋한다.

- data/vocab/jobs.csv: 대표 직무와 대분류
- data/vocab/job_family_policy.csv: 대분류별 자동 FAMILY 여부
- data/vocab/job_relation_manual.csv: 수동 관계 (자동 값을 덮어씀, NONE은 지움)

규칙은 app/core/job_relation.py. 입력 파일을 고치면 이 스크립트를 다시 실행한다 (테스트가 결과 파일과 입력의 일치를 검사한다).

실행:
    uv run python scripts/build_job_relation.py
"""
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.job_relation import build_job_relations  # noqa: E402
from app.sources.vocab import VOCAB_DIR, load_job_families, load_job_family_policy, load_job_relation_manual  # noqa: E402

OUT = VOCAB_DIR / 'job_relation.csv'


def build():
    families = load_job_families()
    policy = load_job_family_policy()
    errors = []
    sizes = Counter(families.values())
    errors += [f'직무가 2개 이상인데 대분류 정책에 없음: {f}' for f, n in sizes.items() if n > 1 and f not in policy]
    relations, build_errors = build_job_relations(families, {f for f, on in policy.items() if on},
                                                  load_job_relation_manual())
    return relations, errors + build_errors


def main() -> int:
    relations, errors = build()
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    with OUT.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['job_a', 'job_b', 'relation', 'source'])
        w.writerows((r.job_a, r.job_b, r.relation, r.source) for r in relations)
    counts = Counter((r.relation, r.source) for r in relations)
    print(f'{OUT.relative_to(ROOT)}: {len(relations)}쌍 — ' + ', '.join(f'{rel}/{src} {n}' for (rel, src), n in sorted(counts.items())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
