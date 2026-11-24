"""
캠프 정규화 v2의 순수 로직: 스키마, 프롬프트, 응답 검증, 병합 규칙, 수동 보정 적용.
파일·네트워크는 다루지 않는다 (scripts/normalize_camps.py가 입출력을 맡는다).

v1과 달라진 점
- LLM은 기준 값을 다시 쓰지 않고 "추가분"만 낸다 (add_jobs, add_industries). 교체는 형식상 표현할 수 없다
- 기준 값(주 직무·하위직무·산업)은 코드가 지킨다. 프롬프트로는 삭제가 막히지 않았다
- 주 직무 교체는 자리표시 직무(원래 코드가 뭉뚱그려진 칸)에서만 허용한다
- 추가·교체에는 캠프명의 근거 구절(evidence)이 있어야 하고, 코드가 캠프명에 실제로 있는지 확인한다
- 기준 산업을 범용(ANY)으로 바꾸자는 판단은 적용하지 않고 제안(remove_industry_suggested)으로만 받는다
- 적용 순서: 수동 보정 > LLM > 규칙(기준선)
"""
import hashlib
import json
import re
from dataclasses import dataclass, field
from string import Template

NORMALIZER_VERSION = 'v2'
ANY = 'ANY'
CAMP_TYPES = ('EXPLORE', 'EXPERIENCE', 'APPLICATION')
MAX_JOBS = 2
MAX_INDUSTRIES = 3
# 원래 코드가 여러 직무를 한 칸에 뭉뚱그린 자리표시 칸. 이 칸에서 온 캠프만 주 직무 교체를 허용한다
PLACEHOLDER_ORIGINS = frozenset({'IT/SW/IT', '금융/은행/보험/금융', '기획/기획', '디자인/디자인'})


@dataclass(frozen=True)
class Vocab:
    job_families: dict[str, str]      # 직무 -> 대분류
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
    placeholder: bool = False         # 주 직무 교체 허용 여부
    job_hint: tuple[str, ...] = ()
    memo: str = ''                    # 사람이 남긴 미결 메모 (수동 보정으로 확정된 캠프에는 넣지 않는다)


@dataclass(frozen=True)
class Manual:
    """사람이 확정한 값. 빈 값(None, ())은 손대지 않는다."""
    is_camp: bool | None = None
    job_ids: tuple[str, ...] = ()
    industry_ids: tuple[str, ...] = ()
    sub_job: str | None = None
    camp_type: str | None = None
    reason: str = ''


@dataclass(frozen=True)
class Profile:
    is_camp: bool
    job_ids: tuple[str, ...]
    sub_job: str
    industry_ids: tuple[str, ...]
    skills: tuple[str, ...]
    camp_type: str
    status: str                       # auto_approved | pending_review | approved(수동 보정)
    log: tuple[str, ...] = ()         # 버린 교체 시도, 근거 검증 실패, 되살린 기준 값 등
    remove_industry_suggested: bool = False
    evidence: tuple[str, ...] = ()


# ---------- 스키마와 프롬프트 ----------
def build_schema(vocab: Vocab) -> dict:
    jobs = list(vocab.jobs)
    industries = [i for i in vocab.industries if i != ANY]
    return {
        'type': 'object',
        'properties': {'camps': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'n': {'type': 'integer'},
                'evidence': {'type': 'array', 'items': {'type': 'string'}},
                'is_camp': {'type': 'boolean'},
                'main_job': {'type': 'string', 'enum': ['', *jobs]},
                'add_jobs': {'type': 'array', 'items': {'type': 'string', 'enum': jobs}},
                'add_industries': {'type': 'array', 'items': {'type': 'string', 'enum': industries}},
                'remove_industry_suggested': {'type': 'boolean'},
                'sub_job': {'type': 'string'},
                'skills': {'type': 'array', 'items': {'type': 'string', 'enum': list(vocab.skills)}},
                'camp_type': {'type': 'string', 'enum': list(CAMP_TYPES)},
            },
            'required': ['n', 'evidence', 'is_camp', 'main_job', 'add_jobs', 'add_industries', 'remove_industry_suggested',
                         'sub_job', 'skills', 'camp_type'],
            'additionalProperties': False,
        }}},
        'required': ['camps'],
        'additionalProperties': False,
    }


