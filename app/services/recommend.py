"""
추천 처리 (API-001이 백그라운드로 시작). 단계와 기록: docs/specs/10_API_SPEC.md "추천 처리 (백그라운드)".

gate1 → field → slot_filling(LLM, asyncio.to_thread) → merge → gate2 → candidates(SQL) → match → reason → save
- 결정은 모두 core 순수 함수가 하고, 여기서는 DB·LLM 호출과 단계 연결·기록만 한다
- LLM 호출 중에는 트랜잭션을 열지 않는다. 결과와 카드는 마지막에 한 트랜잭션으로 저장한다
- 예외는 여기서 잡아 failed / internal_error로 남긴다 (BackgroundTasks의 예외는 HTTP로 가지 않음)
"""
import asyncio
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from app.core.gate import gate_after_merge, gate_before_slots
from app.core.matching import NO_CANDIDATES, candidate_industry_ids, candidate_job_ids, match
from app.core.merge import merge
from app.core.models import MergedSlots, PostInput, Recommendation
from app.core.reason import build_reason
from app.core.slot_filling import SlotInput, company_field_hint, job_field_hint
from app.llm.base import LLMClient
from app.repositories import camps as camp_repo
from app.repositories import recommendations as rec_repo
from app.repositories.recommendations import DONE, FAILED, ItemRow, NewPost, Outcome
from app.services.slot_filling import fill_slots
from app.services.vocab import Vocab, VocabStore

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))        # 모집 중 판단 기준 (Asia/Seoul, 서머타임 없음)
VOCAB_EMPTY = 'vocab_empty'               # DB 적재 전
INTERNAL_ERROR = 'internal_error'


def today_kst() -> date:
    return datetime.now(KST).date()


@dataclass
class Deps:
    """추천 처리에 필요한 것. main.py가 조립하고 테스트는 가짜 LLM 클라이언트를 넣는다."""
    pool: AsyncConnectionPool
    vocab: VocabStore
    llm: LLMClient
    slot_template: str
    today: Callable[[], date] = today_kst


@dataclass
class Recorder:
    """단계별 처리시간과 LLM 측정값을 한 곳에 모은다 (02_BACKEND.md 4장 "로깅 규칙")."""
    started: float = field(default_factory=time.perf_counter)
    stage_ms: dict[str, int] = field(default_factory=dict)
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.stage_ms[name] = round((time.perf_counter() - t) * 1000)

    def outcome(self, status: str, **kwargs) -> Outcome:
        return Outcome(status=status, model=self.model, prompt_tokens=self.prompt_tokens,
                       completion_tokens=self.completion_tokens, stage_ms=dict(self.stage_ms),
                       total_ms=round((time.perf_counter() - self.started) * 1000), **kwargs)


