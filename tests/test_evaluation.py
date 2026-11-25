"""평가 지표 계산 (core/evaluation.py). 캠프·정답·직무·산업은 모두 가짜 값이다."""
import csv
import json

import pytest

from app.core.evaluation import (ALLOWED, DISALLOWED, NO_CANDIDATES, SLOT_ERROR, SLOT_MISSING, UNJUDGED, AnswerKey,
                                 Ratio, blind_pool, camp_for_rule_baseline, check_answer_key, edit_family_pairs,
                                 match_question, parse_answer_row, parse_required_groups, score_match, score_slots,
                                 slots_from_gold, slots_from_trial, summarize, verdict)
from app.core.gate import NO_SIGNAL, OFF_TARGET_GROUP
from app.core.industry import ANY, build_family_index
from app.core.matching import build_relation_index
from app.core.models import BODY_EXPLICIT, FIELD_JOB, HELP_FROM_CATEGORY, Camp, Candidate, MergedSlots, PostInput
from app.core.slot_filling import FieldHint, Slot, SlotResult
from app.sources.camps import RULE, LLM, load_matching_camps
from app.sources.evaluation import load_recs, load_slot_trial

RELATIONS = build_relation_index([('웹개발', 'SW개발', 'CLOSE')])
FAMILIES = build_family_index([('금융', '금융'), ('금융', '은행')])
CCT = {'진로': 'EXPLORE', '스펙': ''}


def key(**kw):
    base = dict(eval_id='T01', allowed=frozenset({'a', 'b', 'c'}), disallowed=frozenset({'x'}))
    base.update(kw)
    return AnswerKey(**base)


def camp(id, jobs, industries=(ANY,), camp_type=None):
    return Camp(id, f'가짜 캠프 {id}', tuple(jobs), tuple(industries), camp_type, recruiting=False)


POST = PostInput('제목', '본문', '진로', '취업 고민')


# ---------- 정답 셋 파싱 ----------
def test_parse_answer_row():
    row = {'eval_id': ' T01 ', 'expected_jobs': 'SW개발|웹개발', 'optional_jobs': '', 'expected_industries': '금융',
           'no_recommendation': 'n', 'allowed_camp_ids': 'a|b', 'disallowed_camp_ids': 'x', 'ideal_camp_ids': 'a',
           'required_groups': 'SW개발:a; 웹개발:b|c'}
    k = parse_answer_row(row)
    assert k.eval_id == 'T01' and k.expected_jobs == ('SW개발', '웹개발') and not k.no_recommendation
    assert k.allowed == {'a', 'b'} and k.ideal == {'a'}
    assert k.required_groups == (('SW개발', frozenset({'a'})), ('웹개발', frozenset({'b', 'c'})))


@pytest.mark.parametrize('text', ['SW개발', 'SW개발:', ':a'])
def test_parse_required_groups_rejects_bad_format(text):
    with pytest.raises(ValueError):
        parse_required_groups(text)


def test_parse_answer_row_requires_yn():
    with pytest.raises(ValueError):
        parse_answer_row({'eval_id': 'T01', 'no_recommendation': ''})


def test_check_answer_key_warnings():
    k = key(allowed=frozenset({'a', 'x'}), ideal=frozenset({'z'}),
            required_groups=(('SW개발', frozenset({'q'})),))
    warnings = ' '.join(check_answer_key(k, {'a', 'x'}))
    assert '허용과 불허' in warnings and 'ideal인데' in warnings and '묶음 SW개발' in warnings
    assert check_answer_key(key(), {'a', 'b', 'c', 'x'}) == []


# ---------- 판정·Hit@3 ----------
def test_verdict():
    k = key()
    assert [verdict(k, c) for c in ('a', 'x', 'new')] == [ALLOWED, DISALLOWED, UNJUDGED]
    # 추천 없음이 정답인 질문의 추천은 불허 (풀링 대상 아님)
    assert verdict(key(no_recommendation=True, allowed=frozenset()), 'new') == DISALLOWED


def test_hit_needs_one_allowed_in_top3():
    assert score_match(key(), ['x', 'new', 'b']).hit is True
    assert score_match(key(), ['x', 'new']).hit is False
    # 4위 이하는 보지 않는다
    assert score_match(key(), ['x', 'y', 'z', 'a']).hit is False
    assert score_match(key(), []).hit is False


def test_hit_with_required_groups_needs_every_group():
    k = key(required_groups=(('무역', frozenset({'a'})), ('물류', frozenset({'b', 'c'}))))
    s = score_match(k, ['a', 'x', 'new'])
    assert s.hit is False and s.missing_groups == ('물류',)
    assert score_match(k, ['a', 'c']).hit is True


def test_no_recommendation_question_has_no_hit():
    s = score_match(key(no_recommendation=True, allowed=frozenset(), disallowed=frozenset()), ['a'])
    assert s.hit is None and s.verdicts == (DISALLOWED,)


