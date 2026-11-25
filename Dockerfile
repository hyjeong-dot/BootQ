# API 컨테이너 (docs/rules/06_INFRA_DEPLOY.md). 의존성은 uv.lock 그대로, 개발 의존성 제외.
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 의존성 층을 먼저 (코드만 바뀌면 이 층은 캐시)
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY db ./db
COPY prompts ./prompts
COPY data/vocab ./data/vocab

RUN useradd --create-home --uid 1000 bootq
USER bootq

EXPOSE 8000
# 시작할 때 마이그레이션 적용 후 서버 (컨테이너 안은 0.0.0.0, 호스트 게시는 compose.yaml에서 127.0.0.1만)
CMD ["sh", "-c", "python scripts/migrate.py && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
