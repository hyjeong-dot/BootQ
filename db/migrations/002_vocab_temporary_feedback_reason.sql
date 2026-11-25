-- 002 (#14): API·DB 적재를 구현하며 생긴 스키마 변경 (docs/rules/04_DATABASE.md 4장)

-- 자리표시 직무(jobs.csv의 '임시'). 캠프가 쓰고 있어 어휘에는 넣고, 슬롯필링 선택지에서만 뺀다
ALTER TABLE vocab_job ADD COLUMN temporary boolean NOT NULL DEFAULT false;

-- 파일 순서. 슬롯필링 프롬프트·스키마의 Enum 순서가 평가(파일에서 읽음)와 같아야 같은 프롬프트가 된다
ALTER TABLE vocab_job ADD COLUMN position integer NOT NULL DEFAULT 0;
ALTER TABLE vocab_industry ADD COLUMN position integer NOT NULL DEFAULT 0;

-- 👎 사유는 코드로만 받는다 (docs/specs/10_API_SPEC.md API-003)
ALTER TABLE feedback ADD CONSTRAINT feedback_reason_code_check
    CHECK (reason IN ('job_mismatch', 'industry_mismatch', 'not_needed', 'other'));
