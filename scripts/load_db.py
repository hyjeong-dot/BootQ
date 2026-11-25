"""
DB 적재 (BAT-006, #14). 명세: docs/specs/12_BATCH_SPEC.md BAT-006.

어휘·관계 파일과 정규화 산출물을 서비스가 읽는 DB 테이블로 옮긴다. 파일이 원본이고 DB는 적재본이다.
- 전체를 한 트랜잭션으로 (실패하면 아무것도 바뀌지 않음)
- 어휘 8개 테이블은 비우고 다시 넣고, 캠프는 upsert. 파일에 없는 csv 캠프는 비활성
- data/private/ 입력 필드 사전이 없으면 그 두 테이블은 비우고 경고

실행:
    uv run python scripts/load_db.py            # DATABASE_URL (개발 DB)
    uv run python scripts/load_db.py --test     # TEST_DATABASE_URL
서버가 떠 있으면 적재 후: curl -X POST http://127.0.0.1:8000/api/admin/vocab/reload
"""
import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import database_url, load_env, testing_database_url  # noqa: E402
from app.core.industry import ANY  # noqa: E402
from app.core.normalize_v2 import NORMALIZER_VERSION  # noqa: E402
from app.repositories.camps import (ProfileRow, RawCamp, deactivate_missing, upsert_camp_profile,  # noqa: E402
                                    upsert_camp_raw)
from app.repositories.vocab import VocabRows, replace_vocab  # noqa: E402
from app.sources import camps as camp_files  # noqa: E402
from app.sources import vocab as vocab_files  # noqa: E402

SOURCE_CSV = 'csv'
ID_COLUMNS = ('source', 'source_camp_id')
NAME_COLUMN = '캠프명'


@dataclass
class Report:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def read_vocab(report: Report) -> VocabRows:
    """어휘 파일 → VocabRows. 입력 필드 사전(data/private/)이 없으면 빈 값 + 경고."""
    def private(loader, name):
        try:
            return loader()
        except FileNotFoundError:
            report.warnings.append(f'{name} 없음 (data/private/): 빈 테이블로 적재')
            return {}
    return VocabRows(
        jobs=vocab_files.load_job_rows(), industries=vocab_files.load_industry_list(),
        skills=vocab_files.load_skills(), industry_families=vocab_files.load_industry_family_pairs(),
        job_relations=vocab_files.load_job_relation_rows(),
        job_aliases=private(vocab_files.load_job_alias, 'job_alias.csv'),
        companies=private(vocab_files.load_company_industry, 'company_industry.csv'),
        categories=vocab_files.load_category_camp_type())


def raw_camp(key: tuple[str, str], rows: list[dict[str, str]]) -> RawCamp:
    """원본 행들 → camp_raw 한 행. content_hash는 ID 칸을 뺀 원본 행들(캠프명+원래 코드)의 해시."""
    payload = [{k: v for k, v in r.items() if k not in ID_COLUMNS} for r in rows]
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    return RawCamp(key[0], key[1], rows[0][NAME_COLUMN], payload, digest)


def profile_row(r: dict[str, str]) -> ProfileRow:
    split = camp_files.split_values
    return ProfileRow(
        source=SOURCE_CSV, source_camp_id=r['source_camp_id'], is_camp=r['is_camp'].strip().lower() == 'true',
        job_ids=split(r['job_ids']), sub_job=r['sub_job'] or None, industry_ids=split(r['industry_ids']),
        skills=split(r['skills']), camp_type=r['camp_type'] or None,
        base_job_ids=split(r['base_job_ids']), base_industry_ids=split(r['base_industry_ids']),
        base_sub_jobs=split(r['base_sub_jobs']), base_skills=split(r['base_skills']),
        remove_industry_suggested=r['remove_industry_suggested'].strip().lower() == 'true',
        evidence=list(split(r['evidence'])), status=r['status'],
        normalizer_version=r.get('normalizer_version') or NORMALIZER_VERSION,   # 산출물에 칸이 없으면 지금 버전
        result_hash=r['result_hash'])


def unknown_values(p: ProfileRow, jobs: set[str], industries: set[str]) -> list[str]:
    """어휘에 없는 직무·산업 (배열이라 FK가 없어 여기서 검사)."""
    bad = [j for j in (*p.job_ids, *p.base_job_ids) if j not in jobs]
    bad += [i for i in (*p.industry_ids, *p.base_industry_ids) if i not in industries and i != ANY]
    return bad


async def load(url: str) -> Report:
    report = Report()
    vocab = read_vocab(report)
    raw = {k: raw_camp(k, rows) for k, rows in camp_files.load_raw_camp_rows().items()}
    profiles = [profile_row(r) for r in camp_files.load_profile_rows()]

    jobs, industries = {j for j, _, _ in vocab.jobs}, set(vocab.industries)
    ok_profiles = []
    for p in profiles:
        if (p.source, p.source_camp_id) not in raw:
            report.warnings.append(f'camp_raw에 없는 캠프라 건너뜀: {p.source_camp_id}')
        elif bad := unknown_values(p, jobs, industries):
            report.warnings.append(f'어휘에 없는 값이라 건너뜀: {p.source_camp_id} {sorted(set(bad))}')
        else:
            ok_profiles.append(p)

    async with await psycopg.AsyncConnection.connect(url) as conn, conn.transaction():
        await replace_vocab(conn, vocab)
        report.counts.update({f'vocab.{k}': v for k, v in vocab.counts().items()})
        report.counts['camp_raw 변경'] = await upsert_camp_raw(conn, list(raw.values()))
        report.counts['camp_raw 비활성'] = await deactivate_missing(
            conn, SOURCE_CSV, [cid for src, cid in raw if src == SOURCE_CSV])
        report.counts['camp_profile 적재'] = await upsert_camp_profile(conn, ok_profiles)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='어휘·캠프 파일 → DB (BAT-006)')
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--database-url', help='접속 주소 (기본: DATABASE_URL)')
    target.add_argument('--test', action='store_true', help='TEST_DATABASE_URL에 적재')
    args = parser.parse_args()
    load_env()
    url = args.database_url or (testing_database_url() if args.test else database_url())
    report = asyncio.run(load(url))
    for name, n in report.counts.items():
        print(f'{name}: {n}')
    for w in report.warnings:
        print(f'경고: {w}', file=sys.stderr)
    print(f'완료 (경고 {len(report.warnings)}건)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
