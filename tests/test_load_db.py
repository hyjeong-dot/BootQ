"""DB 적재 (BAT-006): 원본 행 → camp_raw 변환, 어휘 검사, upsert·비활성·재로드. 캠프·어휘는 가짜 값."""
from datetime import date

import psycopg
import pytest

from app.repositories.camps import (ProfileRow, RawCamp, deactivate_missing, find_candidates, upsert_camp_profile,
                                    upsert_camp_raw)
from app.repositories.vocab import VocabRows, load_vocab_rows, replace_vocab
from scripts.load_db import profile_row, raw_camp, unknown_values
from scripts.migrate import migrate

TODAY = date(2026, 11, 26)
ROW = {'source': 'csv', 'source_camp_id': 'a1', '직무코드': 'X-1', '산업': '식품', '캠프명': '가짜 캠프'}


def test_raw_camp_keeps_all_rows_and_hashes_content_only():
    one = raw_camp(('csv', 'a1'), [ROW])
    two = raw_camp(('csv', 'a1'), [ROW, {**ROW, '직무코드': 'X-2'}])     # 같은 캠프가 코드만 다른 두 행
    assert one.name == '가짜 캠프' and one.payload == [{'직무코드': 'X-1', '산업': '식품', '캠프명': '가짜 캠프'}]
    assert len(two.payload) == 2 and two.content_hash != one.content_hash
    assert raw_camp(('csv', 'other-id'), [{**ROW, 'source_camp_id': 'other-id'}]).content_hash == one.content_hash


def test_profile_row_parses_draft_columns():
    p = profile_row({'source_camp_id': 'a1', 'is_camp': 'True', 'job_ids': '마케팅|영업', 'sub_job': '',
                     'industry_ids': 'ANY', 'skills': '', 'camp_type': 'EXPLORE', 'base_job_ids': '마케팅',
                     'base_industry_ids': '식품', 'base_sub_jobs': '', 'base_skills': '',
                     'remove_industry_suggested': 'False', 'evidence': '마케팅|영업', 'status': 'approved',
                     'result_hash': 'r'})
    assert (p.job_ids, p.sub_job, p.industry_ids, p.is_camp, p.evidence) == (
        ('마케팅', '영업'), None, ('ANY',), True, ['마케팅', '영업'])
    assert unknown_values(p, {'마케팅'}, {'식품'}) == ['영업']


VOCAB = VocabRows(jobs=[('마케팅', '마케팅', False), ('자리표시', '마케팅', True)], industries=['ANY', '식품'],
                  categories={'직무': '', '면접': 'APPLICATION'})


def _profile(cid: str, status: str = 'auto_approved', jobs=('마케팅',), base=('마케팅',)) -> ProfileRow:
    return ProfileRow('csv', cid, True, jobs, None, ('식품',), (), None, base, ('식품',), (), (), False, [], status,
                      'v2', 'r')


@pytest.mark.db
@pytest.mark.anyio
async def test_upsert_deactivate_and_candidates(empty_schema):
    url, _ = empty_schema
    await migrate(url)
    async with await psycopg.AsyncConnection.connect(url) as conn:
        await replace_vocab(conn, VOCAB)
        await replace_vocab(conn, VOCAB)                       # 다시 넣어도 같은 결과 (비우고 다시)
        rows = await load_vocab_rows(conn)
        assert rows.jobs == VOCAB.jobs and rows.categories == {'직무': '', '면접': 'APPLICATION'}

        camps = [RawCamp('csv', c, f'가짜 {c}', [{'캠프명': c}], f'h{c}') for c in ('a1', 'a2', 'a3')]
        assert await upsert_camp_raw(conn, camps) == 3
        assert await upsert_camp_raw(conn, camps) == 0         # 내용이 같으면 손대지 않음
        assert await upsert_camp_profile(conn, [_profile('a1'), _profile('a2'),
                                                _profile('a3', 'pending_review', jobs=('영업',))]) == 3
        assert await upsert_camp_profile(conn, [_profile('없는캠프')]) == 0    # camp_raw에 없으면 넣지 않음

        found, sources = await find_candidates(conn, today=TODAY,
                                               job_ids={'마케팅'})
        assert [c.id for c in found] == ['a1', 'a2', 'a3']    # a3는 pending_review라 기준값(마케팅)으로 후보
        assert sources == {'a1': 'csv', 'a2': 'csv', 'a3': 'csv'}

        assert await deactivate_missing(conn, 'csv', ['a1', 'a3']) == 1
        await conn.execute("UPDATE camp_raw SET recruit_end = '2026-11-01' WHERE source_camp_id = 'a3'")
        found, _ = await find_candidates(conn, today=TODAY, job_ids={'마케팅'})
        assert [c.id for c in found] == ['a1']                 # 비활성(a2)·마감(a3) 제외
        assert await upsert_camp_raw(conn, camps) == 1         # 다시 나타난 a2는 활성으로
        await conn.rollback()
