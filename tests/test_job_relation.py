from app.core.job_relation import CLOSE, FAMILY, build_job_relations, pair
from app.core.normalize_v2 import CAMP_TYPES
from app.sources.vocab import load_category_camp_type, load_job_relations
from scripts.build_job_relation import build

FAMILIES = {'SW개발': 'IT', '웹개발': 'IT', '데이터': 'IT', '조종사': '특수', '큐레이터': '특수', '재무': '경영', '회계': '경영'}


def relations_of(auto, manual):
    relations, errors = build_job_relations(FAMILIES, auto, manual)
    return {(r.job_a, r.job_b): (r.relation, r.source) for r in relations}, errors


def test_auto_family_only_for_enabled_families():
    rel, errors = relations_of({'IT'}, [])
    assert not errors
    assert rel == {pair('SW개발', '웹개발'): (FAMILY, 'auto'), pair('SW개발', '데이터'): (FAMILY, 'auto'),
                   pair('웹개발', '데이터'): (FAMILY, 'auto')}


def test_manual_overrides_auto_and_none_removes():
    rel, errors = relations_of({'IT'}, [('웹개발', 'SW개발', CLOSE, ''), ('데이터', '웹개발', 'NONE', '')])
    assert not errors
    assert rel[pair('SW개발', '웹개발')] == (CLOSE, 'manual')
    assert pair('데이터', '웹개발') not in rel


def test_manual_adds_pairs_in_families_without_auto():
    rel, _ = relations_of(set(), [('재무', '회계', CLOSE, '')])
    assert rel == {pair('재무', '회계'): (CLOSE, 'manual')}


def test_manual_errors():
    _, errors = relations_of({'없는대분류'}, [('재무', '없는직무', CLOSE, ''), ('재무', '재무', CLOSE, ''),
                                              ('재무', '회계', 'SAME', ''), ('회계', '재무', CLOSE, ''),
                                              ('재무', '회계', FAMILY, '')])
    assert len(errors) == 5   # 없는 대분류, 없는 직무, 자기 자신, SAME 금지, 순서만 바꾼 중복


def test_committed_job_relation_matches_inputs():
    # data/vocab/job_relation.csv는 생성 파일이다. 입력을 고치고 다시 만들지 않으면 실패한다
    relations, errors = build()
    assert not errors
    assert [(r.job_a, r.job_b, r.relation) for r in relations] == load_job_relations()


def test_category_camp_type_values():
    categories = load_category_camp_type()
    assert all(t in ('', *CAMP_TYPES) for t in categories.values())
    assert categories['자소서'] == 'APPLICATION' and categories['직무'] == 'EXPLORE' and categories['인턴'] == 'EXPERIENCE'
