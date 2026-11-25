"""API 통합 테스트 (07_TEST.md 통합 ①): 글 등록 → 추천 저장 → SSE 수신, 피드백, 어휘 재로드.
LLM은 가짜 클라이언트. DB는 테스트 DB 안의 빈 스키마에 마이그레이션 + 가짜 어휘·캠프를 넣는다 (서버가 자기 커넥션으로 읽으므로 커밋).
캠프명·직무·산업은 모두 가짜 값이고, 글은 재작성 샘플 수준의 지어낸 문장이다."""
import asyncio
import json

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.llm.base import LLMResult
from app.main import create_app
from app.repositories.camps import ProfileRow, RawCamp, upsert_camp_profile, upsert_camp_raw
from app.repositories.vocab import VocabRows, replace_vocab
from scripts.migrate import migrate

pytestmark = pytest.mark.db

VOCAB = VocabRows(
    jobs=[('마케팅', '마케팅', False), ('브랜드마케팅', '마케팅', False), ('영업', '영업', False),
          ('자리표시직무', '마케팅', True)],
    industries=['ANY', '식품', '화장품', 'IT'],
    industry_families=[('소비재', '식품'), ('소비재', '화장품')],
    job_relations=[('마케팅', '브랜드마케팅', 'CLOSE', 'manual'), ('마케팅', '영업', 'FAMILY', 'auto')],
    job_aliases={'퍼포먼스 마케터': (('마케팅',), ())},
    companies={'가짜식품회사': ('식품',)},
    categories={'직무': 'EXPLORE'})

CAMPS = [  # (id, 이름, 직무, 산업, camp_type, status)
    ('m1', '가짜 식품 마케팅 캠프', ('마케팅',), ('식품',), 'EXPERIENCE', 'auto_approved'),
    ('m2', '가짜 산업무관 마케팅 캠프', ('마케팅',), ('ANY',), 'EXPLORE', 'auto_approved'),
    ('m3', '가짜 화장품 브랜드 캠프', ('브랜드마케팅',), ('화장품',), 'EXPERIENCE', 'approved'),
    ('s1', '가짜 IT 영업 캠프', ('영업',), ('IT',), 'EXPERIENCE', 'auto_approved'),
]


def slot_json(jobs=(('마케팅', '마케팅', 'EXPLICIT'),), industries=(('식품', '식품', 'EXPLICIT'),),
              help_='UNKNOWN', help_mention='') -> str:
    return json.dumps({'jobs': [{'job': j, 'raw_mention': m, 'basis': b} for j, m, b in jobs],
                       'industries': [{'industry': i, 'raw_mention': m, 'basis': b} for i, m, b in industries],
                       'desired_help': help_, 'help_mention': help_mention}, ensure_ascii=False)


class FakeLLM:
    model = 'fake-model'

    def __init__(self, text: str | None = None, error_code: str | None = None):
        self.text, self.error_code, self.calls = text, error_code, 0

    def complete_json(self, system, user, schema, schema_name='result', max_tokens=3000) -> LLMResult:
        self.calls += 1
        self.schema = schema
        return LLMResult(self.text, 120, 30, 0.01, self.error_code)


async def _seed(url: str) -> None:
    await migrate(url)
    async with await psycopg.AsyncConnection.connect(url) as conn, conn.transaction():
        await replace_vocab(conn, VOCAB)
        await upsert_camp_raw(conn, [RawCamp('csv', cid, name, [{'캠프명': name}], f'h-{cid}')
                                     for cid, name, *_ in CAMPS])
        await upsert_camp_profile(conn, [
            ProfileRow('csv', cid, True, jobs, None, inds, (), ctype, jobs, inds, (), (), False, [], status, 'v2', 'r')
            for cid, _, jobs, inds, ctype, status in CAMPS])


@pytest.fixture
def seeded(empty_schema):
    url, _ = empty_schema
    asyncio.run(_seed(url))
    return url


def client_for(url: str, llm: FakeLLM, sse=(0.01, 2.0, 0.5)) -> TestClient:
    return TestClient(create_app(db_url=url, llm=llm, sse=sse))


def read_events(client: TestClient, post_id: str) -> list[tuple[str, dict]]:
    with client.stream('GET', f'/api/posts/{post_id}/recommendations/stream') as r:
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('text/event-stream')
        text = ''.join(r.iter_text())
    events = []
    for block in text.strip().split('\n\n'):
        lines = dict(line.split(': ', 1) for line in block.splitlines() if not line.startswith(':'))
        if lines:
            events.append((lines['event'], json.loads(lines['data'])))
    return events


