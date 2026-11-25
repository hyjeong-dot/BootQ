"""병합 규칙 (07_TEST.md 우선순위 4): 본문 명시 > 입력 필드 > 본문 추론."""
import pytest

from app.core.merge import merge
from app.core.models import (BODY_EXPLICIT, BODY_INFERRED, FIELD_COMPANY, FIELD_JOB, HELP_FROM_BODY,
                             HELP_FROM_CATEGORY)
from app.core.slot_filling import FieldHint, Slot, SlotResult

CATEGORY_TYPES = {'자소서': 'APPLICATION', '인턴': 'EXPERIENCE', '스펙': ''}


def slots(jobs=(), industries=(), help='UNKNOWN', help_mention=''):
    return SlotResult(tuple(Slot(*j) for j in jobs), tuple(Slot(*i) for i in industries), help, help_mention)


def values(cands):
    return [(c.value, c.source) for c in cands]


def test_explicit_before_field_and_both_kept():
    result = merge(slots(jobs=[('품질관리', '품질 엔지니어', 'EXPLICIT')]),
                   FieldHint('공정설계', ('공정설계',)), None, '', {})
    assert values(result.jobs) == [('품질관리', BODY_EXPLICIT), ('공정설계', FIELD_JOB)]
    assert 'job_conflict' in result.flags


def test_no_conflict_when_explicit_and_field_overlap():
    result = merge(slots(jobs=[('품질관리', '품질', 'EXPLICIT'), ('공정기술', '공정 엔지니어', 'EXPLICIT')]),
                   FieldHint('품질관리', ('품질관리',)), None, '', {})
    assert values(result.jobs) == [('품질관리', BODY_EXPLICIT), ('공정기술', BODY_EXPLICIT)]
    assert 'job_conflict' not in result.flags
    assert result.jobs[0].mention == '품질'      # 중복이면 앞 출처(본문)의 근거 표기를 남긴다


def test_field_used_when_body_has_nothing():
    result = merge(slots(), FieldHint('웹개발', ('웹개발',)), None, '', {})
    assert values(result.jobs) == [('웹개발', FIELD_JOB)]
    assert result.jobs[0].mention == '웹개발'
    assert not result.flags


def test_inferred_dropped_when_explicit_or_field_exists():
    result = merge(slots(jobs=[('데이터분석', '분석 공부', 'INFERRED')]),
                   FieldHint('SW개발', ('SW개발',)), None, '', {})
    assert values(result.jobs) == [('SW개발', FIELD_JOB)]
    assert any('본문 추론 버림' in line for line in result.log)


def test_inferred_used_only_when_nothing_else():
    result = merge(slots(jobs=[('데이터분석', '분석 공부', 'INFERRED')]), None, None, '', {})
    assert values(result.jobs) == [('데이터분석', BODY_INFERRED)]
    assert 'job_inferred_only' in result.flags


def test_axes_are_merged_independently():
    # 직무는 명시가 있어도 산업은 추론만 있으면 추론 산업을 쓴다
    result = merge(slots(jobs=[('SW개발', '개발자', 'EXPLICIT')], industries=[('금융', '은행 쪽', 'INFERRED')]),
                   None, None, '', {})
    assert values(result.industries) == [('금융', BODY_INFERRED)]
    assert result.flags == {'industry_inferred_only'}


def test_field_industries_from_job_alias_and_company():
    result = merge(slots(), FieldHint('배터리개발', ('연구개발',), ('2차전지',)),
                   FieldHint('가짜전자', industries=('전자/기계',)), '', {})
    assert values(result.industries) == [('2차전지', FIELD_JOB), ('전자/기계', FIELD_COMPANY)]
    assert result.industries[1].mention == '가짜전자'


def test_industry_conflict_flag():
    result = merge(slots(industries=[('금융', '은행', 'EXPLICIT')]), None,
                   FieldHint('가짜자동차', industries=('자동차',)), '', {})
    assert values(result.industries) == [('금융', BODY_EXPLICIT), ('자동차', FIELD_COMPANY)]
    assert 'industry_conflict' in result.flags


def test_unmapped_field_term_makes_no_candidate():
    result = merge(slots(), FieldHint('처음보는직무'), FieldHint('처음보는회사'), '', {})
    assert result.jobs == () and result.industries == ()
    assert len(result.log) == 2


def test_desired_help_from_body_wins_over_category():
    result = merge(slots(help='EXPERIENCE', help_mention='실무 경험'), None, None, '자소서', CATEGORY_TYPES)
    assert (result.camp_type, result.help_source, result.help_mention) == ('EXPERIENCE', HELP_FROM_BODY, '실무 경험')


def test_desired_help_unknown_uses_category_default():
    result = merge(slots(), None, None, '자소서', CATEGORY_TYPES)
    assert (result.camp_type, result.help_source, result.help_mention) == ('APPLICATION', HELP_FROM_CATEGORY, '')


def test_desired_help_none_when_category_default_empty_or_missing():
    assert merge(slots(), None, None, '스펙', CATEGORY_TYPES).camp_type is None
    assert merge(slots(), None, None, '없는분류', CATEGORY_TYPES).camp_type is None


def test_error_slot_result_is_not_merged():
    with pytest.raises(ValueError):
        merge(SlotResult(error_code='rate_limited'), None, None, '', {})
