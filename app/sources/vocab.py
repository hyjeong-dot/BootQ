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


# ---------- 매칭용 어휘 (#8) ----------
PRIVATE_DIR = VOCAB_DIR.parents[0] / 'private'
SEP = '|'


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(SEP) if v.strip())


def load_job_family_policy(path: Path | None = None) -> dict[str, bool]:
    """job_family_policy.csv의 대분류 -> 자동 FAMILY 여부."""
    return {r['family']: r['auto_family'] == 'Y' for r in _read(path or VOCAB_DIR / 'job_family_policy.csv')}


def load_job_relation_manual(path: Path | None = None) -> list[tuple[str, str, str, str]]:
    """job_relation_manual.csv의 (job_a, job_b, relation, reason)."""
    return [(r['job_a'], r['job_b'], r['relation'], r['reason'])
            for r in _read(path or VOCAB_DIR / 'job_relation_manual.csv')]


def load_job_relations(path: Path | None = None) -> list[tuple[str, str, str]]:
    """생성된 job_relation.csv의 (job_a, job_b, relation). 자기 자신(SAME)은 들어 있지 않다."""
    return [(r['job_a'], r['job_b'], r['relation']) for r in _read(path or VOCAB_DIR / 'job_relation.csv')]


def load_category_camp_type(path: Path | None = None) -> dict[str, str]:
    """question_category -> camp_type 기본값. 선호 없음은 빈 문자열."""
    return {r['category']: r['camp_type'] for r in _read(path or VOCAB_DIR / 'category_camp_type.csv')}


def load_job_alias(path: Path | None = None) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """(git 제외) 유저 target_job 표기 -> (대표 직무들, 산업들). 직무가 비어 있으면 '본문으로 판단'."""
    return {r['user_term']: (_split(r['jobs']), _split(r['industry']))
            for r in _read(path or PRIVATE_DIR / 'job_alias.csv')}


def load_company_industry(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    """(git 제외) 유저 target_company 표기 -> 산업들. 제외 행(미지정·회사 아님)은 빈 튜플."""
    return {r['company']: _split(r['industries']) for r in _read(path or PRIVATE_DIR / 'company_industry.csv')}