def post(client: TestClient, **fields) -> dict:
    body = {'title': '식품 회사 마케팅 준비', 'content': '식품 마케팅 직무로 가고 싶어요.', **fields}
    r = client.post('/api/posts', json=body)
    assert r.status_code == 201, r.text
    return r.json()


def db_row(url: str, sql: str, *params):
    with psycopg.connect(url) as conn:
        return conn.execute(sql, params).fetchone()


# ---------- 핵심 흐름 ----------
def test_post_then_stream_returns_cards_and_saves_record(seeded):
    llm = FakeLLM(slot_json())
    with client_for(seeded, llm) as client:
        created = post(client)
        assert created['status'] == 'processing'
        events = read_events(client, created['post_id'])

    assert [e for e, _ in events] == ['recommendation']
    data = events[0][1]
    assert data['recommendation_id'] == created['recommendation_id'] and data['status'] == 'done'
    cards = data['cards']
    # 산업 등급(2단계)이 직무 SAME/CLOSE(3단계)보다 먼저: 일치(m1) > 계열(m3, CLOSE) > ANY(m2, SAME)
    assert [c['camp_id'] for c in cards] == ['m1', 'm3', 'm2']
    assert cards[0]['camp_name'] == '가짜 식품 마케팅 캠프'
    assert "'마케팅'" in cards[0]['reason'] and all(c['review'] is False for c in cards)
    # 표시용 해시태그: 주 직무 → 산업(ANY 제외). 모집기간은 데이터가 없어 null
    assert [c['tags'] for c in cards] == [['마케팅', '식품'], ['브랜드마케팅', '화장품'], ['마케팅']]
    assert all(c['recruit_start'] is None and c['recruit_end'] is None for c in cards)
    assert llm.calls == 1
    assert '자리표시직무' not in llm.schema['properties']['jobs']['items']['properties']['job']['enum']

    status, end_reason, model, tokens, stage_ms, merged = db_row(
        seeded, 'SELECT status, end_reason, model, prompt_tokens, stage_ms, merged FROM recommendation WHERE id = %s',
        created['recommendation_id'])
    assert (status, end_reason, model, tokens) == ('done', None, 'fake-model', 120)
    assert {'gate1', 'field', 'slot_filling', 'merge', 'candidates', 'match', 'reason'} <= set(stage_ms)
    assert [j['value'] for j in merged['jobs']] == ['마케팅']
    relation, grade = db_row(seeded, 'SELECT relation, industry_grade FROM recommendation_item '
                                     'WHERE recommendation_id = %s AND rank = 1', created['recommendation_id'])
    assert (relation, grade) == ('SAME', 'MATCH')


def test_gate1_stops_without_calling_llm(seeded):
    llm = FakeLLM(slot_json())
    with client_for(seeded, llm) as client:
        created = post(client, category_group='랜선 사수')
        (event, data), = read_events(client, created['post_id'])
    assert (event, data['status'], data['cards']) == ('recommendation', 'done', [])
    assert llm.calls == 0
    assert db_row(seeded, 'SELECT end_reason FROM recommendation WHERE id = %s',
                  created['recommendation_id']) == ('off_target_group',)


def test_llm_error_is_failed_with_code_but_post_succeeds(seeded):
    with client_for(seeded, FakeLLM(None, 'rate_limited')) as client:
        created = post(client)
        (_, data), = read_events(client, created['post_id'])
    assert (data['status'], data['cards']) == ('failed', [])
    assert db_row(seeded, 'SELECT status, error_code FROM recommendation WHERE id = %s',
                  created['recommendation_id']) == ('failed', 'rate_limited')


def test_no_signal_and_industry_only(seeded):
    with client_for(seeded, FakeLLM(slot_json(jobs=(), industries=()))) as client:
        created = post(client)
        (_, data), = read_events(client, created['post_id'])
    assert data['cards'] == []
    assert db_row(seeded, 'SELECT end_reason FROM recommendation WHERE id = %s',
                  created['recommendation_id']) == ('no_signal',)

    with client_for(seeded, FakeLLM(slot_json(jobs=()))) as client:     # 직무 없이 산업(식품)만
        created = post(client)
        (_, data), = read_events(client, created['post_id'])
    assert [c['camp_id'] for c in data['cards']] == ['m1', 'm3']         # 일치 > 계열, ANY 제외
    assert all(c['review'] for c in data['cards'])


