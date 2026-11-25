import json

import pytest

from app.core.slot_filling import (ANY, PARSE_ERROR, SCHEMA_ERROR, SLOT_PROMPT_VERSION, FieldHint, Slot, SlotInput,
                                   SlotVocab, build_schema, build_system_prompt, build_user_prompt, company_field_hint,
                                   job_field_hint, mention_in_text, parse_response)
from app.services.slot_filling import SLOT_MAX_RETRIES, SLOT_TIMEOUT_SECONDS, fill_slots, make_slot_client
from app.sources.prompts import load_prompt
from app.sources.vocab import load_slot_vocab

# 재작성 샘플 (실제 유저 글이 아님)
VOCAB = SlotVocab(job_families={'품질': '품질', '공정기술': '생산/제조', 'SW개발': 'IT/SW', '데이터분석': 'IT/SW'},
                  industries=(ANY, '반도체', '전자/기계', 'IT'))
POST = SlotInput('전자회사 품질 직무 고민',
                 '전자공학과 4학년입니다. 품질관리나 공정 엔지니어 중에 고민 중인데 실무 경험이 없어서 걱정이에요. '
                 '프로젝트 경험을 쌓고 싶습니다.')


def answer(jobs=(), industries=(), desired_help='UNKNOWN', help_mention=''):
    return json.dumps({
        'jobs': [{'job': j, 'raw_mention': m, 'basis': b} for j, m, b in jobs],
        'industries': [{'industry': i, 'raw_mention': m, 'basis': b} for i, m, b in industries],
        'desired_help': desired_help, 'help_mention': help_mention}, ensure_ascii=False)


# ---------- 스키마·프롬프트 ----------
def test_schema_enums_come_from_vocab_and_exclude_any():
    props = build_schema(VOCAB)['properties']
    assert props['jobs']['items']['properties']['job']['enum'] == ['품질', '공정기술', 'SW개발', '데이터분석']
    assert props['industries']['items']['properties']['industry']['enum'] == ['반도체', '전자/기계', 'IT']
    assert props['desired_help']['enum'] == ['EXPLORE', 'EXPERIENCE', 'APPLICATION', 'UNKNOWN']


def test_schema_is_strict_mode_compatible():
    # strict 모드는 모든 속성이 required이고 추가 속성을 막아야 한다
    def check(node):
        if node.get('type') == 'object':
            assert set(node['required']) == set(node['properties']) and node['additionalProperties'] is False
            for child in node['properties'].values():
                check(child)
        if node.get('type') == 'array':
            check(node['items'])
    check(build_schema(VOCAB))


def test_system_prompt_lists_jobs_by_family_and_industries():
    prompt = build_system_prompt(VOCAB, load_prompt('slot_filling'))
    assert '- IT/SW: SW개발, 데이터분석' in prompt and '- 품질: 품질' in prompt
    assert '반도체, 전자/기계, IT' in prompt and ANY not in prompt.split('## 산업 선택지')[1]
    assert '${' not in prompt


def test_unknown_placeholder_is_an_error():
    with pytest.raises(KeyError):
        build_system_prompt(VOCAB, '${jobs} ${typo}')


def test_user_prompt_shows_field_terms_with_conversion():
    text = build_user_prompt(SlotInput('제목', '본문', FieldHint('반도체설계', ('HW개발',), ('반도체',)),
                                       FieldHint('어느 회사')))
    assert text == ('제목: 제목\n\n본문:\n본문\n\n입력 필드:\n- 희망 직무: 반도체설계 → HW개발, 반도체\n'
                    '- 목표 회사: 어느 회사 → (사전에 없음)')
    assert build_user_prompt(SlotInput('제목', '본문')).endswith('입력 필드:\n- 없음')


# ---------- 입력 필드 정규화 ----------
def test_job_field_hint():
    alias = {'품질관리': (('품질',), ()), '배터리개발': ((), ('2차전지',))}
    assert job_field_hint('모든 직무', VOCAB, alias) is None and job_field_hint(' ', VOCAB, alias) is None
    assert job_field_hint('SW개발', VOCAB, alias) == FieldHint('SW개발', ('SW개발',))
    assert job_field_hint('품질관리', VOCAB, alias) == FieldHint('품질관리', ('품질',))
    assert job_field_hint('배터리개발', VOCAB, alias) == FieldHint('배터리개발', (), ('2차전지',))
    assert job_field_hint('새로운표기', VOCAB, alias) == FieldHint('새로운표기')


def test_company_field_hint():
    companies = {'모든 회사': (), '대학': (), '어느전자': ('전자/기계',)}
    assert company_field_hint('모든 회사', companies) is None
    assert company_field_hint('대학', companies) is None          # 사전에서 제외한 표기
    assert company_field_hint('어느전자', companies) == FieldHint('어느전자', industries=('전자/기계',))
    assert company_field_hint('처음보는회사', companies) == FieldHint('처음보는회사')


# ---------- 응답 검증 ----------
def test_valid_answer_is_kept_in_order():
    r = parse_response(answer(jobs=[('품질', '품질관리', 'EXPLICIT'), ('공정기술', '공정 엔지니어', 'EXPLICIT')],
                              industries=[('전자/기계', '전자회사', 'EXPLICIT')],
                              desired_help='EXPERIENCE', help_mention='프로젝트 경험을 쌓고 싶습니다'), POST, VOCAB)
    assert r.ok and r.log == () and r.prompt_version == SLOT_PROMPT_VERSION
    assert r.jobs == (Slot('품질', '품질관리', 'EXPLICIT'), Slot('공정기술', '공정 엔지니어', 'EXPLICIT'))
    assert r.industries == (Slot('전자/기계', '전자회사', 'EXPLICIT'),)
    assert (r.desired_help, r.help_mention) == ('EXPERIENCE', '프로젝트 경험을 쌓고 싶습니다')


