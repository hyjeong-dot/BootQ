"""
슬롯필링 시험 (#12). 재작성한 평가 질문(eval/answer_set.csv의 title·content·target_job·target_company)만 보낸다.
실제 유저 글(data/raw/)은 읽지 않는다 — 무료 LLM 티어에 원문을 보내지 않기 위해서다 (05_AI.md 안전장치).

결과는 data/derived/slot_trial.jsonl (git 제외)에 한 줄씩, 요약은 표준 출력.
정답 칸(expected_*)은 읽지 않는다. 슬롯 정확도 채점은 평가 스크립트(#11)가 한다.

실행:
    uv run python scripts/try_slot_filling.py                  # 전체 (요청 사이 3초 간격)
    uv run python scripts/try_slot_filling.py --ids E01 E13
"""
import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_env, resolve_model  # noqa: E402
from app.core.slot_filling import SlotInput, company_field_hint, job_field_hint  # noqa: E402
from app.services.slot_filling import fill_slots, make_slot_client  # noqa: E402
from app.sources.prompts import load_prompt  # noqa: E402
from app.sources.vocab import PRIVATE_DIR, load_company_industry, load_job_alias, load_slot_vocab  # noqa: E402

DEFAULT_INPUT = ROOT / 'eval' / 'answer_set.csv'
OUTPUT = ROOT / 'data' / 'derived' / 'slot_trial.jsonl'
INPUT_COLUMNS = ('eval_id', 'title', 'content', 'target_job', 'target_company')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, default=DEFAULT_INPUT)
    parser.add_argument('--ids', nargs='*', help='eval_id 일부만 (예: E01 E13)')
    parser.add_argument('--model')
    parser.add_argument('--interval', type=float, default=3.0, help='요청 사이 대기 초 (Groq 분당 토큰 한도)')
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get('GROQ_API_KEY')
    if not api_key:
        print('GROQ_API_KEY가 없습니다 (.env)', file=sys.stderr)
        return 1
    model = resolve_model('groq', args.model)

    with args.input.open(encoding='utf-8', newline='') as f:
        rows = [{k: r[k] for k in INPUT_COLUMNS} for r in csv.DictReader(f)]
    if args.ids:
        rows = [r for r in rows if r['eval_id'] in set(args.ids)]

    vocab, template = load_slot_vocab(), load_prompt('slot_filling')
    has_private = (PRIVATE_DIR / 'job_alias.csv').exists() and (PRIVATE_DIR / 'company_industry.csv').exists()
    alias = load_job_alias() if has_private else {}
    companies = load_company_industry() if has_private else {}
    client = make_slot_client(api_key, model)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    failures = 0
    with OUTPUT.open('w', encoding='utf-8') as out:
        for n, row in enumerate(rows):
            if n:
                time.sleep(args.interval)
            slot_input = SlotInput(row['title'], row['content'], job_field_hint(row['target_job'], vocab, alias),
                                   company_field_hint(row['target_company'], companies))
            result, metrics = fill_slots(client, slot_input, vocab, template)
            failures += not result.ok
            out.write(json.dumps({'eval_id': row['eval_id'], 'model': model, **asdict(result), 'metrics': metrics},
                                 ensure_ascii=False) + '\n')
            jobs = ', '.join(f'{s.value}({s.basis[0]})' for s in result.jobs) or '-'
            industries = ', '.join(f'{s.value}({s.basis[0]})' for s in result.industries) or '-'
            status = result.error_code or 'ok'
            print(f"{row['eval_id']} {status:<16} 직무={jobs} | 산업={industries} | 도움={result.desired_help} | "
                  f"{metrics['input_tokens']}+{metrics['output_tokens']}tok {metrics['elapsed_seconds']}s"
                  + (f" | 버림 {len(result.log)}" if result.log else ''))
    print(f'{len(rows)}건, 실패 {failures}건 → {OUTPUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
