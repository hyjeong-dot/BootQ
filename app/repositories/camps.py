"""캠프 읽기(추천 후보)·쓰기(BAT-006)."""
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.core.models import Camp, camp_for_matching

# 활성 + 모집 중 + 직무(또는 산업) 집합과 겹침. 결과 칸과 기준 칸을 둘 다 본다 —
# 어느 칸으로 매칭할지(pending_review면 기준 칸)는 core.models.camp_for_matching이 정한다 (10_API_SPEC.md "후보 조회 SQL")
_CANDIDATES = """
SELECT p.source, p.source_camp_id, r.name, p.status, p.is_camp, p.job_ids, p.industry_ids,
       p.base_job_ids, p.base_industry_ids, p.camp_type
FROM camp_profile p
JOIN camp_raw r USING (source, source_camp_id)
WHERE r.active
  AND (r.recruit_start IS NULL OR r.recruit_start <= %(today)s)
  AND (r.recruit_end IS NULL OR r.recruit_end >= %(today)s)
  AND {overlap}
ORDER BY p.source, p.source_camp_id
"""
_BY_JOB = '(p.job_ids && %(values)s OR p.base_job_ids && %(values)s)'
_BY_INDUSTRY = '(p.industry_ids && %(values)s OR p.base_industry_ids && %(values)s)'


async def find_candidates(conn: AsyncConnection, *, today: date, job_ids: Collection[str] = (),
                          industry_ids: Collection[str] = ()) -> tuple[list[Camp], dict[str, str]]:
    """추천 후보 캠프와 {캠프 ID: 출처}. job_ids가 있으면 직무로, 없으면 industry_ids로 거른다 (산업만 매칭).
    둘 다 비면 빈 목록. SQL이 모집 중을 이미 걸렀으므로 Camp.recruiting은 모두 True."""
    if job_ids:
        overlap, values = _BY_JOB, sorted(job_ids)
    elif industry_ids:
        overlap, values = _BY_INDUSTRY, sorted(industry_ids)
    else:
        return [], {}
    cur = await conn.execute(_CANDIDATES.format(overlap=overlap), {'today': today, 'values': values})
    camps: list[Camp] = []
    sources: dict[str, str] = {}
    for source, cid, name, status, is_camp, jobs, inds, base_jobs, base_inds, camp_type in await cur.fetchall():
        camp = camp_for_matching(id=cid, name=name, status=status, is_camp=is_camp, job_ids=tuple(jobs),
                                 industry_ids=tuple(inds), base_job_ids=tuple(base_jobs),
                                 base_industry_ids=tuple(base_inds), camp_type=camp_type)
        if camp is not None:
            camps.append(camp)
            sources[cid] = source
    return camps, sources


# ---------- BAT-006 ----------
@dataclass(frozen=True)
class RawCamp:
    source: str
    source_camp_id: str
    name: str
    payload: list[dict]            # 원본 행들 (같은 캠프가 직무코드만 다른 여러 행이면 모두)
    content_hash: str


@dataclass(frozen=True)
class ProfileRow:
    source: str
    source_camp_id: str
    is_camp: bool
    job_ids: tuple[str, ...]
    sub_job: str | None
    industry_ids: tuple[str, ...]
    skills: tuple[str, ...]
    camp_type: str | None
    base_job_ids: tuple[str, ...]
    base_industry_ids: tuple[str, ...]
    base_sub_jobs: tuple[str, ...]
    base_skills: tuple[str, ...]
    remove_industry_suggested: bool
    evidence: list
    status: str
    normalizer_version: str
    result_hash: str


async def upsert_camp_raw(conn: AsyncConnection, camps: list[RawCamp]) -> int:
    """(source, source_camp_id)로 upsert. 내용 해시가 같으면 손대지 않는다. 바뀐(새로 넣은 것 포함) 행 수."""
    changed = 0
    for c in camps:
        cur = await conn.execute(
            """INSERT INTO camp_raw (source, source_camp_id, name, payload, content_hash, active)
               VALUES (%s, %s, %s, %s, %s, true)
               ON CONFLICT (source, source_camp_id) DO UPDATE
                 SET name = EXCLUDED.name, payload = EXCLUDED.payload, content_hash = EXCLUDED.content_hash,
                     active = true, updated_at = now()
               WHERE camp_raw.content_hash IS DISTINCT FROM EXCLUDED.content_hash OR NOT camp_raw.active""",
            (c.source, c.source_camp_id, c.name, Jsonb(c.payload), c.content_hash))
        changed += cur.rowcount
    return changed


async def deactivate_missing(conn: AsyncConnection, source: str, keep_ids: Collection[str]) -> int:
    """출처에서 사라진 캠프를 비활성으로 (삭제하지 않음: 추천 기록·피드백이 가리킨다). 비활성으로 바꾼 수."""
    cur = await conn.execute(
        'UPDATE camp_raw SET active = false, updated_at = now() '
        'WHERE source = %s AND active AND NOT (source_camp_id = ANY(%s))', (source, list(keep_ids)))
    return cur.rowcount


async def upsert_camp_profile(conn: AsyncConnection, rows: list[ProfileRow]) -> int:
    """정규화 결과 upsert (항상 덮어씀: 파일이 원본). content_hash는 그 시점 camp_raw의 값. camp_raw에 없는 캠프는 0행."""
    changed = 0
    for r in rows:
        cur = await conn.execute(
            """INSERT INTO camp_profile (source, source_camp_id, is_camp, job_ids, sub_job, industry_ids, skills,
                   camp_type, base_job_ids, base_industry_ids, base_sub_jobs, base_skills, remove_industry_suggested,
                   evidence, status, normalizer_version, content_hash, result_hash)
               SELECT %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, r.content_hash, %s
               FROM camp_raw r WHERE r.source = %s AND r.source_camp_id = %s
               ON CONFLICT (source, source_camp_id) DO UPDATE SET
                   is_camp = EXCLUDED.is_camp, job_ids = EXCLUDED.job_ids, sub_job = EXCLUDED.sub_job,
                   industry_ids = EXCLUDED.industry_ids, skills = EXCLUDED.skills, camp_type = EXCLUDED.camp_type,
                   base_job_ids = EXCLUDED.base_job_ids, base_industry_ids = EXCLUDED.base_industry_ids,
                   base_sub_jobs = EXCLUDED.base_sub_jobs, base_skills = EXCLUDED.base_skills,
                   remove_industry_suggested = EXCLUDED.remove_industry_suggested, evidence = EXCLUDED.evidence,
                   status = EXCLUDED.status, normalizer_version = EXCLUDED.normalizer_version,
                   content_hash = EXCLUDED.content_hash, result_hash = EXCLUDED.result_hash, updated_at = now()""",
            (r.source, r.source_camp_id, r.is_camp, list(r.job_ids), r.sub_job, list(r.industry_ids), list(r.skills),
             r.camp_type, list(r.base_job_ids), list(r.base_industry_ids), list(r.base_sub_jobs), list(r.base_skills),
             r.remove_industry_suggested, Jsonb(r.evidence), r.status, r.normalizer_version, r.result_hash,
             r.source, r.source_camp_id))
        changed += cur.rowcount
    return changed
