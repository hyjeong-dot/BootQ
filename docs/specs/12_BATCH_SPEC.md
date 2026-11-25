# 12. 배치 명세서

> 문서 상태: 산출물 문서 (개발하며 갱신)
> **규칙**: 새 배치/스케줄 작업을 구현하기 전에 반드시 여기에 명세를 먼저 작성하고 사용자 확인을 받은 후 구현한다.
> 배치가 없는 프로젝트라면 이 문서 전체를 ➖ 해당없음 처리한다.
> 사전 기입(2026-11-24): 이 프로젝트의 "오프라인" 처리(캠프 등록 시점의 정규화)가 배치에 해당한다. 이미 있는 스크립트와 설계 메모의 계획을 옮겼다.

## 0. 배치 공통 규칙

### 스케줄러 방식
- 상태: ✅ 결정
- 선택지 예: Spring @Scheduled / Spring Batch / node-cron / OS 스케줄러(작업 스케줄러, cron) / 클라우드 스케줄러
- 결정: 스케줄러 없음 — MVP는 `scripts/`의 CLI를 수동 실행 (관리자 화면 없이 status 컬럼과 스크립트 재실행으로 데모)
- 이유: 데모 규모. 실서비스에서는 출처 동기화 주기를 분리한다(모집기간·상태는 자주 / 캠프명·직무코드가 바뀐 캠프만 재정규화)
- 결정일: 2026-11-24

### 공통 실패 처리
- 상태: ✅ 결정
- 결정:
  - **멱등**: 캠프 내용(캠프명+코드) 해시로 이미 처리한 캠프는 건너뛴다 → 실패 후 같은 명령으로 재실행
  - LLM 호출: 429·5xx·네트워크 오류 최대 3회 재시도(05_AI.md), Groq 하루 한도를 넘으면 다음 날 이어서
  - LLM 호출 기록은 `data/derived/llm_calls.jsonl`
  - DB에 쓰는 배치는 캠프 단위 커밋 (04_DATABASE.md)
  - **알림 없음** — 수동 실행이라 종료 시 콘솔 요약(처리·건너뜀·실패 건수)으로 충분
- 결정일: 2026-11-25

## 1. 배치 목록

> 상태: 📝 설계 / 🔄 개발중 / ✅ 완료 / 🗑 폐기

| ID | 배치명 | 실행 주기 | 설명 | 상태 |
|---|---|---|---|---|
| BAT-001 | 캠프 원본 정리 (A단계) | 수동 | 출처 CSV → camp_raw 후보. 공백 정리, 캠프명 해시 ID (`scripts/prepare_camps.py`, 상세 2장) | ✅ |
| BAT-002 | 기준 프로파일 (C단계) | 수동 | 매핑표만으로 새 어휘로 옮긴 규칙 기준선, LLM 없음 (`scripts/build_baseline.py`, 상세 2장) | ✅ |
| BAT-003 | LLM 정규화 (D단계, v2) | 수동 | 기준선 + LLM 추가분 + 수동 보정 + 검수 승인 → camp_profile, 검수 목록 (`scripts/normalize_camps.py`, 상세 2장) | ✅ |
| BAT-004 | 매핑표 검사 | 수동 | 직무·산업·상세분류 매핑표 누락·잉여 검사 (`scripts/check_*_map.py`) | ✅ |
| BAT-005 | 평가 | 수동 | 정답 셋 기준 슬롯·매칭 지표 계산, 3갈래 비교 (`scripts/evaluate.py`, 상세 2장) | ✅ |
| BAT-006 | DB 적재 | 수동 | 어휘·관계·camp_raw·camp_profile 파일 → PostgreSQL (`scripts/load_db.py`, 상세 2장) | ✅ |
| BAT-007 | 응답 시간 측정 | 수동 | 정답 셋 질문을 떠 있는 API에 등록하고 SSE 결과까지의 전 구간 시간을 잰다 (`scripts/measure_latency.py`, 상세 2장) | ✅ |

