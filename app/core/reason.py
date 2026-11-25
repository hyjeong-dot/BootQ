"""
추천 사유 (MVP 템플릿). 순수 함수만 둔다.
규칙 원본: docs/rules/02_BACKEND.md 5장 "추천 사유 (템플릿)"

- 근거는 병합 후보의 근거 표기(본문 raw_mention 또는 입력 필드 원문)와 매칭에 쓰인 값(캠프의 대표 직무·산업, camp_type)만
- 조사는 받침과 무관한 것(에, 의)만 쓴다. 발췌가 영문·숫자로 끝나도 문장이 깨지지 않게
"""
from app.core.industry import IndustryGrade
from app.core.models import (CLOSE, FAMILY, FIELD_COMPANY, FIELD_JOB, HELP_FROM_BODY, SAME, Candidate, HelpGrade,
                             MergedSlots, Recommendation)

CAMP_TYPE_LABELS = {'EXPLORE': '직무 탐색형', 'EXPERIENCE': '실무 경험형', 'APPLICATION': '지원 준비형'}


def basis_phrase(candidate: Candidate) -> str:
    if candidate.source == FIELD_JOB:
        return f"희망 직무 '{candidate.mention}'"
    if candidate.source == FIELD_COMPANY:
        return f"목표 회사 '{candidate.mention}'"
    return f"글에 쓴 '{candidate.mention}'"


def _job_sentence(rec: Recommendation) -> str | None:
    if rec.job is None or rec.camp_job is None:
        return None
    basis = basis_phrase(rec.job)
    if rec.relation == SAME:
        return f'{basis}에 맞춘 {rec.camp_job} 캠프예요.'
    if rec.relation == CLOSE:
        return f'{basis}에 가까운 {rec.camp_job} 캠프예요.'
    if rec.relation == FAMILY:
        return f'{basis}에서 넓혀 찾은 같은 직군의 {rec.camp_job} 캠프예요.'
    return None


def _industry_sentence(rec: Recommendation) -> str | None:
    if rec.industry_grade == IndustryGrade.ANY:
        return '산업과 무관하게 들을 수 있어요.'
    if rec.industry is None or rec.camp_industry is None:
        return None
    basis = basis_phrase(rec.industry)
    if rec.industry_grade == IndustryGrade.MATCH:
        if rec.industry.source in (FIELD_JOB, FIELD_COMPANY):
            return f'{basis}의 {rec.camp_industry} 분야를 다뤄요.'
        return f'{basis} 분야를 다뤄요.'
    if rec.industry_grade == IndustryGrade.FAMILY:
        return f'{basis}에 가까운 {rec.camp_industry} 분야예요.'
    return None


def _help_sentence(rec: Recommendation, merged: MergedSlots) -> str | None:
    """category 기본값으로 정한 camp_type은 유저가 쓴 말이 아니라 문장에 넣지 않는다."""
    if (rec.help_grade != HelpGrade.MATCH or merged.help_source != HELP_FROM_BODY
            or not merged.help_mention or rec.camp.camp_type not in CAMP_TYPE_LABELS):
        return None
    return f"글에 쓴 '{merged.help_mention}'에 맞는 {CAMP_TYPE_LABELS[rec.camp.camp_type]} 과정이에요."


def build_reason(rec: Recommendation, merged: MergedSlots) -> str:
    sentences = [_job_sentence(rec), _industry_sentence(rec), _help_sentence(rec, merged)]
    return ' '.join(s for s in sentences if s)
