"""공통 픽스처. DB 테스트(@pytest.mark.db)는 TEST_DATABASE_URL(bootq_test)을 쓴다 (docs/rules/07_TEST.md 2장).
- 연결할 수 없으면 로컬에서는 사유를 보여주고 건너뛰고, BOOTQ_REQUIRE_DB=1(CI)이면 실패한다
- 세션 시작 시 마이그레이션을 한 번 적용하고, 테스트마다 트랜잭션을 열었다가 롤백한다"""
import asyncio
import os
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app.config import load_env, testing_database_url
from scripts.migrate import migrate


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'


@pytest.fixture(scope='session')
def test_db_url() -> str:
    """마이그레이션을 적용한 테스트 DB 주소. 연결할 수 없으면 건너뜀(로컬) 또는 실패(CI)."""
    load_env()
    url = testing_database_url()
    try:
        asyncio.run(migrate(url))
    except psycopg.OperationalError as e:
        reason = f'테스트 DB에 연결할 수 없음 (docker compose up -d db): {str(e).splitlines()[0] if str(e) else e}'
        if os.environ.get('BOOTQ_REQUIRE_DB') == '1':
            pytest.fail(reason)
        pytest.skip(reason)
    return url


@pytest.fixture
async def db(test_db_url):
    """테스트마다 트랜잭션 하나. 끝나면 롤백해 다음 테스트에 남기지 않는다."""
    async with await psycopg.AsyncConnection.connect(test_db_url) as conn:
        try:
            yield conn
        finally:
            await conn.rollback()


@pytest.fixture
def empty_schema(test_db_url):
    """테스트 DB 안의 빈 스키마 하나와 search_path를 그 스키마로 둔 주소 (url, schema). 끝나면 지운다.
    마이그레이션 적용 자체를 시험하거나, 커밋되는 데이터가 필요한 테스트(서버가 자기 커넥션으로 읽음)에 쓴다."""
    schema = f'test_{uuid.uuid4().hex[:10]}'
    with psycopg.connect(test_db_url, autocommit=True) as conn:
        conn.execute(f'CREATE SCHEMA {schema}')
    try:
        yield make_conninfo(test_db_url, options=f'-csearch_path={schema}'), schema
    finally:
        with psycopg.connect(test_db_url, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA {schema} CASCADE')
