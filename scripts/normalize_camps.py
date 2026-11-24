"""
정규화 D단계(v2): 기준 프로파일(build_baseline.py)에 캠프명을 읽는 LLM의 '추가분'을 합치고, 사람의 수동 보정을 덮는다.
적용 순서: 수동 보정(data/private/camp_manual.csv) > LLM > 규칙(기준선). 병합 규칙은 app/core/normalize_v2.py.

- 멱등: (캠프 내용 + 프롬프트 + 버전의 해시, 모델)이 이미 있으면 건너뛴다. 모델을 바꾸면 다시 처리한다
- 하루 예산 가드: Groq는 모델별 토큰(무료 하루 200K), OpenRouter는 요청 수(무료 하루 50회)
- 처리 순서: 평가 질문 유형에 걸리는 대분류의 캠프를 먼저 (한도가 모자라도 평가에 덜 중요한 캠프만 남게)

실행 (build_baseline.py를 먼저 실행, .env에 키와 모델):
    python scripts/normalize_camps.py --dry-run                     # 프롬프트와 입력 크기만 확인, 호출 없음
    python scripts/normalize_camps.py --contains 키워드 --model M    # 캠프명에 단어가 든 캠프만 (시험)
    python scripts/normalize_camps.py --batch-size 25               # 남은 캠프 전체
    python scripts/normalize_camps.py --report-only                 # 호출 없이 초안·diff만 다시 만들기
    python scripts/normalize_camps.py --v1-retro                    # v1 결과에 새 병합 규칙을 적용한 집계 (호출 없음)
출력 (모두 git 제외): data/derived/camp_llm.jsonl, llm_calls.jsonl, camp_profile_draft.csv, camp_diff.csv,
                     data/private/industry_removal_review.csv (산업 제거 제안을 모은 검수 목록)
"""
import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import load_env, resolve_model  # noqa: E402
from app.core import normalize as v1  # noqa: E402
from app.core.normalize_v2 import (NORMALIZER_VERSION, PLACEHOLDER_ORIGINS, CampInput, Manual, Vocab,  # noqa: E402
                                   build_schema, build_system_prompt, build_user_prompt, content_hash, merge,
                                   v1_item_to_v2, validate_item)
from app.llm.groq import GroqClient  # noqa: E402
from app.llm.openrouter import OpenRouterClient  # noqa: E402
from app.sources.vocab import load_industries, load_job_families, load_skills  # noqa: E402

DERIVED = ROOT / 'data' / 'derived'
PRIVATE = ROOT / 'data' / 'private'
BASELINE = DERIVED / 'camp_baseline.csv'
DETAIL_MAP = PRIVATE / 'detail_map.csv'
OVERRIDES = PRIVATE / 'camp_overrides.csv'
MANUAL = PRIVATE / 'camp_manual.csv'
REMOVAL_REVIEW = PRIVATE / 'industry_removal_review.csv'
LLM_JSONL = DERIVED / 'camp_llm.jsonl'
CALLS_JSONL = DERIVED / 'llm_calls.jsonl'
DRAFT = DERIVED / 'camp_profile_draft.csv'
DIFF = DERIVED / 'camp_diff.csv'
SEP = '|'
MODEL_ENV_NAMES = {'groq': 'GROQ_MODEL', 'openrouter': 'OPENROUTER_MODEL'}
OPENROUTER_MIN_INTERVAL = 3.5   # 분당 20회 제한
PROVIDERS = {'groq': ('GROQ_API_KEY', GroqClient), 'openrouter': ('OPENROUTER_API_KEY', OpenRouterClient)}
# 평가 질문 유형이 걸리는 대분류. 이 대분류의 캠프를 먼저 처리한다
EVAL_FAMILIES = frozenset({'경영/사무/행정', '영업/고객상담', '생산/제조', '건설/기계/기술', '연구개발', '품질', '금융/은행/보험',
                           'IT/SW', '기획', '유통/물류/무역', '고객서비스', '전문특수직'})


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


def load_manual() -> dict[str, Manual]:
    manual = {}
    for r in read_csv(MANUAL):
        manual[r['source_camp_id']] = Manual(
            is_camp={'true': True, 'false': False}.get(r['is_camp'].strip().lower()),
            job_ids=split(r['job_ids']), industry_ids=split(r['industry_ids']),
            sub_job=r['sub_job'] or None, camp_type=r['camp_type'] or None, reason=r['reason'])
    return manual


