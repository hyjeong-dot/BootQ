"""
슬롯필링의 순수 로직: 입력 필드 힌트, 스키마, 프롬프트 조립, 응답 검증.
LLM 호출·파일 읽기는 하지 않는다 (app/services/slot_filling.py가 호출을 맡는다).

- LLM은 글 제목+본문에 근거한 값만 낸다. 입력 필드(희망 직무·목표 회사) 값은 병합 단계가 직접 넣으므로 LLM에는 힌트로만 준다
- 출력은 어휘 Enum으로 강제(strict JSON schema)하고, 응답 후 코드가 다시 검증한다:
  어휘에 있는 값인지, 원문 발췌(raw_mention)가 제목+본문에 실제로 있는지. 발췌가 없으면 그 값을 버린다 (정밀도 우선)
- 근거 '없음'은 빈 배열로 표현한다. basis(EXPLICIT/INFERRED)는 값마다 둔다: 병합 규칙(본문 명시 > 입력 필드 > 본문 추론)이 값 단위라서
- 응답을 쓸 수 없으면 error_code를 채운다. 호출자는 추천 없음으로 끝낸다 (05_AI.md 실패 시 폴백)
"""
import json
import re
from dataclasses import dataclass
from string import Template

SLOT_PROMPT_VERSION = 'slot-v1'   # prompts/slot_filling.md나 스키마를 바꾸면 올린다. recommendation에 저장
ANY = 'ANY'
DESIRED_HELP = ('EXPLORE', 'EXPERIENCE', 'APPLICATION', 'UNKNOWN')
BASIS = ('EXPLICIT', 'INFERRED')
MAX_JOBS = 3
MAX_INDUSTRIES = 3
ALL_JOBS, ALL_COMPANIES = '모든 직무', '모든 회사'

# 응답을 쓸 수 없을 때의 오류코드 (LLM 공급자 오류코드는 LLMResult.error_code를 그대로 쓴다)
PARSE_ERROR = 'slot_parse_error'      # JSON이 아님
SCHEMA_ERROR = 'slot_schema_error'    # 형식이 스키마와 다름 (strict 모드라도 코드가 다시 확인)


@dataclass(frozen=True)
class SlotVocab:
    job_families: dict[str, str]      # 직무 -> 대분류 ('임시' 직무는 넣지 않는다)
    industries: tuple[str, ...]       # ANY가 들어 있어도 선택지에서는 뺀다

    @property
    def jobs(self) -> tuple[str, ...]:
        return tuple(self.job_families)

    @property
    def user_industries(self) -> tuple[str, ...]:
        """유저 쪽 산업 선택지. ANY는 캠프 쪽에서만 쓰는 값이다."""
        return tuple(i for i in self.industries if i != ANY)


@dataclass(frozen=True)
class FieldHint:
    """입력 필드 하나의 원문 표기와 사전 변환 결과. 사전에 없는 표기는 변환 결과가 비어 있다."""
    term: str
    jobs: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()


@dataclass(frozen=True)
class SlotInput:
    title: str
    content: str
    target_job: FieldHint | None = None
    target_company: FieldHint | None = None


@dataclass(frozen=True)
class Slot:
    value: str            # 대표 직무 또는 대표 산업
    raw_mention: str      # 제목+본문에 실제로 있는 구절
    basis: str            # EXPLICIT | INFERRED


@dataclass(frozen=True)
class SlotResult:
    jobs: tuple[Slot, ...] = ()
    industries: tuple[Slot, ...] = ()
    desired_help: str = 'UNKNOWN'
    help_mention: str = ''
    error_code: str | None = None
    log: tuple[str, ...] = ()         # 버린 값과 이유 (어휘 밖, 발췌 불일치, 중복, 개수 초과)
    prompt_version: str = SLOT_PROMPT_VERSION

    @property
    def ok(self) -> bool:
        return self.error_code is None


# ---------- 입력 필드 정규화 (사전 조회) ----------
def job_field_hint(term: str, vocab: SlotVocab,
                   job_alias: dict[str, tuple[tuple[str, ...], tuple[str, ...]]]) -> FieldHint | None:
    """희망 직무 필드. 미지정이면 None. 대표 직무와 같은 표기는 그대로, 별칭은 사전으로, 사전에 없으면 표기만."""
    term = term.strip()
    if term in ('', ALL_JOBS):
        return None
    if term in vocab.job_families:
        return FieldHint(term, (term,))
    jobs, industries = job_alias.get(term, ((), ()))
    return FieldHint(term, jobs, industries)


def company_field_hint(term: str, company_industry: dict[str, tuple[str, ...]]) -> FieldHint | None:
    """목표 회사 필드. 미지정이거나 사전에서 제외한 표기(회사가 아님 등)면 None, 사전에 없으면 표기만."""
    term = term.strip()
    if term in ('', ALL_COMPANIES):
        return None
    if term in company_industry and not company_industry[term]:
        return None
    return FieldHint(term, industries=company_industry.get(term, ()))


# ---------- 스키마와 프롬프트 ----------
def _slot_items(key: str, enum: list[str]) -> dict:
    return {'type': 'array', 'items': {
        'type': 'object',
        'properties': {key: {'type': 'string', 'enum': enum}, 'raw_mention': {'type': 'string'},
                       'basis': {'type': 'string', 'enum': list(BASIS)}},
        'required': [key, 'raw_mention', 'basis'],
        'additionalProperties': False,
    }}