> BAT-001~003은 파일(`data/derived/`)로 출력하고, BAT-006이 그 파일을 DB에 옮긴다 (2026-11-26, #14). 정규화 스크립트가 DB에 직접 쓰지 않는 이유: 평가(BAT-005)가 DB 없이 같은 파일을 읽고, 검수가 파일(diff·검수 목록) 단위로 돌기 때문이다. 파일이 원본, DB는 서비스용 적재본.

## 2. 배치 상세 명세

> 새 배치는 아래 항목(목적·주기·처리 내용·대상 데이터·실패 처리·비고)을 같은 형식으로 쓴다.

---

### BAT-001. 캠프 원본 정리 (A단계)

- **목적**: 출처 CSV를 정리해 camp_raw 후보 파일을 만든다 (LLM 없음)
- **실행 주기**: 수동 (출처 CSV가 바뀔 때)
- **실행 시간대 기준**: 해당 없음
- **상태**: ✅ 구현

#### 처리 내용

1. 모든 칸의 앞뒤 공백을 지운다 (같은 값이 공백 차이로 다른 값이 되는 문제)
2. 캠프명에 '삭제'가 들어간 더미 행을 뺀다
3. `source_camp_id`를 캠프명 해시로 만든다 (직무코드는 넣지 않음: 같은 캠프가 코드만 다른 여러 행으로 들어 있어 두 번 추천될 수 있음. 04_DATABASE.md)

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
| `data/raw/`의 캠프 CSV (git 제외) | `data/derived/camp_raw.csv` (git 제외) | 캠프 수백 개 |

#### 실패 / 예외 처리
- 파일만 읽고 써서 재시도 없음. 다시 돌리면 같은 결과

#### 비고
- 실행: `uv run python scripts/prepare_camps.py`

---

### BAT-002. 기준 프로파일 (C단계)

- **목적**: 매핑표만으로 캠프를 새 어휘로 옮긴 규칙 기준선을 만든다 (LLM 없음). BAT-003의 비교 기준이자 평가 ①
- **실행 주기**: 수동 (BAT-001 후, 매핑표가 바뀔 때)
- **실행 시간대 기준**: 해당 없음
- **상태**: ✅ 구현

#### 처리 내용

1. 원래 (대분류, 중분류) → 대표 직무, 원래 산업 → 대표 산업 (`data/private/`의 매핑표)
2. 상세분류는 분류표로 나눠 하위 직무·스킬·산업(산업 성격일 때)에 넣는다. 직무 성격이거나 버린 값은 참고용 칸에만 남긴다
3. 캠프명에 2차전지·이차전지·배터리가 있으면 산업에 `2차전지`를 더한다 (키워드로 정할 수 있는 판단은 규칙으로)
4. 같은 캠프의 여러 행은 값을 합친다. camp_type은 캠프명을 읽어야 해서 비워 둔다 (BAT-003)

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
| `data/derived/camp_raw.csv`, `data/private/` 매핑표 | `data/derived/camp_baseline.csv` (git 제외) | 캠프 수백 개 |

#### 실패 / 예외 처리
- 파일만 읽고 써서 재시도 없음. 매핑표에 없는 값은 BAT-004 검사로 먼저 막는다

#### 비고
- 실행: `uv run python scripts/build_baseline.py`

---

### BAT-003. LLM 정규화 (D단계, v2)

- **목적**: 기준 프로파일(BAT-002)에 캠프명을 읽은 LLM의 추가분을 합치고, 사람의 검수 결과를 반영해 camp_profile 초안을 만든다
- **실행 주기**: 수동 (캠프 추가 시, 정규화 버전·프롬프트 변경 시)
- **실행 시간대 기준**: Asia/Seoul (Groq 하루 한도 집계는 로컬 날짜 기준)
- **상태**: ✅ 구현

#### 처리 내용

1. 기준선·수동 보정(`camp_manual.csv`)·메모(`camp_overrides.csv`)·검수 승인(`camp_approvals.csv`)을 읽는다
2. (캠프 입력 + 시스템 프롬프트 + 버전) 해시와 모델이 이미 처리된 캠프는 건너뛰고, 나머지를 묶음으로 LLM에 보낸다
3. 병합(`app/core/normalize_v2.py`): 수동 보정 > LLM 추가분 > 기준. 결과마다 **결과 해시**를 계산한다 — 기준과 달라질 수 있는 칸(is_camp, job_ids, industry_ids, sub_job)과 산업 제거 제안 여부의 해시
4. status 결정 (위에서부터 먼저 걸리는 것):

   | 조건 | status | 쓰이는 값 |
   |---|---|---|
   | 수동 보정이 있음 | approved | 수동 보정 > LLM > 기준 |
   | 승인 기록이 있고 결과 해시가 같음, decision=accept | approved | 병합 결과 |
   | 승인 기록이 있고 결과 해시가 같음, decision=reject | approved | 기준값 (LLM의 직무·산업·하위직무 추가분 버림. camp_type·skills는 유지) |
   | 기준과 같고 버림·제안·캠프 아님 판정 없음 | auto_approved | 병합 결과 |
   | 그 밖 | pending_review | 매칭에는 기준값만 (승인 전) |

   - 승인은 결과 해시에 묶인다. 다시 돌려 결과가 바뀌면 승인 기록이 맞지 않게 되어 pending_review로 돌아간다
5. 검수 목록 생성 (`data/private/review/v2_diff_review.csv`):
   - 대상: pending_review 전체 + **메모가 있는데 결과가 기준과 같은 캠프**(LLM이 메모를 따르지 않으면 auto_approved가 되어 diff에서 안 보이므로. status는 바꾸지 않고 유형에 `메모 미반영`으로 표시)
   - 칸: 유형(주 직무 교체 / 직무 추가 / 산업 추가 / 교체 시도 버림 / 산업 ANY 제안 / 근거 검증 실패로 버림 / 캠프 아님 / 메모 미반영), 기준·결과 값, 버려진 제안, 실질 변화 없음, 근거, 메모, 결과 해시, 검수 칸(decision, fix_job_ids, fix_industry_ids, fix_sub_job, 검수 메모)
   - 다시 만들 때 같은 캠프·같은 결과 해시의 검수 칸은 보존한다
6. 검수 반영 (`--apply-review`): 검수 목록에서 decision이 accept/reject인 행을 `camp_approvals.csv`에 (source_camp_id, result_hash, decision, reviewed_at, 메모)로 옮긴다. fix·rerun 행은 옮기지 않는다 — 사람이 수동 보정 또는 메모로 반영하고 재실행한 뒤, 새 결과로 다시 검수한다
7. 출력: 초안·diff·검수 목록·산업 제거 제안 목록

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
| `data/derived/camp_baseline.csv`, `data/private/camp_manual.csv`, `camp_overrides.csv`, `camp_approvals.csv` | `data/derived/camp_llm.jsonl`, `llm_calls.jsonl`, `camp_profile_draft.csv`, `camp_diff.csv`, `data/private/review/v2_diff_review.csv`, `data/private/industry_removal_review.csv` | 캠프 수백 개, 검수 대상 수십 개 |

#### 실패 / 예외 처리

- **재시도**: 호출 단위 재시도는 0장 공통 규칙. 묶음이 실패하거나 응답 일부가 빠지면 그 캠프는 저장되지 않고 다음 실행에서 다시 처리된다
- **출력 상한**: 출력 토큰이 상한에 닿으면 뒤쪽 캠프가 빠진다. 묶음 크기 15·출력 상한 3000을 기본으로 쓴다 (25·2500에서 출력 상한에 걸린 묶음이 생겨 바꿈)
- **부분 실패 시**: 실패 건만 남기고 계속. rate_limited·auth·request_too_large는 즉시 멈춤
- **중복 실행 방지**: 해시 기반 멱등 (락 없음)
- **알림**: 없음 (콘솔 요약)

#### 실행 이력 기록
- 호출마다 `llm_calls.jsonl`(모델·버전·캠프 ID·토큰·오류), 캠프마다 `camp_llm.jsonl`(content_hash·batch_id). 검수 판정은 `camp_approvals.csv`

#### 비고
- 실행: `python scripts/normalize_camps.py --batch-size 15 --max-output 3000` → 검수 목록 작성 → `--apply-review` → 수동 보정·메모 반영 후 `--ids`로 해당 캠프만 재실행
- **메모는 필드 형식으로 쓴다**: 예) `main_job='심사·신용평가', add_industries=['금융']. evidence=['기업 심사', '금융공기업']`. 문장형 메모("주 직무 ○○ 검토")는 LLM이 따르지 않는 경우가 있었다
- 하루 예산 가드는 로컬 호출 기록의 오늘 합계를 본다. 키를 바꿔 같은 날 이어 돌릴 때는 `--max-tokens-today`를 (이미 쓴 양 + 새 키 한도)로 준다
- 승인 기록과 검수 목록은 캠프명·원래 코드가 드러나므로 git 제외(`data/private/`)