def load_camps(manual: dict[str, Manual]) -> tuple[list[CampInput], dict[str, set[str]]]:
    """기준선 → CampInput. 수동 보정으로 확정된 캠프에는 미결 메모를 넣지 않는다."""
    memos = {}
    for r in read_csv(OVERRIDES):
        if r['source_camp_id'] not in manual:
            memos.setdefault(r['source_camp_id'], []).append(r['지시'])
    camps, families = [], {}
    for r in read_csv(BASELINE):
        jobs, sub_jobs, industries = split(r['job_ids']), split(r['sub_jobs']), split(r['industry_ids'])
        placeholder = any(o in PLACEHOLDER_ORIGINS for o in split(r['orig_job']))
        m = manual.get(r['source_camp_id'])
        if m is not None:   # 수동 확정값을 기준으로 보여 주고, 주 직무 교체는 막는다 (LLM에는 빈 칸만 맡긴다)
            jobs, industries = m.job_ids or jobs, m.industry_ids or industries
            sub_jobs = (m.sub_job,) if m.sub_job else sub_jobs
            placeholder = False
        camps.append(CampInput(
            r['source_camp_id'], r['캠프명'], jobs, sub_jobs, industries,
            split(r['skills']), placeholder=placeholder,
            job_hint=split(r['job_hint']), memo=' / '.join(memos.get(r['source_camp_id'], []))))
        families[r['source_camp_id']] = set(split(r['job_families']))
    return camps, families


def calls_today(provider: str, model: str | None = None) -> list[dict]:
    today = date.today().isoformat()
    return [c for c in read_jsonl(CALLS_JSONL) if c['date'] == today and c.get('provider', 'groq') == provider
            and (model is None or c['model'] == model)]


def tokens_used_today(provider: str, model: str | None = None) -> int:
    return sum(c['input_tokens'] + c['output_tokens'] for c in calls_today(provider, model))


def run_batches(camps, system, schema, client, provider, args):
    batches = [camps[i:i + args.batch_size] for i in range(0, len(camps), args.batch_size)]
    failed = 0
    for n, batch in enumerate(batches, 1):
        if provider == 'groq' and tokens_used_today(provider, client.model) >= args.max_tokens_today:
            print(f'오늘 {client.model} 토큰 {tokens_used_today(provider, client.model)}개 사용 — 예산 {args.max_tokens_today}개에 도달해 멈춥니다. '
                  '남은 캠프는 내일 같은 명령으로 이어서 실행하세요.')
            break
        if provider == 'openrouter' and len(calls_today(provider)) >= args.max_requests_today:
            print(f'오늘 {provider} 요청 {len(calls_today(provider))}회 — 예산 {args.max_requests_today}회에 도달해 멈춥니다.')
            break
        batch_id = f'{date.today().isoformat()}-{int(time.time())}'
        result = client.complete_json(system, build_user_prompt(batch), schema, 'camp_profiles', max_tokens=args.max_output)
        append_jsonl(CALLS_JSONL, {'batch_id': batch_id, 'date': date.today().isoformat(), 'provider': provider,
                                   'model': client.model, 'normalizer_version': NORMALIZER_VERSION,
                                   'camp_ids': [c.id for c in batch], 'input_tokens': result.input_tokens,
                                   'output_tokens': result.output_tokens, 'elapsed_seconds': result.elapsed_seconds,
                                   'error_code': result.error_code, 'error_message': result.error_message,
                                   'meta': result.meta})
        if not result.ok:
            print(f'[{n}/{len(batches)}] 실패: {result.error_code} {result.error_message[:150]}')
            if result.error_code in ('rate_limited', 'auth', 'insufficient_credits', 'request_too_large'):
                break
            failed += 1
            continue
        try:
            items = json.loads(result.text)['camps']
        except (json.JSONDecodeError, KeyError, TypeError):
            print(f'[{n}/{len(batches)}] 응답이 JSON 형식이 아님')
            failed += 1
            continue
        saved = 0
        for item in items:
            idx = item.get('n') if isinstance(item, dict) else None
            if not isinstance(idx, int) or not 1 <= idx <= len(batch):
                continue
            camp = batch[idx - 1]
            append_jsonl(LLM_JSONL, {'source_camp_id': camp.id, 'content_hash': content_hash(camp, system),
                                     'normalizer_version': NORMALIZER_VERSION, 'model': client.model,
                                     'batch_id': batch_id, 'item': item})
            saved += 1
        print(f'[{n}/{len(batches)}] 캠프 {len(batch)}개 → 저장 {saved}개 | 토큰 입력 {result.input_tokens} 출력 {result.output_tokens} '
              f'| {result.elapsed_seconds}초 | 남은 분당 토큰 {result.meta.get("x-ratelimit-remaining-tokens", "?")}', flush=True)
        wait = (60 * result.total_tokens / args.tpm if provider == 'groq' else OPENROUTER_MIN_INTERVAL) - result.elapsed_seconds
        if n < len(batches) and wait > 0:
            time.sleep(wait)
    if failed:
        print(f'실패한 묶음 {failed}개는 다음 실행에서 다시 시도됩니다.')


