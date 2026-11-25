"""매칭 정렬 (07_TEST.md 우선순위 1): 사전식 단계 순서, 직무 B등급은 A가 3개 미만일 때만, 복수 직무 분배.
캠프명·직무·산업은 모두 가짜 값이다."""
from app.core.industry import ANY, IndustryGrade, build_family_index
from app.core.matching import (FAMILY_USED, INDUSTRY_ONLY, NO_CANDIDATES, build_relation_index, job_relation,
                               match)
from app.core.models import (BODY_EXPLICIT, CLOSE, FAMILY, HELP_FROM_BODY, HELP_FROM_CATEGORY, PENDING_REVIEW, SAME,
                             Camp, Candidate, HelpGrade, MergedSlots, camp_for_matching)

RELATIONS = build_relation_index([
    ('웹개발', 'SW개발', CLOSE),
    ('SW개발', '데이터분석', FAMILY),
    ('품질관리', '공정기술', FAMILY),
])
FAMILIES = build_family_index([('금융', '금융'), ('금융', '은행')])


def job(value):
    return Candidate(value, BODY_EXPLICIT, value)


def ind(value):
    return Candidate(value, BODY_EXPLICIT, value)


def camp(id, jobs, industries=(ANY,), camp_type=None, recruiting=True):
    return Camp(id, f'가짜 캠프 {id}', tuple(jobs), tuple(industries), camp_type, recruiting)


def ids(result):
    return [r.camp.id for r in result.recommendations]


def run(merged, camps, **kw):
    return match(merged, camps, RELATIONS, FAMILIES, **kw)


# ---------- 관계 조회 ----------
def test_job_relation_is_symmetric_and_same_for_identical():
    assert job_relation('SW개발', 'SW개발', RELATIONS) == SAME
    assert job_relation('SW개발', '웹개발', RELATIONS) == CLOSE
    assert job_relation('웹개발', 'SW개발', RELATIONS) == CLOSE
    assert job_relation('SW개발', '인사', RELATIONS) is None


# ---------- 사전식 단계 순서 ----------
def test_unrelated_job_is_excluded():
    result = run(MergedSlots(jobs=(job('SW개발'),)), [camp('a', ['인사'], ['금융'])])
    assert ids(result) == [] and NO_CANDIDATES in result.flags


def test_job_grade_a_beats_b_even_if_b_matches_industry_and_type():
    # 가중합이면 산업·camp_type이 맞는 B가 올라올 수 있다. 사전식이면 A가 항상 먼저
    merged = MergedSlots(jobs=(job('SW개발'),), industries=(ind('금융'),), camp_type='EXPERIENCE')
    camps = [camp('b', ['데이터분석'], ['금융'], 'EXPERIENCE'), camp('a', ['SW개발'], ['제조'], 'EXPLORE')]
    assert ids(run(merged, camps)) == ['a', 'b']


def test_industry_before_same_close():
    # 산업이 맞는 CLOSE 캠프가 산업무관 SAME 캠프보다 위
    merged = MergedSlots(jobs=(job('SW개발'),), industries=(ind('금융'),))
    camps = [camp('same_any', ['SW개발'], [ANY]), camp('close_match', ['웹개발'], ['금융'])]
    assert ids(run(merged, camps)) == ['close_match', 'same_any']


def test_industry_grade_order_match_family_any_mismatch():
    merged = MergedSlots(jobs=(job('SW개발'),), industries=(ind('금융'),))
    camps = [camp('mismatch', ['SW개발'], ['제조']), camp('any', ['SW개발'], [ANY]),
             camp('family', ['SW개발'], ['은행']), camp('match', ['SW개발'], ['금융'])]
    assert ids(run(merged, camps, limit=4)) == ['match', 'family', 'any', 'mismatch']


def test_same_before_close_when_industry_equal():
    merged = MergedSlots(jobs=(job('SW개발'),))
    assert ids(run(merged, [camp('close', ['웹개발']), camp('same', ['SW개발'])])) == ['same', 'close']


def test_camp_type_is_last_key():
    merged = MergedSlots(jobs=(job('SW개발'),), camp_type='EXPERIENCE', help_source=HELP_FROM_BODY)
    camps = [camp('mis', ['SW개발'], camp_type='EXPLORE'), camp('none', ['SW개발']),
             camp('hit', ['SW개발'], camp_type='EXPERIENCE'), camp('close_hit', ['웹개발'], camp_type='EXPERIENCE')]
    result = run(merged, camps, limit=4)
    assert ids(result) == ['hit', 'none', 'mis', 'close_hit']   # camp_type은 SAME>CLOSE를 뒤집지 못한다
    assert [r.help_grade for r in result.recommendations][:3] == [HelpGrade.MATCH, HelpGrade.NO_TYPE,
                                                                  HelpGrade.MISMATCH]