---

### BAT-005. 평가

- **목적**: 정답 셋 기준으로 슬롯 정확도와 매칭 정확도를 DB·LLM 없이 다시 계산한다 (설계와 지표 정의의 원본: `EVAL.md` "평가 스크립트")
- **실행 주기**: 수동 (매칭 규칙·어휘·정규화 결과·정답 셋이 바뀔 때)
- **실행 시간대 기준**: 해당 없음
- **상태**: ✅ 구현. 3갈래 첫 측정 완료(#16, 결과 `EVAL_RESULTS.md`)

#### 처리 내용

1. 정답 셋, 슬롯(시험 결과 파일 또는 정답 슬롯), 캠프(정규화 산출물, 변형 ①/②), 어휘, 입력 필드 사전을 읽는다
2. 질문마다 `app/core/evaluation.py`: 1차 게이트 → 슬롯 → 입력 필드 사전 변환 → 병합 → 2차 게이트 → 매칭(모집 중 검사 끔). `--recs`면 주어진 추천 목록을 그대로 쓴다
3. 질문별 판정(허용/불허/미판정, ideal)과 지표를 계산한다
4. 결과 파일을 쓰고 콘솔에 요약한다

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
| `eval/answer_set.csv`, `data/derived/slot_trial.jsonl`(또는 정답 슬롯, 또는 ③의 `--recs data/derived/camp_select.jsonl`), `data/derived/camp_profile_draft.csv`, `data/vocab/`, `data/private/`의 입력 필드 사전 | `data/derived/eval/<실행 이름>/recommendations.csv`, `slots.csv`, `summary.json`, `data/derived/eval/blind_pool.csv` | 질문 23개, 캠프 수백 개 |

#### 실패 / 예외 처리

- **재시도**: 없음 (파일만 읽음)
- **부분 실패 시**: 정답 셋에 있는데 슬롯 파일에 없는 질문은 슬롯 없음(추천 없음)으로 처리하고 콘솔에 경고. 정답 셋의 캠프 ID가 캠프 파일에 없으면 경고
- **중복 실행 방지**: 없음 (같은 입력이면 같은 결과, 실행 이름 폴더를 덮어씀. 블라인드 풀링 파일은 합쳐서 다시 씀)
- **알림**: 없음 (콘솔 요약)

#### 실행 이력 기록
- `summary.json`에 실행 설정(변형, 슬롯 출처·해시, 계열 변경, 정답 셋 해시)

#### 비고
- 실행: `uv run python scripts/evaluate.py --variant llm --slots gold`, `--variant rule --slots data/derived/slot_trial.jsonl`, `--add-family 전자·반도체=반도체,전자/기계`
- ③ 추천 만들기: `uv run python scripts/run_camp_select.py --model openai/gpt-oss-120b` (OpenRouter 유료. 먼저 `--ids E01`로 토큰 확인) → `uv run python scripts/evaluate.py --recs data/derived/camp_select.jsonl --name select_llm`
- 결과 폴더는 캠프명이 들어가므로 git 제외. 커밋하는 수치는 캠프명 없이 `EVAL_RESULTS.md`에 적는다
- `summary.json`의 `llm_calls`: 슬롯필링(또는 ③) 호출의 평균 토큰·시간과 시간 중앙값

---

### BAT-006. DB 적재

- **목적**: 어휘·관계 파일과 정규화 산출물을 서비스가 읽는 DB 테이블로 옮긴다. 파일이 원본이고 DB는 적재본이다
- **실행 주기**: 수동 (어휘·정규화 결과가 바뀐 뒤). 실행 후 서버가 떠 있으면 API-004로 어휘 재로드
- **실행 시간대 기준**: 해당 없음
- **상태**: ✅ 구현 (#14)

#### 처리 내용

1. 파일을 읽는다 (`sources/`). `data/private/`의 입력 필드 사전이 없으면(CI·리뷰어 환경) 그 두 테이블은 비우고 경고
2. **어휘**: 8개 테이블을 비우고 다시 넣는다. jobs.csv의 `임시` 직무는 `vocab_job.temporary=true`로 넣는다(캠프가 자리표시 직무로 쓰고 있어 빼면 안 되고, 슬롯필링 선택지에서는 뺀다). 직무·산업은 파일 순서를 `position`에 남긴다 (슬롯필링 프롬프트가 평가와 같아야 해서). 기존 `sources/vocab.py` 함수가 읽는 것과 같은 행만 넣는다 (예: industry_family는 `확정`만)
3. **camp_raw**: 출처 `csv`의 행을 `(source, source_camp_id)`로 upsert. payload = 원본 행 전체의 **배열**(같은 캠프가 직무코드만 다른 여러 행이면 모두), content_hash = ID 칸을 뺀 원본 행들(캠프명+원래 코드)의 해시. 바뀐 행만 `updated_at` 갱신. 파일에 없는 `csv` 캠프는 `active=false` (삭제하지 않음: 추천 기록·피드백이 가리키고 있음)
4. **camp_profile**: 정규화 산출물(`camp_profile_draft.csv`)의 행을 upsert. `content_hash`는 그 시점 camp_raw의 content_hash. camp_raw에 없는 캠프 행은 건너뛰고 경고
5. 검사: 캠프의 직무·산업 값이 어휘에 있는지 (배열이라 FK가 없음). 없으면 그 캠프를 건너뛰고 경고 (정규화 단계의 어휘 검사가 이미 막으므로 정상이면 0건)
6. 콘솔 요약: 테이블별 넣은 행 수, 비활성화·건너뜀·경고 수

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
| `data/vocab/*.csv`, `data/private/job_alias.csv`·`company_industry.csv`, `data/derived/camp_raw.csv`, `data/derived/camp_profile_draft.csv` | 어휘 8개 테이블, `camp_raw`, `camp_profile` | 어휘 수백 행, 캠프 수백 개 |

#### 실패 / 예외 처리

- **재시도**: 없음 (로컬 파일 → 로컬 DB)
- **부분 실패 시**: **전체를 한 트랜잭션으로** — 실패하면 아무것도 바뀌지 않는다. 파일을 그대로 옮기는 작업이라 반쯤 들어간 상태(어휘는 새것, 캠프는 옛것)가 더 위험하다. (정규화의 "캠프 단위 커밋"은 LLM 호출이 있는 BAT-003 규칙)
- **중복 실행 방지**: upsert라 다시 돌려도 같은 결과
- **알림**: 없음 (콘솔 요약)

#### 실행 이력 기록
- 없음 (콘솔 요약). 적재본의 출처 버전은 camp_profile의 `normalizer_version`·`result_hash`로 남는다

#### 비고
- 실행: `uv run python scripts/load_db.py` (기본 `DATABASE_URL`), `--test`면 테스트 DB
- 확인(2026-11-26): 적재 후 DB에서 읽은 어휘가 파일 어휘와 같고, 정답 셋 23문항 × (정답 슬롯·시험 슬롯)의 추천이 DB 경로(후보 SQL + core)와 평가(파일)에서 모두 같았다. 두 번째 실행은 camp_raw 변경 0건
- 사내 DB 연동 시에는 3번만 `load_camps_from_company_db()` 출처로 바뀐다 (02_BACKEND.md 1장: 출처 읽기는 `sources/`)

---

### BAT-007. 응답 시간 측정

- **목적**: 성공 지표 3(글 등록 → 토스트 표시 중앙값 5초 이하, `rules/00_PROJECT.md`)을 전 구간으로 잰다. BAT-005는 LLM 호출 시간만 잰다
- **실행 주기**: 수동 (API·슬롯필링·매칭이 바뀐 뒤)
- **실행 시간대 기준**: 해당 없음
- **상태**: ✅ 구현 (#17, 결과 `EVAL_RESULTS.md`)

#### 처리 내용

1. `eval/answer_set.csv`(재작성 질문)를 읽는다
2. 질문마다: 시계 시작 → `POST /api/posts`(API-001) → SSE(API-002)에서 `recommendation`/`timeout` 이벤트를 받으면 시계 멈춤. 데모 페이지가 하는 호출과 같다 (토스트 그리기 시간은 빠짐)
3. DB `recommendation`에서 서버가 남긴 `total_ms`·`stage_ms`·`status`를 읽어 함께 기록한다
4. 질문 사이에 `--interval`초(기본 25초) 쉰다. Groq 분당 토큰 한도(8K TPM)에 걸리면 재시도 대기가 시간에 섞이기 때문이다 (#16 첫 측정에서 겪음)
5. 결과 파일을 쓰고 콘솔에 요약(전 구간·서버 처리·슬롯필링의 평균·중앙값·최대, 카드 수, 실패 수)한다

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
| `eval/answer_set.csv`, 떠 있는 API(`--base-url`, 기본 `http://127.0.0.1:8000`), 개발 DB | `data/derived/latency/<실행 이름>.jsonl` (질문별 시간·카드 수, 캠프명 없음) | 질문 23개 |

#### 실패 / 예외 처리

- **재시도**: 없음. 오류·timeout도 그대로 기록한다 (측정 대상이므로)
- **부분 실패 시**: 질문 단위로 기록하고 다음 질문으로
- **중복 실행 방지**: 없음. 실행할 때마다 글이 새로 쌓인다 (개발 DB, 재작성 질문만)
- **알림**: 없음 (콘솔 요약)

#### 비고
- 실행: `docker compose up -d --build` 후 `uv run python scripts/measure_latency.py --name e2e-<날짜>`
- 재작성 질문만 LLM에 보낸다 (유저 원문 금지)
