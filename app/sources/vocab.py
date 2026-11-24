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
