"""FastAPI 조립 (02_BACKEND.md 1장): 설정 읽기 → DB 풀 → 어휘 로드 → LLM 클라이언트 → 라우터.
테스트는 create_app에 테스트 DB 주소와 가짜 LLM 클라이언트를 넣는다."""
import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from psycopg_pool import AsyncConnectionPool

from app.config import database_url, load_env, resolve_model
from app.errors import install_handlers
from app.llm.base import LLMClient
from app.routers import admin, posts, recommendations
from app.services.recommend import Deps
from app.services.slot_filling import make_slot_client
from app.services.vocab import VocabStore
from app.sources.prompts import load_prompt

log = logging.getLogger(__name__)

_STANDARD = set(logging.LogRecord('', 0, '', 0, '', None, None).__dict__) | {'message', 'asctime'}


class JsonFormatter(logging.Formatter):
    """한 줄에 JSON 하나 (02_BACKEND.md 4장 "로깅 규칙"). 글 본문·제목은 로그에 넣지 않는다 — ID만."""

    def format(self, record: logging.LogRecord) -> str:
        data = {'level': record.levelname, 'logger': record.name, 'event': record.getMessage()}
        data.update({k: v for k, v in record.__dict__.items() if k not in _STANDARD})
        if record.exc_info:
            data['exc'] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def default_llm() -> LLMClient:
    """슬롯필링 클라이언트 (Groq, 05_AI.md). 키가 없으면 호출이 auth 오류로 끝나 추천이 failed로 남는다."""
    return make_slot_client(os.environ.get('GROQ_API_KEY', '').strip(), resolve_model('groq'))


def create_app(*, db_url: str | None = None, llm: LLMClient | None = None,
               sse: tuple[float, float, float] | None = None) -> FastAPI:
    """sse = (폴링 간격, 타임아웃, ping 간격) 초. 테스트에서 짧게 줄인다."""
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        load_env()
        pool = AsyncConnectionPool(db_url or database_url(), min_size=1, max_size=5, open=False)
        await pool.open(wait=True)
        store = VocabStore()
        try:
            counts = await store.reload(pool)
            log.info('vocab_loaded', extra=counts)
        except Exception as e:   # noqa: BLE001 — 적재 전이어도 서버는 뜬다 (추천은 vocab_empty로 끝남)
            log.warning('vocab_load_failed', extra={'error': type(e).__name__})
        app.state.deps = Deps(pool=pool, vocab=store, llm=llm or default_llm(),
                              slot_template=load_prompt('slot_filling'))
        try:
            yield
        finally:
            await pool.close()

    app = FastAPI(title='BootQ', summary='커뮤니티 고민 글 → 직무 부트캠프 추천', lifespan=lifespan)
    app.state.sse = sse or (posts.POLL_SECONDS, posts.TIMEOUT_SECONDS, posts.PING_SECONDS)
    install_handlers(app)
    for r in (posts.router, recommendations.router, admin.router):
        app.include_router(r)
    return app


setup_logging()
app = create_app()
