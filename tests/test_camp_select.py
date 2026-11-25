import json

from app.core.camp_select import MAX_CAMPS, PARSE_ERROR, SCHEMA_ERROR, SelectCamp, SelectInput, build_schema, \
    build_system_prompt, build_user_prompt, camp_line, parse_response, prompt_keys

CAMPS = [SelectCamp('b2', '품질', '품질관리', 'N/A', '제조업', '품질 캠프'),
         SelectCamp('a1', 'IT/SW', '개발', '백엔드', 'IT', '백엔드 캠프')]
KEYS = {'C001': 'a1', 'C002': 'b2', 'C003': 'c3', 'C004': 'd4'}


def test_camp_line_blanks_na_detail():
    assert camp_line('C002', CAMPS[0]) == 'C002 | 품질 > 품질관리 |  | 제조업 | 품질 캠프'
    assert camp_line('C001', CAMPS[1]) == 'C001 | IT/SW > 개발 | 백엔드 | IT | 백엔드 캠프'


def test_prompt_keys_follow_camp_id_order():
    assert prompt_keys(CAMPS) == {'C001': 'a1', 'C002': 'b2'}


def test_system_prompt_lists_camps_sorted_by_id():
    text = build_system_prompt(CAMPS, '목록\n${camps}')
    assert text.splitlines()[1].startswith('C001 | IT/SW') and text.splitlines()[2].startswith('C002 | 품질')
    assert build_system_prompt(list(reversed(CAMPS)), '${camps}') == build_system_prompt(CAMPS, '${camps}')


def test_user_prompt_marks_empty_fields():
    text = build_user_prompt(SelectInput('제목', '본문', target_job='품질관리', category='직무'))
    assert '- 희망 직무: 품질관리' in text and '- 목표 회사: (없음)' in text and '- 질문 분류: 직무' in text


def test_schema_is_strict_object():
    schema = build_schema()
    assert schema['additionalProperties'] is False and set(schema['required']) == {'camp_ids', 'reason'}


def test_parse_drops_unknown_duplicate_and_extra_ids():
    text = json.dumps({'camp_ids': ['C001', 'C9', 'c001', ' C002 ', 'C003', 'C004'], 'reason': ' 이유 '})
    result = parse_response(text, KEYS)
    assert result.ok and result.camp_ids == ('a1', 'b2', 'c3') and len(result.camp_ids) == MAX_CAMPS
    assert result.reason == '이유' and len(result.log) == 3


def test_parse_empty_selection_is_ok():
    result = parse_response('{"camp_ids": [], "reason": "신호 없음"}', KEYS)
    assert result.ok and result.camp_ids == ()


def test_parse_errors():
    assert parse_response('not json', KEYS).error_code == PARSE_ERROR
    assert parse_response('{"camp_ids": "a1", "reason": ""}', KEYS).error_code == SCHEMA_ERROR
    assert parse_response('[]', KEYS).error_code == SCHEMA_ERROR