def test_ideal_pushed():
    k = key(ideal=frozenset({'a', 'b'}))
    assert score_match(k, ['a', 'b', 'c']).ideal_pushed is False
    assert score_match(k, ['a', 'c', 'x']).ideal_pushed is True        # ideal 2개 중 1개만
    assert score_match(key(ideal=frozenset({'a', 'b', 'c', 'd'})), ['a', 'b', 'c']).ideal_pushed is False
    assert score_match(key(ideal=frozenset({'a'})), []).ideal_pushed is True
    assert score_match(key(), ['x']).ideal_pushed is False             # ideal 없음


# ---------- 집계 ----------
def test_summarize_counts_unjudged_as_not_allowed_and_precision_over_all_recs():
    need1 = score_match(key(eval_id='T1'), ['a', 'new', 'x'])          # 허용 1, 미판정 1, 불허 1, Hit
    need2 = score_match(key(eval_id='T2'), [])                         # 추천 없음 → Hit 실패
    none1 = score_match(key(eval_id='T3', no_recommendation=True, allowed=frozenset()), [])
    none2 = score_match(key(eval_id='T4', no_recommendation=True, allowed=frozenset()), ['a'])
    s = summarize([need1, need2, none1, none2])
    assert s.hit_at_3 == Ratio(1, 2)
    assert s.precision_at_3 == Ratio(1, 4)                             # 추천 없음 질문의 추천도 분모에
    assert s.unjudged == 1
    assert s.no_rec_correct == Ratio(1, 2) and s.rec_given == Ratio(1, 2)
    assert s.jobs is None
    assert blind_pool([need1, need2, none2]) == [('T1', 'new')]


def test_ratio_without_denominator():
    assert Ratio(0, 0).value is None and str(Ratio(0, 0)) == '0/0'


# ---------- 슬롯 정확도 ----------
def merged(jobs=(), industries=()):
    return MergedSlots(tuple(Candidate(j, BODY_EXPLICIT, j) for j in jobs),
                       tuple(Candidate(i, BODY_EXPLICIT, i) for i in industries))


def test_slot_exact_allows_optional_but_not_extra():
    k = key(expected_jobs=('SW개발',), optional_jobs=('웹개발',), expected_industries=('금융',))
    assert score_slots(k, merged(['SW개발', '웹개발'], ['금융'])).jobs.exact
    s = score_slots(k, merged(['SW개발', '인사'], ['금융', '은행']))
    assert not s.jobs.exact and not s.industries.exact
    assert (s.jobs.found, s.jobs.correct) == (1, 1)
    assert not score_slots(k, merged(['웹개발'])).jobs.exact          # 정답 값이 빠짐


def test_slot_summary_and_gate_stopped_question_is_empty_prediction():
    k_none = key(eval_id='T2')                                       # 정답 슬롯 없음 (추천 없음 질문)
    assert score_slots(k_none, None).jobs.exact                      # 비어 있는 예측 = 정답
    k = key(expected_jobs=('SW개발', '웹개발'))
    slots = [score_slots(k, merged(['SW개발', '인사'])), score_slots(k_none, None)]
    s = summarize([score_match(k, ['a']), score_match(k_none, [])], slots)
    assert s.jobs.exact == Ratio(1, 2) and s.jobs.recall == Ratio(1, 2) and s.jobs.precision == Ratio(1, 2)


# ---------- 질문 하나 처리 ----------
CAMPS = [camp('a', ['SW개발'], ['금융']), camp('b', ['웹개발']), camp('c', ['인사'])]


def test_trial_slots_run_gate_merge_match_without_recruiting_check():
    slots = SlotResult(jobs=(Slot('SW개발', 'SW 개발', 'EXPLICIT'),), industries=(Slot('은행', '은행', 'EXPLICIT'),))
    merged_slots, stop = slots_from_trial(POST, slots, FieldHint('웹', ('웹개발',)), None, CCT)
    assert stop is None and [c.value for c in merged_slots.jobs] == ['SW개발', '웹개발']
    assert merged_slots.jobs[1].source == FIELD_JOB and merged_slots.camp_type == 'EXPLORE'
    run = match_question('T01', merged_slots, stop, CAMPS, RELATIONS, FAMILIES)
    assert run.stop_reason is None and run.camp_ids == ('a', 'b')     # recruiting=False 캠프도 후보


@pytest.mark.parametrize('post, slots, reason', [
    (PostInput('제목', '본문', '', '랜선 사수'), SlotResult(), OFF_TARGET_GROUP),
    (POST, None, SLOT_MISSING),
    (POST, SlotResult(error_code='rate_limited'), SLOT_ERROR),
])
def test_trial_slots_stop_reasons(post, slots, reason):
    merged_slots, stop = slots_from_trial(post, slots, None, None, CCT)
    run = match_question('T01', merged_slots, stop, CAMPS, RELATIONS, FAMILIES)
    assert merged_slots is None and run.stop_reason == reason and run.camp_ids == ()


def test_gate2_and_no_candidates():
    run = match_question('T01', MergedSlots(), None, CAMPS, RELATIONS, FAMILIES)
    assert run.stop_reason == NO_SIGNAL
    run = match_question('T01', merged(['재무']), None, CAMPS, RELATIONS, FAMILIES)
    assert run.stop_reason == NO_CANDIDATES and run.camp_ids == ()


