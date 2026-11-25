"""평가 입력 파일 읽기: 정답 셋, 슬롯필링 시험 결과, 다른 방법의 추천 목록. 채점은 core/evaluation.py."""
import csv
import json
from pathlib import Path

from app.core.slot_filling import Slot, SlotResult

ROOT = Path(__file__).resolve().parents[2]
ANSWER_SET = ROOT / 'eval' / 'answer_set.csv'
SLOT_TRIAL = ROOT / 'data' / 'derived' / 'slot_trial.jsonl'


def load_answer_rows(path: Path = ANSWER_SET) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def _slot(d: dict) -> Slot:
    return Slot(d['value'], d['raw_mention'], d['basis'])


def slot_result_from_dict(d: dict) -> SlotResult:
    """scripts/try_slot_filling.py가 쓴 한 줄(asdict(SlotResult) + eval_id·model·metrics) → SlotResult."""
    return SlotResult(
        jobs=tuple(_slot(s) for s in d.get('jobs', ())),
        industries=tuple(_slot(s) for s in d.get('industries', ())),
        desired_help=d.get('desired_help', 'UNKNOWN'), help_mention=d.get('help_mention', ''),
        error_code=d.get('error_code'), log=tuple(d.get('log', ())),
        prompt_version=d.get('prompt_version', ''))


def load_slot_trial(path: Path = SLOT_TRIAL) -> dict[str, tuple[SlotResult, dict]]:
    """eval_id → (슬롯 결과, 호출 기록 metrics). 같은 eval_id가 여러 번 있으면 마지막 줄."""
    return {d['eval_id']: (slot_result_from_dict(d), d.get('metrics') or {}) for d in _read_jsonl(path)}


def load_recs(path: Path) -> dict[str, tuple[str, ...]]:
    """다른 방법(③ LLM 캠프 선택 등)의 추천: 한 줄에 {"eval_id": ..., "camp_ids": [순서대로]}."""
    return {d['eval_id']: tuple(d.get('camp_ids') or ()) for d in _read_jsonl(path)}


def load_recs_metrics(path: Path) -> list[dict]:
    """추천 파일 줄에 호출 기록(metrics)이 있으면 그 목록 (③의 토큰·응답 시간 집계용)."""
    return [d['metrics'] for d in _read_jsonl(path) if isinstance(d.get('metrics'), dict)]