def latest_records(model: str, system: str, camps: list[CampInput]) -> dict[str, dict]:
    hashes = {c.id: content_hash(c, system) for c in camps}
    latest = {}
    for r in read_jsonl(LLM_JSONL):
        if r.get('normalizer_version') == NORMALIZER_VERSION and r['model'] == model and hashes.get(r['source_camp_id']) == r['content_hash']:
            latest[r['source_camp_id']] = r
    return latest


def profile_row(camp: CampInput, profile, errors=()):
    return {'source_camp_id': camp.id, '캠프명': camp.name, 'status': profile.status, 'is_camp': profile.is_camp,
            'job_ids': SEP.join(profile.job_ids), 'sub_job': profile.sub_job, 'industry_ids': SEP.join(profile.industry_ids),
            'skills': SEP.join(profile.skills), 'camp_type': profile.camp_type,
            'remove_industry_suggested': profile.remove_industry_suggested,
            'evidence': ' / '.join(profile.evidence), 'log': ' ; '.join(profile.log), 'errors': '; '.join(errors),
            'base_job_ids': SEP.join(camp.jobs), 'base_sub_jobs': SEP.join(camp.sub_jobs),
            'base_industry_ids': SEP.join(camp.industries), 'base_skills': SEP.join(camp.skills),
            'placeholder': camp.placeholder, 'memo': camp.memo}


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_reports(camps, system, vocab, manual, model):
    latest = latest_records(model, system, camps)
    rows = []
    for camp in camps:
        record = latest.get(camp.id)
        llm, errors = (validate_item(record['item'], vocab) if record else (None, []))
        if record is None and camp.id not in manual:
            continue
        rows.append(profile_row(camp, merge(camp, llm, manual.get(camp.id)), errors))
    write_csv(DRAFT, rows)
    write_csv(DIFF, [r for r in rows if r['status'] == 'pending_review'])
    update_removal_review(rows, f'v2 LLM ({model})')
    return rows


def update_removal_review(rows, source):
    """산업 제거 제안을 검수 목록에 모은다. 이미 있는 캠프는 그대로 두고(사람이 적은 판정 보존) 새 제안만 덧붙인다."""
    existing = read_csv(REMOVAL_REVIEW) if REMOVAL_REVIEW.exists() else []
    known = {r['source_camp_id'] for r in existing}
    added = [{'source_camp_id': r['source_camp_id'], '캠프명': r['캠프명'], 'base_industry_ids': r['base_industry_ids'],
              'orig_industry': '', '출처': source, 'decision': '', '메모': ''}
             for r in rows if r['remove_industry_suggested'] in (True, 'True') and r['source_camp_id'] not in known]
    if added:
        write_csv(REMOVAL_REVIEW, existing + added)
    return len(added)


