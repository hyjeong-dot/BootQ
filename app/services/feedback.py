"""카드별 피드백 (API-003). 덧붙이기만 한다."""
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from app.errors import NotFoundError, ValidationError
from app.repositories import recommendations as rec_repo

DOWN = 'down'


async def add_feedback(pool: AsyncConnectionPool, rec_id: UUID, rank: int, camp_id: str, vote: str,
                       reason: str | None) -> UUID:
    if reason is not None and vote != DOWN:
        raise ValidationError('reason은 vote=down일 때만 보낼 수 있습니다')
    async with pool.connection() as conn, conn.transaction():
        card = await rec_repo.get_card_camp(conn, rec_id, rank)
        if card is None:
            raise NotFoundError('그 추천의 그 순위 카드가 없습니다')
        source, source_camp_id = card
        if camp_id != source_camp_id:
            raise ValidationError('camp_id가 그 순위 카드의 캠프와 다릅니다')
        return await rec_repo.add_feedback(conn, rec_id, rank, source, source_camp_id, vote, reason)
