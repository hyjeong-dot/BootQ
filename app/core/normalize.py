"""
캠프 정규화(D단계)의 순수 로직: 출력 스키마, 프롬프트, 응답 검증, 기준선과의 diff.
파일·네트워크는 다루지 않는다 (scripts/normalize_camps.py가 입출력을 맡는다).
"""
import hashlib
import json
from dataclasses import dataclass

NORMALIZER_VERSION = 'v1'
ANY = 'ANY'
CAMP_TYPES = ('EXPLORE', 'EXPERIENCE', 'APPLICATION')
MAX_JOBS = 2
MAX_INDUSTRIES = 3


@dataclass(frozen=True)
class Vocab:
    job_families: dict[str, str]      # 직무 -> 대분류 (LLM이 고를 수 있는 직무만)
    industries: tuple[str, ...]       # ANY 포함
    skills: tuple[str, ...]
    sub_jobs: tuple[str, ...]         # 재사용을 권하는 하위 직무 목록 (닫힌 목록은 아님)

    @property
    def jobs(self) -> tuple[str, ...]:
        return tuple(self.job_families)


@dataclass(frozen=True)
class CampInput:
    id: str
    name: str
    jobs: tuple[str, ...]
    sub_jobs: tuple[str, ...]
    industries: tuple[str, ...]
    skills: tuple[str, ...]
    job_hint: tuple[str, ...] = ()
    override: str = ''


@dataclass(frozen=True)
class Profile:
    is_camp: bool
    job_ids: tuple[str, ...]
    sub_job: str
    industry_ids: tuple[str, ...]
    skills: tuple[str, ...]
    camp_type: str
    change_note: str


# ---------- 스키마와 프롬프트 ----------
def build_schema(vocab: Vocab) -> dict:
    return {
        'type': 'object',
        'properties': {'camps': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'id': {'type': 'string'},
                'is_camp': {'type': 'boolean'},
                'job_ids': {'type': 'array', 'items': {'type': 'string', 'enum': list(vocab.jobs)}},
                'sub_job': {'type': 'string'},
                'industry_ids': {'type': 'array', 'items': {'type': 'string', 'enum': list(vocab.industries)}},
                'skills': {'type': 'array', 'items': {'type': 'string', 'enum': list(vocab.skills)}},
                'camp_type': {'type': 'string', 'enum': list(CAMP_TYPES)},
                'change_note': {'type': 'string'},
            },
            'required': ['id', 'is_camp', 'job_ids', 'sub_job', 'industry_ids', 'skills', 'camp_type', 'change_note'],
            'additionalProperties': False,
        }}},
        'required': ['camps'],
        'additionalProperties': False,
    }


def build_system_prompt(vocab: Vocab) -> str:
    by_family: dict[str, list[str]] = {}
    for job, family in vocab.job_families.items():
        by_family.setdefault(family, []).append(job)
    jobs_text = '\n'.join(f'- {family}: {", ".join(jobs)}' for family, jobs in by_family.items())
    return f"""직무 부트캠프(현직자와 직무를 체험하는 온라인 캠프) 카탈로그를 정규화합니다. 캠프명을 읽고 아래 어휘로만 프로파일을 채우세요.

## 원칙
- 산업은 "그 캠프가 다루는 회사의 업종"입니다. 하는 일의 내용(예: 통신 프로토콜 연구개발)은 산업이 아니라 직무와 하위직무에 담습니다.
- 입력의 '기준'은 기존 코드를 규칙으로 옮긴 값이라 틀릴 수 있습니다. 캠프명이 말하는 내용과 맞으면 유지하고, 다르면 고치세요. 근거는 반드시 캠프명의 구절이어야 하며, 추측은 하지 마세요.
- 기준의 하위직무와 스킬은 틀리지 않았다면 그대로 유지하세요. 빈 값으로 지우지 마세요.
- '검수메모'는 사람이 정한 지시이므로 따르세요. '추가직무후보'는 기존 상세분류에서 나온 힌트입니다.

## 필드
- is_camp: 직무 캠프로 보기 어려우면 false (예: 사내 특강, 취업 컨설팅). false여도 나머지는 기준을 그대로 채웁니다.
- job_ids: 1~{MAX_JOBS}개. 첫째가 주 직무입니다. 둘째는 캠프명이 두 직무를 분명히 다룰 때만. 아래 직무에서만 고릅니다.
{jobs_text}
- industry_ids: 1~{MAX_INDUSTRIES}개. 캠프명에 업종이 드러나면 그 업종, 직무만 다루고 업종 언급이 없는 범용 캠프는 {ANY}. {ANY}는 다른 산업과 함께 쓰지 않습니다. 산업은 직무 이름과 별개로 판단합니다: 직무가 IT여도 캠프명이 금융권 IT라면 산업은 금융이고(IT는 IT 회사일 때만), 캠프명에 업종이 여러 개 나오면 나온 만큼 모두 씁니다(예: 금융 공기업 → 금융, 공기업) 단 'OO업계 출신 멘토', '현직자' 같은 강사 소개에 나오는 업종은 캠프의 산업이 아닙니다. 2차전지·배터리가 나오면 2차전지를 쓰고, 정유·화학까지 다루면 에너지/화학을 함께 씁니다. 선택지: {", ".join(vocab.industries)}
- skills: 캠프명에 기술·도구가 명시된 것만. 선택지: {", ".join(vocab.skills)}. 없으면 빈 배열.
- sub_job: 캠프명에 세부 직무가 드러나면 짧은 명사구 하나, 없으면 빈 문자열. 기존 목록에 있으면 그것을 쓰세요: {", ".join(vocab.sub_jobs)}
- camp_type: EXPLORE=직무를 이해·탐색·적성 확인하는 캠프(이름에 이해하기, 알아보기, 기초, 적성), EXPERIENCE=과제·프로젝트·포트폴리오로 실무 경험을 쌓는 캠프, APPLICATION=자소서·면접·지원 전략 준비 캠프.
- change_note: 기준에서 바꾸거나 추가한 것이 있으면 근거가 된 캠프명 구절을 인용해 한 줄(40자 이내)로. 바꾼 것이 없으면 빈 문자열.

입력은 캠프마다 한 줄이고, 응답은 입력의 id를 그대로 쓴 camps 배열입니다."""


