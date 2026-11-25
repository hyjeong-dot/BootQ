"""
평가 (BAT-005). 순수 함수만 둔다: 파일·DB·LLM을 쓰지 않는다. 파일 읽기는 app/sources/, 실행은 scripts/evaluate.py.
설계와 지표 정의의 원본: docs/EVAL.md "평가 스크립트"

- 질문 하나: 1차 게이트 → 슬롯(저장된 시험 결과 또는 정답 슬롯) → 병합 → 2차 게이트 → 매칭 (서비스와 같은 순서)
- 판정: 허용 / 불허 / 미판정. 미판정은 불허로 세고 개수를 따로 낸다 (블라인드 풀링 전)
- 지표: 슬롯 정확도(병합 결과 기준)와 매칭 정확도(Hit@3, Precision@3, 추천 없음 정답률, ideal 밀림)를 분리
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from app.core.gate import gate_after_merge, gate_before_slots
from app.core.industry import FamilyIndex
from app.core.matching import RelationIndex, match
from app.core.merge import merge
from app.core.models import BODY_EXPLICIT, HELP_FROM_CATEGORY, Camp, Candidate, MatchResult, MergedSlots, PostInput
from app.core.slot_filling import FieldHint, SlotResult

SEP = '|'
GROUP_SEP = ';'
TOP_K = 3

ALLOWED, DISALLOWED, UNJUDGED = 'allowed', 'disallowed', 'unjudged'

# 추천 없이 끝난 사유 (게이트 코드 외에 평가에서 생기는 것)
SLOT_MISSING = 'slot_missing'     # 슬롯 파일에 그 질문이 없음
SLOT_ERROR = 'slot_error'         # 슬롯필링이 오류 결과
NO_CANDIDATES = 'no_candidates'   # 매칭 결과 0개


# ---------- 정답 셋 ----------
@dataclass(frozen=True)
class AnswerKey:
    eval_id: str
    expected_jobs: tuple[str, ...] = ()
    optional_jobs: tuple[str, ...] = ()
    expected_industries: tuple[str, ...] = ()
    no_recommendation: bool = False
    allowed: frozenset[str] = frozenset()
    disallowed: frozenset[str] = frozenset()
    ideal: frozenset[str] = frozenset()
    required_groups: tuple[tuple[str, frozenset[str]], ...] = ()   # (직무, 허용 캠프 ID들)


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or '').split(SEP) if v.strip())


def parse_required_groups(text: str) -> tuple[tuple[str, frozenset[str]], ...]:
    """`직무:id|id;직무:id|id` → ((직무, {id, ...}), ...). 형식이 틀리면 ValueError."""
    groups = []
    for part in (text or '').split(GROUP_SEP):
        if not part.strip():
            continue
        job, sep, ids = part.partition(':')
        if not sep or not job.strip() or not _split(ids):
            raise ValueError(f'required_groups 형식 오류: {part!r}')
        groups.append((job.strip(), frozenset(_split(ids))))
    return tuple(groups)


def parse_answer_row(row: Mapping[str, str]) -> AnswerKey:
    """answer_set.csv 한 행 → AnswerKey."""
    flag = (row.get('no_recommendation') or '').strip().upper()
    if flag not in ('Y', 'N'):
        raise ValueError(f"{row.get('eval_id')}: no_recommendation은 Y 또는 N이어야 함 ({flag!r})")
    return AnswerKey(
        eval_id=row['eval_id'].strip(),
        expected_jobs=_split(row.get('expected_jobs', '')),
        optional_jobs=_split(row.get('optional_jobs', '')),
        expected_industries=_split(row.get('expected_industries', '')),
        no_recommendation=flag == 'Y',
        allowed=frozenset(_split(row.get('allowed_camp_ids', ''))),
        disallowed=frozenset(_split(row.get('disallowed_camp_ids', ''))),
        ideal=frozenset(_split(row.get('ideal_camp_ids', ''))),
        required_groups=parse_required_groups(row.get('required_groups', '')),
    )


def check_answer_key(key: AnswerKey, camp_ids: Iterable[str]) -> list[str]:
    """정답 셋의 모순·누락 경고 (실행은 계속한다)."""
    known = set(camp_ids)
    warnings = []
    if key.allowed & key.disallowed:
        warnings.append(f'{key.eval_id}: 허용과 불허에 모두 있음 {sorted(key.allowed & key.disallowed)}')
    if not key.ideal <= key.allowed:
        warnings.append(f'{key.eval_id}: ideal인데 허용이 아님 {sorted(key.ideal - key.allowed)}')
    for job, ids in key.required_groups:
        if not ids <= key.allowed:
            warnings.append(f'{key.eval_id}: 묶음 {job}에 허용이 아닌 캠프 {sorted(ids - key.allowed)}')
    unknown = (key.allowed | key.disallowed) - known
    if unknown:
        warnings.append(f'{key.eval_id}: 캠프 파일에 없는 ID {sorted(unknown)}')
    if key.no_recommendation and (key.allowed or key.required_groups):
        warnings.append(f'{key.eval_id}: 추천 없음이 정답인데 허용 캠프가 있음')
    return warnings


# ---------- 캠프 (3갈래 ①) ----------
def camp_for_rule_baseline(*, id: str, name: str, base_job_ids: tuple[str, ...],
                           base_industry_ids: tuple[str, ...], manual_not_camp: bool = False) -> Camp | None:
    """① 규칙+수동: 기준값(기준선 + 수동 보정) 칸만 쓴다. camp_type 없음, LLM의 캠프 아님 판정은 쓰지 않는다.
    ②는 core.models.camp_for_matching을 그대로 쓴다."""
    if manual_not_camp:
        return None
    return Camp(id, name, tuple(base_job_ids), tuple(base_industry_ids), None, True)


# ---------- 산업 계열 넣고 빼기 (E13 비교용) ----------
def edit_family_pairs(pairs: Iterable[tuple[str, str]], add: Sequence[tuple[str, Sequence[str]]] = (),
                      drop: Iterable[str] = ()) -> list[tuple[str, str]]:
    """(계열, 산업) 쌍에서 drop 계열을 빼고 add 계열을 더한다. 순서 유지, 중복 제거."""
    dropped = set(drop)
    result: list[tuple[str, str]] = []
    for p in [*(p for p in pairs if p[0] not in dropped), *((f, i) for f, inds in add for i in inds)]:
        if p not in result:
            result.append(p)
    return result


# ---------- 질문 하나 처리 ----------
@dataclass(frozen=True)
class QuestionRun:
    eval_id: str
    merged: MergedSlots | None             # 1차 게이트·슬롯 오류로 끝나면 None
    stop_reason: str | None                # 추천 없이 끝난 사유. 추천이 있으면 None
    result: MatchResult | None = None

    @property
    def camp_ids(self) -> tuple[str, ...]:
        return tuple(r.camp.id for r in self.result.recommendations) if self.result else ()


def slots_from_trial(post: PostInput, slots: SlotResult | None, job_hint: FieldHint | None,
                     company_hint: FieldHint | None, category_camp_type: Mapping[str, str]
                     ) -> tuple[MergedSlots | None, str | None]:
    """시험 결과 슬롯 모드: 1차 게이트 → 슬롯 → 병합. (병합 결과, 종료 사유)."""
    stop = gate_before_slots(post)
    if stop:
        return None, stop
    if slots is None:
        return None, SLOT_MISSING
    if not slots.ok:
        return None, SLOT_ERROR
    return merge(slots, job_hint, company_hint, post.category, category_camp_type), None


def slots_from_gold(post: PostInput, key: AnswerKey, category_camp_type: Mapping[str, str]
                    ) -> tuple[MergedSlots | None, str | None]:
    """정답 슬롯 모드: expected_*를 병합 결과로 그대로 (나열 순서 = 병합 순서, 출처는 본문 명시, optional 제외).
    desired_help는 UNKNOWN으로 보고 category 기본값을 쓴다."""
    stop = gate_before_slots(post)
    if stop:
        return None, stop
    camp_type = category_camp_type.get(post.category.strip()) or None
    return MergedSlots(
        jobs=tuple(Candidate(j, BODY_EXPLICIT, j) for j in key.expected_jobs),
        industries=tuple(Candidate(i, BODY_EXPLICIT, i) for i in key.expected_industries),
        camp_type=camp_type, help_source=HELP_FROM_CATEGORY if camp_type else None), None


def match_question(eval_id: str, merged: MergedSlots | None, stop_reason: str | None, camps: Sequence[Camp],
                   relations: RelationIndex, families: FamilyIndex) -> QuestionRun:
    """2차 게이트 → 매칭. 평가에서는 모집 중 검사를 끈다."""
    if merged is None:
        return QuestionRun(eval_id, None, stop_reason)
    stop = gate_after_merge(merged)
    if stop:
        return QuestionRun(eval_id, merged, stop)
    result = match(merged, camps, relations, families, check_recruiting=False)
    return QuestionRun(eval_id, merged, None if result.recommendations else NO_CANDIDATES, result)


# ---------- 채점 ----------
def verdict(key: AnswerKey, camp_id: str) -> str:
    """추천 없음이 정답인 질문의 추천은 모두 불허 (풀링 대상이 아니다)."""
    if key.no_recommendation:
        return DISALLOWED
    if camp_id in key.allowed:
        return ALLOWED
    if camp_id in key.disallowed:
        return DISALLOWED
    return UNJUDGED


@dataclass(frozen=True)
class MatchScore:
    eval_id: str
    no_recommendation: bool
    camp_ids: tuple[str, ...]              # 상위 3개, 순서대로
    verdicts: tuple[str, ...]
    hit: bool | None                       # 추천이 필요한 질문만. 추천 없음이 정답이면 None
    missing_groups: tuple[str, ...]        # 상위 3개에 하나도 없는 required_groups 직무
    ideal_total: int                       # 정답 셋의 ideal 수
    ideal_in_top: int
    ideal_pushed: bool                     # 상위 3개의 ideal 수 < min(3, ideal 수)

    @property
    def allowed_count(self) -> int:
        return self.verdicts.count(ALLOWED)

    @property
    def unjudged(self) -> tuple[str, ...]:
        return tuple(c for c, v in zip(self.camp_ids, self.verdicts) if v == UNJUDGED)


def score_match(key: AnswerKey, camp_ids: Sequence[str], k: int = TOP_K) -> MatchScore:
    top = tuple(camp_ids[:k])
    verdicts = tuple(verdict(key, c) for c in top)
    hit, missing = None, ()
    if not key.no_recommendation:
        if key.required_groups:
            missing = tuple(job for job, ids in key.required_groups if not ids & set(top))
            hit = bool(top) and not missing
        else:
            hit = ALLOWED in verdicts
    ideal_in_top = sum(1 for c in top if c in key.ideal)
    pushed = bool(key.ideal) and not key.no_recommendation and ideal_in_top < min(k, len(key.ideal))
    return MatchScore(key.eval_id, key.no_recommendation, top, verdicts, hit, missing, len(key.ideal), ideal_in_top,
                      pushed)


@dataclass(frozen=True)
class AxisScore:
    """슬롯 한 축(직무 또는 산업). 병합 결과 기준."""
    expected: tuple[str, ...]
    optional: tuple[str, ...]
    predicted: tuple[str, ...]

    @property
    def exact(self) -> bool:
        """expected ⊆ 예측 ⊆ expected ∪ optional"""
        pred = set(self.predicted)
        return set(self.expected) <= pred <= set(self.expected) | set(self.optional)

    @property
    def found(self) -> int:
        """정답 값 중 예측에 있는 수 (재현율 분자)"""
        return sum(1 for v in self.expected if v in self.predicted)

    @property
    def correct(self) -> int:
        """예측 값 중 정답·optional인 수 (정밀도 분자)"""
        ok = set(self.expected) | set(self.optional)
        return sum(1 for v in self.predicted if v in ok)


@dataclass(frozen=True)
class SlotScore:
    eval_id: str
    jobs: AxisScore
    industries: AxisScore


def score_slots(key: AnswerKey, merged: MergedSlots | None) -> SlotScore:
    """1차 게이트·슬롯 오류로 끝난 질문은 예측이 비어 있는 것으로 본다."""
    jobs = tuple(c.value for c in merged.jobs) if merged else ()
    industries = tuple(c.value for c in merged.industries) if merged else ()
    return SlotScore(key.eval_id, AxisScore(key.expected_jobs, key.optional_jobs, jobs),
                     AxisScore(key.expected_industries, (), industries))


# ---------- 집계 ----------
@dataclass(frozen=True)
class Ratio:
    num: int
    den: int

    @property
    def value(self) -> float | None:
        return self.num / self.den if self.den else None

    def __str__(self) -> str:
        return f'{self.num}/{self.den}' + (f' ({self.value:.1%})' if self.den else '')


@dataclass(frozen=True)
class AxisSummary:
    exact: Ratio          # 질문 단위 정확
    recall: Ratio         # 값 단위
    precision: Ratio      # 값 단위


@dataclass(frozen=True)
class Summary:
    questions: int
    hit_at_3: Ratio                        # 추천이 필요한 질문 중 Hit
    precision_at_3: Ratio                  # 전체 추천 중 허용 (미판정은 불허로 셈)
    unjudged: int                          # 미판정 추천 수 (블라인드 풀링 대상)
    no_rec_correct: Ratio                  # 추천 없음이 정답인 질문 중 추천하지 않은 비율
    rec_given: Ratio                       # 추천이 필요한 질문 중 추천한 비율
    ideal_pushed: tuple[str, ...]          # ideal 밀림 질문
    ideal_questions: int                   # ideal이 있는 질문 수 (추천이 필요한 질문만)
    jobs: AxisSummary | None = None        # 슬롯 정확도 (시험 결과 슬롯 모드에서만)
    industries: AxisSummary | None = None


def _axis_summary(axes: Sequence[AxisScore]) -> AxisSummary:
    return AxisSummary(
        exact=Ratio(sum(a.exact for a in axes), len(axes)),
        recall=Ratio(sum(a.found for a in axes), sum(len(a.expected) for a in axes)),
        precision=Ratio(sum(a.correct for a in axes), sum(len(a.predicted) for a in axes)))


def summarize(matches: Sequence[MatchScore], slots: Sequence[SlotScore] | None = None) -> Summary:
    need = [m for m in matches if not m.no_recommendation]
    none = [m for m in matches if m.no_recommendation]
    return Summary(
        questions=len(matches),
        hit_at_3=Ratio(sum(bool(m.hit) for m in need), len(need)),
        precision_at_3=Ratio(sum(m.allowed_count for m in matches), sum(len(m.camp_ids) for m in matches)),
        unjudged=sum(len(m.unjudged) for m in matches),
        no_rec_correct=Ratio(sum(not m.camp_ids for m in none), len(none)),
        rec_given=Ratio(sum(bool(m.camp_ids) for m in need), len(need)),
        ideal_pushed=tuple(m.eval_id for m in need if m.ideal_pushed),
        ideal_questions=sum(1 for m in need if m.ideal_total),
        jobs=_axis_summary([s.jobs for s in slots]) if slots else None,
        industries=_axis_summary([s.industries for s in slots]) if slots else None,
    )


def blind_pool(matches: Iterable[MatchScore]) -> list[tuple[str, str]]:
    """미판정 (eval_id, camp_id). 어느 실행이 냈는지는 담지 않는다."""
    return sorted({(m.eval_id, c) for m in matches for c in m.unjudged})