def build_system_prompt(vocab: Vocab, template: str) -> str:
    """프롬프트 본문(template, prompts/normalize_v2.md)에 어휘를 끼워 넣는다.
    본문의 자리표시: ${jobs}(대분류별 직무 목록), ${industries}, ${sub_jobs}, ${skills}. 모르는 자리표시가 있으면 KeyError.
    본문을 바꾸면 content_hash가 바뀌어 다음 실행에서 전체 재정규화 대상이 된다."""
    by_family: dict[str, list[str]] = {}
    for job, family in vocab.job_families.items():
        by_family.setdefault(family, []).append(job)
    jobs_text = '\n'.join(f'  - {family}: {", ".join(jobs)}' for family, jobs in by_family.items())
    industries = [i for i in vocab.industries if i != ANY]
    return Template(template).substitute(jobs=jobs_text, industries=', '.join(industries),
                                         sub_jobs=', '.join(vocab.sub_jobs), skills=', '.join(vocab.skills))


def build_user_prompt(camps: list[CampInput]) -> str:
    lines = []
    for n, c in enumerate(camps, 1):
        base = f"직무={','.join(c.jobs)}; 하위직무={','.join(c.sub_jobs) or '-'}; 산업={','.join(c.industries)}"
        flags = ' | 주직무교체가능' if c.placeholder else ''
        if c.job_hint:
            flags += f" | 추가직무후보={','.join(c.job_hint)}"
        if c.memo:
            flags += f' | 메모={c.memo}'
        lines.append(f'{n}. {c.name} | 기준: {base}{flags}')
    return '\n'.join(lines)


def content_hash(camp: CampInput, system_prompt: str) -> str:
    payload = json.dumps([camp.name, camp.jobs, camp.sub_jobs, camp.industries, camp.skills, camp.placeholder,
                          camp.job_hint, camp.memo, NORMALIZER_VERSION, system_prompt], ensure_ascii=False)
    return hashlib.sha1(payload.encode('utf-8')).hexdigest()[:12]


# ---------- 응답 검증 ----------
def _str_list(value: object) -> list[str] | None:
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return value
    return None


def validate_item(item: object, vocab: Vocab) -> tuple[dict | None, list[str]]:
    """형식 검증. 통과하면 정리된 dict, 아니면 (None, 오류들)."""
    if not isinstance(item, dict):
        return None, ['항목이 객체가 아님']
    errors = []
    lists = {k: _str_list(item.get(k)) for k in ('add_jobs', 'add_industries', 'skills', 'evidence')}
    for k, v in lists.items():
        if v is None:
            errors.append(f'{k}가 문자열 배열이 아님')
    if not isinstance(item.get('is_camp'), bool) or not isinstance(item.get('remove_industry_suggested'), bool):
        errors.append('is_camp/remove_industry_suggested가 bool이 아님')
    main_job, sub_job = item.get('main_job'), item.get('sub_job')
    if not isinstance(main_job, str) or (main_job and main_job not in vocab.job_families):
        errors.append(f'main_job 오류: {main_job!r}')
    if not isinstance(sub_job, str):
        errors.append('sub_job이 문자열이 아님')
    if item.get('camp_type') not in CAMP_TYPES:
        errors.append(f'camp_type 오류: {item.get("camp_type")!r}')
    if errors:
        return None, errors
    bad = [j for j in lists['add_jobs'] if j not in vocab.job_families]
    bad += [i for i in lists['add_industries'] if i not in vocab.industries or i == ANY]
    bad += [s for s in lists['skills'] if s not in vocab.skills]
    if bad:
        return None, [f'어휘에 없는 값: {bad}']
    return {
        'is_camp': item['is_camp'], 'main_job': main_job, 'add_jobs': list(dict.fromkeys(lists['add_jobs'])),
        'add_industries': list(dict.fromkeys(lists['add_industries'])),
        'remove_industry_suggested': item['remove_industry_suggested'], 'sub_job': sub_job.strip(),
        'skills': list(dict.fromkeys(lists['skills'])), 'camp_type': item['camp_type'],
        'evidence': [e.strip() for e in lists['evidence'] if e.strip()],
    }, []


def _squash(text: str) -> str:
    return re.sub(r'\s+', '', text).lower()


def evidence_in_name(evidence: list[str], name: str) -> bool:
    """근거 구절이 모두 캠프명에 실제로 있는지 (공백·대소문자 무시). 캠프명 전체를 통째로 복사한 것은 근거로 치지 않는다."""
    squashed = _squash(name)
    return bool(evidence) and all(_squash(e) in squashed and _squash(e) != squashed for e in evidence)