def build_user_prompt(camps: list[CampInput]) -> str:
    lines = []
    for c in camps:
        base = f"직무={','.join(c.jobs)}; 하위직무={','.join(c.sub_jobs) or '-'}; 산업={','.join(c.industries)}; 스킬={','.join(c.skills) or '-'}"
        extra = ''
        if c.job_hint:
            extra += f" | 추가직무후보={','.join(c.job_hint)}"
        if c.override:
            extra += f' | 검수메모={c.override}'
        lines.append(f'[{c.id}] {c.name} | 기준: {base}{extra}')
    return '\n'.join(lines)


def content_hash(camp: CampInput, system_prompt: str) -> str:
    """같은 캠프 내용 + 같은 프롬프트(어휘 포함) + 같은 버전이면 같은 값. 다시 돌릴 필요 판단에 쓴다."""
    payload = json.dumps([camp.name, camp.jobs, camp.sub_jobs, camp.industries, camp.skills, camp.job_hint,
                          camp.override, NORMALIZER_VERSION, system_prompt], ensure_ascii=False)
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]


# ---------- 검증 ----------
def validate_item(item: object, camp: CampInput, vocab: Vocab) -> tuple[Profile | None, list[str]]:
    """LLM이 돌려준 캠프 하나를 검증한다. 오류가 있으면 (None, 오류들). 고칠 수 있는 것은 고치고 경고로 남긴다."""
    errors: list[str] = []
    if not isinstance(item, dict):
        return None, ['항목이 객체가 아님']

    is_camp = item.get('is_camp')
    if not isinstance(is_camp, bool):
        errors.append('is_camp가 bool이 아님')

    jobs = _str_list(item.get('job_ids'))
    if jobs is None or not 1 <= len(jobs) <= MAX_JOBS or len(set(jobs)) != len(jobs) or any(j not in vocab.job_families for j in jobs):
        errors.append(f'job_ids 오류: {item.get("job_ids")!r}')

    industries = _str_list(item.get('industry_ids'))
    warnings: list[str] = []
    if industries is not None and ANY in industries and len(industries) > 1:
        industries = [i for i in industries if i != ANY]
        warnings.append('ANY를 다른 산업과 같이 써서 ANY 제거')
    if industries is None or not 1 <= len(industries) <= MAX_INDUSTRIES or len(set(industries)) != len(industries) \
            or any(i not in vocab.industries for i in industries):
        errors.append(f'industry_ids 오류: {item.get("industry_ids")!r}')

    skills = _str_list(item.get('skills'))
    if skills is None or any(s not in vocab.skills for s in skills):
        errors.append(f'skills 오류: {item.get("skills")!r}')

    camp_type = item.get('camp_type')
    if camp_type not in CAMP_TYPES:
        errors.append(f'camp_type 오류: {camp_type!r}')

    sub_job, note = item.get('sub_job'), item.get('change_note')
    if not isinstance(sub_job, str) or not isinstance(note, str):
        errors.append('sub_job/change_note가 문자열이 아님')

    if errors:
        return None, errors
    note = ' '.join(filter(None, [note.strip(), *[f'[{w}]' for w in warnings]]))
    return Profile(is_camp, tuple(jobs), sub_job.strip(), tuple(industries), tuple(dict.fromkeys(skills)), camp_type, note), []


def _str_list(value: object) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


# ---------- 기준선과의 비교 ----------
def changed_fields(camp: CampInput, profile: Profile) -> list[str]:
    """기준선과 달라진 필드. 비어 있던 sub_job·skills에 값이 채워지는 것은 달라진 것으로 세지 않는다 (추가일 뿐 충돌이 아님)."""
    changed = []
    if set(profile.job_ids) != set(camp.jobs):
        changed.append('job_ids')
    if set(profile.industry_ids) != set(camp.industries):
        changed.append('industry_ids')
    if camp.sub_jobs and profile.sub_job not in camp.sub_jobs:
        changed.append('sub_job')
    if not set(camp.skills) <= set(profile.skills):
        changed.append('skills')
    if not profile.is_camp:
        changed.append('is_camp')
    return changed


def review_status(camp: CampInput, profile: Profile | None) -> str:
    """CLAUDE.md의 status 규칙: 기준선과 일치하면 auto_approved, 다르거나 LLM 응답이 잘못됐으면 pending_review."""
    if profile is None or changed_fields(camp, profile):
        return 'pending_review'
    return 'auto_approved'
