"""정규화 산출물 파일 → 매칭용 캠프 목록. 변환 규칙은 core에 있고(②: core.models.camp_for_matching,
①: core.evaluation.camp_for_rule_baseline), 여기서는 파일만 읽는다. 변형 정의: docs/EVAL.md "캠프 프로파일 변형"."""
import csv
from pathlib import Path

from app.core.evaluation import camp_for_rule_baseline
from app.core.models import Camp, camp_for_matching

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / 'data' / 'derived' / 'camp_profile_draft.csv'
MANUAL = ROOT / 'data' / 'private' / 'camp_manual.csv'
SEP = '|'

RULE, LLM = 'rule', 'llm'      # 3갈래 ① 규칙+수동 / ② 규칙+수동+LLM
VARIANTS = (RULE, LLM)


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or '').split(SEP) if v.strip())


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def load_manual_not_camp(path: Path = MANUAL) -> set[str]:
    """수동 보정에서 캠프 아님으로 확정한 ID. 파일이 없으면 빈 집합."""
    if not path.exists():
        return set()
    return {r['source_camp_id'] for r in _read(path) if r.get('is_camp', '').strip().lower() == 'false'}


def load_matching_camps(variant: str, path: Path = PROFILE, manual_path: Path = MANUAL) -> list[Camp]:
    """정규화 산출물(camp_profile_draft.csv) → 변형별 매칭용 캠프. 후보가 아닌 캠프는 뺀다."""
    if variant not in VARIANTS:
        raise ValueError(f'variant는 {VARIANTS} 중 하나: {variant!r}')
    not_camp = load_manual_not_camp(manual_path) if variant == RULE else set()
    camps = []
    for r in _read(path):
        if variant == RULE:
            camp = camp_for_rule_baseline(
                id=r['source_camp_id'], name=r['캠프명'], base_job_ids=_split(r['base_job_ids']),
                base_industry_ids=_split(r['base_industry_ids']), manual_not_camp=r['source_camp_id'] in not_camp)
        else:
            camp = camp_for_matching(
                id=r['source_camp_id'], name=r['캠프명'], status=r['status'],
                is_camp=r['is_camp'].strip().lower() == 'true',
                job_ids=_split(r['job_ids']), industry_ids=_split(r['industry_ids']),
                base_job_ids=_split(r['base_job_ids']), base_industry_ids=_split(r['base_industry_ids']),
                camp_type=r['camp_type'] or None)
        if camp is not None:
            camps.append(camp)
    return camps


def load_camp_names(path: Path = PROFILE) -> dict[str, str]:
    """캠프 ID → 캠프명 (결과 파일·블라인드 풀링용, 캠프 아님 포함)."""
    return {r['source_camp_id']: r['캠프명'] for r in _read(path)}
