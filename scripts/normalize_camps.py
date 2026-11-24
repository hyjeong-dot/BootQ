"""
정규화 D단계: 기준 프로파일(build_baseline.py)을 캠프명을 읽는 LLM으로 보강한다.
추가 직무, 캠프명에만 있는 산업, 스킬, 하위 직무, camp_type을 채우고 기준선과 달라진 캠프를 표시한다.

- 멱등: 캠프 내용 + 프롬프트(어휘 포함) + 버전의 해시가 이미 있으면 건너뛴다 (data/derived/camp_llm.jsonl)
- 공급자: groq(기본) 또는 openrouter. 같은 모델(gpt-oss-120b)이라 섞어 써도 결과의 일관성이 유지된다
- 하루 예산 가드: groq는 오늘 쓴 토큰(무료 하루 한도 200K), openrouter는 오늘 보낸 요청 수(무료 하루 50회)
- 분당 한도 간격: groq는 호출마다 사용 토큰/분당 한도만큼, openrouter는 분당 20회에 맞춰 기다린다

실행 (build_baseline.py를 먼저 실행, .env에 GROQ_API_KEY):
    python scripts/normalize_camps.py --dry-run            # 프롬프트와 입력 크기만 확인, 호출 없음
    python scripts/normalize_camps.py --pilot 10           # 대표 10개로 시험
    python scripts/normalize_camps.py --contains 배터리 --contains 2차전지   # 캠프명에 단어가 든 캠프만
    python scripts/normalize_camps.py --batch-size 20      # 남은 캠프 전체 (groq)
    python scripts/normalize_camps.py --provider openrouter --batch-size 20   # groq 한도가 끝났을 때 이어서
    python scripts/normalize_camps.py --report-only        # 호출 없이 초안과 diff만 다시 만들기
출력 (모두 git 제외): data/derived/camp_llm.jsonl, llm_calls.jsonl, camp_profile_draft.csv, camp_diff.csv
"""
import argparse
import csv
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_env, resolve_model  # noqa: E402
from app.core.normalize import (CampInput, NORMALIZER_VERSION, Vocab, build_schema, build_system_prompt,  # noqa: E402
                                build_user_prompt, changed_fields, content_hash, review_status, validate_item)
from app.llm.groq import GroqClient  # noqa: E402
from app.llm.openrouter import OpenRouterClient  # noqa: E402
from app.sources.vocab import load_industries, load_job_families, load_skills  # noqa: E402

DERIVED = ROOT / 'data' / 'derived'
BASELINE = DERIVED / 'camp_baseline.csv'
DETAIL_MAP = ROOT / 'data' / 'private' / 'detail_map.csv'
LLM_JSONL = DERIVED / 'camp_llm.jsonl'
CALLS_JSONL = DERIVED / 'llm_calls.jsonl'
DRAFT = DERIVED / 'camp_profile_draft.csv'
DIFF = DERIVED / 'camp_diff.csv'
SEP = '|'
OPENROUTER_MIN_INTERVAL = 3.5   # 분당 20회 제한
PROVIDERS = {'groq': ('GROQ_API_KEY', GroqClient), 'openrouter': ('OPENROUTER_API_KEY', OpenRouterClient)}


