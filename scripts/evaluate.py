"""
평가 (BAT-005, #11). DB·LLM 없이 저장된 슬롯과 고정 캠프 데이터로 core.matching을 직접 호출해
질문별 추천과 지표를 다시 계산한다. 설계·지표 정의: docs/EVAL.md "평가 스크립트", 명세: docs/specs/12_BATCH_SPEC.md BAT-005.

결과 (git 제외. 캠프명이 들어감): data/derived/eval/<실행 이름>/recommendations.csv, slots.csv, summary.json
블라인드 풀링 대상: data/derived/eval/blind_pool.csv (실행 정보 없이 합쳐서 다시 씀)

실행:
    uv run python scripts/evaluate.py --variant llm                      # 슬롯필링 시험 결과로
    uv run python scripts/evaluate.py --variant rule --slots gold        # 정답 슬롯으로 (매칭만의 성능)
    uv run python scripts/evaluate.py --add-family 전자·반도체=반도체,전자/기계 --name e13_family
    uv run python scripts/evaluate.py --recs data/derived/llm_select.jsonl   # 다른 방법의 추천 목록 채점
"""
import argparse
import csv
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.evaluation import (ALLOWED, DISALLOWED, AnswerKey, QuestionRun, check_answer_key,  # noqa: E402
                                 edit_family_pairs, match_question, parse_answer_row, score_match, score_slots,
                                 slots_from_gold, slots_from_trial, summarize, blind_pool, SLOT_MISSING)
from app.core.industry import build_family_index  # noqa: E402
from app.core.matching import build_relation_index  # noqa: E402
from app.core.models import PostInput  # noqa: E402
from app.core.slot_filling import company_field_hint, job_field_hint  # noqa: E402
from app.sources.camps import LLM, PROFILE, VARIANTS, load_camp_names, load_matching_camps  # noqa: E402
from app.sources.evaluation import ANSWER_SET, SLOT_TRIAL, load_answer_rows, load_recs, load_slot_trial  # noqa: E402
from app.sources.vocab import (PRIVATE_DIR, load_category_camp_type, load_company_industry,  # noqa: E402
                               load_industry_family_pairs, load_job_alias, load_job_relations, load_slot_vocab)

OUT_DIR = ROOT / 'data' / 'derived' / 'eval'
GOLD = 'gold'
VERDICT_KO = {ALLOWED: '허용', DISALLOWED: '불허'}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def parse_add_family(values: list[str]) -> list[tuple[str, list[str]]]:
    result = []
    for v in values:
        family, sep, industries = v.partition('=')
        inds = [i.strip() for i in industries.split(',') if i.strip()]
        if not sep or not family.strip() or len(inds) < 2:
            raise SystemExit(f'--add-family 형식: 계열=산업,산업 (산업 2개 이상): {v!r}')
        result.append((family.strip(), inds))
    return result


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['eval_id'])
        w.writeheader()
        w.writerows(rows)


def recommendation_rows(key: AnswerKey, run: QuestionRun | None, camp_ids: tuple[str, ...], score,
                        names: dict[str, str]) -> list[dict]:
    if not camp_ids:
        stop = run.stop_reason if run else 'no_recs'
        return [{'eval_id': key.eval_id, 'rank': '', 'source_camp_id': '', '캠프명': '', 'verdict': '',
                 'ideal': '', 'user_job': '', 'camp_job': '', 'relation': '', 'industry_grade': '',
                 'help_grade': '', 'review': '', 'guaranteed': '', 'stop_reason': stop}]
    recs = {r.camp.id: r for r in run.result.recommendations} if run and run.result else {}
    rows = []
    for rank, (cid, v) in enumerate(zip(score.camp_ids, score.verdicts), 1):
        r = recs.get(cid)
        rows.append({
            'eval_id': key.eval_id, 'rank': rank, 'source_camp_id': cid, '캠프명': names.get(cid, ''),
            'verdict': VERDICT_KO.get(v, '미판정'), 'ideal': 'Y' if cid in key.ideal else '',
            'user_job': r.job.value if r and r.job else '', 'camp_job': (r.camp_job or '') if r else '',
            'relation': (r.relation or '') if r else '',
            'industry_grade': r.industry_grade.name if r and r.industry_grade is not None else '',
            'help_grade': r.help_grade.name if r and r.help_grade is not None else '',
            'review': 'Y' if r and r.review else '', 'guaranteed': 'Y' if r and r.guaranteed else '',
            'stop_reason': ''})
    return rows


