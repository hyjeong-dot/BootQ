"""API-001 글 등록, API-002 추천 결과 수신(SSE). 명세: docs/specs/10_API_SPEC.md"""
import asyncio
import json
import time
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.errors import NotFoundError
from app.repositories import recommendations as rec_repo
from app.repositories.recommendations import PROCESSING, NewPost, RecommendationView
from app.services.recommend import Deps, create_post, run_recommendation

router = APIRouter(prefix='/api/posts', tags=['posts'])

POLL_SECONDS = 0.5        # DB를 다시 읽는 간격
TIMEOUT_SECONDS = 45.0    # 슬롯필링 최악 약 30초 + 여유
PING_SECONDS = 15.0       # keep-alive 주석 줄


class PostIn(BaseModel):
    title: str = Field(max_length=200)
    content: str = Field(max_length=5000)
    category: str = Field('', max_length=50)
    category_group: str = Field('', max_length=50)
    target_job: str = Field('', max_length=100)
    target_company: str = Field('', max_length=100)


class PostCreated(BaseModel):
    post_id: UUID
    recommendation_id: UUID
    status: str


def deps_of(request: Request) -> Deps:
    return request.app.state.deps


@router.post('', status_code=201, response_model=PostCreated, summary='글 등록 (추천은 백그라운드)')
async def create(body: PostIn, background: BackgroundTasks, request: Request) -> PostCreated:
    deps = deps_of(request)
    post = NewPost(**body.model_dump())
    post_id, rec_id = await create_post(deps, post)
    background.add_task(run_recommendation, deps, rec_id, post)
    return PostCreated(post_id=post_id, recommendation_id=rec_id, status=PROCESSING)


def sse(event: str, data: dict) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


def result_payload(view: RecommendationView) -> dict:
    return {'recommendation_id': str(view.id), 'status': view.status,
            'cards': [{'rank': c.rank, 'camp_id': c.camp_id, 'camp_name': c.camp_name, 'reason': c.reason,
                       'review': c.review, 'tags': list(c.tags),
                       'recruit_start': c.recruit_start.isoformat() if c.recruit_start else None,
                       'recruit_end': c.recruit_end.isoformat() if c.recruit_end else None}
                      for c in view.cards]}


async def _events(deps: Deps, post_id: UUID, first: RecommendationView,
                  poll: float, timeout: float, ping: float) -> AsyncIterator[str]:
    view, started, last_ping = first, time.monotonic(), time.monotonic()
    while view.status == PROCESSING:
        now = time.monotonic()
        if now - started >= timeout:
            yield sse('timeout', {'recommendation_id': str(view.id)})
            return
        if now - last_ping >= ping:
            yield ': ping\n\n'
            last_ping = now
        await asyncio.sleep(poll)
        async with deps.pool.connection() as conn:
            view = await rec_repo.get_for_post(conn, post_id)
    yield sse('recommendation', result_payload(view))


@router.get('/{post_id}/recommendations/stream', summary='추천 결과 수신 (SSE)',
            response_description='text/event-stream: recommendation 또는 timeout 이벤트 하나 후 닫힘')
async def stream(post_id: UUID, request: Request) -> StreamingResponse:
    deps = deps_of(request)
    async with deps.pool.connection() as conn:
        view = await rec_repo.get_for_post(conn, post_id)
    if view is None:
        raise NotFoundError('글이 없습니다')
    settings = request.app.state.sse
    return StreamingResponse(_events(deps, post_id, view, *settings), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
