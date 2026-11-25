"""
마이그레이션 적용 (#13, docs/rules/04_DATABASE.md 1장 "마이그레이션 도구").

db/migrations/NNN_이름.sql을 번호 순서로 보고, schema_migration에 없는 파일만 파일마다 트랜잭션 하나로 적용한다.
- 이미 적용한 파일의 내용(checksum)이 바뀌었으면 아무것도 적용하지 않고 멈춘다 (적용한 파일은 고치지 않고 새 번호로 추가)
- 실패하면 그 파일만 롤백되고 멈춘다. 앞서 적용한 파일은 남는다
- 적용 중에는 advisory lock을 잡아 동시 실행(API 컨테이너 시작 + 수동 실행)을 막는다
- 되돌리기(down)는 없다. 로컬 데모라 `docker compose down -v`로 지우고 다시 만든다

실행:
    uv run python scripts/migrate.py                       # .env의 DATABASE_URL (없으면 기본값)
    uv run python scripts/migrate.py --test                # TEST_DATABASE_URL (bootq_test)
    uv run python scripts/migrate.py --database-url postgresql://...
    uv run python scripts/migrate.py --status              # 적용 여부만 출력
"""
import argparse
import asyncio
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import database_url, load_env, testing_database_url  # noqa: E402

MIGRATIONS_DIR = ROOT / 'db' / 'migrations'
FILENAME = re.compile(r'^(\d{3})_[a-z0-9_]+\.sql$')
LOCK_KEY = 7_013_001          # pg_advisory_lock 키 (이 프로젝트의 마이그레이션 전용 임의 값)

CREATE_HISTORY = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     text        PRIMARY KEY,
    filename    text        NOT NULL,
    checksum    text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    """적용을 멈춰야 하는 상태 (파일 이름 규칙 위반, 번호 중복, 적용한 파일 변경)."""


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    sql: str
    checksum: str


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """마이그레이션 파일 목록 (번호 순). .sql이 아닌 파일은 무시하고, 이름 규칙을 어기거나 번호가 겹치면 멈춘다."""
    found: dict[str, Migration] = {}
    for path in sorted(directory.glob('*.sql')):
        m = FILENAME.match(path.name)
        if not m:
            raise MigrationError(f'파일 이름은 NNN_소문자_이름.sql 이어야 함: {path.name}')
        version = m.group(1)
        if version in found:
            raise MigrationError(f'번호 중복: {found[version].filename}, {path.name}')
        data = path.read_bytes()
        found[version] = Migration(version, path.name, data.decode('utf-8'), hashlib.sha256(data).hexdigest())
    return [found[v] for v in sorted(found)]


def plan(migrations: list[Migration], applied: dict[str, str]) -> list[Migration]:
    """적용할 파일. applied는 이미 적용한 {version: checksum}.
    적용한 파일의 checksum이 다르거나, 적용 기록은 있는데 파일이 없으면 멈춘다 (DB와 파일이 갈라진 상태)."""
    by_version = {m.version: m for m in migrations}
    for version, checksum in applied.items():
        if version not in by_version:
            raise MigrationError(f'적용 기록은 있는데 파일이 없음: {version}')
        if by_version[version].checksum != checksum:
            raise MigrationError(f'이미 적용한 파일이 바뀜: {by_version[version].filename} '
                                 '(적용한 파일은 고치지 않고 새 번호로 추가)')
    return [m for m in migrations if m.version not in applied]


async def _applied(conn: psycopg.AsyncConnection) -> dict[str, str]:
    cur = await conn.execute('SELECT version, checksum FROM schema_migration')
    return {v: c for v, c in await cur.fetchall()}


async def migrate(url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """적용하고, 이번에 적용한 파일 이름 목록을 돌려준다."""
    migrations = discover(directory)
    done: list[str] = []
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        await conn.execute('SELECT pg_advisory_lock(%s)', (LOCK_KEY,))
        try:
            await conn.execute(CREATE_HISTORY)
            for m in plan(migrations, await _applied(conn)):
                async with conn.transaction():
                    await conn.execute(m.sql.encode('utf-8'))      # 매개변수 없는 여러 문장
                    await conn.execute(
                        'INSERT INTO schema_migration (version, filename, checksum) VALUES (%s, %s, %s)',
                        (m.version, m.filename, m.checksum))
                done.append(m.filename)
        finally:
            await conn.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
    return done


async def status(url: str, directory: Path = MIGRATIONS_DIR) -> list[tuple[str, bool]]:
    """(파일 이름, 적용 여부). schema_migration이 없으면 모두 미적용."""
    migrations = discover(directory)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
        cur = await conn.execute("SELECT to_regclass('schema_migration') IS NOT NULL")
        exists = (await cur.fetchone())[0]
        applied = await _applied(conn) if exists else {}
    return [(m.filename, m.version in applied) for m in migrations]


def main() -> int:
    parser = argparse.ArgumentParser(description='db/migrations/*.sql 적용')
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--database-url', help='접속 주소 (기본: DATABASE_URL)')
    target.add_argument('--test', action='store_true', help='TEST_DATABASE_URL(bootq_test)에 적용')
    parser.add_argument('--status', action='store_true', help='적용하지 않고 상태만 출력')
    args = parser.parse_args()

    load_env()
    url = args.database_url or (testing_database_url() if args.test else database_url())
    try:
        if args.status:
            for filename, applied in asyncio.run(status(url)):
                print(f"{'적용됨' if applied else '미적용'}  {filename}")
            return 0
        done = asyncio.run(migrate(url))
    except MigrationError as e:
        print(f'멈춤: {e}', file=sys.stderr)
        return 1
    print(f"적용 {len(done)}개" + (f": {', '.join(done)}" if done else ' (이미 최신)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