def test_mention_not_in_post_drops_the_value():
    r = parse_response(answer(jobs=[('품질', '품질관리', 'EXPLICIT'), ('SW개발', '개발자', 'INFERRED')]), POST, VOCAB)
    assert [s.value for s in r.jobs] == ['품질'] and any('발췌가 글에 없어 버림: SW개발' in m for m in r.log)


def test_mention_match_ignores_spaces_and_case_but_not_empty():
    assert mention_in_text('공정엔지니어', POST.content) and mention_in_text('ABC', 'x a b c y')
    assert not mention_in_text('  ', POST.content)
    assert parse_response(answer(jobs=[('품질', '', 'INFERRED')]), POST, VOCAB).jobs == ()


def test_mention_in_title_counts():
    assert parse_response(answer(industries=[('전자/기계', '전자회사', 'EXPLICIT')]), POST, VOCAB).industries


def test_out_of_vocab_any_duplicates_and_overflow_are_dropped():
    r = parse_response(answer(
        jobs=[('품질', '품질', 'EXPLICIT'), ('품질', '품질관리', 'EXPLICIT'), ('공정기술', '공정', 'EXPLICIT'),
              ('없는직무', '실무', 'EXPLICIT'), ('SW개발', '전자공학과', 'INFERRED'), ('데이터분석', '4학년', 'INFERRED')],
        industries=[(ANY, '전자회사', 'EXPLICIT')]), POST, VOCAB)
    assert [s.value for s in r.jobs] == ['품질', '공정기술', 'SW개발'] and r.industries == ()
    assert any('중복' in m for m in r.log) and any('어휘에 없는 값' in m for m in r.log)
    assert any('3개 초과' in m for m in r.log) and any("'ANY'" in m for m in r.log)


def test_desired_help_without_real_mention_becomes_unknown():
    r = parse_response(answer(desired_help='APPLICATION', help_mention='자소서를 봐 주세요'), POST, VOCAB)
    assert (r.desired_help, r.help_mention) == ('UNKNOWN', '') and r.log
    r = parse_response(answer(desired_help='UNKNOWN', help_mention='실무 경험'), POST, VOCAB)
    assert (r.desired_help, r.help_mention, r.log) == ('UNKNOWN', '', ())


def test_no_evidence_is_empty_but_ok():
    r = parse_response(answer(), POST, VOCAB)
    assert r.ok and r.jobs == () and r.industries == ()


@pytest.mark.parametrize('text, code', [
    ('not json', PARSE_ERROR),
    ('[]', SCHEMA_ERROR),
    (json.dumps({'jobs': [{'job': '품질', 'raw_mention': '품질'}], 'industries': [], 'desired_help': 'UNKNOWN',
                 'help_mention': ''}), SCHEMA_ERROR),
    (json.dumps({'jobs': [], 'industries': [], 'desired_help': 'HELP', 'help_mention': ''}), SCHEMA_ERROR),
])
def test_unusable_response_sets_error_code(text, code):
    r = parse_response(text, POST, VOCAB)
    assert r.error_code == code and not r.ok and r.jobs == ()


# ---------- 호출 (가짜 transport) ----------
def ok_body(content):
    return json.dumps({'choices': [{'message': {'content': content}}],
                       'usage': {'prompt_tokens': 900, 'completion_tokens': 80}})


def make_client(responses):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((json.loads(body), timeout))
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return make_slot_client('key', 'openai/gpt-oss-120b', transport=transport, sleep=lambda s: None), calls


def test_fill_slots_success_sends_vocab_schema_and_records_metrics():
    client, calls = make_client([(200, {}, ok_body(answer(jobs=[('품질', '품질관리', 'EXPLICIT')])))])
    result, metrics = fill_slots(client, POST, VOCAB, load_prompt('slot_filling'))
    assert result.ok and [s.value for s in result.jobs] == ['품질']
    assert (metrics['input_tokens'], metrics['output_tokens']) == (900, 80)
    sent, timeout = calls[0]
    assert timeout == SLOT_TIMEOUT_SECONDS == 15.0
    assert sent['response_format']['json_schema']['schema'] == build_schema(VOCAB)
    assert '품질관리나 공정 엔지니어' in sent['messages'][1]['content']


def test_fill_slots_retries_once_then_fails_with_provider_error():
    client, calls = make_client([(503, {}, 'down')])
    result, _ = fill_slots(client, POST, VOCAB, load_prompt('slot_filling'))
    assert len(calls) == 1 + SLOT_MAX_RETRIES == 2
    assert result.error_code == 'server_error' and not result.ok and result.jobs == ()


def test_fill_slots_invalid_json_is_a_failure():
    client, _ = make_client([(200, {}, ok_body('{"jobs": '))])
    result, _ = fill_slots(client, POST, VOCAB, load_prompt('slot_filling'))
    assert result.error_code == PARSE_ERROR


# ---------- 실제 어휘 파일 ----------
def test_slot_vocab_from_files_is_ordered_and_matches_prompt():
    vocab = load_slot_vocab()
    assert vocab == load_slot_vocab() and ANY in vocab.industries and ANY not in vocab.user_industries
    prompt = build_system_prompt(vocab, load_prompt('slot_filling'))
    assert all(job in prompt for job in vocab.jobs) and '${' not in prompt
