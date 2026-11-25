"""
3갈래 평가 ③ LLM 캠프 선택의 순수 로직: 캠프 목록·프롬프트 조립, 스키마, 응답 검증 (docs/EVAL.md "③ LLM 캠프 선택 실행").
LLM 호출·파일 읽기는 하지 않는다 (scripts/run_camp_select.py가 맡는다).

평가 전용 비교군이다. 오프라인 정규화 없이 LLM이 캠프 전체 목록에서 직접 고르게 해서, ①②(정규화 + 매칭 규칙)와 같은 정답 셋으로 비교한다.
"""
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Template

CAMP_SELECT_PROMPT_VERSION = 'camp-select-v2'   # v2: 순번 ID
MAX_CAMPS = 3
PARSE_ERROR = 'select_parse_error'
SCHEMA_ERROR = 'select_schema_error'
NA = 'N/A'


@dataclass(frozen=True)
class SelectCamp:
    """원본 캠프 행의 칸 그대로 (정규화 결과는 쓰지 않는다)."""
    id: str
    family: str          # 직무대분류
    job: str             # 직무중분류
    detail: str          # 상세분류 (N/A는 빈칸으로)
    industry: str
    name: str


@dataclass(frozen=True)
class SelectInput:
    title: str
    content: str
    target_job: str = ''
    target_company: str = ''
    category: str = ''


@dataclass(frozen=True)
class SelectResult:
    camp_ids: tuple[str, ...] = ()
    reason: str = ''
    error_code: str | None = None
    log: tuple[str, ...] = ()
    prompt_version: str = CAMP_SELECT_PROMPT_VERSION

    @property
    def ok(self) -> bool:
        return self.error_code is None


def prompt_keys(camps: Sequence[SelectCamp]) -> dict[str, str]:
    """프롬프트용 짧은 순번 ID(C001~) → 캠프 ID. 캠프 ID 순으로 매겨 실행마다 같게 한다.
    12자리 해시를 그대로 주면 모델이 한 글자씩 틀리게 베껴(시험 1건에서 확인) 고르는 능력이 아닌 베끼는 능력이 점수에 섞인다."""
    ordered = sorted(camps, key=lambda c: c.id)
    width = max(3, len(str(len(ordered))))
    return {f'C{n:0{width}d}': c.id for n, c in enumerate(ordered, 1)}


def camp_line(key: str, camp: SelectCamp) -> str:
    detail = '' if camp.detail.strip() == NA else camp.detail.strip()
    return f'{key} | {camp.family} > {camp.job} | {detail} | {camp.industry} | {camp.name}'


def build_system_prompt(camps: Sequence[SelectCamp], template: str) -> str:
    by_id = {c.id: c for c in camps}
    lines = '\n'.join(camp_line(key, by_id[cid]) for key, cid in prompt_keys(camps).items())
    return Template(template).substitute(camps=lines)


def build_user_prompt(select_input: SelectInput) -> str:
    fields = [('희망 직무', select_input.target_job), ('목표 회사', select_input.target_company),
              ('질문 분류', select_input.category)]
    lines = '\n'.join(f'- {label}: {value.strip() or "(없음)"}' for label, value in fields)
    return f'제목: {select_input.title}\n\n본문:\n{select_input.content}\n\n입력 필드:\n{lines}'


def build_schema() -> dict:
    return {'type': 'object',
            'properties': {'camp_ids': {'type': 'array', 'items': {'type': 'string'}},
                           'reason': {'type': 'string'}},
            'required': ['camp_ids', 'reason'], 'additionalProperties': False}


def failed(error_code: str, message: str | None = None) -> SelectResult:
    return SelectResult(error_code=error_code, log=(message,) if message else ())


def parse_response(text: str, keys: Mapping[str, str]) -> SelectResult:
    """순번 ID를 캠프 ID로 되돌린다. 목록에 없는 ID·중복을 버리고 앞 MAX_CAMPS개만 쓴다. 형식이 틀리면 오류코드."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return failed(PARSE_ERROR, (text or '')[:200])
    if not (isinstance(data, dict) and isinstance(data.get('camp_ids'), list)
            and all(isinstance(i, str) for i in data['camp_ids']) and isinstance(data.get('reason'), str)):
        return failed(SCHEMA_ERROR, json.dumps(data, ensure_ascii=False)[:200])
    picked: list[str] = []
    log: list[str] = []
    for raw in data['camp_ids']:
        cid = keys.get(raw.strip().upper())
        if cid is None:
            log.append(f'목록에 없는 ID 버림: {raw!r}')
        elif cid in picked:
            log.append(f'중복 버림: {cid}')
        elif len(picked) >= MAX_CAMPS:
            log.append(f'개수 초과 버림: {cid}')
        else:
            picked.append(cid)
    return SelectResult(tuple(picked), data['reason'].strip(), log=tuple(log))