def slot_row(key: AnswerKey, run: QuestionRun, s) -> dict:
    m = run.merged
    return {
        'eval_id': key.eval_id, 'stop_reason': run.stop_reason or '',
        'pred_jobs': '|'.join(f'{c.value}({c.source})' for c in m.jobs) if m else '',
        'expected_jobs': '|'.join(key.expected_jobs), 'optional_jobs': '|'.join(key.optional_jobs),
        'jobs_exact': 'Y' if s.jobs.exact else 'N',
        'pred_industries': '|'.join(f'{c.value}({c.source})' for c in m.industries) if m else '',
        'expected_industries': '|'.join(key.expected_industries),
        'industries_exact': 'Y' if s.industries.exact else 'N',
        'camp_type': (m.camp_type or '') if m else '', 'flags': '|'.join(sorted(m.flags)) if m else ''}


def update_blind_pool(path: Path, pairs: list[tuple[str, str]], names: dict[str, str],
                      titles: dict[str, str]) -> int:
    """기존 풀과 합쳐 eval_id·캠프 ID 순으로 다시 쓴다. 판정 칸이 있으면 보존."""
    existing: dict[tuple[str, str], dict] = {}
    if path.exists():
        with path.open(encoding='utf-8', newline='') as f:
            existing = {(r['eval_id'], r['source_camp_id']): r for r in csv.DictReader(f)}
    for eid, cid in pairs:
        existing.setdefault((eid, cid), {'eval_id': eid, 'title': titles.get(eid, ''), 'source_camp_id': cid,
                                         '캠프명': names.get(cid, ''), 'decision': '', 'memo': ''})
    write_csv(path, [existing[k] for k in sorted(existing)])
    return len(existing)


