from app.core.industry import ANY, IndustryGrade
from app.core.models import (BODY_EXPLICIT, CLOSE, FAMILY, FIELD_COMPANY, FIELD_JOB, HELP_FROM_BODY,
                             HELP_FROM_CATEGORY, SAME, Camp, Candidate, HelpGrade, MergedSlots, Recommendation)
from app.core.reason import build_reason

CAMP = Camp('x', '가짜 캠프', ('SW개발',), ('금융',), 'EXPERIENCE')


def rec(job=None, camp_job='SW개발', relation=SAME, industry=None, camp_industry=None, grade=None, help=None):
    return Recommendation(CAMP, 1, job, camp_job if job else None, relation if job else None,
                          industry, camp_industry, grade, help)


BODY_JOB = Candidate('SW개발', BODY_EXPLICIT, '백엔드 개발자')


def test_same_from_body():
    assert build_reason(rec(BODY_JOB), MergedSlots()) == "글에 쓴 '백엔드 개발자'에 맞춘 SW개발 캠프예요."


def test_close_from_field():
    r = rec(Candidate('SW개발', FIELD_JOB, '서버개발'), camp_job='웹개발', relation=CLOSE)
    assert build_reason(r, MergedSlots()) == "희망 직무 '서버개발'에 가까운 웹개발 캠프예요."


def test_family():
    r = rec(BODY_JOB, camp_job='데이터분석', relation=FAMILY)
    assert build_reason(r, MergedSlots()) == "글에 쓴 '백엔드 개발자'에서 넓혀 찾은 같은 직군의 데이터분석 캠프예요."


def test_industry_match_body_and_company_field():
    body = rec(BODY_JOB, industry=Candidate('금융', BODY_EXPLICIT, '은행권'), camp_industry='금융',
               grade=IndustryGrade.MATCH)
    assert build_reason(body, MergedSlots()).endswith("글에 쓴 '은행권' 분야를 다뤄요.")
    company = rec(BODY_JOB, industry=Candidate('금융', FIELD_COMPANY, '가짜은행'), camp_industry='금융',
                  grade=IndustryGrade.MATCH)
    assert build_reason(company, MergedSlots()).endswith("목표 회사 '가짜은행'의 금융 분야를 다뤄요.")


def test_industry_family_and_any_and_mismatch():
    fam = rec(BODY_JOB, industry=Candidate('금융', BODY_EXPLICIT, '금융권'), camp_industry='은행',
              grade=IndustryGrade.FAMILY)
    assert build_reason(fam, MergedSlots()).endswith("글에 쓴 '금융권'에 가까운 은행 분야예요.")
    any_ = rec(BODY_JOB, camp_industry=ANY, grade=IndustryGrade.ANY)
    assert build_reason(any_, MergedSlots()).endswith('산업과 무관하게 들을 수 있어요.')
    mis = rec(BODY_JOB, grade=IndustryGrade.MISMATCH)
    assert build_reason(mis, MergedSlots()) == "글에 쓴 '백엔드 개발자'에 맞춘 SW개발 캠프예요."


def test_help_sentence_only_when_from_body():
    body = MergedSlots(camp_type='EXPERIENCE', help_source=HELP_FROM_BODY, help_mention='실무 프로젝트')
    assert build_reason(rec(BODY_JOB, help=HelpGrade.MATCH), body).endswith(
        "글에 쓴 '실무 프로젝트'에 맞는 실무 경험형 과정이에요.")
    category = MergedSlots(camp_type='EXPERIENCE', help_source=HELP_FROM_CATEGORY)
    assert '과정' not in build_reason(rec(BODY_JOB, help=HelpGrade.MATCH), category)
    assert '과정' not in build_reason(rec(BODY_JOB, help=HelpGrade.MISMATCH), body)


def test_industry_only_has_no_job_sentence():
    r = rec(None, industry=Candidate('금융', BODY_EXPLICIT, '금융권'), camp_industry='금융',
            grade=IndustryGrade.MATCH)
    assert build_reason(r, MergedSlots()) == "글에 쓴 '금융권' 분야를 다뤄요."
