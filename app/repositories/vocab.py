"""어휘 테이블 읽기·쓰기. 읽기는 서버 시작·재로드(API-004), 쓰기는 DB 적재(BAT-006)."""
from collections.abc import Sequence
from dataclasses import dataclass, field

from psycopg import AsyncConnection


@dataclass(frozen=True)
class VocabRows:
    """어휘 테이블 내용 그대로. 인덱스(관계·계열)는 services가 core 함수로 만든다."""
    jobs: list[tuple[str, str, bool]] = field(default_factory=list)            # (직무, 대분류, 임시) 파일 순서
    industries: list[str] = field(default_factory=list)                        # 파일 순서, ANY 포함
    skills: list[str] = field(default_factory=list)
    industry_families: list[tuple[str, str]] = field(default_factory=list)     # (계열, 산업)
    job_relations: list[tuple[str, str, str, str]] = field(default_factory=list)   # (a, b, relation, source)
    job_aliases: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = field(default_factory=dict)  # 표기 -> (직무들, 산업들)
    companies: dict[str, tuple[str, ...]] = field(default_factory=dict)        # 회사 -> 산업들
    categories: dict[str, str] = field(default_factory=dict)                   # category -> camp_type ('' = 선호 없음)

    def counts(self) -> dict[str, int]:
        return {'jobs': len(self.jobs), 'industries': len(self.industries),
                'industry_families': len(self.industry_families), 'job_relations': len(self.job_relations),
                'job_aliases': len(self.job_aliases), 'companies': len(self.companies),
                'categories': len(self.categories)}


async def _rows(conn: AsyncConnection, sql: str) -> list[tuple]:
    cur = await conn.execute(sql)
    return await cur.fetchall()


async def load_vocab_rows(conn: AsyncConnection) -> VocabRows:
    return VocabRows(
        jobs=[(j, f, t) for j, f, t in await _rows(
            conn, 'SELECT job_id, family, temporary FROM vocab_job ORDER BY position, job_id')],
        industries=[i for (i,) in await _rows(conn, 'SELECT industry_id FROM vocab_industry ORDER BY position, industry_id')],
        skills=[s for (s,) in await _rows(conn, 'SELECT skill_id FROM vocab_skill ORDER BY skill_id')],
        industry_families=[(f, i) for f, i in await _rows(
            conn, 'SELECT family, industry_id FROM industry_family ORDER BY family, industry_id')],
        job_relations=[tuple(r) for r in await _rows(
            conn, 'SELECT job_a, job_b, relation, source FROM job_relation ORDER BY job_a, job_b')],
        job_aliases={t: (tuple(j), (i,) if i else ()) for t, j, i in await _rows(
            conn, 'SELECT user_term, job_ids, industry_id FROM job_alias ORDER BY user_term')},
        companies={c: tuple(i) for c, i in await _rows(
            conn, 'SELECT company, industry_ids FROM company_industry ORDER BY company')},
        categories={c: t or '' for c, t in await _rows(
            conn, 'SELECT category, camp_type FROM category_camp_type ORDER BY category')},
    )


VOCAB_TABLES = ('job_relation', 'industry_family', 'job_alias', 'company_industry', 'category_camp_type',
                'vocab_skill', 'vocab_job', 'vocab_industry')     # FK 순서 (참조하는 쪽 먼저)


async def replace_vocab(conn: AsyncConnection, v: VocabRows) -> None:
    """어휘 테이블을 비우고 v로 다시 채운다. 트랜잭션은 호출자가 연다 (BAT-006: 전체 한 트랜잭션)."""
    for table in VOCAB_TABLES:
        await conn.execute(f'DELETE FROM {table}')
    async with conn.cursor() as cur:
        await _many(cur, 'INSERT INTO vocab_job (job_id, family, temporary, position) VALUES (%s, %s, %s, %s)',
                    [(j, f, t, i) for i, (j, f, t) in enumerate(v.jobs)])
        await _many(cur, 'INSERT INTO vocab_industry (industry_id, position) VALUES (%s, %s)',
                    [(ind, i) for i, ind in enumerate(v.industries)])
        await _many(cur, 'INSERT INTO vocab_skill (skill_id) VALUES (%s)', [(s,) for s in v.skills])
        await _many(cur, 'INSERT INTO industry_family (family, industry_id) VALUES (%s, %s)', v.industry_families)
        await _many(cur, 'INSERT INTO job_relation (job_a, job_b, relation, source) VALUES (%s, %s, %s, %s)',
                    v.job_relations)
        await _many(cur, 'INSERT INTO job_alias (user_term, job_ids, industry_id) VALUES (%s, %s, %s)',
                    [(t, list(j), i[0] if i else None) for t, (j, i) in v.job_aliases.items()])
        await _many(cur, 'INSERT INTO company_industry (company, industry_ids) VALUES (%s, %s)',
                    [(c, list(i)) for c, i in v.companies.items()])
        await _many(cur, 'INSERT INTO category_camp_type (category, camp_type) VALUES (%s, %s)',
                    [(c, t or None) for c, t in v.categories.items()])


async def _many(cur, sql: str, rows: Sequence[tuple]) -> None:
    if rows:
        await cur.executemany(sql, rows)