def to_jsonable(value):
    """core 데이터클래스 → JSONB에 넣을 값 (frozenset은 정렬한 리스트, Enum은 이름)."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, (set, frozenset)):
        return sorted(to_jsonable(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    return value


def _item(rec: Recommendation, source: str, reason: str) -> ItemRow:
    return ItemRow(
        rank=rec.rank, source=source, source_camp_id=rec.camp.id,
        job_id=rec.job.value if rec.job else None, camp_job_id=rec.camp_job, relation=rec.relation,
        industry_id=rec.industry.value if rec.industry else None, camp_industry_id=rec.camp_industry,
        industry_grade=rec.industry_grade.name if rec.industry_grade is not None else None,
        help_grade=rec.help_grade.name if rec.help_grade is not None else None,
        review=rec.review, guaranteed=rec.guaranteed, reason=reason)


async def _pipeline(deps: Deps, post: NewPost, rec: Recorder) -> tuple[Outcome, list[ItemRow]]:
    vocab: Vocab = deps.vocab.current
    if vocab.empty:
        return rec.outcome(FAILED, error_code=VOCAB_EMPTY), []

    with rec.stage('gate1'):
        stop = gate_before_slots(PostInput(post.title, post.content, post.category, post.category_group))
    if stop:
        return rec.outcome(DONE, end_reason=stop), []

    with rec.stage('field'):
        job_hint = job_field_hint(post.target_job, vocab.slot_vocab, vocab.job_aliases)
        company_hint = company_field_hint(post.target_company, vocab.companies)

    with rec.stage('slot_filling'):
        slots, metrics = await asyncio.to_thread(
            fill_slots, deps.llm, SlotInput(post.title, post.content, job_hint, company_hint),
            vocab.slot_vocab, deps.slot_template)
    rec.model = getattr(deps.llm, 'model', None)
    rec.prompt_tokens, rec.completion_tokens = metrics.get('input_tokens'), metrics.get('output_tokens')
    if not slots.ok:
        return rec.outcome(FAILED, error_code=slots.error_code, slots=to_jsonable(slots)), []

    with rec.stage('merge'):
        merged: MergedSlots = merge(slots, job_hint, company_hint, post.category, vocab.categories)
        stop = gate_after_merge(merged)
    recorded = {'slots': to_jsonable(slots), 'merged': to_jsonable(merged)}
    if stop:
        return rec.outcome(DONE, end_reason=stop, flags=tuple(sorted(merged.flags)), **recorded), []

    with rec.stage('candidates'):
        user_jobs = [c.value for c in merged.jobs]
        async with deps.pool.connection() as conn:
            camps, sources = await camp_repo.find_candidates(
                conn, today=deps.today(),
                job_ids=candidate_job_ids(user_jobs, vocab.relations) if user_jobs else (),
                industry_ids=() if user_jobs else candidate_industry_ids(
                    [c.value for c in merged.industries], vocab.families))

    with rec.stage('match'):
        # 모집 중은 SQL이 이미 걸렀다 (find_candidates가 넘기는 캠프는 모두 recruiting=True)
        result = match(merged, camps, vocab.relations, vocab.families)
    flags = tuple(sorted(merged.flags | result.flags))
    if not result.recommendations:
        return rec.outcome(DONE, end_reason=NO_CANDIDATES, flags=flags, **recorded), []

    with rec.stage('reason'):
        items = [_item(r, sources[r.camp.id], build_reason(r, merged)) for r in result.recommendations]
    return rec.outcome(DONE, flags=flags, **recorded), items


async def run_recommendation(deps: Deps, rec_id: UUID, post: NewPost) -> None:
    """추천 하나를 만들어 저장한다. 어떤 경우에도 recommendation 행을 processing에서 끝낸다."""
    rec = Recorder()
    try:
        outcome, items = await _pipeline(deps, post, rec)
    except Exception as e:      # noqa: BLE001 — 백그라운드라 여기서 잡지 않으면 processing으로 남는다
        log.exception('recommendation_failed', extra={'rec_id': str(rec_id), 'error': type(e).__name__})
        outcome, items = rec.outcome(FAILED, error_code=INTERNAL_ERROR), []
    try:
        async with deps.pool.connection() as conn, conn.transaction():
            await rec_repo.finish(conn, rec_id, outcome, items)
    except Exception as e:      # noqa: BLE001 — 카드 저장이 실패해도 행은 끝낸다
        log.exception('recommendation_save_failed', extra={'rec_id': str(rec_id), 'error': type(e).__name__})
        async with deps.pool.connection() as conn, conn.transaction():
            await rec_repo.finish(conn, rec_id, rec.outcome(FAILED, error_code=INTERNAL_ERROR), [])
        return
    log.info('recommendation_done', extra={'rec_id': str(rec_id), 'status': outcome.status,
                                           'end_reason': outcome.end_reason, 'error_code': outcome.error_code,
                                           'cards': len(items), 'total_ms': outcome.total_ms})


async def create_post(deps: Deps, post: NewPost) -> tuple[UUID, UUID]:
    """글과 processing 상태의 추천 행을 만든다 (API-001). 추천 처리는 호출자가 백그라운드로 시작한다."""
    async with deps.pool.connection() as conn, conn.transaction():
        return await rec_repo.create_post(conn, post)
