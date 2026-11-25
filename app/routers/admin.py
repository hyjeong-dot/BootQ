"""API-004 어휘 재로드. 127.0.0.1에만 노출 (02_BACKEND.md 3장)."""
from fastapi import APIRouter, Request

router = APIRouter(prefix='/api/admin', tags=['admin'])


@router.post('/vocab/reload', summary='어휘·관계 재로드 (DB 적재 후)')
async def reload_vocab(request: Request) -> dict[str, int]:
    deps = request.app.state.deps
    return await deps.vocab.reload(deps.pool)
