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
| BAT-001 | 캠프 원본 정리 (A단계) | 수동 | 출처 CSV → camp_raw 후보. 공백 정리, 캠프명 해시 ID (`scripts/prepare_camps.py`) | 🔄 |
| BAT-002 | 기준 프로파일 (C단계) | 수동 | 매핑표만으로 새 어휘로 옮긴 규칙 기준선, LLM 없음 (`scripts/build_baseline.py`) | 🔄 |
| BAT-003 | LLM 정규화 (D단계, v2) | 수동 | 기준선 + LLM 추가분 + 수동 보정 + 검수 승인 → camp_profile, 검수 목록 (`scripts/normalize_camps.py`, 상세 2장) | ✅ |
| BAT-004 | 매핑표 검사 | 수동 | 직무·산업·상세분류 매핑표 누락·잉여 검사 (`scripts/check_*_map.py`) | ✅ |
| BAT-005 | 평가 | 수동 | 정답 셋 기준 슬롯·매칭 지표 계산, 3갈래 비교 | 📝 |
| BAT-006 | DB 적재 | 수동 | 어휘·관계·camp_raw·camp_profile 파일 → PostgreSQL | 📝 |

> 현재 BAT-001~003은 파일(`data/derived/`)로 출력한다. DB 도입 후 출력 대상을 DB로 바꿀지(BAT-006과 합칠지)는 04_DATABASE.md 결정 후 정한다.

## 2. 배치 상세 명세

> 새 배치마다 아래 템플릿을 복사해 작성한다.

---

### BAT-001. (배치명)

- **목적**:
- **실행 주기**: (cron 식과 사람이 읽는 설명을 함께. 예: `0 0 18 * * MON-FRI` — 평일 18시)
- **실행 시간대 기준**: (예: Asia/Seoul)
- **상태**: 📝 설계

#### 처리 내용

1. (처리 단계를 순서대로 기술)
2.
3.

#### 대상 데이터

| 입력 | 출력 | 예상 건수 |
|---|---|---|
|  |  |  |

#### 실패 / 예외 처리

- **재시도**: (횟수, 간격)
- **부분 실패 시**: (전체 롤백 / 실패 건만 기록 후 계속)
- **중복 실행 방지**: (락, 실행 이력 확인 등)
- **알림**: (실패 시 알림 방법)

#### 실행 이력 기록
- (로그 위치, 이력 테이블 여부)

#### 비고
- (수동 실행 방법, 소요 시간 예상 등)

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
