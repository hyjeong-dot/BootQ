from app.core.normalize_v2 import (ANY, CampInput, Manual, Vocab, build_schema, build_system_prompt, build_user_prompt,
                                   evidence_in_name, merge, v1_item_to_v2, validate_item)
from app.sources.prompts import load_prompt

VOCAB = Vocab(
    job_families={'SW개발': 'IT/SW', 'IT일반': 'IT/SW', 'IT인프라': 'IT/SW', '공간디자인': '디자인', 'UI/UX디자인': '디자인',
                  '기술영업': '영업', '영업관리': '영업', '회계': '경영'},
    industries=(ANY, 'IT', '금융', '회계/컨설팅', '에너지/화학'),
    skills=('SQL', '클라우드'),
    sub_jobs=('백엔드',),
)


def llm(**over):
    base = {'is_camp': True, 'main_job': '', 'add_jobs': [], 'add_industries': [], 'remove_industry_suggested': False,
            'sub_job': '', 'skills': [], 'camp_type': 'EXPERIENCE', 'evidence': []}
    return {**base, **over}


def camp(name='x', jobs=('공간디자인',), industries=('IT',), sub_jobs=(), skills=(), placeholder=False):
    return CampInput('c', name, jobs, sub_jobs, industries, skills, placeholder)


def test_schema_has_no_way_to_replace_baseline_values():
    props = build_schema(VOCAB)['properties']['camps']['items']['properties']
    assert 'job_ids' not in props and 'industry_ids' not in props
    assert ANY not in props['add_industries']['items']['enum']
    assert props['main_job']['enum'][0] == ''


def test_prompt_marks_placeholder_and_memo():
    line = build_user_prompt([CampInput('c', '이름', ('IT일반',), (), ('IT',), (), True, ('PM',), '메모')])
    assert line == '1. 이름 | 기준: 직무=IT일반; 하위직무=-; 산업=IT | 주직무교체가능 | 추가직무후보=PM | 메모=메모'
    assert '멘토의 소속' in build_system_prompt(VOCAB, load_prompt('normalize_v2'))


def test_replacing_a_non_placeholder_main_job_is_dropped_and_logged():
    p = merge(camp('공간디자인 트렌드 분석'), llm(main_job='UI/UX디자인', evidence=['공간디자인']))
    assert p.job_ids == ('공간디자인',) and any('주 직무 교체 시도 버림' in m for m in p.log)
    assert p.status == 'pending_review'   # 버린 기록이 있으니 사람이 한 번 본다


def test_placeholder_main_job_can_be_replaced_with_evidence():
    c = camp('서버&프론트 개발 실무', jobs=('IT일반',), placeholder=True)
    p = merge(c, llm(main_job='SW개발', evidence=['서버&프론트 개발']))
    assert p.job_ids == ('SW개발',) and p.status == 'pending_review'


def test_additions_need_evidence_that_is_really_in_the_name():
    c = camp('B2B기술영업 & B2C영업관리 두마리 토끼잡기', jobs=('기술영업',))
    ok = merge(c, llm(add_jobs=['영업관리'], evidence=['B2C 영업관리']))   # 공백 차이는 허용
    assert ok.job_ids == ('기술영업', '영업관리')
    bad = merge(c, llm(add_jobs=['영업관리'], evidence=['영업관리 실무 과제']))   # 캠프명에 없는 구절
    assert bad.job_ids == ('기술영업',) and any('근거 검증 실패' in m for m in bad.log)
    none = merge(c, llm(add_jobs=['영업관리'], evidence=[]))
    assert none.job_ids == ('기술영업',)


def test_baseline_values_are_kept_by_code():
    c = camp('백엔드 개발', jobs=('SW개발',), sub_jobs=('백엔드',), industries=('IT',), skills=('SQL',))
    p = merge(c, llm(sub_job='', skills=[]))
    assert p.sub_job == '백엔드' and p.skills == ('SQL',) and p.industry_ids == ('IT',) and p.status == 'auto_approved'


def test_industry_is_added_to_any_or_appended_but_removal_is_only_a_suggestion():
    on_any = merge(camp('정유사 해외영업', industries=(ANY,)), llm(add_industries=['에너지/화학'], evidence=['정유사']))
    assert on_any.industry_ids == ('에너지/화학',)
    appended = merge(camp('금융 IT 운영', industries=('IT',)), llm(add_industries=['금융'], evidence=['금융']))
    assert appended.industry_ids == ('IT', '금융')
    removal = merge(camp('콘텐츠 마케팅 실무', industries=('IT',)), llm(remove_industry_suggested=True))
    assert removal.industry_ids == ('IT',) and removal.remove_industry_suggested and removal.status == 'pending_review'
    on_any_removal = merge(camp('x', industries=(ANY,)), llm(remove_industry_suggested=True))
    assert not on_any_removal.remove_industry_suggested


def test_manual_correction_wins_over_llm_and_rules():
    c = camp('빅4 컨설팅펌 SCM', industries=('전자/기계',))
    p = merge(c, llm(add_industries=['IT'], evidence=['빅4']), Manual(industry_ids=('회계/컨설팅',), reason='업종 확정'))
    assert p.industry_ids == ('회계/컨설팅',) and p.status == 'approved'
    excluded = merge(c, None, Manual(is_camp=False, reason='사내 특강'))
    assert excluded.is_camp is False and excluded.status == 'approved'


def test_manual_fixes_only_filled_fields():
    p = merge(camp('x'), llm(camp_type='APPLICATION', skills=['SQL']), Manual(job_ids=('UI/UX디자인',), reason='직무만 확정'))
    assert p.job_ids == ('UI/UX디자인',) and p.industry_ids == ('IT',)
    assert p.camp_type == 'APPLICATION' and p.skills == ('SQL',)


def test_validate_rejects_out_of_vocab_and_any_in_additions():
    assert validate_item(llm(add_industries=[ANY]), VOCAB)[0] is None
    assert validate_item(llm(main_job='없는직무'), VOCAB)[0] is None
    assert validate_item(llm(skills=['Python']), VOCAB)[0] is None
    assert validate_item(llm(), VOCAB)[0] is not None


def test_evidence_check_ignores_spaces_and_case():
    assert evidence_in_name(['aws 구축'], 'AWS구축부터 운영까지')
    assert not evidence_in_name([], '아무 이름')
    assert not evidence_in_name(['AWS 구축부터 운영까지'], 'AWS구축부터 운영까지')   # 캠프명 통째 복사는 무효


def test_schema_asks_for_evidence_before_changes():
    props = list(build_schema(VOCAB)['properties']['camps']['items']['properties'])
    assert props.index('evidence') < props.index('main_job') < props.index('add_jobs')


def test_v1_replacement_is_not_counted_as_addition():
    c = camp('공간디자인 트렌드', jobs=('공간디자인',), industries=('IT',))
    converted = v1_item_to_v2({'job_ids': ['UI/UX디자인'], 'industry_ids': ['IT']}, c)
    assert converted['main_job'] == 'UI/UX디자인' and converted['add_jobs'] == []
    to_any = v1_item_to_v2({'job_ids': ['공간디자인'], 'industry_ids': [ANY]}, c)
    assert to_any['remove_industry_suggested'] and to_any['add_industries'] == []
    replaced = v1_item_to_v2({'job_ids': ['공간디자인'], 'industry_ids': ['금융']}, c)
    assert replaced['_v1_industry_replaced'] and replaced['add_industries'] == []
