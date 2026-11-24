"""
시험 비교: 같은 캠프에 대한 v1(gpt-oss-120b) 결과와 v2 모델별 결과를 병합 규칙을 거친 최종 프로파일로 나란히 보여준다.
v1은 v1_item_to_v2로 바꿔 같은 병합 규칙에 넣는다 (규칙 차이가 아니라 모델·프롬프트 차이만 보이게).

실행: python scripts/compare_pilot.py --ids id1,id2,... --models qwen/qwen3.8-27b,openai/gpt-oss-20b
출력: data/derived/pilot_compare.csv (git 제외)
"""
import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.normalize_camps import (DERIVED, LLM_JSONL, load_camps, load_manual,  # noqa: E402
                                     load_system_prompt, load_vocab, read_jsonl)
from app.core.normalize_v2 import content_hash, merge, v1_item_to_v2, validate_item  # noqa: E402

OUT = DERIVED / 'pilot_compare.csv'


def summarize(profile):
    return {'직무': '|'.join(profile.job_ids), '산업': '|'.join(profile.industry_ids), '하위': profile.sub_job,
            '스킬': '|'.join(profile.skills), '유형': profile.camp_type,
            '제거제안': 'Y' if profile.remove_industry_suggested else '', '기록': ' ; '.join(profile.log)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--ids', required=True)
    parser.add_argument('--models', required=True)
    args = parser.parse_args()
    ids, models = args.ids.split(','), args.models.split(',')

    vocab = load_vocab()
    manual = load_manual()
    camps, _ = load_camps(manual)
    by_id = {c.id: c for c in camps}
    system = load_system_prompt(vocab)
    records = read_jsonl(LLM_JSONL)
    v1_latest, v2_latest = {}, {}
    for r in records:
        if r.get('normalizer_version', 'v1') == 'v1':
            v1_latest[r['source_camp_id']] = r
        elif by_id.get(r['source_camp_id']) and r['content_hash'] == content_hash(by_id[r['source_camp_id']], system):
            v2_latest[(r['source_camp_id'], r['model'])] = r

    rows = []
    for cid in ids:
        camp = by_id[cid]
        base = {'캠프명': camp.name, '자리표시': 'Y' if camp.placeholder else '',
                '기준': f"{'|'.join(camp.jobs)} / {'|'.join(camp.industries)} / {'|'.join(camp.sub_jobs) or '-'}"}
        variants = []
        if cid in v1_latest:
            converted = {k: v for k, v in v1_item_to_v2(v1_latest[cid]['item'], camp).items() if not k.startswith('_')}
            variants.append(('v1 gpt-oss-120b', merge(camp, converted), None))
        for model in models:
            record = v2_latest.get((cid, model))
            if record is None:
                variants.append((f'v2 {model}', None, '결과 없음'))
                continue
            llm, errors = validate_item(record['item'], vocab)
            variants.append((f'v2 {model}', merge(camp, llm), '; '.join(errors)))
        for name, profile, note in variants:
            rows.append({**base, '버전': name, **(summarize(profile) if profile else {}), '근거': ' / '.join(profile.evidence) if profile else '',
                         '오류': note or ''})
    with OUT.open('w', encoding='utf-8', newline='') as f:
        fields = ['캠프명', '자리표시', '기준', '버전', '직무', '산업', '하위', '스킬', '유형', '제거제안', '근거', '기록', '오류']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f'{len(ids)}개 캠프 × {1 + len(models)}개 버전 → {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