def test_gold_slots_use_expected_in_order_and_category_default():
    k = key(expected_jobs=('웹개발', 'SW개발'), optional_jobs=('인사',), expected_industries=('금융',))
    m, stop = slots_from_gold(POST, k, CCT)
    assert stop is None and [c.value for c in m.jobs] == ['웹개발', 'SW개발']      # optional은 넣지 않음
    assert m.jobs[0].source == BODY_EXPLICIT and m.camp_type == 'EXPLORE' and m.help_source == HELP_FROM_CATEGORY
    m, _ = slots_from_gold(PostInput('제목', '본문', '스펙'), k, CCT)
    assert m.camp_type is None and m.help_source is None
    assert slots_from_gold(PostInput('', ''), k, CCT)[0] is None


# ---------- 캠프 변형 ①·계열 ----------
def test_rule_baseline_camp_has_no_camp_type():
    c = camp_for_rule_baseline(id='a', name='가짜', base_job_ids=('SW개발',), base_industry_ids=('금융',))
    assert c.camp_type is None and c.job_ids == ('SW개발',)
    assert camp_for_rule_baseline(id='a', name='가짜', base_job_ids=(), base_industry_ids=(),
                                  manual_not_camp=True) is None


def test_edit_family_pairs():
    pairs = [('금융', '금융'), ('금융', '은행'), ('공공', '공기업')]
    assert edit_family_pairs(pairs, [('전자·반도체', ['반도체', '전자/기계'])], ['공공']) == [
        ('금융', '금융'), ('금융', '은행'), ('전자·반도체', '반도체'), ('전자·반도체', '전자/기계')]
    assert edit_family_pairs(pairs, [('금융', ['금융'])]) == pairs


# ---------- 파일 읽기 (sources) ----------
PROFILE_COLUMNS = ['source_camp_id', '캠프명', 'status', 'is_camp', 'job_ids', 'industry_ids', 'camp_type',
                   'base_job_ids', 'base_industry_ids']


def test_load_matching_camps_variants(tmp_path):
    profile, manual = tmp_path / 'profile.csv', tmp_path / 'manual.csv'
    rows = [
        ['a', '가짜 A', 'auto_approved', 'True', 'SW개발|웹개발', '금융', 'EXPERIENCE', 'SW개발', '금융'],
        ['b', '가짜 B', 'pending_review', 'False', '인사', 'ANY', 'EXPLORE', 'SW개발', 'ANY'],
        ['c', '가짜 C', 'approved', 'False', '인사', 'ANY', '', '인사', 'ANY'],
        ['d', '가짜 D', 'approved', 'True', '인사', 'ANY', '', '인사', 'ANY'],
    ]
    with profile.open('w', encoding='utf-8', newline='') as f:
        csv.writer(f).writerows([PROFILE_COLUMNS, *rows])
    manual.write_text('source_camp_id,is_camp\nd,false\n', encoding='utf-8')

    llm = {c.id: c for c in load_matching_camps(LLM, profile, manual)}
    assert set(llm) == {'a', 'b', 'd'}                                  # 승인된 캠프 아님(c) 제외
    assert llm['a'].job_ids == ('SW개발', '웹개발') and llm['a'].camp_type == 'EXPERIENCE'
    assert llm['b'].job_ids == ('SW개발',) and llm['b'].camp_type == 'EXPLORE'   # 검수 전은 기준값

    rule = {c.id: c for c in load_matching_camps(RULE, profile, manual)}
    assert set(rule) == {'a', 'b', 'c'}                                 # LLM 캠프 아님은 무시, 수동 캠프 아님(d)은 제외
    assert rule['a'].job_ids == ('SW개발',) and all(c.camp_type is None for c in rule.values())
    with pytest.raises(ValueError):
        load_matching_camps('other', profile, manual)


def test_load_slot_trial_and_recs(tmp_path):
    trial = tmp_path / 'trial.jsonl'
    line = {'eval_id': 'T01', 'model': 'm', 'jobs': [{'value': 'SW개발', 'raw_mention': 'SW', 'basis': 'EXPLICIT'}],
            'industries': [], 'desired_help': 'EXPLORE', 'help_mention': '탐색', 'error_code': None, 'log': [],
            'prompt_version': 'slot-v1', 'metrics': {'input_tokens': 10, 'output_tokens': 2, 'elapsed_seconds': 1.0}}
    trial.write_text(json.dumps(line, ensure_ascii=False) + '\n', encoding='utf-8')
    result, metrics = load_slot_trial(trial)['T01']
    assert result.ok and result.jobs == (Slot('SW개발', 'SW', 'EXPLICIT'),) and result.desired_help == 'EXPLORE'
    assert metrics['input_tokens'] == 10

    recs = tmp_path / 'recs.jsonl'
    recs.write_text('{"eval_id": "T01", "camp_ids": ["b", "a"]}\n', encoding='utf-8')
    assert load_recs(recs) == {'T01': ('b', 'a')}