def build_schema(vocab: SlotVocab) -> dict:
    """어휘에서 Enum을 자동 생성한 strict JSON schema. 개수 상한(maxItems)은 공급자 지원이 고르지 않아 코드가 자른다."""
    return {
        'type': 'object',
        'properties': {
            'jobs': _slot_items('job', list(vocab.jobs)),
            'industries': _slot_items('industry', list(vocab.user_industries)),
            'desired_help': {'type': 'string', 'enum': list(DESIRED_HELP)},
            'help_mention': {'type': 'string'},
        },
        'required': ['jobs', 'industries', 'desired_help', 'help_mention'],
        'additionalProperties': False,
    }


def build_system_prompt(vocab: SlotVocab, template: str) -> str:
    """프롬프트 본문(prompts/slot_filling.md)에 어휘를 끼워 넣는다. 자리표시: ${jobs}(대분류별), ${industries}.
    모르는 자리표시가 있으면 KeyError."""
    by_family: dict[str, list[str]] = {}
    for job, family in vocab.job_families.items():
        by_family.setdefault(family, []).append(job)
    jobs_text = '\n'.join(f'- {family}: {", ".join(jobs)}' for family, jobs in by_family.items())
    return Template(template).substitute(jobs=jobs_text, industries=', '.join(vocab.user_industries))


def _hint_line(label: str, hint: FieldHint) -> str:
    converted = [*hint.jobs, *hint.industries]
    return f'- {label}: {hint.term} → ' + (', '.join(converted) if converted else '(사전에 없음)')


def build_user_prompt(slot_input: SlotInput) -> str:
    parts = [f'제목: {slot_input.title}', f'본문:\n{slot_input.content}']
    hints = [_hint_line(label, h) for label, h in (('희망 직무', slot_input.target_job),
                                                   ('목표 회사', slot_input.target_company)) if h is not None]
    parts.append('입력 필드:\n' + ('\n'.join(hints) if hints else '- 없음'))
    return '\n\n'.join(parts)


# ---------- 응답 검증 ----------
def _squash(text: str) -> str:
    return re.sub(r'\s+', '', text).lower()


def mention_in_text(mention: str, text: str) -> bool:
    """발췌가 원문에 실제로 있는지 (공백·대소문자 무시). 빈 발췌는 근거가 아니다."""
    squashed = _squash(mention)
    return bool(squashed) and squashed in _squash(text)


def _parse_slots(items: list, key: str, allowed: tuple[str, ...], text: str, limit: int,
                 log: list[str]) -> tuple[Slot, ...]:
    slots: list[Slot] = []
    for item in items:
        value, mention, basis = item[key], item['raw_mention'].strip(), item['basis']
        if value not in allowed:
            log.append(f'{key} 어휘에 없는 값 버림: {value!r}')
        elif not mention_in_text(mention, text):
            log.append(f'{key} 발췌가 글에 없어 버림: {value} ({mention!r})')
        elif any(s.value == value for s in slots):
            log.append(f'{key} 중복 버림: {value}')
        elif len(slots) >= limit:
            log.append(f'{key} {limit}개 초과 버림: {value}')
        else:
            slots.append(Slot(value, mention, basis))
    return tuple(slots)


def _well_formed(data: object, list_key: str, value_key: str) -> bool:
    items = data.get(list_key) if isinstance(data, dict) else None
    return isinstance(items, list) and all(
        isinstance(i, dict) and isinstance(i.get(value_key), str) and isinstance(i.get('raw_mention'), str)
        and i.get('basis') in BASIS for i in items)


def parse_response(text: str, slot_input: SlotInput, vocab: SlotVocab) -> SlotResult:
    """LLM 응답(JSON 문자열)을 검증해 SlotResult로. 형식이 틀리면 error_code, 값 단위 문제는 그 값만 버리고 log에 남긴다."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return SlotResult(error_code=PARSE_ERROR, log=('JSON 파싱 실패',))
    if not (_well_formed(data, 'jobs', 'job') and _well_formed(data, 'industries', 'industry')
            and data.get('desired_help') in DESIRED_HELP and isinstance(data.get('help_mention'), str)):
        return SlotResult(error_code=SCHEMA_ERROR, log=('응답 형식이 스키마와 다름',))

    source = f'{slot_input.title}\n{slot_input.content}'
    log: list[str] = []
    jobs = _parse_slots(data['jobs'], 'job', vocab.jobs, source, MAX_JOBS, log)
    industries = _parse_slots(data['industries'], 'industry', vocab.user_industries, source, MAX_INDUSTRIES, log)
    desired_help, help_mention = data['desired_help'], data['help_mention'].strip()
    if desired_help == 'UNKNOWN':
        help_mention = ''
    elif not mention_in_text(help_mention, source):
        log.append(f'desired_help 발췌가 글에 없어 UNKNOWN으로: {desired_help} ({help_mention!r})')
        desired_help, help_mention = 'UNKNOWN', ''
    return SlotResult(jobs, industries, desired_help, help_mention, log=tuple(log))


def failed(error_code: str, message: str = '') -> SlotResult:
    """LLM 호출 자체가 실패했을 때의 결과 (공급자 오류코드를 그대로 담는다)."""
    return SlotResult(error_code=error_code, log=(message[:200],) if message else ())
