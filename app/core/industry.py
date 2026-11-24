"""
산업 등급 판정 (매칭 정렬 2단계). 순수 함수만 둔다: 파일·DB를 읽지 않는다.

등급 순서: 일치 > 계열 > ANY > 불일치 (숫자가 작을수록 좋다. 정렬 키로 그대로 쓴다)
- 일치: 유저 산업과 캠프 산업이 같다
- 계열: 두 산업이 계열을 하나 이상 공유한다. 한 산업이 여러 계열에 속할 수 있다
        (유통/물류는 유통·커머스와 물류·무역 둘 다). 무역↔커머스처럼 계열을 공유하지 않으면 계열이 아니다
- ANY: 캠프가 어느 산업이든 해당하는 범용 캠프
- 불일치: 위 어디에도 해당하지 않음
"""
from collections.abc import Iterable, Mapping
from enum import IntEnum

ANY = 'ANY'

FamilyIndex = Mapping[str, frozenset[str]]  # 산업 -> 그 산업이 속한 계열들


class IndustryGrade(IntEnum):
    MATCH = 0
    FAMILY = 1
    ANY = 2
    MISMATCH = 3


def build_family_index(pairs: Iterable[tuple[str, str]]) -> dict[str, frozenset[str]]:
    """(계열, 산업) 쌍들로 산업 -> 계열 집합 인덱스를 만든다."""
    index: dict[str, set[str]] = {}
    for family, industry in pairs:
        index.setdefault(industry, set()).add(family)
    return {industry: frozenset(families) for industry, families in index.items()}


def shares_family(a: str, b: str, families: FamilyIndex) -> bool:
    return bool(families.get(a, frozenset()) & families.get(b, frozenset()))


def industry_grade(
    user_industries: Iterable[str],
    camp_industries: Iterable[str],
    families: FamilyIndex,
) -> IndustryGrade | None:
    """
    유저 산업들과 캠프 산업들 사이의 가장 좋은 등급.
    유저 산업이 비어 있으면 None: 이 단계를 건너뛴다(모든 캠프가 동급).
    """
    user = [i for i in user_industries if i != ANY]
    if not user:
        return None
    camp = list(camp_industries)

    best = IndustryGrade.MISMATCH
    if ANY in camp:
        best = IndustryGrade.ANY
    for u in user:
        for c in camp:
            if c == ANY:
                continue
            if u == c:
                return IndustryGrade.MATCH
            if shares_family(u, c, families):
                best = min(best, IndustryGrade.FAMILY)
    return best
