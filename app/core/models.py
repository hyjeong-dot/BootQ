"""
요청 파이프라인(게이트·병합·매칭·사유)이 주고받는 값. 순수 데이터와 순수 함수만 둔다: 파일·DB를 읽지 않는다.

규칙의 원본은 docs/rules/02_BACKEND.md 5장.
"""
from dataclasses import dataclass, field
from enum import IntEnum

from app.core.industry import IndustryGrade

# 병합 후보의 출처 (병합 우선순위: 본문 명시 > 입력 필드 > 본문 추론)
BODY_EXPLICIT = 'body_explicit'
FIELD_JOB = 'field_job'            # 희망 직무 필드의 사전 변환 결과 (직무, 또는 별칭이 주는 산업)
FIELD_COMPANY = 'field_company'    # 목표 회사 필드의 사전 변환 결과 (산업)
BODY_INFERRED = 'body_inferred'
FIELD_SOURCES = (FIELD_JOB, FIELD_COMPANY)

# desired_help(선호 camp_type)의 출처
HELP_FROM_BODY = 'body'
HELP_FROM_CATEGORY = 'category'

# 직무 관계 (core/job_relation.py와 같은 값)
SAME, CLOSE, FAMILY = 'SAME', 'CLOSE', 'FAMILY'

# 캠프 정규화 status
PENDING_REVIEW = 'pending_review'


@dataclass(frozen=True)
class PostInput:
    """게이트 1차가 보는 입력 필드."""
    title: str
    content: str
    category: str = ''
    category_group: str = ''


@dataclass(frozen=True)
class Candidate:
    """병합된 유저 직무 또는 산업 하나. mention은 사유가 쓰는 근거 표기: 본문이면 raw_mention, 필드면 필드 원문 표기."""
    value: str
    source: str
    mention: str


@dataclass(frozen=True)
class MergedSlots:
    jobs: tuple[Candidate, ...] = ()
    industries: tuple[Candidate, ...] = ()
    camp_type: str | None = None          # 선호 camp_type. None이면 정렬 4단계를 건너뛴다
    help_source: str | None = None        # HELP_FROM_BODY | HELP_FROM_CATEGORY
    help_mention: str = ''                # 출처가 본문일 때만
    flags: frozenset[str] = frozenset()   # job_conflict, industry_conflict, job_inferred_only, industry_inferred_only
    log: tuple[str, ...] = ()


@dataclass(frozen=True)
class Camp:
    """매칭에 쓰는 캠프 값. 검수 전 캠프는 camp_for_matching이 기준값으로 바꿔 만든다."""
    id: str
    name: str
    job_ids: tuple[str, ...]
    industry_ids: tuple[str, ...]
    camp_type: str | None = None
    recruiting: bool = True                     # 모집 중 (모집기간 데이터가 없으면 True)


def camp_for_matching(*, id: str, name: str, status: str, is_camp: bool,
                      job_ids: tuple[str, ...], industry_ids: tuple[str, ...],
                      base_job_ids: tuple[str, ...], base_industry_ids: tuple[str, ...],
                      camp_type: str | None, recruiting: bool = True) -> Camp | None:
    """정규화 결과 한 행 → 매칭용 캠프. 후보가 아니면 None.
    pending_review는 기준값(원래 코드에서 온 직무·산업)으로 후보에 넣고 캠프 아님 판정도 무시한다 (승인 전이라서).
    camp_type은 검수 대상이 아니라 status와 무관하게 정규화 결과를 쓴다."""
    if status == PENDING_REVIEW:
        return Camp(id, name, tuple(base_job_ids), tuple(base_industry_ids), camp_type or None, recruiting)
    if not is_camp:
        return None
    return Camp(id, name, tuple(job_ids), tuple(industry_ids), camp_type or None, recruiting)


class HelpGrade(IntEnum):
    """정렬 4단계: desired_help ↔ camp_type. 숫자가 작을수록 좋다."""
    MATCH = 0
    NO_TYPE = 1        # 캠프 camp_type 없음
    MISMATCH = 2


@dataclass(frozen=True)
class Recommendation:
    camp: Camp
    rank: int                                  # 1부터
    job: Candidate | None                      # 맞춘 유저 직무 (산업만 매칭이면 None)
    camp_job: str | None                       # 그 유저 직무와 관계를 만든 캠프 직무
    relation: str | None                       # SAME | CLOSE | FAMILY
    industry: Candidate | None                 # 산업 등급을 만든 유저 산업 (일치·계열일 때)
    camp_industry: str | None                  # 그 등급을 만든 캠프 산업 (ANY 포함)
    industry_grade: IndustryGrade | None       # None이면 산업 단계를 건너뜀
    help_grade: HelpGrade | None               # None이면 4단계를 건너뜀
    review: bool = False                       # B등급(FAMILY) 또는 산업만 매칭
    guaranteed: bool = False                   # 복수 직무 분배로 자리를 보장받아 뽑힘


@dataclass(frozen=True)
class MatchResult:
    recommendations: tuple[Recommendation, ...] = ()
    flags: frozenset[str] = frozenset()        # industry_only, family_used, no_candidates
    log: tuple[str, ...] = field(default=())