def v1_retro(camps, vocab, manual):
    """v1 결과(gpt-oss-120b)를 v2 병합 규칙에 넣어 본다. v1 오류 중 재실행 없이 고쳐지는 것을 센다."""
    v1_system = v1.build_system_prompt(v1.Vocab(load_job_families(), vocab.industries, vocab.skills, vocab.sub_jobs))
    by_id = {c.id: c for c in camps}
    latest = {}
    for r in read_jsonl(LLM_JSONL):
        if r.get('normalizer_version', 'v1') == 'v1':
            latest[r['source_camp_id']] = r
    counts = Counter()
    examples = {}
    for cid, record in latest.items():
        camp = by_id.get(cid)
        if camp is None:
            continue
        v1_camp = v1.CampInput(camp.id, camp.name, camp.jobs, camp.sub_jobs, camp.industries, camp.skills)
        old_profile, errors = v1.validate_item(record['item'], v1_camp, v1.Vocab(load_job_families(), vocab.industries, vocab.skills, vocab.sub_jobs))
        if old_profile is None or v1.review_status(v1_camp, old_profile) != 'pending_review':
            continue
        counts['v1 검수 대상'] += 1
        converted = v1_item_to_v2(record['item'], camp)
        replaced_industry = converted.pop('_v1_industry_replaced')
        profile = merge(camp, converted, manual.get(cid))
        kinds = []
        if any('주 직무 교체 시도 버림' in m for m in profile.log):
            kinds.append('주 직무 교체 시도 버림')
        if replaced_industry:
            kinds.append('산업 교체 시도 버림')
        if profile.remove_industry_suggested:
            kinds.append('산업 제거 → 제안으로')
        if profile.status == 'approved':
            kinds.append('수동 보정으로 확정')
        if not kinds:
            kinds.append('추가분으로 인정' if profile.status == 'pending_review' else '변경 없음')
        for k in kinds:
            counts[k] += 1
            examples.setdefault(k, []).append(camp.name[:40])
        if profile.status != 'pending_review':
            counts['검수 불필요로 바뀜'] += 1
    print('\n'.join(f'{k}: {v}' for k, v in counts.items()))
    for k, names in examples.items():
        print(f'\n[{k}] 예: ' + ' | '.join(names[:4]))
    del v1_system


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--report-only', action='store_true')
    parser.add_argument('--v1-retro', action='store_true')
    parser.add_argument('--provider', choices=list(PROVIDERS), default='groq')
    parser.add_argument('--model', default=None, help='모델 (없으면 .env의 GROQ_MODEL/OPENROUTER_MODEL, 그것도 없으면 기본값)')
    parser.add_argument('--contains', action='append', default=[], help='캠프명에 이 단어가 든 캠프만 (여러 번 지정 가능)')
    parser.add_argument('--ids', default='', help='쉼표로 구분한 source_camp_id만 (시험용)')
    parser.add_argument('--batch-size', type=int, default=25)
    parser.add_argument('--max-output', type=int, default=2500)
    parser.add_argument('--max-tokens-today', type=int, default=190_000, help='groq 모델별 하루 토큰 예산 (무료 한도 200K)')
    parser.add_argument('--max-requests-today', type=int, default=45, help='openrouter 하루 요청 예산 (무료 한도 50회)')
    parser.add_argument('--tpm', type=int, default=8_000)
    args = parser.parse_args()

    load_env()
    model = resolve_model(args.provider, args.model)
    vocab = load_vocab()
    manual = load_manual()
    camps, families = load_camps(manual)
    system = build_system_prompt(vocab)
    schema = build_schema(vocab)

    if args.v1_retro:
        v1_retro(camps, vocab, manual)
        return 0

    # 수동 보정은 적은 칸만 고정한다. 캠프 아님이거나 camp_type까지 정한 캠프만 LLM에 보내지 않는다
    skip = {cid for cid, m in manual.items() if m.is_camp is False or m.camp_type}
    targets = [c for c in camps if c.id not in skip]
    if args.contains:
        targets = [c for c in targets if any(word in c.name for word in args.contains)]
    if args.ids:
        wanted = set(args.ids.split(','))
        targets = [c for c in targets if c.id in wanted]
    targets.sort(key=lambda c: (not (families[c.id] & EVAL_FAMILIES), c.name))

    done = {(r['source_camp_id'], r['content_hash'], r['model']) for r in read_jsonl(LLM_JSONL)}
    todo = [c for c in targets if (c.id, content_hash(c, system), model) not in done]
    print(f'대상 {len(targets)}개 중 처리할 캠프 {len(todo)}개 | {args.provider}:{model or "(모델 미지정)"} '
          f'| 오늘 이 모델 {tokens_used_today(args.provider, model)}토큰 / {len(calls_today(args.provider, model))}회 '
          f'| 수동 보정 {len(manual)}개 중 {len(skip)}개 제외')

    if args.dry_run:
        user = build_user_prompt(todo[:args.batch_size])
        print(f'\n시스템 프롬프트 {len(system)}자, 스키마 {len(json.dumps(schema, ensure_ascii=False))}자, '
              f'입력 {min(args.batch_size, len(todo))}개 {len(user)}자')
        print('\n===== 시스템 프롬프트 =====\n' + system + '\n\n===== 사용자 입력 (앞 3줄) =====\n' + '\n'.join(user.splitlines()[:3]))
        return 0

    if not args.report_only and todo:
        key_name, client_class = PROVIDERS[args.provider]
        key = os.environ.get(key_name)
        if not key:
            print(f'.env에 {key_name}가 없습니다', file=sys.stderr)
            return 1
        if not model:
            print(f'{MODEL_ENV_NAMES[args.provider]}를 .env에 설정하거나 --model로 모델을 지정하세요', file=sys.stderr)
            return 1
        run_batches(todo, system, schema, client_class(key, model=model), args.provider, args)

    rows = build_reports(camps, system, vocab, manual, model)
    status = Counter(r['status'] for r in rows)
    print(f'\n초안 {len(rows)}개 캠프 ({model}): ' + ', '.join(f'{k} {v}개' for k, v in status.items()))
    print(f'→ {DRAFT.relative_to(ROOT)}, {DIFF.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
