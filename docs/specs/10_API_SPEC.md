# 10. API 명세서

> 문서 상태: 산출물 문서 (개발하며 갱신)
> **규칙**: 새 API를 구현하기 전에 반드시 여기에 명세를 먼저 작성하고 사용자 확인을 받은 후 구현한다.
> 공통 응답 포맷·에러 규약은 `rules/02_BACKEND.md`를 따른다. 여기에는 개별 API만 기록한다.

## 0. 문서 원본(source of truth) 규칙

이 문서의 역할은 **구현 전 설계 계약**이다. 문서-코드 불일치를 막기 위해 다음을 따른다.

### 자동 생성 문서 도입 여부
- 상태: ✅ 결정
- 선택지: Springdoc(Swagger UI) / Spring REST Docs / NestJS Swagger 모듈 / FastAPI 기본 제공 / 도입 안 함
- 결정: **FastAPI 기본 제공 (`/docs`)**. 구현 완료 후 상세 명세의 원본은 `/docs`. 단 **SSE 이벤트 형식은 `/docs`에 나오지 않으므로 이 문서(API-002)에 계속 유지**한다
- 결정일: 2026-11-25

### 도입 후 운영 방식
- 자동 생성 문서를 도입한 시점부터 **상세 명세(파라미터·응답 필드)의 원본은 자동 생성 문서(코드)**다.
- 이 문서에는 **1장 API 목록과 API별 설계 의도·정책**(인증, 페이징, 멱등성 등)만 유지하고, 2장 상세 명세는 "구현 완료 후 자동 문서 참조"로 표기한다.
- 자동 생성 문서를 도입하지 않는 프로젝트는 이 문서가 끝까지 원본이며, API 변경 시 같은 작업 안에서 갱신한다.

## 1. API 목록

> 상태: 📝 설계 / 🔄 개발중 / ✅ 완료 / 🗑 폐기
> 인증은 모두 불필요 (02_BACKEND.md 3장: 인증 없음, 서버는 127.0.0.1에만 노출)

| ID | 메서드 | URL | 이름 | 인증 | 상태 |
|---|---|---|---|---|---|
| API-001 | POST | `/api/posts` | 글 등록 — 저장 후 백그라운드 추천 시작 | 불필요 | ✅ |
| API-002 | GET | `/api/posts/{post_id}/recommendations/stream` | 추천 결과 수신 (SSE, DB에 저장된 결과를 읽어 전송) | 불필요 | ✅ |
| API-003 | POST | `/api/recommendations/{rec_id}/feedback` | 카드별 피드백 (캠프, 순위, 👍/👎, 👎 사유 코드) | 불필요 | ✅ |
| API-004 | POST | `/api/admin/vocab/reload` | 어휘·관계 재로드 (DB 적재 후) | 불필요 | ✅ |

