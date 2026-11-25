"""
3갈래 평가 ③ LLM 캠프 선택 (#16, docs/EVAL.md "③ LLM 캠프 선택 실행").
재작성한 평가 질문(eval/answer_set.csv의 title·content·target_job·target_company·category)만 보낸다. 정답 칸은 읽지 않는다.
OpenRouter 유료 모델이라 모델을 반드시 지정한다(--model 또는 .env OPENROUTER_MODEL). 먼저 --ids 하나로 토큰을 확인한다.

결과는 data/derived/camp_select.jsonl (git 제외). 이미 있는 줄은 eval_id 기준으로 덮어쓰고 나머지는 보존한다.
채점: uv run python scripts/evaluate.py --recs data/derived/camp_select.jsonl --name select_llm

실행:
    uv run python scripts/run_camp_select.py --model openai/gpt-oss-120b --ids E01
    uv run python scripts/run_camp_select.py --model openai/gpt-oss-120b
"""
import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_env, resolve_model  # noqa: E402
from app.core.camp_select import SelectInput, build_schema, build_system_prompt, build_user_prompt, failed, \
    parse_response, prompt_keys  # noqa: E402
from app.llm.openrouter import OpenRouterClient  # noqa: E402
from app.sources.camps import load_select_camps  # noqa: E402
from app.sources.evaluation import ANSWER_SET, load_answer_rows  # noqa: E402
from app.sources.prompts import load_prompt  # noqa: E402

OUTPUT = ROOT / 'data' / 'derived' / 'camp_select.jsonl'
MAX_TOKENS = 4000


def read_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding='utf-8') as f:
        return {d['eval_id']: d for d in (json.loads(line) for line in f if line.strip())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', nargs='*', help='eval_id 일부만 (예: E01)')
    parser.add_argument('--model')
    parser.add_argument('--interval', type=float, default=3.0)
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    model = resolve_model('openrouter', args.model)
    if not api_key or not model:
        print('OPENROUTER_API_KEY와 모델(--model 또는 OPENROUTER_MODEL)이 필요합니다', file=sys.stderr)
        return 1

    rows = load_answer_rows(ANSWER_SET)
    if args.ids:
        rows = [r for r in rows if r['eval_id'] in set(args.ids)]
    camps = load_select_camps()
    keys = prompt_keys(camps)
    system = build_system_prompt(camps, load_prompt('camp_select'))
    schema = build_schema()
    client = OpenRouterClient(api_key, model)
    print(f'캠프 {len(camps)}개, 시스템 프롬프트 {len(system)}자, 질문 {len(rows)}개, 모델 {model}')

    results = read_existing(OUTPUT)
    for n, row in enumerate(rows):
        if n:
            time.sleep(args.interval)
        select_input = SelectInput(row['title'], row['content'], row.get('target_job', ''),
                                   row.get('target_company', ''), row.get('category', ''))
        llm = client.complete_json(system, build_user_prompt(select_input), schema, 'camp_select', MAX_TOKENS)
        result = parse_response(llm.text, keys) if llm.ok else failed(llm.error_code or 'empty_response',
                                                                            llm.error_message)
        metrics = {'input_tokens': llm.input_tokens, 'output_tokens': llm.output_tokens,
                   'elapsed_seconds': llm.elapsed_seconds, 'meta': llm.meta}
        results[row['eval_id']] = {'eval_id': row['eval_id'], 'model': model, **asdict(result), 'metrics': metrics}
        dropped = f' | 버림 {len(result.log)}' if result.log and result.ok else ''
        print(f"{row['eval_id']} {result.error_code or 'ok':<20} {len(result.camp_ids)}개 | "
              f"{llm.input_tokens}+{llm.output_tokens}tok {llm.elapsed_seconds}s{dropped}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open('w', encoding='utf-8') as out:
        for eid in sorted(results):
            out.write(json.dumps(results[eid], ensure_ascii=False) + '\n')
    print(f'→ {OUTPUT.relative_to(ROOT)} ({len(results)}건)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
