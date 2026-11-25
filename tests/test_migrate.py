"""마이그레이션 적용 스크립트와 001_init 스키마 제약 (#13).
파일 목록·계획은 DB 없이, 적용·제약은 테스트 DB로 확인한다."""
import uuid

import psycopg
import pytest

from scripts.migrate import MIGRATIONS_DIR, Migration, MigrationError, discover, migrate, plan, status

EXPECTED_TABLES = {
    'schema_migration', 'vocab_job', 'vocab_industry', 'vocab_skill', 'industry_family', 'job_relation',
    'job_alias', 'company_industry', 'category_camp_type', 'camp_raw', 'camp_profile', 'post',
    'recommendation', 'recommendation_item', 'feedback',
}


def _m(version: str, checksum: str = 'c') -> Migration:
    return Migration(version, f'{version}_x.sql', '', checksum)


# ---------- 파일 목록·계획 (DB 없음) ----------
def test_discover_reads_repo_migrations_in_order():
    found = discover(MIGRATIONS_DIR)
    assert found[0].filename == '001_init.sql'
    assert [m.version for m in found] == sorted(m.version for m in found)


def test_discover_ignores_other_files_and_sorts(tmp_path):
    (tmp_path / '002_b.sql').write_text('SELECT 2;', encoding='utf-8')
    (tmp_path / '001_a.sql').write_text('SELECT 1;', encoding='utf-8')
    (tmp_path / 'README.md').write_text('x', encoding='utf-8')
    assert [m.filename for m in discover(tmp_path)] == ['001_a.sql', '002_b.sql']


@pytest.mark.parametrize('name', ['1_init.sql', '001-init.sql', '001_Init.sql'])
def test_discover_rejects_bad_names(tmp_path, name):
    (tmp_path / name).write_text('', encoding='utf-8')
    with pytest.raises(MigrationError):
        discover(tmp_path)


def test_discover_rejects_duplicate_versions(tmp_path):
    (tmp_path / '001_a.sql').write_text('', encoding='utf-8')
    (tmp_path / '001_b.sql').write_text('', encoding='utf-8')
    with pytest.raises(MigrationError, match='번호 중복'):
        discover(tmp_path)


def test_plan_returns_only_unapplied():
    assert [m.version for m in plan([_m('001'), _m('002')], {'001': 'c'})] == ['002']
    assert plan([_m('001')], {'001': 'c'}) == []


def test_plan_stops_when_applied_file_changed():
    with pytest.raises(MigrationError, match='바뀜'):
        plan([_m('001', 'new')], {'001': 'old'})


def test_plan_stops_when_applied_file_missing():
    with pytest.raises(MigrationError, match='파일이 없음'):
        plan([_m('002')], {'001': 'c'})


# ---------- 적용 (테스트 DB 안의 임시 스키마) ----------
async def _tables(url: str, schema: str) -> set[str]:
    async with await psycopg.AsyncConnection.connect(url) as conn:
        cur = await conn.execute('SELECT table_name FROM information_schema.tables WHERE table_schema = %s', (schema,))
        return {r[0] for r in await cur.fetchall()}


@pytest.mark.db
@pytest.mark.anyio
async def test_migrate_creates_schema_and_is_idempotent(empty_schema):
    url, schema = empty_schema
    files = [m.filename for m in discover(MIGRATIONS_DIR)]
    assert await migrate(url) == files
    assert await _tables(url, schema) == EXPECTED_TABLES
    assert await migrate(url) == []                       # 다시 돌려도 아무것도 안 함
    assert await status(url) == [(f, True) for f in files]


@pytest.mark.db
@pytest.mark.anyio
async def test_migrate_applies_new_files_only_and_stops_on_change(empty_schema, tmp_path):
    url, _ = empty_schema
    (tmp_path / '001_a.sql').write_text('CREATE TABLE a (x int);', encoding='utf-8')
    assert await migrate(url, tmp_path) == ['001_a.sql']
    (tmp_path / '002_b.sql').write_text('CREATE TABLE b (x int);', encoding='utf-8')
    assert await migrate(url, tmp_path) == ['002_b.sql']
    (tmp_path / '001_a.sql').write_text('CREATE TABLE a (y int);', encoding='utf-8')
    with pytest.raises(MigrationError, match='바뀜'):
        await migrate(url, tmp_path)


@pytest.mark.db
@pytest.mark.anyio
async def test_failed_file_is_rolled_back_and_not_recorded(empty_schema, tmp_path):
    url, schema = empty_schema
    (tmp_path / '001_ok.sql').write_text('CREATE TABLE ok (x int);', encoding='utf-8')
    (tmp_path / '002_bad.sql').write_text('CREATE TABLE half (x int); SELECT * FROM no_such_table;', encoding='utf-8')
    with pytest.raises(psycopg.errors.UndefinedTable):
        await migrate(url, tmp_path)
    assert await _tables(url, schema) == {'schema_migration', 'ok'}      # half는 롤백됨
    assert await status(url, tmp_path) == [('001_ok.sql', True), ('002_bad.sql', False)]


