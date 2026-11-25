"""작은 예외 계층과 전역 핸들러 (02_BACKEND.md 4장 "예외 처리 전략", 2장 "에러 응답 규약").
응답 형식: {"error": {"code": "...", "message": "..."}}"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)

VALIDATION_ERROR, NOT_FOUND, INTERNAL_ERROR = 'validation_error', 'not_found', 'internal_error'


class AppError(Exception):
    def __init__(self, code: str, status: int, message: str = ''):
        super().__init__(message or code)
        self.code, self.status, self.message = code, status, message or code


class NotFoundError(AppError):
    def __init__(self, message: str = '찾을 수 없습니다'):
        super().__init__(NOT_FOUND, 404, message)


class ValidationError(AppError):
    def __init__(self, message: str):
        super().__init__(VALIDATION_ERROR, 400, message)


def error_body(code: str, message: str) -> dict:
    return {'error': {'code': code, 'message': message}}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError) -> JSONResponse:
        return JSONResponse(error_body(e.code, e.message), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        # FastAPI 기본 422를 400 validation_error로. 어느 칸이 왜 틀렸는지만 (입력값은 되돌려 보내지 않는다)
        detail = '; '.join(f"{'.'.join(str(p) for p in err['loc'][1:]) or 'body'}: {err['msg']}" for err in e.errors())
        return JSONResponse(error_body(VALIDATION_ERROR, detail), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        code = NOT_FOUND if e.status_code == 404 else VALIDATION_ERROR if e.status_code < 500 else INTERNAL_ERROR
        return JSONResponse(error_body(code, str(e.detail)), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, e: Exception) -> JSONResponse:
        log.exception('unhandled_error', extra={'error': type(e).__name__})
        return JSONResponse(error_body(INTERNAL_ERROR, '서버 오류'), status_code=500)
