"""글·추천·카드·피드백 (API-001~003, 추천 처리 저장)."""
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.core.models import camp_hashtags

PROCESSING, DONE, FAILED = 'processing', 'done', 'failed'


@dataclass(frozen=True)
class NewPost:
    title: str
    content: str
    category: str = ''
    category_group: str = ''
    target_job: str = ''
    target_company: str = ''


@dataclass(frozen=True)
class ItemRow:
    """저장할 카드 한 장 (core.models.Recommendation + 사유)."""
    rank: int
    source: str
    source_camp_id: str
    job_id: str | None
    camp_job_id: str | None
    relation: str | None
    industry_id: str | None
    camp_industry_id: str | None
    industry_grade: str | None
    help_grade: str | None
    review: bool
    guaranteed: bool
    reason: str


@dataclass(frozen=True)
class Outcome:
    """추천 처리 1회의 결과 기록 (recorder가 모은 것)."""
    status: str                    # done | failed
    end_reason: str | None = None
    error_code: str | None = None
    slots: dict | None = None
    merged: dict | None = None
    flags: tuple[str, ...] = ()
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    stage_ms: dict | None = None
    total_ms: int | None = None


@dataclass(frozen=True)
class Card:
    rank: int
    camp_id: str
    camp_name: str
    reason: str
    review: bool
    tags: tuple[str, ...] = ()
    recruit_start: date | None = None
    recruit_end: date | None = None


@dataclass(frozen=True)
class RecommendationView:
    id: UUID
    status: str
    cards: tuple[Card, ...]


async def create_post(conn: AsyncConnection, post: NewPost) -> tuple[UUID, UUID]:
    """글과 recommendation(processing)을 만든다. (post_id, recommendation_id)."""
    cur = await conn.execute(
        'INSERT INTO post (title, content, category, category_group, target_job, target_company) '
        'VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
        (post.title, post.content, post.category, post.category_group, post.target_job, post.target_company))
    post_id = (await cur.fetchone())[0]
    cur = await conn.execute('INSERT INTO recommendation (post_id) VALUES (%s) RETURNING id', (post_id,))
    return post_id, (await cur.fetchone())[0]


async def finish(conn: AsyncConnection, rec_id: UUID, outcome: Outcome, items: list[ItemRow]) -> None:
    """처리 결과와 카드를 저장한다. 트랜잭션은 호출자가 연다 (결과와 카드를 함께)."""
    await conn.execute(
        """UPDATE recommendation SET status = %s, end_reason = %s, error_code = %s, slots = %s, merged = %s,
               flags = %s, model = %s, prompt_tokens = %s, completion_tokens = %s, stage_ms = %s, total_ms = %s,
               completed_at = now()
           WHERE id = %s""",
        (outcome.status, outcome.end_reason, outcome.error_code,
         Jsonb(outcome.slots) if outcome.slots is not None else None,
         Jsonb(outcome.merged) if outcome.merged is not None else None,
         list(outcome.flags), outcome.model, outcome.prompt_tokens, outcome.completion_tokens,
         Jsonb(outcome.stage_ms or {}), outcome.total_ms, rec_id))
    if items:
        async with conn.cursor() as cur:
            await cur.executemany(
                """INSERT INTO recommendation_item (recommendation_id, rank, source, source_camp_id, job_id,
                       camp_job_id, relation, industry_id, camp_industry_id, industry_grade, help_grade, review,
                       guaranteed, reason)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(rec_id, i.rank, i.source, i.source_camp_id, i.job_id, i.camp_job_id, i.relation, i.industry_id,
                  i.camp_industry_id, i.industry_grade, i.help_grade, i.review, i.guaranteed, i.reason)
                 for i in items])


async def post_exists(conn: AsyncConnection, post_id: UUID) -> bool:
    cur = await conn.execute('SELECT 1 FROM post WHERE id = %s', (post_id,))
    return await cur.fetchone() is not None


async def get_for_post(conn: AsyncConnection, post_id: UUID) -> RecommendationView | None:
    """글의 추천 상태와 카드 (rank 순). 글이 없으면 None."""
    cur = await conn.execute('SELECT id, status FROM recommendation WHERE post_id = %s', (post_id,))
    row = await cur.fetchone()
    if row is None:
        return None
    rec_id, status = row
    # 해시태그는 지금의 camp_profile로 만든다 (표시용이라 추천 시점 값을 따로 저장하지 않음)
    cur = await conn.execute(
        """SELECT i.rank, i.source_camp_id, r.name, i.reason, i.review, r.recruit_start, r.recruit_end,
                  p.status, p.job_ids, p.industry_ids, p.skills, p.tags,
                  p.base_job_ids, p.base_industry_ids, p.base_skills
           FROM recommendation_item i
           JOIN camp_raw r USING (source, source_camp_id)
           LEFT JOIN camp_profile p USING (source, source_camp_id)
           WHERE i.recommendation_id = %s ORDER BY i.rank""", (rec_id,))
    cards = []
    for (rank, camp_id, name, reason, review, start, end,
         p_status, jobs, inds, skills, tags, b_jobs, b_inds, b_skills) in await cur.fetchall():
        hashtags = () if p_status is None else camp_hashtags(
            status=p_status, job_ids=tuple(jobs), industry_ids=tuple(inds), skills=tuple(skills),
            tags=tuple(tags), base_job_ids=tuple(b_jobs), base_industry_ids=tuple(b_inds),
            base_skills=tuple(b_skills))
        cards.append(Card(rank, camp_id, name, reason, review, hashtags, start, end))
    return RecommendationView(rec_id, status, tuple(cards))


async def get_card_camp(conn: AsyncConnection, rec_id: UUID, rank: int) -> tuple[str, str] | None:
    """그 추천의 그 순위 카드의 (source, source_camp_id). 없으면 None."""
    cur = await conn.execute(
        'SELECT source, source_camp_id FROM recommendation_item WHERE recommendation_id = %s AND rank = %s',
        (rec_id, rank))
    row = await cur.fetchone()
    return (row[0], row[1]) if row else None


async def add_feedback(conn: AsyncConnection, rec_id: UUID, rank: int, source: str, source_camp_id: str,
                       vote: str, reason: str | None) -> UUID:
    cur = await conn.execute(
        'INSERT INTO feedback (recommendation_id, rank, source, source_camp_id, vote, reason) '
        'VALUES (%s, %s, %s, %s, %s, %s) RETURNING id', (rec_id, rank, source, source_camp_id, vote, reason))
    return (await cur.fetchone())[0]
