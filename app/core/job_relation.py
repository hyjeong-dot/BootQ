"""
직무 관계(job_relation) 생성. 순수 함수만 둔다: 파일·DB를 읽지 않는다.

관계 등급 (매칭 정렬 1·3단계에서 쓴다)
- SAME: 같은 직무 (자기 자신. 대표 직무로 이미 합쳤으므로 다른 직무끼리 SAME은 두지 않는다)
- CLOSE: 사실상 같은 일 — 좁게 잡는다. 산업이 맞는 CLOSE 캠프가 산업무관 SAME 캠프보다 위로 오기 때문
- FAMILY: 같은 직군이지만 다른 일. 직무 A등급(SAME·CLOSE) 캠프가 3개 미만일 때만 쓰고 리뷰 플래그를 단다

만드는 순서
1. 자동: 대분류 정책에서 자동 FAMILY를 켠 대분류는 그 안의 모든 직무 쌍을 FAMILY로
2. 수동: 수동 관계 파일이 자동 값을 덮는다. NONE은 자동으로 생긴 관계를 지운다
"""
from dataclasses import dataclass
from itertools import combinations

SAME, CLOSE, FAMILY, NONE = 'SAME', 'CLOSE', 'FAMILY', 'NONE'
MANUAL_RELATIONS = (CLOSE, FAMILY, NONE)


@dataclass(frozen=True)
class Relation:
    job_a: str
    job_b: str
    relation: str
    source: str        # auto | manual
    reason: str = ''


def pair(a: str, b: str) -> tuple[str, str]:
    """순서 없는 쌍의 표준 표기 (사전순)."""
    return (a, b) if a <= b else (b, a)


def build_job_relations(job_families: dict[str, str], auto_families: set[str],
                        manual: list[tuple[str, str, str, str]]) -> tuple[list[Relation], list[str]]:
    """(관계 목록, 오류 목록). 오류가 있으면 관계 목록은 신뢰하지 않는다.
    manual: (job_a, job_b, relation, reason). 자기 자신(SAME)은 목록에 넣지 않는다 (매칭에서 항상 SAME)."""
    errors: list[str] = []
    errors += [f'대분류 정책에 있지만 직무가 없는 대분류: {f}' for f in sorted(auto_families - set(job_families.values()))]

    by_family: dict[str, list[str]] = {}
    for job, family in job_families.items():
        by_family.setdefault(family, []).append(job)
    relations: dict[tuple[str, str], Relation] = {}
    for family in sorted(auto_families):
        for a, b in combinations(sorted(by_family.get(family, [])), 2):
            relations[(a, b)] = Relation(a, b, FAMILY, 'auto')

    seen: set[tuple[str, str]] = set()
    for a, b, relation, reason in manual:
        missing = [j for j in (a, b) if j not in job_families]
        if missing:
            errors.append(f'수동 관계의 직무가 어휘에 없음: {missing} ({a}, {b})')
            continue
        if a == b:
            errors.append(f'자기 자신과의 관계는 넣지 않음: {a}')
            continue
        if relation not in MANUAL_RELATIONS:
            errors.append(f'수동 관계 값 오류: {relation!r} ({a}, {b})')
            continue
        key = pair(a, b)
        if key in seen:
            errors.append(f'수동 관계 중복: {key}')
            continue
        seen.add(key)
        if relation == NONE:
            relations.pop(key, None)
        else:
            relations[key] = Relation(*key, relation, 'manual', reason)
    return sorted(relations.values(), key=lambda r: (r.job_a, r.job_b)), errors
