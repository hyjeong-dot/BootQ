-- 001_init: 첫 스키마. 이 파일부터 스키마 원본은 db/migrations/*.sql이다 (docs/rules/04_DATABASE.md 4장).
-- 적용은 scripts/migrate.py가 파일 하나를 트랜잭션 하나로 실행하고 schema_migration에 기록한다.
-- 적용한 뒤에는 이 파일을 고치지 않는다. 바꿀 것은 002_…sql로 추가한다.
-- schema_migration 테이블은 적용 스크립트가 만든다 (이 파일을 적용하기 전에 이력을 볼 수 있어야 하므로).

-- ---------- 어휘 (파일 data/vocab/, data/private/의 적재본. BAT-006이 비우고 다시 넣는다) ----------

CREATE TABLE vocab_job (
    job_id      text        PRIMARY KEY,
    family      text        NOT NULL,                 -- 대분류 (계열 정책 단위)
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vocab_industry (
    industry_id text        PRIMARY KEY,              -- 'ANY' 포함
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE vocab_skill (
    skill_id    text        PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- 산업 → 계열 집합. 한 산업이 여러 계열에 속할 수 있다 (산업 하나 = 계열 하나 구조 금지)
CREATE TABLE industry_family (
    family      text        NOT NULL,
    industry_id text        NOT NULL REFERENCES vocab_industry (industry_id) ON DELETE CASCADE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (family, industry_id)
);

-- 직무 쌍 관계. 자기 자신(SAME)은 저장하지 않는다. 한 방향으로 저장하고 대칭으로 읽는다
CREATE TABLE job_relation (
    job_a       text        NOT NULL REFERENCES vocab_job (job_id) ON DELETE CASCADE,
    job_b       text        NOT NULL REFERENCES vocab_job (job_id) ON DELETE CASCADE,
    relation    text        NOT NULL CHECK (relation IN ('CLOSE', 'FAMILY')),
    source      text        NOT NULL CHECK (source IN ('auto', 'manual')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (job_a, job_b),
    CHECK (job_a <> job_b)
);

-- 유저 target_job 자유 표기 → 대표 직무(+산업). job_ids가 빈 배열이면 "본문으로 판단"
CREATE TABLE job_alias (
    user_term   text        PRIMARY KEY,
    job_ids     text[]      NOT NULL DEFAULT '{}',
    industry_id text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- 유저 target_company → 산업 (여러 개 가능). 빈 배열 = 회사 아님·판단 불가
CREATE TABLE company_industry (
    company      text        PRIMARY KEY,
    industry_ids text[]      NOT NULL DEFAULT '{}',
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- question_category → camp_type 기본값. NULL = 선호 없음
CREATE TABLE category_camp_type (
    category    text        PRIMARY KEY,
    camp_type   text        CHECK (camp_type IN ('EXPLORE', 'EXPERIENCE', 'APPLICATION')),
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---------- 캠프 ----------

-- 출처 원본 복제. 매칭은 이 테이블이 아니라 camp_profile을 본다
CREATE TABLE camp_raw (
    source          text        NOT NULL,             -- 'csv', 나중엔 사내 DB
    source_camp_id  text        NOT NULL,             -- CSV는 캠프명 해시 (직무코드 제외)
    name            text        NOT NULL,
    payload         jsonb       NOT NULL,             -- 원본 행 전체
    content_hash    text        NOT NULL,             -- 캠프명+원래 코드 해시. 바뀐 캠프만 재정규화
    active          boolean     NOT NULL DEFAULT true, -- 출처에서 사라지면 false
    recruit_start   date,
    recruit_end     date,                             -- NULL이면 모집 중으로 본다 (매칭 0단계)
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_camp_id),
    CHECK (recruit_start IS NULL OR recruit_end IS NULL OR recruit_start <= recruit_end)
);

-- 정규화 결과. 결과 칸과 기준(base_*) 칸을 둘 다 둔다.
-- 어느 칸으로 매칭할지(pending_review면 기준 칸)는 core.models.camp_for_matching이 정한다
CREATE TABLE camp_profile (
    source                     text        NOT NULL,
    source_camp_id             text        NOT NULL,
    is_camp                    boolean     NOT NULL DEFAULT true,
    job_ids                    text[]      NOT NULL DEFAULT '{}',   -- 첫 값이 주 직무
    sub_job                    text,
    industry_ids               text[]      NOT NULL DEFAULT '{}',   -- 산업무관은 {ANY}
    skills                     text[]      NOT NULL DEFAULT '{}',
    tags                       text[]      NOT NULL DEFAULT '{}',   -- 표시용, 매칭에 쓰지 않음
    camp_type                  text        CHECK (camp_type IN ('EXPLORE', 'EXPERIENCE', 'APPLICATION')),
    base_job_ids               text[]      NOT NULL DEFAULT '{}',
    base_industry_ids          text[]      NOT NULL DEFAULT '{}',
    base_sub_jobs              text[]      NOT NULL DEFAULT '{}',
    base_skills                text[]      NOT NULL DEFAULT '{}',
    remove_industry_suggested  boolean     NOT NULL DEFAULT false,
    evidence                   jsonb       NOT NULL DEFAULT '[]',
    status                     text        NOT NULL CHECK (status IN ('auto_approved', 'pending_review', 'approved')),
    normalizer_version         text        NOT NULL,
    content_hash               text        NOT NULL,              -- 이 결과를 만든 camp_raw.content_hash
    result_hash                text        NOT NULL,              -- 검수 승인이 묶이는 해시
    created_at                 timestamptz NOT NULL DEFAULT now(),
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, source_camp_id),
    FOREIGN KEY (source, source_camp_id) REFERENCES camp_raw (source, source_camp_id) ON DELETE CASCADE
);

-- ---------- 요청 ----------

-- 유저 글. 데모·테스트에는 재작성 샘플만. 본문·제목은 로그에 남기지 않는다
CREATE TABLE post (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    title           text        NOT NULL,
    content         text        NOT NULL,
    category        text        NOT NULL DEFAULT '',
    category_group  text        NOT NULL DEFAULT '',
    target_job      text        NOT NULL DEFAULT '',  -- 입력 필드 원문 ('모든 직무' 포함)
    target_company  text        NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- 추천 처리 1회. 게이트 종료·결과 0개·LLM 오류도 행이 남는다
CREATE TABLE recommendation (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id            uuid        NOT NULL UNIQUE REFERENCES post (id) ON DELETE CASCADE,
    status             text        NOT NULL DEFAULT 'processing' CHECK (status IN ('processing', 'done', 'failed')),
    end_reason         text,                          -- 추천 없이 끝난 이유
    slots              jsonb,                         -- 슬롯필링 원본 출력
    merged             jsonb,                         -- 병합 결과
    flags              text[]      NOT NULL DEFAULT '{}',
    error_code         text,
    model              text,
    prompt_tokens      integer     CHECK (prompt_tokens >= 0),
    completion_tokens  integer     CHECK (completion_tokens >= 0),
    stage_ms           jsonb       NOT NULL DEFAULT '{}',
    total_ms           integer     CHECK (total_ms >= 0),
    created_at         timestamptz NOT NULL DEFAULT now(),
    completed_at       timestamptz,
    CHECK ((status = 'processing') = (completed_at IS NULL)),
    CHECK (status <> 'failed' OR error_code IS NOT NULL)
);

-- 토스트에 보여준 카드 한 장
CREATE TABLE recommendation_item (
    recommendation_id  uuid        NOT NULL REFERENCES recommendation (id) ON DELETE CASCADE,
    rank               smallint    NOT NULL CHECK (rank BETWEEN 1 AND 3),
    source             text        NOT NULL,
    source_camp_id     text        NOT NULL,
    job_id             text,                          -- 맞춘 유저 직무 (산업만 매칭이면 NULL)
    camp_job_id        text,
    relation           text        CHECK (relation IN ('SAME', 'CLOSE', 'FAMILY')),
    industry_id        text,
    camp_industry_id   text,
    industry_grade     text,                          -- core IndustryGrade 이름
    help_grade         text,                          -- core HelpGrade 이름
    review             boolean     NOT NULL DEFAULT false,
    guaranteed         boolean     NOT NULL DEFAULT false,
    reason             text        NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (recommendation_id, rank),
    UNIQUE (recommendation_id, source, source_camp_id),
    UNIQUE (recommendation_id, rank, source, source_camp_id),   -- feedback 복합 FK 대상
    FOREIGN KEY (source, source_camp_id) REFERENCES camp_raw (source, source_camp_id)
);

CREATE INDEX recommendation_item_camp_idx ON recommendation_item (source, source_camp_id);

-- 카드별 👍/👎. 덧붙이기만 한다 (최신 created_at이 현재 의견)
CREATE TABLE feedback (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id  uuid        NOT NULL,
    rank               smallint    NOT NULL,
    source             text        NOT NULL,
    source_camp_id     text        NOT NULL,
    vote               text        NOT NULL CHECK (vote IN ('up', 'down')),
    reason             text        CHECK (vote = 'down' OR reason IS NULL),
    created_at         timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (recommendation_id, rank, source, source_camp_id)
        REFERENCES recommendation_item (recommendation_id, rank, source, source_camp_id) ON DELETE CASCADE
);

CREATE INDEX feedback_card_idx ON feedback (recommendation_id, rank);