# ---------- 병합 (수동 > LLM > 규칙) ----------
def merge(camp: CampInput, llm: dict | None, manual: Manual | None = None) -> Profile:
    """기준(camp) 위에 LLM 추가분을 합치고, 마지막에 수동 보정을 덮는다."""
    log: list[str] = []
    jobs, industries = list(camp.jobs), list(camp.industries)
    sub_job = camp.sub_jobs[0] if camp.sub_jobs else ''
    skills = list(camp.skills)
    is_camp, camp_type, remove_suggested, evidence = True, '', False, ()
    pending = llm is None

    if llm is not None:
        is_camp, camp_type, evidence = llm['is_camp'], llm['camp_type'], tuple(llm['evidence'])
        remove_suggested = llm['remove_industry_suggested'] and camp.industries != (ANY,)
        wants = bool(llm['main_job'] and llm['main_job'] != jobs[0]) or bool(llm['add_jobs']) \
            or bool(llm['add_industries']) or bool(llm['sub_job'] and not camp.sub_jobs)
        grounded = evidence_in_name(llm['evidence'], camp.name)
        if wants and not grounded:
            log.append(f'근거 검증 실패로 추가분 버림 (근거={list(llm["evidence"])})')
        if wants and grounded:
            if llm['main_job'] and llm['main_job'] != jobs[0]:
                if camp.placeholder:
                    log.append(f'자리표시 주 직무 교체 {jobs[0]}→{llm["main_job"]}')
                    jobs = [llm['main_job'], *[j for j in jobs[1:] if j != llm['main_job']]]
                else:
                    log.append(f'주 직무 교체 시도 버림 ({jobs[0]}→{llm["main_job"]})')
            for job in llm['add_jobs']:
                if job not in jobs and len(jobs) < MAX_JOBS:
                    jobs.append(job)
                    log.append(f'직무 추가 {job}')
            if industries == [ANY] and llm['add_industries']:
                industries = []
            for industry in llm['add_industries']:
                if industry not in industries and len(industries) < MAX_INDUSTRIES:
                    industries.append(industry)
                    log.append(f'산업 추가 {industry}')
            if llm['sub_job'] and not camp.sub_jobs:
                sub_job = llm['sub_job']
        skills += [s for s in llm['skills'] if s not in skills]
        if remove_suggested:
            log.append('기준 산업 제거 제안 (적용 안 함)')
        if not is_camp:
            log.append('캠프 아님 판정')
        pending = (set(jobs) != set(camp.jobs) or set(industries) != set(camp.industries)
                   or not is_camp or remove_suggested or any('버림' in m for m in log))

    status = 'pending_review' if pending else 'auto_approved'
    if manual is not None:
        if manual.is_camp is not None:
            is_camp = manual.is_camp
        if manual.job_ids:
            jobs = list(manual.job_ids)
        if manual.industry_ids:
            industries = list(manual.industry_ids)
        if manual.sub_job is not None:
            sub_job = manual.sub_job
        if manual.camp_type:
            camp_type = manual.camp_type
        log.append(f'수동 보정 적용: {manual.reason}')
        status = 'approved'
    return Profile(is_camp, tuple(jobs), sub_job, tuple(industries), tuple(skills), camp_type, status,
                   tuple(log), remove_suggested, evidence)


def v1_item_to_v2(v1_item: dict, camp: CampInput) -> dict:
    """v1 응답(기준을 통째로 다시 쓴 형식)을 v2의 '추가분' 형식으로 바꾼다. v1을 재실행 없이 새 병합 규칙에 넣어 보려는 용도.
    기준을 뺀 교체는 추가로 인정하지 않는다. 기준 산업을 ANY로만 바꾼 것은 제거 제안으로 본다. v1에는 근거 칸이 없어
    캠프명 앞부분을 근거로 둔다(v1은 근거 검증을 하지 않는다는 뜻)."""
    jobs = v1_item.get('job_ids') or []
    industries = v1_item.get('industry_ids') or []
    kept_main = bool(jobs) and jobs[0] == camp.jobs[0]
    main_job = jobs[0] if jobs and not kept_main else ''
    add_jobs = [j for j in jobs[1:] if j not in camp.jobs] if kept_main else []
    base_specific = [i for i in camp.industries if i != ANY]
    kept_industries = all(i in industries for i in base_specific)
    add_industries = [i for i in industries if i not in camp.industries and i != ANY] if kept_industries or not base_specific else []
    return {
        'is_camp': v1_item.get('is_camp', True), 'main_job': main_job, 'add_jobs': add_jobs,
        'add_industries': add_industries, 'remove_industry_suggested': bool(base_specific) and industries == [ANY],
        'sub_job': v1_item.get('sub_job', '') or '', 'skills': v1_item.get('skills', []) or [],
        'camp_type': v1_item.get('camp_type', ''), 'evidence': [camp.name[:-1] or camp.name],
        '_v1_industry_replaced': bool(base_specific) and not kept_industries and industries != [ANY],
    }
