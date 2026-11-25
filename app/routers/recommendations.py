"""API-003 카드별 피드백. 명세: docs/specs/10_API_SPEC.md"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.feedback import add_feedback

router = APIRouter(prefix='/api/recommendations', tags=['feedback'])

ReasonCode = Literal['job_mismatch', 'industry_mismatch', 'not_needed', 'other']


class FeedbackIn(BaseModel):
    rank: int = Field(ge=1, le=3)
    camp_id: str = Field(min_length=1, max_length=100)
    vote: Literal['up', 'down']
    reason: ReasonCode | None = None


class FeedbackCreated(BaseModel):
    feedback_id: UUID


@router.post('/{rec_id}/feedback', status_code=201, response_model=FeedbackCreated, summary='카드별 👍/👎')
async def feedback(rec_id: UUID, body: FeedbackIn, request: Request) -> FeedbackCreated:
    feedback_id = await add_feedback(request.app.state.deps.pool, rec_id, body.rank, body.camp_id, body.vote,
                                     body.reason)
    return FeedbackCreated(feedback_id=feedback_id)