def averages(metrics: list[dict]) -> dict:
    keys = ('input_tokens', 'output_tokens', 'elapsed_seconds')
    rows = [m for m in metrics if all(isinstance(m.get(k), (int, float)) for k in keys)]
    if not rows:
        return {}
    return {f'avg_{k}': round(sum(m[k] for m in rows) / len(rows), 2) for k in keys} | {'calls': len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant', choices=VARIANTS, default=LLM, help='캠프 프로파일: rule(①) / llm(②)')
    parser.add_argument('--slots', default=str(SLOT_TRIAL), help=f'슬롯필링 시험 결과 jsonl 또는 {GOLD}')
    parser.add_argument('--recs', type=Path, help='다른 방법의 추천 jsonl (주면 매칭 없이 채점만)')
    parser.add_argument('--add-family', action='append', default=[], metavar='계열=산업,산업')
    parser.add_argument('--drop-family', action='append', default=[], metavar='계열')
    parser.add_argument('--answer-set', type=Path, default=ANSWER_SET)
    parser.add_argument('--profile', type=Path, default=PROFILE)
    parser.add_argument('--ids', nargs='*', help='eval_id 일부만')
    parser.add_argument('--name', help='실행 이름 (결과 폴더). 기본: 변형_슬롯_계열')
    parser.add_argument('--out-dir', type=Path, default=OUT_DIR)
    args = parser.parse_args()

    answer_rows = load_answer_rows(args.answer_set)
    if args.ids:
        answer_rows = [r for r in answer_rows if r['eval_id'] in set(args.ids)]
    keys = [parse_answer_row(r) for r in answer_rows]
    names = load_camp_names(args.profile)
    warnings = [w for k in keys for w in check_answer_key(k, names)]

    add_family = parse_add_family(args.add_family)
    family_label = 'base' if not (add_family or args.drop_family) else 'fam' + ''.join(
        [f'+{f}' for f, _ in add_family] + [f'-{f}' for f in args.drop_family])
    gold = args.slots == GOLD
    slots_path = None if gold or args.recs else Path(args.slots)
    if args.recs:
        name = args.name or f'recs_{args.recs.stem}'
    else:
        name = args.name or f"{args.variant}_{GOLD if gold else slots_path.stem}_{family_label}"

    runs: dict[str, QuestionRun] = {}
    camp_lists: dict[str, tuple[str, ...]] = {}
    trial_metrics: list[dict] = []
    if args.recs:
        recs = load_recs(args.recs)
        camp_lists = {k.eval_id: recs.get(k.eval_id, ()) for k in keys}
        warnings += [f'{k.eval_id}: 추천 파일에 없음 (추천 없음으로 셈)' for k in keys if k.eval_id not in recs]
    else:
        camps = load_matching_camps(args.variant, args.profile)
        relations = build_relation_index(load_job_relations())
        families = build_family_index(edit_family_pairs(load_industry_family_pairs(), add_family, args.drop_family))
        cct = load_category_camp_type()
        has_private = (PRIVATE_DIR / 'job_alias.csv').exists() and (PRIVATE_DIR / 'company_industry.csv').exists()
        if not has_private:
            warnings.append('입력 필드 사전(data/private/)이 없어 빈 사전으로 실행')
        alias = load_job_alias() if has_private else {}
        companies = load_company_industry() if has_private else {}
        vocab = load_slot_vocab()
        trial = {} if gold else load_slot_trial(slots_path)
        for key, row in zip(keys, answer_rows):
            post = PostInput(row['title'], row['content'], row.get('category', ''), row.get('category_group', ''))
            if gold:
                merged, stop = slots_from_gold(post, key, cct)
            else:
                slots, metrics = trial.get(key.eval_id, (None, {}))
                trial_metrics.append(metrics)
                merged, stop = slots_from_trial(post, slots, job_field_hint(row.get('target_job', ''), vocab, alias),
                                                company_field_hint(row.get('target_company', ''), companies), cct)
                if stop == SLOT_MISSING:
                    warnings.append(f'{key.eval_id}: 슬롯 파일에 없음 (추천 없음으로 셈)')
            runs[key.eval_id] = match_question(key.eval_id, merged, stop, camps, relations, families)
            camp_lists[key.eval_id] = runs[key.eval_id].camp_ids

    matches = [score_match(k, camp_lists[k.eval_id]) for k in keys]
    slot_scores = [score_slots(k, runs[k.eval_id].merged) for k in keys] if runs and not gold else None
    summary = summarize(matches, slot_scores)

    out = args.out_dir / name
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / 'recommendations.csv', [row for k, m in zip(keys, matches)
                                            for row in recommendation_rows(k, runs.get(k.eval_id), m.camp_ids, m,
                                                                           names)])
    if slot_scores:
        write_csv(out / 'slots.csv', [slot_row(k, runs[k.eval_id], s) for k, s in zip(keys, slot_scores)])
    config = {
        'name': name, 'variant': None if args.recs else args.variant,
        'slots': 'recs' if args.recs else (GOLD if gold else str(slots_path.relative_to(ROOT)
                                                                  if slots_path.is_relative_to(ROOT) else slots_path)),
        'slots_hash': file_hash(slots_path) if slots_path else (file_hash(args.recs) if args.recs else None),
        'add_family': add_family, 'drop_family': args.drop_family,
        'answer_set_hash': file_hash(args.answer_set), 'profile_hash': file_hash(args.profile),
        'ids': args.ids or None}
    (out / 'summary.json').write_text(json.dumps(
        {'config': config, 'summary': asdict(summary), 'slot_calls': averages(trial_metrics),
         'warnings': warnings}, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    titles = {r['eval_id']: r['title'] for r in answer_rows}
    pool_size = update_blind_pool(args.out_dir / 'blind_pool.csv', blind_pool(matches), names, titles)

    for w in warnings:
        print(f'경고: {w}', file=sys.stderr)
    print(f'[{name}] 질문 {summary.questions}개')
    print(f'  Hit@3 {summary.hit_at_3} | Precision@3 {summary.precision_at_3} (미판정 {summary.unjudged}개는 불허로 셈)')
    print(f'  추천 없음 정답 {summary.no_rec_correct} | 추천 필요 질문에 추천 {summary.rec_given}')
    print(f'  ideal 밀림 {len(summary.ideal_pushed)}/{summary.ideal_questions} {list(summary.ideal_pushed)}')
    if summary.jobs:
        for label, axis in (('직무', summary.jobs), ('산업', summary.industries)):
            print(f'  슬롯 {label}: 질문 정확 {axis.exact} | 재현율 {axis.recall} | 정밀도 {axis.precision}')
    print(f'→ {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out} | 블라인드 풀 {pool_size}개')
    return 0


if __name__ == '__main__':
    sys.exit(main())
