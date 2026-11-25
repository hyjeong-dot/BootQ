"""
2단 게이트. 순수 함수만 둔다. 반환값은 종료 사유 코드(종료)이거나 None(통과).
게이트 종료는 오류가 아니라 정상 종료(추천 없음 = 토스트 미표시). 규칙 원본: docs/rules/02_BACKEND.md 5장 "게이트 (2단)"
"""
from app.core.models import MergedSlots, PostInput

EMPTY_POST = 'empty_post'
OFF_TARGET_GROUP = 'off_target_group'
NO_SIGNAL = 'no_signal'

# 1차에서 자르는 question_category_group. 재직자의 회사생활 질문 그룹
OFF_TARGET_GROUPS = frozenset({'랜선 사수'})


def gate_before_slots(post: PostInput, off_target_groups: frozenset[str] = OFF_TARGET_GROUPS) -> str | None:
    """1차 (슬롯필링 전, 입력 필드만). LLM 호출을 아끼는 컷이라 확실한 것만 자른다."""
    if not post.title.strip() and not post.content.strip():
        return EMPTY_POST
    if post.category_group.strip() in off_target_groups:
        return OFF_TARGET_GROUP
    return None


def gate_after_merge(merged: MergedSlots) -> str | None:
    """2차 (병합 후). 직무도 산업도 없으면 종료. 산업만 있으면 통과한다 (매칭이 산업만으로 고른다)."""
    if not merged.jobs and not merged.industries:
        return NO_SIGNAL
    return None
