import pytest

from app.core.industry import ANY, IndustryGrade, build_family_index, industry_grade, shares_family
from app.sources.vocab import load_industries, load_industry_family_pairs


@pytest.fixture(scope='module')
def families():
    return build_family_index(load_industry_family_pairs())


# 계열 테이블 (data/vocab/industry_family.csv)
def test_trade_and_logistics_share_family(families):
    assert shares_family('무역', '유통/물류', families)


def test_logistics_and_commerce_share_family(families):
    assert shares_family('유통/물류', '커머스', families)


def test_trade_and_commerce_do_not_share_family(families):
    # 유통/물류가 두 계열에 걸쳐 있어도 계열은 이어지지 않는다 (A~B, B~C가 A~C를 뜻하지 않음)
    assert not shares_family('무역', '커머스', families)


def test_semiconductor_and_electronics_do_not_share_family(families):
    # 반도체 77개 vs 전자/기계 25개 비대칭이라 평가 전까지 계열에서 제외
    assert not shares_family('반도체', '전자/기계', families)


def test_broadcast_and_culture_performance_do_not_share_family(families):
    assert not shares_family('방송/엔터', '문화/공연', families)
    assert shares_family('방송/엔터', '영화/콘텐츠', families)


def test_logistics_belongs_to_two_families(families):
    assert families['유통/물류'] == {'유통·커머스', '물류·무역'}


def test_family_pairs_use_known_industries():
    known = load_industries()
    assert {i for _, i in load_industry_family_pairs()} <= known


# 등급 판정
def test_grade_order_is_match_family_any_mismatch():
    assert IndustryGrade.MATCH < IndustryGrade.FAMILY < IndustryGrade.ANY < IndustryGrade.MISMATCH


def test_grades(families):
    assert industry_grade(['은행'], ['은행'], families) == IndustryGrade.MATCH
    assert industry_grade(['공기업'], ['정부/공공기관'], families) == IndustryGrade.FAMILY
    assert industry_grade(['은행'], [ANY], families) == IndustryGrade.ANY
    assert industry_grade(['은행'], ['반도체'], families) == IndustryGrade.MISMATCH


def test_trade_user_sees_logistics_camp_as_family_and_commerce_camp_as_mismatch(families):
    assert industry_grade(['무역'], ['유통/물류'], families) == IndustryGrade.FAMILY
    assert industry_grade(['무역'], ['커머스'], families) == IndustryGrade.MISMATCH


def test_best_grade_across_multiple_industries(families):
    # 캠프가 여러 산업에 걸치면 가장 좋은 등급 (예: 금융 IT 공기업)
    assert industry_grade(['IT'], ['금융', 'IT', '공기업'], families) == IndustryGrade.MATCH
    # 유저가 여러 산업을 말해도 마찬가지
    assert industry_grade(['반도체', '통신'], ['IT'], families) == IndustryGrade.FAMILY
    # 구체 산업이 계열이면 ANY보다 위
    assert industry_grade(['통신'], ['IT', ANY], families) == IndustryGrade.FAMILY


def test_empty_user_industry_skips_the_step(families):
    assert industry_grade([], ['IT'], families) is None
    assert industry_grade([ANY], ['IT'], families) is None


# 평가용: 계열을 넣고 빼며 비교할 수 있어야 한다
def test_family_index_is_a_parameter_so_evaluation_can_toggle_a_family():
    base = load_industry_family_pairs()
    without = build_family_index(base)
    with_semi = build_family_index(base + [('전자·반도체', '반도체'), ('전자·반도체', '전자/기계')])
    assert industry_grade(['전자/기계'], ['반도체'], without) == IndustryGrade.MISMATCH
    assert industry_grade(['전자/기계'], ['반도체'], with_semi) == IndustryGrade.FAMILY