# ---------- 001_init 제약 (마이그레이션된 bootq_test, 테스트마다 롤백) ----------
async def _camp(db, camp_id: str = 'c1') -> None:
    await db.execute("INSERT INTO camp_raw (source, source_camp_id, name, payload, content_hash) "
                     "VALUES ('test', %s, '가짜 캠프', '{}', 'h')", (camp_id,))


async def _card(db, rank: int = 1, camp_id: str = 'c1') -> uuid.UUID:
    cur = await db.execute("INSERT INTO post (title, content) VALUES ('제목', '본문') RETURNING id")
    post_id = (await cur.fetchone())[0]
    cur = await db.execute("INSERT INTO recommendation (post_id, status, completed_at) VALUES (%s, 'done', now()) "
                           "RETURNING id", (post_id,))
    rec_id = (await cur.fetchone())[0]
    await db.execute("INSERT INTO recommendation_item (recommendation_id, rank, source, source_camp_id, relation, reason) "
                     "VALUES (%s, %s, 'test', %s, 'SAME', '사유')", (rec_id, rank, camp_id))
    return rec_id


@pytest.mark.db
@pytest.mark.anyio
async def test_feedback_must_point_to_shown_card(db):
    await _camp(db, 'c1')
    await _camp(db, 'c2')
    rec_id = await _card(db, 1, 'c1')
    await db.execute("INSERT INTO feedback (recommendation_id, rank, source, source_camp_id, vote) "
                     "VALUES (%s, 1, 'test', 'c1', 'up')", (rec_id,))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        async with db.transaction():      # savepoint: 실패하면 여기까지만 롤백
            await db.execute("INSERT INTO feedback (recommendation_id, rank, source, source_camp_id, vote) "
                             "VALUES (%s, 1, 'test', 'c2', 'down')", (rec_id,))   # 1순위 캠프가 아님
    cur = await db.execute('SELECT count(*) FROM feedback WHERE recommendation_id = %s', (rec_id,))
    assert (await cur.fetchone())[0] == 1


@pytest.mark.db
@pytest.mark.anyio
async def test_feedback_reason_is_code_and_only_for_down_vote(db):
    await _camp(db)
    rec_id = await _card(db)
    sql = ("INSERT INTO feedback (recommendation_id, rank, source, source_camp_id, vote, reason) "
           "VALUES (%s, 1, 'test', 'c1', %s, %s)")
    await db.execute(sql, (rec_id, 'down', 'job_mismatch'))
    await db.execute(sql, (rec_id, 'down', None))
    with pytest.raises(psycopg.errors.CheckViolation):     # 👍에는 사유 없음
        async with db.transaction():
            await db.execute(sql, (rec_id, 'up', 'other'))
    with pytest.raises(psycopg.errors.CheckViolation):     # 정해진 코드만 (002)
        await db.execute(sql, (rec_id, 'down', '직무가 달라요'))


@pytest.mark.db
@pytest.mark.anyio
async def test_same_camp_twice_in_one_recommendation_rejected(db):
    await _camp(db)
    rec_id = await _card(db, 1, 'c1')
    with pytest.raises(psycopg.errors.UniqueViolation):
        await db.execute("INSERT INTO recommendation_item (recommendation_id, rank, source, source_camp_id, reason) "
                         "VALUES (%s, 2, 'test', 'c1', '사유')", (rec_id,))


@pytest.mark.db
@pytest.mark.anyio
async def test_recommendation_status_rules(db):
    cur = await db.execute("INSERT INTO post (title, content) VALUES ('제목', '본문') RETURNING id")
    post_id = (await cur.fetchone())[0]
    with pytest.raises(psycopg.errors.CheckViolation):         # failed인데 오류코드 없음
        async with db.transaction():
            await db.execute("INSERT INTO recommendation (post_id, status, completed_at) VALUES (%s, 'failed', now())",
                             (post_id,))
    with pytest.raises(psycopg.errors.CheckViolation):         # 끝났는데 completed_at 없음
        async with db.transaction():
            await db.execute("INSERT INTO recommendation (post_id, status) VALUES (%s, 'done')", (post_id,))
    await db.execute("INSERT INTO recommendation (post_id) VALUES (%s)", (post_id,))   # 기본값 processing
    with pytest.raises(psycopg.errors.UniqueViolation):        # 글당 1회
        await db.execute("INSERT INTO recommendation (post_id) VALUES (%s)", (post_id,))


@pytest.mark.db
@pytest.mark.anyio
async def test_camp_profile_follows_camp_raw(db):
    await _camp(db)
    await db.execute("INSERT INTO camp_profile (source, source_camp_id, job_ids, industry_ids, status, "
                     "normalizer_version, content_hash, result_hash) "
                     "VALUES ('test', 'c1', '{SW개발}', '{ANY}', 'auto_approved', 'v2', 'h', 'r')")
    cur = await db.execute("SELECT job_ids, industry_ids, evidence FROM camp_profile WHERE source_camp_id = 'c1'")
    assert await cur.fetchone() == (['SW개발'], ['ANY'], [])
    await db.execute("DELETE FROM camp_raw WHERE source_camp_id = 'c1'")
    cur = await db.execute("SELECT count(*) FROM camp_profile")
    assert (await cur.fetchone())[0] == 0