def test_input_field_dictionary_is_used(seeded):
    """희망 직무 별칭 → 대표 직무, 목표 회사 → 산업 (본문에 직무·산업이 없어도 필드로 매칭)."""
    with client_for(seeded, FakeLLM(slot_json(jobs=(), industries=()))) as client:
        created = post(client, target_job='퍼포먼스 마케터', target_company='가짜식품회사')
        (_, data), = read_events(client, created['post_id'])
    assert data['cards'][0]['camp_id'] == 'm1'
    assert "희망 직무 '퍼포먼스 마케터'" in data['cards'][0]['reason']


def test_stream_waits_while_processing_then_times_out(seeded):
    """처리 중인 추천은 폴링하다가 timeout 이벤트. (백그라운드 없이 processing 행만 만든다)"""
    with client_for(seeded, FakeLLM(slot_json()), sse=(0.01, 0.1, 0.03)) as client:
        with psycopg.connect(seeded) as conn:
            post_id = conn.execute("INSERT INTO post (title, content) VALUES ('t', 'c') RETURNING id").fetchone()[0]
            rec_id = conn.execute('INSERT INTO recommendation (post_id) VALUES (%s) RETURNING id',
                                  (post_id,)).fetchone()[0]
        with client.stream('GET', f'/api/posts/{post_id}/recommendations/stream') as r:
            text = ''.join(r.iter_text())
    assert ': ping' in text
    assert text.strip().endswith(json.dumps({'recommendation_id': str(rec_id)}))
    assert 'event: timeout' in text


# ---------- 피드백 ----------
def test_feedback_rules(seeded):
    with client_for(seeded, FakeLLM(slot_json())) as client:
        created = post(client)
        rec_id = created['recommendation_id']
        read_events(client, created['post_id'])
        url = f'/api/recommendations/{rec_id}/feedback'

        r = client.post(url, json={'rank': 1, 'camp_id': 'm1', 'vote': 'down', 'reason': 'industry_mismatch'})
        assert r.status_code == 201 and r.json()['feedback_id']
        assert client.post(url, json={'rank': 1, 'camp_id': 'm1', 'vote': 'up'}).status_code == 201   # 덧붙이기

        cases = [
            ({'rank': 1, 'camp_id': 'm2', 'vote': 'up'}, 400),                       # 그 순위 카드가 아님
            ({'rank': 1, 'camp_id': 'm1', 'vote': 'up', 'reason': 'other'}, 400),    # 👍에 사유
            ({'rank': 1, 'camp_id': 'm1', 'vote': 'down', 'reason': '별로'}, 400),    # 코드가 아님
            ({'rank': 4, 'camp_id': 'm1', 'vote': 'up'}, 400),
        ]
        for body, status in cases:
            r = client.post(url, json=body)
            assert r.status_code == status, body
            assert r.json()['error']['code'] == 'validation_error'

        missing = client.post('/api/recommendations/00000000-0000-0000-0000-000000000000/feedback',
                              json={'rank': 1, 'camp_id': 'm1', 'vote': 'up'})
        assert (missing.status_code, missing.json()['error']['code']) == (404, 'not_found')
    assert db_row(seeded, 'SELECT count(*) FROM feedback WHERE recommendation_id = %s', rec_id) == (2,)


# ---------- 검증·에러 형식, 어휘 재로드 ----------
def test_validation_and_not_found_use_error_format(seeded):
    with client_for(seeded, FakeLLM(slot_json())) as client:
        r = client.post('/api/posts', json={'title': 'x' * 201, 'content': ''})
        assert (r.status_code, r.json()['error']['code']) == (400, 'validation_error')
        assert 'title' in r.json()['error']['message']
        r = client.get('/api/posts/00000000-0000-0000-0000-000000000000/recommendations/stream')
        assert (r.status_code, r.json()['error']['code']) == (404, 'not_found')
        r = client.get('/api/posts/not-a-uuid/recommendations/stream')
        assert (r.status_code, r.json()['error']['code']) == (400, 'validation_error')


def test_vocab_reload_and_empty_vocab(empty_schema):
    url, _ = empty_schema
    asyncio.run(migrate(url))                       # 어휘 적재 전
    with client_for(url, FakeLLM(slot_json())) as client:
        created = post(client)
        (_, data), = read_events(client, created['post_id'])
        assert data['status'] == 'failed'
        assert db_row(url, 'SELECT error_code FROM recommendation WHERE id = %s',
                      created['recommendation_id']) == ('vocab_empty',)

        asyncio.run(_seed(url))                     # 서버를 띄운 채 적재 → 재로드
        r = client.post('/api/admin/vocab/reload')
        assert r.status_code == 200
        assert r.json()['jobs'] == len(VOCAB.jobs) and r.json()['job_relations'] == 2
        created = post(client)
        (_, data), = read_events(client, created['post_id'])
        assert data['status'] == 'done' and data['cards']
