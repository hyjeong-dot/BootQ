"""카드 표시용 해시태그 (API-002 cards[].tags, core.models.camp_hashtags). 값은 모두 가짜."""
from app.core.models import camp_hashtags


def tags(status='auto_approved', jobs=('마케팅', '영업'), inds=('식품',), skills=(), disp=(),
         b_jobs=('기준직무',), b_inds=('기준산업',), b_skills=('기준스킬',), **kw):
    return camp_hashtags(status=status, job_ids=jobs, industry_ids=inds, skills=skills, tags=disp,
                         base_job_ids=b_jobs, base_industry_ids=b_inds, base_skills=b_skills, **kw)


def test_order_primary_job_industry_skill_tag():
    assert tags(skills=('SQL',), disp=('이커머스',)) == ('마케팅', '식품', 'SQL', '이커머스')


def test_any_industry_dropped_and_duplicates_removed():
    assert tags(inds=('ANY',), skills=('마케팅', 'SQL')) == ('마케팅', 'SQL')


def test_limit():
    assert tags(inds=('a', 'b', 'c'), skills=('d',)) == ('마케팅', 'a', 'b', 'c')
    assert tags(inds=('a', 'b'), limit=2) == ('마케팅', 'a')


def test_pending_review_uses_base_columns_without_display_tags():
    assert tags(status='pending_review', disp=('이커머스',)) == ('기준직무', '기준산업', '기준스킬')


def test_empty():
    assert tags(jobs=(), inds=()) == ()
