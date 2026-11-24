import pytest

from app.core.normalize import (CampInput, Vocab, build_schema, build_system_prompt, build_user_prompt, changed_fields,
                                content_hash, review_status, validate_item)

VOCAB = Vocab(
    job_families={'SW개발': 'IT/SW', '데이터분석': 'IT/SW', '품질': '품질', 'IB': '금융/은행/보험'},
    industries=('ANY', 'IT', '금융', '에너지/화학', '2차전지'),
    skills=('SQL', 'GMP'),
    sub_jobs=('백엔드', '프론트엔드'),
)
CAMP = CampInput('c1', 'SQL로 배우는 데이터 실무', ('데이터분석',), (), ('IT',), ())


def item(**over):
    base = {'id': 'c1', 'is_camp': True, 'job_ids': ['데이터분석'], 'sub_job': '', 'industry_ids': ['IT'],
            'skills': ['SQL'], 'camp_type': 'EXPERIENCE', 'change_note': ''}
    return {**base, **over}


def test_schema_is_strict_and_uses_vocab_enums():
    schema = build_schema(VOCAB)
    props = schema['properties']['camps']['items']
    assert props['additionalProperties'] is False
    assert set(props['required']) == set(props['properties'])
    assert props['properties']['job_ids']['items']['enum'] == ['SW개발', '데이터분석', '품질', 'IB']
    assert props['properties']['industry_ids']['items']['enum'][0] == 'ANY'


def test_prompts_contain_vocab_and_camp_lines():
    system = build_system_prompt(VOCAB)
    assert '2차전지' in system and 'IT/SW: SW개발, 데이터분석' in system
    user = build_user_prompt([CampInput('c1', '이름', ('IB',), ('기업금융',), ('금융',), (), ('PM',), '→ IB')])
    assert user == '[c1] 이름 | 기준: 직무=IB; 하위직무=기업금융; 산업=금융; 스킬=- | 추가직무후보=PM | 검수메모=→ IB'


def test_valid_item_becomes_profile():
    profile, errors = validate_item(item(), CAMP, VOCAB)
    assert errors == [] and profile.job_ids == ('데이터분석',) and profile.skills == ('SQL',)


@pytest.mark.parametrize('bad', [
    {'job_ids': ['없는직무']}, {'job_ids': []}, {'job_ids': ['SW개발', '품질', 'IB']},
    {'industry_ids': ['반도체']}, {'skills': ['Python']}, {'camp_type': 'OTHER'}, {'is_camp': 'yes'},
])
def test_invalid_items_are_rejected(bad):
    profile, errors = validate_item(item(**bad), CAMP, VOCAB)
    assert profile is None and errors


def test_any_combined_with_other_industry_is_fixed_with_a_warning():
    profile, errors = validate_item(item(industry_ids=['ANY', 'IT']), CAMP, VOCAB)
    assert errors == [] and profile.industry_ids == ('IT',) and 'ANY 제거' in profile.change_note


def test_review_status_follows_the_baseline_diff():
    same, _ = validate_item(item(), CAMP, VOCAB)
    assert review_status(CAMP, same) == 'auto_approved'          # 스킬만 채워진 것은 추가일 뿐
    moved, _ = validate_item(item(job_ids=['SW개발']), CAMP, VOCAB)
    assert changed_fields(CAMP, moved) == ['job_ids'] and review_status(CAMP, moved) == 'pending_review'
    other_industry, _ = validate_item(item(industry_ids=['금융']), CAMP, VOCAB)
    assert changed_fields(CAMP, other_industry) == ['industry_ids']
    assert review_status(CAMP, None) == 'pending_review'


def test_replacing_an_existing_sub_job_or_dropping_a_baseline_skill_needs_review():
    camp = CampInput('c2', 'x', ('SW개발',), ('백엔드',), ('IT',), ('SQL',))
    p1, _ = validate_item(item(job_ids=['SW개발'], sub_job='프론트엔드', skills=['SQL']), camp, VOCAB)
    assert changed_fields(camp, p1) == ['sub_job']
    p2, _ = validate_item(item(job_ids=['SW개발'], sub_job='백엔드', skills=[]), camp, VOCAB)
    assert changed_fields(camp, p2) == ['skills']
    not_a_camp, _ = validate_item(item(job_ids=['SW개발'], sub_job='백엔드', skills=['SQL'], is_camp=False), camp, VOCAB)
    assert changed_fields(camp, not_a_camp) == ['is_camp']


def test_content_hash_changes_with_prompt_or_camp():
    base = content_hash(CAMP, 'prompt')
    assert base == content_hash(CAMP, 'prompt')
    assert base != content_hash(CAMP, 'prompt2')
    assert base != content_hash(CampInput('c1', CAMP.name, ('SW개발',), (), ('IT',), ()), 'prompt')
