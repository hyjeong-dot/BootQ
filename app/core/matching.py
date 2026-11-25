"""
매칭 정렬. 순수 함수만 둔다: 평가 스크립트가 DB·LLM 없이 이 모듈을 직접 호출한다.
규칙 원본: docs/rules/02_BACKEND.md 5장 (정렬 순서, 정렬 키 계산 세부, 복수 직무 분배, 직무 없이 산업만 있을 때)

사전식 정렬 (가중합 아님. 앞 단계가 같을 때만 뒤 단계가 순서를 정한다)
  0. 모집 중 (check_recruiting=False면 끈다)
  1. 직무 등급 A(SAME·CLOSE) / B(FAMILY) / 제외. B는 A가 3개 미만일 때만, 리뷰 플래그
  2. 산업 등급: 일치 > 계열 > ANY > 불일치 (유저 산업이 없으면 건너뜀)
  3. 직무 SAME > CLOSE
  4. desired_help ↔ camp_type: 일치 > 캠프 camp_type 없음 > 불일치 (선호 없음이면 건너뜀)
  마지막 동점은 캠프 ID 순
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.core.industry import ANY, FamilyIndex, IndustryGrade, industry_grade, shares_family
from app.core.job_relation import pair
from app.core.models import (CLOSE, FAMILY, SAME, Camp, Candidate, HelpGrade, MatchResult, MergedSlots,
                             Recommendation)

LIMIT = 3
MAX_GUARANTEED_JOBS = 3        # 복수 직무 분배에서 자리를 보장하는 직무 수 (병합 순서 앞부터)
GRADE_A, GRADE_B = 0, 1
_RELATION_RANK = {SAME: 0, CLOSE: 1, FAMILY: 2}

INDUSTRY_ONLY = 'industry_only'
FAMILY_USED = 'family_used'
NO_CANDIDATES = 'no_candidates'

RelationIndex = Mapping[tuple[str, str], str]     # pair(job_a, job_b) -> CLOSE | FAMILY


def build_relation_index(rows: Iterable[tuple[str, str, str]]) -> dict[tuple[str, str], str]:
    """(job_a, job_b, relation) 행들 → 순서 없는 쌍 인덱스. SAME은 넣지 않는다 (같은 직무면 항상 SAME)."""
    return {pair(a, b): rel for a, b, rel in rows if rel in (CLOSE, FAMILY)}


def job_relation(user_job: str, camp_job: str, relations: RelationIndex) -> str | None:
    if user_job == camp_job:
        return SAME
    return relations.get(pair(user_job, camp_job))


def help_grade(preferred: str | None, camp_type: str | None) -> HelpGrade | None:
    if preferred is None:
        return None
    if not camp_type:
        return HelpGrade.NO_TYPE
    return HelpGrade.MATCH if camp_type == preferred else HelpGrade.MISMATCH


@dataclass(frozen=True)
class _JobFit:
    key: tuple                  # (직무 등급, 산업, 관계 순위, camp_type, 유저 직무 순서)
    job: Candidate
    camp_job: str
    relation: str

    @property
    def grade(self) -> int:
        return self.key[0]


@dataclass(frozen=True)
class _Scored:
    camp: Camp
    industry_grade: IndustryGrade | None
    industry: Candidate | None
    camp_industry: str | None
    help_grade: HelpGrade | None
    fits: tuple[_JobFit | None, ...]   # 유저 직무별 (병합 순서). 관계가 없으면 None
    best: _JobFit | None

    def key(self) -> tuple:
        """전체 정렬 키. 산업만 매칭이면 best가 없다."""
        if self.best is None:
            return (self.industry_grade, _num(self.help_grade), self.camp.id)
        return (*self.best.key[:4], self.camp.id)


def _num(grade: int | None) -> int:
    return 0 if grade is None else int(grade)


def _industry_source(camp: Camp, industries: tuple[Candidate, ...], grade: IndustryGrade | None,
                     families: FamilyIndex) -> tuple[Candidate | None, str | None]:
    """등급을 만든 (유저 산업, 캠프 산업). 유저 산업은 병합 순서가 앞선 것."""
    if grade is None or grade == IndustryGrade.MISMATCH:
        return None, None
    if grade == IndustryGrade.ANY:
        return None, ANY
    for cand in industries:
        for c in camp.industry_ids:
            if c == ANY:
                continue
            if grade == IndustryGrade.MATCH and c == cand.value:
                return cand, c
            if grade == IndustryGrade.FAMILY and shares_family(cand.value, c, families):
                return cand, c
    return None, None


def _job_fit(camp: Camp, order: int, job: Candidate, ind: IndustryGrade | None, hlp: HelpGrade | None,
             relations: RelationIndex) -> _JobFit | None:
    best: _JobFit | None = None
    for camp_job in camp.job_ids:
        rel = job_relation(job.value, camp_job, relations)
        if rel is None:
            continue
        grade = GRADE_B if rel == FAMILY else GRADE_A
        fit = _JobFit((grade, _num(ind), _RELATION_RANK[rel], _num(hlp), order), job, camp_job, rel)
        if best is None or fit.key < best.key:
            best = fit
    return best


def _score(camp: Camp, merged: MergedSlots, relations: RelationIndex, families: FamilyIndex) -> _Scored:
    ind = industry_grade((c.value for c in merged.industries), camp.industry_ids, families)
    ind_cand, camp_ind = _industry_source(camp, merged.industries, ind, families)
    hlp = help_grade(merged.camp_type, camp.camp_type)
    fits = tuple(_job_fit(camp, i, job, ind, hlp, relations) for i, job in enumerate(merged.jobs))
    present = [f for f in fits if f is not None]
    best = min(present, key=lambda f: f.key) if present else None
    return _Scored(camp, ind, ind_cand, camp_ind, hlp, fits, best)


def _recommendation(s: _Scored, rank: int, review: bool, guaranteed: bool) -> Recommendation:
    best = s.best
    return Recommendation(
        camp=s.camp, rank=rank,
        job=best.job if best else None, camp_job=best.camp_job if best else None,
        relation=best.relation if best else None,
        industry=s.industry, camp_industry=s.camp_industry, industry_grade=s.industry_grade,
        help_grade=s.help_grade, review=review, guaranteed=guaranteed)


def _unique_recruiting(camps: Iterable[Camp], check_recruiting: bool, log: list[str]) -> list[Camp]:
    seen: set[str] = set()
    result: list[Camp] = []
    for camp in camps:
        if camp.id in seen:
            log.append(f'같은 캠프 ID 중복 입력은 하나만 씀: {camp.id}')
            continue
        seen.add(camp.id)
        if check_recruiting and not camp.recruiting:
            continue
        result.append(camp)
    return result


def _match_industry_only(scored: list[_Scored], limit: int, log: list[str]) -> MatchResult:
    eligible = [s for s in scored if s.industry_grade in (IndustryGrade.MATCH, IndustryGrade.FAMILY)]
    picked = sorted(eligible, key=_Scored.key)[:limit]
    log.append(f'직무 없이 산업만 매칭: 산업 일치·계열 후보 {len(eligible)}개')
    recs = tuple(_recommendation(s, i + 1, review=True, guaranteed=False) for i, s in enumerate(picked))
    flags = {INDUSTRY_ONLY} | (set() if recs else {NO_CANDIDATES})
    return MatchResult(recs, frozenset(flags), tuple(log))


def match(merged: MergedSlots, camps: Sequence[Camp], relations: RelationIndex, families: FamilyIndex,
          *, limit: int = LIMIT, check_recruiting: bool = True) -> MatchResult:
    """병합 결과와 후보 캠프로 최대 limit개를 고른다. 후보 캠프는 SQL이 좁혀 넘기거나(서비스) 전체를 넘겨도(평가) 된다."""
    log: list[str] = []
    pool = _unique_recruiting(camps, check_recruiting, log)
    scored = [_score(c, merged, relations, families) for c in pool]

    if not merged.jobs:
        if not merged.industries:
            return MatchResult(flags=frozenset({NO_CANDIDATES}), log=('직무·산업이 없어 매칭하지 않음',))
        return _match_industry_only(scored, limit, log)

    a_count = sum(1 for s in scored if s.best is not None and s.best.grade == GRADE_A)
    allow_b = a_count < LIMIT
    eligible = [s for s in scored if s.best is not None and (s.best.grade == GRADE_A or allow_b)]
    if allow_b:
        log.append(f'A등급 캠프 {a_count}개라 B등급(FAMILY)도 후보에 넣음')

    # 복수 직무 분배: 앞 직무부터 그 직무 기준 A등급 최상위 캠프를 하나씩 보장
    guaranteed: list[_Scored] = []
    if len(merged.jobs) >= 2:
        for i, job in enumerate(merged.jobs[:min(MAX_GUARANTEED_JOBS, limit)]):
            options = [s for s in eligible if s not in guaranteed
                       and s.fits[i] is not None and s.fits[i].grade == GRADE_A]
            if not options:
                log.append(f'직무 {job.value}: A등급 캠프가 없어 자리 보장 없음')
                continue
            guaranteed.append(min(options, key=lambda s: (s.fits[i].key[:4], s.camp.id)))

    rest = sorted((s for s in eligible if s not in guaranteed), key=_Scored.key)
    picked = sorted([*guaranteed, *rest[:max(0, limit - len(guaranteed))]], key=_Scored.key)
    recs = tuple(_recommendation(s, i + 1, review=s.best.grade == GRADE_B, guaranteed=s in guaranteed)
                 for i, s in enumerate(picked))

    flags: set[str] = set()
    if any(r.review for r in recs):
        flags.add(FAMILY_USED)
    if not recs:
        flags.add(NO_CANDIDATES)
    return MatchResult(recs, frozenset(flags), tuple(log))
