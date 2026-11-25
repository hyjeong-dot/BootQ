"""
슬롯 병합: 본문 명시 > 입력 필드 > 본문 추론. 순수 함수만 둔다.
규칙 원본: docs/rules/02_BACKEND.md 5장 "병합"

- 직무와 산업을 따로 같은 규칙으로 병합한다
- 후보 = 본문 명시 ∪ 입력 필드 (이 순서, 중복은 앞 출처를 남김)
- 본문 명시와 입력 필드가 모두 있고 겹치는 값이 없으면 둘 다 두고 충돌 플래그
- 본문 추론 값은 명시·필드 값이 하나도 없을 때만 쓰고 inferred_only 플래그. 아니면 버리고 로그
- desired_help: 슬롯 값(UNKNOWN 아님) > category 기본값 > 선호 없음
"""
from collections.abc import Mapping

from app.core.models import (BODY_EXPLICIT, BODY_INFERRED, FIELD_COMPANY, FIELD_JOB, HELP_FROM_BODY,
                             HELP_FROM_CATEGORY, Candidate, MergedSlots)
from app.core.slot_filling import FieldHint, Slot, SlotResult

UNKNOWN = 'UNKNOWN'


def _body(slots: tuple[Slot, ...], basis: str, source: str) -> list[Candidate]:
    return [Candidate(s.value, source, s.raw_mention) for s in slots if s.basis == basis]


def _merge_axis(name: str, explicit: list[Candidate], field: list[Candidate], inferred: list[Candidate],
                flags: set[str], log: list[str]) -> tuple[Candidate, ...]:
    merged: list[Candidate] = []
    for c in [*explicit, *field]:
        if any(m.value == c.value for m in merged):
            log.append(f'{name} 중복은 앞 출처를 남김: {c.value} ({c.source})')
        else:
            merged.append(c)
    if explicit and field and not {c.value for c in explicit} & {c.value for c in field}:
        flags.add(f'{name}_conflict')
        log.append(f'{name} 본문 명시와 입력 필드가 다름: 둘 다 후보')
    if merged:
        for c in inferred:
            log.append(f'{name} 본문 추론 버림 (명시·필드 값이 있음): {c.value}')
        return tuple(merged)
    deduped: list[Candidate] = []
    for c in inferred:
        if all(d.value != c.value for d in deduped):
            deduped.append(c)
    if deduped:
        flags.add(f'{name}_inferred_only')
    return tuple(deduped)


def merge(slots: SlotResult, job_hint: FieldHint | None, company_hint: FieldHint | None,
          category: str, category_camp_type: Mapping[str, str]) -> MergedSlots:
    """슬롯필링 결과와 입력 필드 힌트를 병합한다.
    slots가 오류 결과면 ValueError: 호출자는 슬롯필링이 실패하면 병합하지 않고 추천 없음으로 끝낸다."""
    if not slots.ok:
        raise ValueError(f'슬롯필링 오류 결과는 병합하지 않는다: {slots.error_code}')
    flags: set[str] = set()
    log: list[str] = []

    field_jobs: list[Candidate] = []
    field_industries: list[Candidate] = []
    if job_hint is not None:
        field_jobs = [Candidate(j, FIELD_JOB, job_hint.term) for j in job_hint.jobs]
        field_industries += [Candidate(i, FIELD_JOB, job_hint.term) for i in job_hint.industries]
        if not job_hint.jobs and not job_hint.industries:
            log.append(f'희망 직무 표기가 사전에 없어 후보로 쓰지 않음: {job_hint.term}')
    if company_hint is not None:
        field_industries += [Candidate(i, FIELD_COMPANY, company_hint.term) for i in company_hint.industries]
        if not company_hint.industries:
            log.append(f'목표 회사 표기가 사전에 없어 후보로 쓰지 않음: {company_hint.term}')

    jobs = _merge_axis('job', _body(slots.jobs, 'EXPLICIT', BODY_EXPLICIT), field_jobs,
                       _body(slots.jobs, 'INFERRED', BODY_INFERRED), flags, log)
    industries = _merge_axis('industry', _body(slots.industries, 'EXPLICIT', BODY_EXPLICIT), field_industries,
                             _body(slots.industries, 'INFERRED', BODY_INFERRED), flags, log)

    camp_type, help_source, help_mention = None, None, ''
    if slots.desired_help != UNKNOWN:
        camp_type, help_source, help_mention = slots.desired_help, HELP_FROM_BODY, slots.help_mention
    elif category_camp_type.get(category.strip()):
        camp_type, help_source = category_camp_type[category.strip()], HELP_FROM_CATEGORY
    return MergedSlots(jobs, industries, camp_type, help_source, help_mention, frozenset(flags), tuple(log))