def test_camp_type_skipped_without_preference_ties_by_id():
    merged = MergedSlots(jobs=(job('SW개발'),))
    camps = [camp('c2', ['SW개발'], camp_type='EXPLORE'), camp('c1', ['SW개발'], camp_type='EXPERIENCE')]
    result = run(merged, camps)
    assert ids(result) == ['c1', 'c2'] and result.recommendations[0].help_grade is None


def test_camp_type_skipped_when_help_from_category():
    # category 기본값은 유저가 쓴 말이 아니라 정렬에 쓰지 않는다 (#35)
    merged = MergedSlots(jobs=(job('SW개발'),), camp_type='EXPERIENCE', help_source=HELP_FROM_CATEGORY)
    camps = [camp('c2', ['SW개발'], camp_type='EXPERIENCE'), camp('c1', ['SW개발'], camp_type='EXPLORE')]
    result = run(merged, camps)
    assert ids(result) == ['c1', 'c2'] and result.recommendations[0].help_grade is None


def test_industry_skipped_without_user_industry():
    merged = MergedSlots(jobs=(job('SW개발'),))
    result = run(merged, [camp('x', ['SW개발'], ['제조'])])
    assert result.recommendations[0].industry_grade is None


# ---------- 0단계: 모집 중 ----------
def test_closed_camp_excluded_unless_check_recruiting_off():
    merged = MergedSlots(jobs=(job('SW개발'),))
    camps = [camp('closed', ['SW개발'], recruiting=False), camp('open', ['SW개발'])]
    assert ids(run(merged, camps)) == ['open']
    assert ids(run(merged, camps, check_recruiting=False)) == ['closed', 'open']


# ---------- B등급은 A가 3개 미만일 때만 ----------
def test_family_excluded_when_three_a_camps():
    merged = MergedSlots(jobs=(job('SW개발'),))
    camps = [camp('a1', ['SW개발']), camp('a2', ['SW개발']), camp('a3', ['웹개발']), camp('b1', ['데이터분석'])]
    result = run(merged, camps)
    assert ids(result) == ['a1', 'a2', 'a3']
    assert FAMILY_USED not in result.flags


def test_family_counts_a_over_whole_pool_not_top3():
    # A가 4개면 limit=1이어도 B는 후보에 들지 않는다
    merged = MergedSlots(jobs=(job('SW개발'),))
    camps = [camp(f'a{i}', ['SW개발']) for i in range(4)] + [camp('b1', ['데이터분석'])]
    assert 'b1' not in ids(run(merged, camps, limit=5))


def test_family_fills_when_fewer_than_three_a_with_review_flag():
    merged = MergedSlots(jobs=(job('SW개발'),))
    camps = [camp('a1', ['SW개발']), camp('b1', ['데이터분석']), camp('a2', ['웹개발'])]
    result = run(merged, camps)
    assert ids(result) == ['a1', 'a2', 'b1']
    assert [r.review for r in result.recommendations] == [False, False, True]
    assert result.recommendations[2].relation == FAMILY
    assert FAMILY_USED in result.flags


# ---------- 캠프·유저 직무가 여럿일 때 ----------
def test_multi_job_camp_uses_best_pair():
    merged = MergedSlots(jobs=(job('SW개발'),))
    result = run(merged, [camp('multi', ['데이터분석', '웹개발', 'SW개발'])])
    rec = result.recommendations[0]
    assert (rec.relation, rec.camp_job, rec.review) == (SAME, 'SW개발', False)


def test_matched_user_job_is_best_pair_then_merge_order():
    merged = MergedSlots(jobs=(job('웹개발'), job('SW개발')))
    rec = run(merged, [camp('x', ['SW개발'])]).recommendations[0]
    assert rec.job.value == 'SW개발' and rec.relation == SAME   # 웹개발과는 CLOSE라 SW개발과의 SAME 쌍


# ---------- 복수 직무 분배 ----------
def test_each_job_gets_a_slot():
    # SW개발 캠프가 산업까지 맞아 단일 정렬이면 3자리를 독식한다
    merged = MergedSlots(jobs=(job('SW개발'), job('품질관리')), industries=(ind('금융'),))
    camps = [camp('sw1', ['SW개발'], ['금융']), camp('sw2', ['SW개발'], ['금융']),
             camp('sw3', ['SW개발'], ['금융']), camp('qa1', ['품질관리'], ['제조'])]
    result = run(merged, camps)
    assert ids(result) == ['sw1', 'sw2', 'qa1']           # 표시 순서는 정렬 키 순 (보장 캠프도 키가 나쁘면 뒤)
    assert [r.guaranteed for r in result.recommendations] == [True, False, True]


def test_no_guarantee_without_a_grade_camp():
    merged = MergedSlots(jobs=(job('SW개발'), job('품질관리')))
    camps = [camp('sw1', ['SW개발']), camp('sw2', ['SW개발']), camp('sw3', ['SW개발']), camp('fam', ['공정기술'])]
    result = run(merged, camps)
    assert ids(result) == ['sw1', 'sw2', 'sw3']
    assert any('품질관리' in line and '보장 없음' in line for line in result.log)


