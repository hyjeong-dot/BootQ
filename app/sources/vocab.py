"""어휘 파일(data/vocab/*.csv) 읽기. 파일 입출력은 core/가 아니라 여기서 한다."""
import csv
from pathlib import Path

VOCAB_DIR = Path(__file__).resolve().parents[2] / 'data' / 'vocab'
CONFIRMED = '확정'


def load_industry_family_pairs(path: Path | None = None) -> list[tuple[str, str]]:
    """industry_family.csv에서 상태가 '확정'인 (계열, 산업) 쌍."""
    with (path or VOCAB_DIR / 'industry_family.csv').open(encoding='utf-8', newline='') as f:
        return [(r['family'], r['industry']) for r in csv.DictReader(f) if r['status'] == CONFIRMED]


def load_industries(path: Path | None = None) -> set[str]:
    with (path or VOCAB_DIR / 'industries.csv').open(encoding='utf-8', newline='') as f:
        return {r['industry'] for r in csv.DictReader(f)}


def load_job_families(path: Path | None = None, include_temporary: bool = False) -> dict[str, str]:
    """jobs.csv의 직무 -> 대분류. 상태가 '임시'인 직무(재분류 뒤 삭제 예정)는 기본적으로 뺀다."""
    with (path or VOCAB_DIR / 'jobs.csv').open(encoding='utf-8', newline='') as f:
        return {r['job']: r['family'] for r in csv.DictReader(f) if include_temporary or r['status'] != '임시'}


def load_skills(path: Path | None = None) -> list[str]:
    with (path or VOCAB_DIR / 'skills.csv').open(encoding='utf-8', newline='') as f:
        return [r['skill'] for r in csv.DictReader(f)]