> 사전 기입(2026-11-24): 기존 설계 메모에 나온 엔드포인트만 목록으로 옮겼다. 상세 명세는 2026-11-26(#14) 작성·구현.
> 구현: `app/routers/`(posts, recommendations, admin), `app/services/`(recommend, feedback, vocab), `app/repositories/`(recommendations, camps, vocab), 조립 `app/main.py`. 통합 테스트 `tests/test_api.py`

## 2. API 상세 명세

> 구현 완료 후 요청·응답 필드의 원본은 `/docs`다 (0장). SSE 이벤트 형식(API-002)은 `/docs`에 나오지 않아 이 문서가 원본으로 남는다.
> 에러 형식은 모두 `{"error": {"code": "...", "message": "..."}}` (02_BACKEND.md 2장).

### 공통: 서버가 메모리에 들고 있는 것

- 서버 시작 시 DB에서 어휘(직무·산업·계열·직무 관계·입력 필드 사전·category 기본값)를 읽어 메모리에 둔다. 캠프는 요청마다 SQL로 후보만 읽는다 (캠프는 자주 바뀌고, 어휘는 적재 때만 바뀐다)
- 어휘가 비어 있으면(DB 적재 전) 서버는 뜨지만 추천은 모두 `failed`(`vocab_empty`)로 끝난다

---

### API-001. 글 등록

- **메서드 / URL**: `POST /api/posts`
- **설명**: 글을 저장하고 recommendation 행을 `processing`으로 만든 뒤 바로 응답한다. 추천은 백그라운드(FastAPI BackgroundTasks)에서 만든다
- **인증**: 불필요
- **연관 화면**: SCR-001
- **상태**: ✅ 구현 (요청·응답 필드의 원본은 `/docs`)

#### 요청

**Request Body**

```json
{
  "title": "마케팅 직무로 가고 싶은데 뭘 준비해야 할까요",
  "content": "본문…",
  "category": "직무",
  "category_group": "취업 고민",
  "target_job": "모든 직무",
  "target_company": "모든 회사"
}
```

| 필드 | 타입 | 필수 | 제약 | 설명 |
|---|---|---|---|---|
| title | string | O | 0~200자 | 빈 문자열 허용 (제목·본문이 모두 비면 게이트 1차가 `empty_post`로 끝냄) |
| content | string | O | 0~5,000자 | 슬롯필링 입력 토큰 상한 (Groq 분당 8K 토큰) |
| category | string | X | 0~50자, 기본 `""` | question_category |
| category_group | string | X | 0~50자, 기본 `""` | 게이트 1차 (`랜선 사수`면 종료) |
| target_job | string | X | 0~100자, 기본 `""` | 희망 직무 입력 필드 원문 |
| target_company | string | X | 0~100자, 기본 `""` | 목표 회사 입력 필드 원문 |

#### 응답

**성공 (201)**

```json
{ "post_id": "uuid", "recommendation_id": "uuid", "status": "processing" }
```

**에러**

| HTTP | 에러 코드 | 발생 조건 |
|---|---|---|
| 400 | validation_error | 필드 누락·타입·길이 위반 (FastAPI 기본 422를 400으로) |
| 500 | internal_error | DB 저장 실패 등 |

#### 비고
- LLM 오류는 HTTP 오류가 아니다. 글 등록은 201로 응답하고 recommendation에 오류코드가 남는다
- 멱등성 없음 (같은 글을 두 번 보내면 글 두 개)
- 백그라운드 처리 순서와 기록: 아래 "추천 처리 (백그라운드)"

---

### 추천 처리 (백그라운드, API-001이 시작)

`app/services/recommend.py`. 단계마다 처리시간을 recorder가 모아 `recommendation.stage_ms`에 남긴다. LLM 호출 중에는 트랜잭션을 열지 않는다 (04_DATABASE.md 2장).

| 단계 | 하는 일 | 끝나는 경우 (status / end_reason 또는 error_code) |
|---|---|---|
| gate1 | `core.gate.gate_before_slots` | done / `empty_post`, `off_target_group` |
| field | 입력 필드 사전 변환 (`job_field_hint`, `company_field_hint`) | |
| slot_filling | `services.slot_filling.fill_slots`를 `asyncio.to_thread`로 (타임아웃 15초·재시도 1회) | failed / LLM·파싱 오류코드 (`rate_limited`, `slot_parse_error` …) |
| merge | `core.merge.merge` | |
| gate2 | `core.gate.gate_after_merge` | done / `no_signal` |
| candidates | SQL로 후보 캠프 조회 (아래) | |
| match | `core.matching.match` (모집 중 검사는 SQL이 이미 했으므로 core에는 모두 모집 중으로 넘김) | done / `no_candidates` (캠프 부족 수요) |
| reason | `core.reason.build_reason` 카드마다 | |
| save | recommendation 갱신 + recommendation_item 1~3행을 **한 트랜잭션**으로 | done |

- 예상 못 한 예외는 잡아서 failed / `internal_error`로 남긴다 (BackgroundTasks의 예외는 HTTP로 전달되지 않음). 로그에는 rec_id와 예외 종류만, 글 내용은 남기지 않는다
- 저장하는 기록: `slots`(슬롯필링 결과 — 값·발췌·근거·버린 값 로그), `merged`(병합 후보와 출처·플래그·로그), `flags`(병합 플래그 ∪ 매칭 플래그), `model`, `prompt_tokens`/`completion_tokens`, `stage_ms`, `total_ms`
- **후보 조회 SQL** (02_BACKEND.md 5장 "후보 조회는 SQL"): 활성(`active`) + 모집 중(`recruit_start`·`recruit_end`가 NULL이거나 오늘(Asia/Seoul)이 그 사이) + 아래 집합과 겹치는 캠프
  - 직무가 있으면: 유저 직무 ∪ job_relation으로 이어진 직무(CLOSE·FAMILY) — `core.matching.candidate_job_ids`
  - 산업만 매칭이면: 유저 산업 ∪ 같은 계열 산업 — `core.matching.candidate_industry_ids`
  - 겹침 검사는 결과 칸과 기준 칸(`base_*`)을 **둘 다** 본다(`job_ids && $1 OR base_job_ids && $1`). 넓게 거른 뒤 어느 칸으로 매칭할지는 `core.models.camp_for_matching`이 정한다 (pending_review 규칙을 SQL에 다시 쓰지 않기 위해)

---

### API-002. 추천 결과 수신 (SSE)

- **메서드 / URL**: `GET /api/posts/{post_id}/recommendations/stream`
- **설명**: 그 글의 recommendation 행을 **0.5초마다** 읽다가 `processing`이 아니게 되면 결과 이벤트 하나를 보내고 연결을 닫는다. 결과는 DB에서 읽으므로 다시 접속해도 같은 결과를 받는다
- **인증**: 불필요
- **연관 화면**: SCR-001
- **상태**: ✅ 구현 (요청·응답 필드의 원본은 `/docs`)

#### 요청

| 이름 | 위치 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| post_id | path | uuid | O | API-001의 post_id |

#### 응답

**성공 (200, `Content-Type: text/event-stream`)** — 이벤트는 아래 둘 중 **하나만** 오고 연결이 닫힌다

```
event: recommendation
data: {"recommendation_id": "uuid", "status": "done", "cards": [
        {"rank": 1, "camp_id": "fffcfc1ae457", "camp_name": "가짜 캠프명", "reason": "글에 쓴 '마케팅'에 맞춘 마케팅 캠프예요.", "review": false,
         "tags": ["마케팅", "식품"], "recruit_start": null, "recruit_end": null}
      ]}

event: timeout
data: {"recommendation_id": "uuid"}
```

| 필드 | 설명 |
|---|---|
| status | `done` 또는 `failed` |
| cards | 0~3장, rank 순. **비어 있으면 토스트를 띄우지 않는다** (추천 없음·게이트 종료·오류 모두 같음. end_reason·error_code는 보내지 않는다 — 화면에는 차이가 없고 로그·DB에서 본다) |
| cards[].camp_id | 캠프 ID (`source_camp_id`). 피드백 때 그대로 보낸다 |
| cards[].review | 리뷰 플래그 (B등급·산업만 매칭). 데모 화면은 안내 문구를 붙인다 (SCR-001) |
| cards[].tags | 표시용 해시태그 (`#` 없이) 0~4개. 순서: 캠프 직무 → 산업(ANY 제외) → 스킬 → 표시 태그, 중복 제거. 대표 어휘 이름만 쓴다. 고르는 규칙은 `core.models.camp_hashtags` (검수 전 캠프는 기준 칸). 결과를 읽을 때 현재 camp_profile에서 만든다 (2026-11-26, #15) |
| cards[].recruit_start / recruit_end | 모집기간 `YYYY-MM-DD` 또는 `null` (camp_raw). 지금 데이터에는 모집기간이 없어 모두 `null` → 화면은 "모집기간 정보 없음" (2026-11-26, #15) |

- `timeout`: 45초 동안 `processing`이면 보낸다 (슬롯필링 최악 약 30초 + 여유). 처리는 계속되므로 다시 접속하면 결과를 받을 수 있다
- keep-alive: 15초마다 주석 줄(`: ping`)을 보낸다

**에러** (스트림을 열기 전에 판단)

| HTTP | 에러 코드 | 발생 조건 |
|---|---|---|
| 400 | validation_error | post_id가 uuid가 아님 |
| 404 | not_found | 글이 없음 |

#### 비고
- 폴링을 고른 이유: 동시 1명 로컬 데모라 0.5초 SELECT 부하는 무시할 수 있고, 구현·설명이 가장 단순하다. 대안 LISTEN/NOTIFY는 지연이 없고 서버가 여러 대여도 되지만 연결 관리가 늘어난다 (2026-11-26)

---

### API-003. 카드별 피드백

- **메서드 / URL**: `POST /api/recommendations/{rec_id}/feedback`
- **설명**: 보여준 카드 하나에 👍/👎를 남긴다. 덧붙이기만 한다(같은 카드에 여러 번 누르면 최신이 현재 의견)
- **인증**: 불필요 (rec_id만 맞으면 허용, 02_BACKEND.md 3장)
- **연관 화면**: SCR-001
- **상태**: ✅ 구현 (요청·응답 필드의 원본은 `/docs`)

#### 요청

| 이름 | 위치 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| rec_id | path | uuid | O | API-002의 recommendation_id |

```json
{ "rank": 1, "camp_id": "fffcfc1ae457", "vote": "down", "reason": "job_mismatch" }
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| rank | int | O | 1~3 |
| camp_id | string | O | 그 순위 카드의 camp_id와 같아야 한다 (화면이 다른 카드에 피드백을 붙이는 실수를 막음) |
| vote | string | O | `up` / `down` |
| reason | string | X | `vote=down`일 때만. 코드: `job_mismatch`(직무가 달라요) / `industry_mismatch`(분야가 달라요) / `not_needed`(지금 필요한 도움이 아니에요) / `other`(기타) |

#### 응답

**성공 (201)**

```json
{ "feedback_id": "uuid" }
```

**에러**

| HTTP | 에러 코드 | 발생 조건 |
|---|---|---|
| 400 | validation_error | 형식 위반, `up`에 reason, 모르는 reason 코드, camp_id가 그 순위 카드와 다름 |
| 404 | not_found | rec_id가 없거나 그 순위 카드가 없음 |

#### 비고
- 사유를 코드로 받는 이유: 매칭 근거(recommendation_item의 relation·industry_grade)와 바로 교차 분석한다 (인턴십 프로젝트에서 "1순위 캠프의 직무가 슬롯 직무와 다름"이 👎를 잘 예측했음). 자유 입력은 받지 않는다 (2026-11-26)

---

### API-004. 어휘 재로드

- **메서드 / URL**: `POST /api/admin/vocab/reload`
- **설명**: DB 적재(BAT-006) 후 서버를 다시 띄우지 않고 메모리의 어휘를 다시 읽는다
- **인증**: 불필요 (127.0.0.1에만 노출)
- **상태**: ✅ 구현 (요청·응답 필드의 원본은 `/docs`)

#### 요청
Request Body 없음

#### 응답

**성공 (200)** — 읽은 개수

```json
{ "jobs": 0, "industries": 0, "industry_families": 0, "job_relations": 0, "job_aliases": 0, "companies": 0, "categories": 0 }
```

**에러**

| HTTP | 에러 코드 | 발생 조건 |
|---|---|---|
| 500 | internal_error | DB 읽기 실패 (기존 메모리 어휘를 그대로 유지) |