def read_csv(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def read_jsonl(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def append_jsonl(path, record):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')


def split(value):
    return tuple(v for v in value.split(SEP) if v)


def load_vocab() -> Vocab:
    sub_jobs = sorted({r['정규값'] for r in read_csv(DETAIL_MAP) if r['분류'] == 'sub_job'})
    industries = ('ANY', *sorted(load_industries() - {'ANY'}))
    return Vocab(job_families=load_job_families(), industries=industries, skills=tuple(load_skills()),
                 sub_jobs=tuple(sub_jobs))


def load_camps() -> list[CampInput]:
    return [CampInput(r['source_camp_id'], r['캠프명'], split(r['job_ids']), split(r['sub_jobs']),
                      split(r['industry_ids']), split(r['skills']), split(r['job_hint']), r['override'])
            for r in read_csv(BASELINE)]


def pick_pilot(camps: list[CampInput], n: int) -> list[CampInput]:
    """시험용 대표 캠프: 예외 지시가 붙은 캠프의 일부 + 나머지에서 일정 간격으로."""
    with_override = sorted((c for c in camps if c.override), key=lambda c: c.name)
    without = [c for c in camps if not c.override]
    n_override = min(len(with_override), (n + 1) // 2)
    chosen = with_override[::max(1, len(with_override) // n_override)][:n_override]
    step = max(1, len(without) // (n - len(chosen)))
    return chosen + without[::step][:n - len(chosen)]


def calls_today(provider: str) -> list[dict]:
    today = date.today().isoformat()
    return [c for c in read_jsonl(CALLS_JSONL) if c['date'] == today and c.get('provider', 'groq') == provider]


def tokens_used_today(provider: str = 'groq') -> int:
    return sum(c['input_tokens'] + c['output_tokens'] for c in calls_today(provider))


def run_batches(camps, system, schema, client, provider, batch_size, max_tokens_today, max_requests_today, tpm):
    batches = [camps[i:i + batch_size] for i in range(0, len(camps), batch_size)]
    for n, batch in enumerate(batches, 1):
        if provider == 'groq' and tokens_used_today(provider) >= max_tokens_today:
            print(f'오늘 {provider} 토큰 {tokens_used_today(provider)}개 사용 — 예산 {max_tokens_today}개에 도달해 멈춥니다. '
                  '남은 캠프는 다음에 이어서 실행하거나 --provider openrouter로 이어서 처리하세요.')
            return
        if provider == 'openrouter' and len(calls_today(provider)) >= max_requests_today:
            print(f'오늘 {provider} 요청 {len(calls_today(provider))}회 — 예산 {max_requests_today}회에 도달해 멈춥니다.')
            return
        batch_id = f'{date.today().isoformat()}-{int(time.time())}'
        result = client.complete_json(system, build_user_prompt(batch), schema, 'camp_profiles', max_tokens=3000)
        append_jsonl(CALLS_JSONL, {'batch_id': batch_id, 'date': date.today().isoformat(), 'provider': provider, 'model': client.model,
                                   'camp_ids': [c.id for c in batch], 'input_tokens': result.input_tokens,
                                   'output_tokens': result.output_tokens, 'elapsed_seconds': result.elapsed_seconds,
                                   'error_code': result.error_code, 'error_message': result.error_message,
                                   'meta': result.meta})
        if not result.ok:
            print(f'[{n}/{len(batches)}] 실패: {result.error_code} {result.error_message[:120]}')
            return
        try:
            items = json.loads(result.text)['camps']
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f'[{n}/{len(batches)}] 응답이 JSON 형식이 아님')
            return
        by_id = {c.id: c for c in batch}
        saved = 0
        for item in items:
            camp = by_id.get(item.get('id')) if isinstance(item, dict) else None
            if camp is None:
                continue
            append_jsonl(LLM_JSONL, {'source_camp_id': camp.id, 'content_hash': content_hash(camp, system),
                                     'normalizer_version': NORMALIZER_VERSION, 'model': client.model,
                                     'batch_id': batch_id, 'item': item})
            saved += 1
        print(f'[{n}/{len(batches)}] 캠프 {len(batch)}개 → 저장 {saved}개 | 토큰 입력 {result.input_tokens} 출력 {result.output_tokens} '
              f'| {result.elapsed_seconds}초 | 남은 분당 토큰 {result.meta.get("x-ratelimit-remaining-tokens", "?")}')
        wait = (60 * result.total_tokens / tpm if provider == 'groq' else OPENROUTER_MIN_INTERVAL) - result.elapsed_seconds
        if n < len(batches) and wait > 0:
            time.sleep(wait)


def build_reports(camps, system, vocab):
    latest = {}
    for record in read_jsonl(LLM_JSONL):
        latest[record['source_camp_id']] = record
    rows, diffs = [], []
    for camp in camps:
        record = latest.get(camp.id)
        if record is None or record['content_hash'] != content_hash(camp, system):
            continue
        profile, errors = validate_item(record['item'], camp, vocab)
        fields = changed_fields(camp, profile) if profile else []
        status = review_status(camp, profile)
        row = {'source_camp_id': camp.id, '캠프명': camp.name, 'status': status, 'changed_fields': SEP.join(fields),
               'errors': '; '.join(errors), 'is_camp': profile.is_camp if profile else '',
               'job_ids': SEP.join(profile.job_ids) if profile else '', 'sub_job': profile.sub_job if profile else '',
               'industry_ids': SEP.join(profile.industry_ids) if profile else '',
               'skills': SEP.join(profile.skills) if profile else '', 'camp_type': profile.camp_type if profile else '',
               'change_note': (profile.change_note or ('근거 미기재' if fields else '')) if profile else '',
               'base_job_ids': SEP.join(camp.jobs), 'base_sub_jobs': SEP.join(camp.sub_jobs),
               'base_industry_ids': SEP.join(camp.industries), 'base_skills': SEP.join(camp.skills),
               'override': camp.override}
        rows.append(row)
        if status == 'pending_review':
            diffs.append(row)
    for path, data in ((DRAFT, rows), (DIFF, diffs)):
        if data:
            with path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=list(data[0]))
                writer.writeheader()
                writer.writerows(data)
    return rows, diffs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--provider', choices=list(PROVIDERS), default='groq')
    parser.add_argument('--max-requests-today', type=int, default=45, help='openrouter 하루 요청 예산 (무료 한도 50회)')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--pilot', type=int, default=0)
    parser.add_argument('--contains', action='append', default=[], help='캠프명에 이 단어가 든 캠프만 (여러 번 지정 가능)')
    parser.add_argument('--batch-size', type=int, default=10)
    parser.add_argument('--max-tokens-today', type=int, default=180_000)
    parser.add_argument('--tpm', type=int, default=8_000)
    parser.add_argument('--model', default=None, help='모델 (없으면 .env의 GROQ_MODEL/OPENROUTER_MODEL, 그것도 없으면 기본값)')
    parser.add_argument('--redo', action='store_true', help='이미 처리한 캠프도 다시 처리 (모델·프롬프트를 바꿔 비교할 때)')
    args = parser.parse_args()

    load_env()
    model = resolve_model(args.provider, args.model)
    vocab = load_vocab()
    system = build_system_prompt(vocab)
    schema = build_schema(vocab)
    camps = load_camps()
    targets = pick_pilot(camps, args.pilot) if args.pilot else camps
    if args.contains:
        targets = [c for c in camps if any(word in c.name for word in args.contains)]

    records = read_jsonl(LLM_JSONL)
    done = {r['source_camp_id']: r['content_hash'] for r in records}
    todo = [c for c in targets if args.redo or done.get(c.id) != content_hash(c, system)]
    models = {}
    for r in {r['source_camp_id']: r for r in records}.values():
        models[r['model']] = models.get(r['model'], 0) + 1
    others = {m: n for m, n in models.items() if m.split(':')[0] != model.split(':')[0]}   # :free 같은 접미사는 같은 모델
    if others and not args.report_only:
        print(f'알림: 이미 처리된 캠프 중 {sum(others.values())}개는 다른 모델({", ".join(others)})로 처리됐습니다. '
              f'모델을 바꿔 시험하는 중이면 --redo로 다시 처리하세요 (최신 기록이 초안에 쓰입니다).')
    print(f'대상 {len(targets)}개 중 처리할 캠프 {len(todo)}개 (이미 처리 {len(targets) - len(todo)}개) | {args.provider}:{model} | 오늘 사용 {tokens_used_today(args.provider)}토큰 / {len(calls_today(args.provider))}회')

    if args.dry_run:
        user = build_user_prompt(todo[:args.batch_size])
        print(f'\n시스템 프롬프트 {len(system)}자, 스키마 {len(json.dumps(schema, ensure_ascii=False))}자, 입력 {args.batch_size}개 {len(user)}자')
        print('\n===== 시스템 프롬프트 =====\n' + system + '\n\n===== 사용자 입력 (앞 3줄) =====\n' + '\n'.join(user.splitlines()[:3]))
        return 0

    if not args.report_only and todo:
        key_name, client_class = PROVIDERS[args.provider]
        key = os.environ.get(key_name)
        if not key:
            print(f'.env에 {key_name}가 없습니다', file=sys.stderr)
            return 1
        client = client_class(key, model=model)
        run_batches(todo, system, schema, client, args.provider, args.batch_size, args.max_tokens_today,
                    args.max_requests_today, args.tpm)

    rows, diffs = build_reports(camps, system, vocab)
    print(f'\n초안 {len(rows)}개 캠프: auto_approved {len(rows) - len(diffs)}개, pending_review {len(diffs)}개')
    print(f'→ {DRAFT.relative_to(ROOT)}, {DIFF.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
