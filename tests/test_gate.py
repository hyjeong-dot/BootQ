from app.core.gate import EMPTY_POST, NO_SIGNAL, OFF_TARGET_GROUP, gate_after_merge, gate_before_slots
from app.core.models import BODY_EXPLICIT, Candidate, MergedSlots, PostInput


def test_gate1_passes_normal_post():
    assert gate_before_slots(PostInput('개발 캠프 고민', '백엔드 개발자가 되고 싶어요', '직무', '취업 고민')) is None


def test_gate1_cuts_empty_post():
    assert gate_before_slots(PostInput('  ', '\n', '직무', '취업 고민')) == EMPTY_POST


def test_gate1_cuts_off_target_group():
    assert gate_before_slots(PostInput('입사 첫날 복장', '출근 복장이 궁금해요', '직장생활', '랜선 사수')) == OFF_TARGET_GROUP


def test_gate1_does_not_cut_by_category_alone():
    # 대학생·이직 고민에는 직무 신호가 있는 글이 섞여 있어 1차에서 자르지 않는다
    assert gate_before_slots(PostInput('캡스톤 주제', '공정기술과 엮고 싶어요', '대학생활', '대학생 고민')) is None
    assert gate_before_slots(PostInput('품질 직무로 이직', '경력 전환 고민', '이직', '이직 고민')) is None


def test_gate2_cuts_when_no_job_and_no_industry():
    assert gate_after_merge(MergedSlots()) == NO_SIGNAL


def test_gate2_passes_industry_only():
    merged = MergedSlots(industries=(Candidate('반도체', BODY_EXPLICIT, '반도체 회사'),))
    assert gate_after_merge(merged) is None


def test_gate2_passes_job():
    assert gate_after_merge(MergedSlots(jobs=(Candidate('SW개발', BODY_EXPLICIT, '개발자'),))) is None