def test_guarantee_skips_camp_already_picked_by_earlier_job():
    # both는 두 직무 모두에 SAME. 앞 직무가 가져가면 뒤 직무는 다음 캠프를 보장받는다
    merged = MergedSlots(jobs=(job('SW개발'), job('품질관리')))
    camps = [camp('both', ['SW개발', '품질관리']), camp('qa', ['품질관리']), camp('sw', ['SW개발']),
             camp('sw_b', ['SW개발'])]
    result = run(merged, camps)
    assert set(ids(result)) == {'both', 'qa', 'sw'}
    assert {r.camp.id for r in result.recommendations if r.guaranteed} == {'both', 'qa'}


def test_only_first_three_jobs_guaranteed():
    merged = MergedSlots(jobs=tuple(job(j) for j in ('SW개발', '품질관리', '인사', '회계')))
    camps = [camp('sw', ['SW개발']), camp('qa', ['품질관리']), camp('hr', ['인사']), camp('acc', ['회계'])]
    assert set(ids(run(merged, camps))) == {'sw', 'qa', 'hr'}


# ---------- 직무 없이 산업만 ----------
def test_industry_only_mode():
    merged = MergedSlots(industries=(ind('금융'),))
    camps = [camp('any', ['인사'], [ANY]), camp('mis', ['인사'], ['제조']),
             camp('fam', ['회계'], ['은행']), camp('match', ['SW개발'], ['금융'])]
    result = run(merged, camps)
    assert ids(result) == ['match', 'fam']
    assert all(r.review and r.job is None for r in result.recommendations)
    assert INDUSTRY_ONLY in result.flags
    assert result.recommendations[1].industry_grade == IndustryGrade.FAMILY
    assert result.recommendations[1].camp_industry == '은행'


def test_industry_only_mode_ignores_camp_type():
    # 직무가 없으면 camp_type이 산업 안의 첫 키가 되므로 쓰지 않는다 (#35). 같은 산업 등급 안은 캠프 ID 순
    merged = MergedSlots(industries=(ind('금융'),), camp_type='EXPERIENCE', help_source=HELP_FROM_BODY)
    camps = [camp('m2', ['인사'], ['금융'], 'EXPERIENCE'), camp('m1', ['회계'], ['금융'], 'EXPLORE'),
             camp('fam', ['SW개발'], ['은행'], 'EXPERIENCE')]
    result = run(merged, camps)
    assert ids(result) == ['m1', 'm2', 'fam']
    assert all(r.help_grade is None for r in result.recommendations)


def test_nothing_to_match():
    assert ids(run(MergedSlots(), [camp('x', ['SW개발'])])) == []


# ---------- 입력 정리 ----------
def test_duplicate_camp_id_used_once():
    merged = MergedSlots(jobs=(job('SW개발'),))
    result = run(merged, [camp('x', ['SW개발']), camp('x', ['SW개발'])])
    assert ids(result) == ['x']


def test_result_is_deterministic_regardless_of_input_order():
    merged = MergedSlots(jobs=(job('SW개발'),), industries=(ind('금융'),))
    camps = [camp('c', ['SW개발'], ['금융']), camp('a', ['웹개발'], [ANY]), camp('b', ['SW개발'], ['금융'])]
    assert ids(run(merged, camps)) == ids(run(merged, list(reversed(camps)))) == ['b', 'c', 'a']


# ---------- 검수 전 캠프의 매칭 값 ----------
def test_pending_review_uses_base_values():
    c = camp_for_matching(id='p', name='가짜 캠프', status=PENDING_REVIEW, is_camp=False,
                          job_ids=('데이터분석',), industry_ids=('금융',), base_job_ids=('SW개발',),
                          base_industry_ids=(ANY,), camp_type='EXPERIENCE')
    assert (c.job_ids, c.industry_ids, c.camp_type) == (('SW개발',), (ANY,), 'EXPERIENCE')


def test_approved_uses_profile_and_drops_non_camp():
    kw = dict(id='p', name='가짜 캠프', job_ids=('데이터분석',), industry_ids=('금융',),
              base_job_ids=('SW개발',), base_industry_ids=(ANY,), camp_type='')
    c = camp_for_matching(status='approved', is_camp=True, **kw)
    assert (c.job_ids, c.industry_ids, c.camp_type) == (('데이터분석',), ('금융',), None)
    assert camp_for_matching(status='auto_approved', is_camp=False, **kw) is None


# ---------- 커밋된 어휘 파일로 ----------
def test_relation_index_from_vocab_file():
    from app.sources.vocab import load_job_relations
    index = build_relation_index(load_job_relations())
    assert job_relation('SW개발', '웹개발', index) == CLOSE      # job_relation_manual.csv의 확정 CLOSE
    assert all(rel in (CLOSE, FAMILY) for rel in index.values())
