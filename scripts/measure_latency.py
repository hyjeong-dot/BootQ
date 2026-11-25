"""
응답 시간 측정 (BAT-007, #17). 정답 셋의 재작성 질문을 떠 있는 API에 등록하고, SSE 결과 이벤트까지의
전 구간 시간을 잰다 (데모 페이지와 같은 호출: API-001 → API-002). 명세: docs/specs/12_BATCH_SPEC.md BAT-007.

결과 (git 제외): data/derived/latency/<실행 이름>.jsonl — 질문별 시간·카드 수 (캠프명 없음)

실행:
    docker compose up -d --build
    uv run python scripts/measure_latency.py --name e2e-20261126
    uv run python scripts/measure_latency.py --ids E01 E02 --interval 5     # 일부만
"""
import argparse
import csv
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import database_url, load_env  # noqa: E402

ANSWER_SET = ROOT / 'eval' / 'answer_set.csv'
OUT_DIR = ROOT / 'data' / 'derived' / 'latency'
POST_FIELDS = ('title', 'content', 'category', 'category_group', 'target_job', 'target_company')


def post_json(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def read_first_event(url: str) -> tuple[str, dict]:
    """SSE에서 첫 이벤트(recommendation 또는 timeout)를 읽는다. 주석 줄(: ping)은 건너뛴다."""
    event, data = '', ''
    with urllib.request.urlopen(url, timeout=120) as res:
        for raw in res:
            line = raw.decode('utf-8').rstrip('\n')
            if line.startswith('event:'):
                event = line[6:].strip()
            elif line.startswith('data:'):
                data += line[5:].strip()
            elif line == '' and event:
                return event, json.loads(data)
    raise RuntimeError('이벤트 없이 스트림이 닫힘')


def server_record(conn: psycopg.Connection, rec_id: str) -> dict:
    row = conn.execute('SELECT status, end_reason, error_code, total_ms, stage_ms FROM recommendation WHERE id = %s',
                       (rec_id,)).fetchone()
    if row is None:
        return {}
    status, end_reason, error_code, total_ms, stage_ms = row
    return {'status': status, 'end_reason': end_reason, 'error_code': error_code, 'server_ms': total_ms,
            'slot_ms': (stage_ms or {}).get('slot_filling')}


def measure(base: str, row: dict, conn: psycopg.Connection) -> dict:
    out: dict = {'eval_id': row['eval_id']}
    started = time.perf_counter()
    try:
        created = post_json(f'{base}/api/posts', {k: row.get(k) or '' for k in POST_FIELDS})
        event, data = read_first_event(f"{base}/api/posts/{created['post_id']}/recommendations/stream")
        out['e2e_ms'] = round((time.perf_counter() - started) * 1000)
        out['event'] = event
        out['cards'] = len(data.get('cards', []))
        out.update(server_record(conn, created['recommendation_id']))
    except Exception as e:  # noqa: BLE001 — 측정 대상이라 오류도 기록하고 다음 질문으로
        out['error'] = f'{type(e).__name__}: {e}'
    return out


def describe(values: list[float]) -> str:
    if not values:
        return '-'
    return (f'평균 {statistics.mean(values) / 1000:.2f}초 · 중앙값 {statistics.median(values) / 1000:.2f}초 · '
            f'최대 {max(values) / 1000:.2f}초 (n={len(values)})')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--answer-set', type=Path, default=ANSWER_SET)
    parser.add_argument('--ids', nargs='*', help='eval_id 일부만')
    parser.add_argument('--interval', type=float, default=25.0, help='질문 사이 대기(초). Groq 분당 토큰 한도 회피')
    parser.add_argument('--name', default=time.strftime('e2e-%Y%m%d-%H%M'))
    args = parser.parse_args()

    load_env()
    with args.answer_set.open(encoding='utf-8', newline='') as f:
        rows = [r for r in csv.DictReader(f) if not args.ids or r['eval_id'] in args.ids]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f'{args.name}.jsonl'
    results = []
    with psycopg.connect(database_url(), autocommit=True) as conn, out_path.open('w', encoding='utf-8') as out:
        for i, row in enumerate(rows):
            if i:
                time.sleep(args.interval)
            r = measure(args.base_url.rstrip('/'), row, conn)
            results.append(r)
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
            out.flush()
            print(f"{r['eval_id']}: {r.get('e2e_ms', '-')}ms  카드 {r.get('cards', '-')}  "
                  f"{r.get('status', '')} {r.get('end_reason') or r.get('error_code') or r.get('error') or ''}")

    ok = [r for r in results if 'e2e_ms' in r]
    print(f'\n결과: {out_path}')
    print(f"전 구간 (글 등록 → SSE 결과): {describe([r['e2e_ms'] for r in ok])}")
    print(f"서버 처리 (total_ms): {describe([r['server_ms'] for r in ok if r.get('server_ms') is not None])}")
    print(f"슬롯필링: {describe([r['slot_ms'] for r in ok if r.get('slot_ms') is not None])}")
    print(f"timeout {sum(r.get('event') == 'timeout' for r in ok)}건 · failed {sum(r.get('status') == 'failed' for r in ok)}건 · "
          f"요청 오류 {len(results) - len(ok)}건 · 추천 있음 {sum(r.get('cards', 0) > 0 for r in ok)}건")


if __name__ == '__main__':
    main()
