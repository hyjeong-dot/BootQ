# 02. 백엔드 설계 규칙

> 문서 상태: ✅ 완료 (2026-11-25)
> 사전 기입(2026-11-24): 기존 설계 메모에서 정해진 내용을 ✅로 옮겼다. ❓ 항목의 "추천"은 확인 전이다.

## 1. 아키텍처

### 아키텍처 스타일
- 상태: ✅ 결정
- 선택지:
  - **레이어드** — 단순, 혼자·소규모에 적합
  - **헥사고날(포트&어댑터)** — 협업·테스트 용이, 초기 비용 있음
  - **모듈러 모놀리스** — 도메인별 모듈 분리, 확장 대비
  - **멀티모듈** — 협업 시 모듈 단위 분담 가능
- 결정: **레이어드 + 순수 함수 코어 (functional core, imperative shell)**. 헥사고날은 쓰지 않는다.
- 이유:
  - 이 프로젝트는 단계가 순서대로 이어지는 파이프라인이고 Python이다. Port 계층 대신 순수 함수와 입출력 경계로 도메인을 격리한다.
  - 경계는 **실제로 바뀌는 곳(LLM 공급자, 캠프 데이터 출처)에만** 둔다.
  - 핵심 목적: 평가 스크립트가 DB·LLM 없이 `core.matching`을 직접 호출한다 (고정된 슬롯 JSON + 고정 캠프 데이터로 Hit@3 재계산).
  - 검토한 대안: 레이어드 단독(매칭 로직이 DB·LLM과 섞여 평가 재계산이 어려움), 헥사고날(파이프라인 규모에 비해 Port 계층 비용이 큼)
  - 전환 기준: 입출력 대상이 늘어 오케스트레이터가 감당하기 어려워지면 그 지점에 경계를 추가한다.
- 결정일: 2026-11-24

### 패키지 / 모듈 구조
- 상태: ✅ 결정
- 결정:
```
app/
├── routers/        FastAPI 엔드포인트 (글 등록, SSE, 피드백)
├── services/       오케스트레이션: DB 조회, LLM 호출, 단계 연결, 오류·측정 기록
├── repositories/   SQL 직접 작성, dataclass 반환 (ORM 없음)
├── sources/        캠프 출처·어휘 파일 읽기: load_camps_from_csv() → list[RawCamp]
├── llm/            LLMClient Protocol + groq.py, openrouter.py
├── core/           순수 함수: models, gate, merge, matching, reason (+ industry, job_relation, normalize_v2, slot_filling)
├── config.py       .env 읽기, 공급자별 모델 선택
└── main.py         조립, 설정으로 LLM·출처 선택
scripts/   정규화·검사·평가 CLI
prompts/   프롬프트 본문(*.md). 읽기는 sources/, 조립은 core/ (05_AI.md)
eval/      정답 셋
data/      vocab(커밋) / private·derived·raw(git 제외)
frontend/  데모 페이지
```
  - 규칙:
    - **`core/`는 repositories, llm, sources, DB 드라이버, HTTP 클라이언트를 import하지 않는다.** 구조가 강제하지 않으므로 이를 검사하는 테스트를 둔다.
    - 오케스트레이터 비대화 방지: 단계별 측정·오류 처리는 작은 헬퍼로 감싸고, 기록은 recorder 하나에 모은다.
    - 피드백·검수 상태 변경 같은 단순 CRUD는 일반 routers/services/repositories로.
    - vocab·job_relation은 서버 시작 시 메모리 로드, 정규화 실행 후 갱신 API로 재로드.
  - 현재 구현된 것: `config.py`, `core/`(industry, job_relation, normalize, normalize_v2, slot_filling), `llm/`, `services/slot_filling.py`(동기 호출 함수), `sources/`(vocab, prompts, qna). 나머지는 미구현.
- 결정일: 2026-11-24

## 2. API 설계 규칙

### API 스타일
- 상태: ✅ 결정
- 선택지: REST / GraphQL / gRPC / 혼합
- 결정: REST(JSON) + SSE(추천 결과 전달)
- 이유: 엔드포인트가 글 등록·피드백·결과 수신 몇 개뿐이다. 추천은 글 등록 후 백그라운드에서 만들어지므로 SSE로 밀어준다. SSE는 **DB에 저장된 추천 결과를 읽어 전송**한다(재접속 시에도 결과를 받을 수 있게).
- 결정일: 2026-11-24

### URL / 네이밍 규칙
- 상태: ✅ 결정
- 결정: `/api/{복수형 리소스}`, 케밥케이스, **버저닝 없음**. 운영 API는 `/api/admin/` 아래
```
POST /api/posts
GET  /api/posts/{post_id}/recommendations/stream   (SSE)
POST /api/recommendations/{rec_id}/feedback
POST /api/admin/vocab/reload
```
- 이유: 데모 단일 클라이언트라 호환성 관리 대상이 없음
- 결정일: 2026-11-25

### 공통 응답 포맷
- 상태: ✅ 결정
- 결정: **감싸지 않고 리소스를 그대로 반환** (FastAPI 기본 + Pydantic 응답 모델). 에러만 아래 에러 규약 형식
- 이유: `/docs` 자동 문서와 그대로 맞고, 프론트 TS 타입도 단순
- 결정일: 2026-11-25

### 에러 응답 규약
- 상태: ✅ 결정
- 결정: `{"error": {"code": "...", "message": "..."}}` + HTTP 상태코드
  - 400 `validation_error` (FastAPI 기본 422도 이 형식·상태로 바꾼다), 404 `not_found`, 500 `internal_error`
  - LLM 오류는 HTTP 오류가 아니다: 글 등록은 성공으로 응답하고, recommendation 레코드에 오류코드를 남긴다 (SSE로는 "추천 없음"과 같게 토스트 미표시)
- 결정일: 2026-11-25

## 3. 인증 / 인가

### 인증 방식
- 상태: ✅ 결정
- 선택지: 없음(개인 도구) / 세션 / JWT / OAuth2 소셜 로그인 / API Key
- 결정: **없음**
- 이유: 데모·평가용 로컬 실행(동시 1명). 실서비스에서는 커뮤니티 서비스의 로그인을 그대로 쓴다고 가정하고 한계로 문서화
- 결정일: 2026-11-25

### 인가(권한) 모델
- 상태: ✅ 결정
- 선택지: 없음 / 역할 기반(RBAC) / 리소스 소유자 검증
- 결정: **없음. 대신 서버는 localhost에만 노출** — Docker Compose 포트를 `127.0.0.1:{포트}:{포트}`로 게시 (컨테이너 안에서는 0.0.0.0 바인딩). 운영 API(`/api/admin/*`)를 포함해 로컬에서만 접근. 피드백은 rec_id만 맞으면 허용
- 결정일: 2026-11-25

## 4. 공통 처리 규칙

### 예외 처리 전략
- 상태: ✅ 결정
- 결정:
  - LLM 공급자 오류는 예외가 아니라 공통 반환 타입의 `error_code`로 돌려준다 (rate_limited, request_too_large, auth, bad_request, server_error, network, empty_response)
  - 파이프라인 중간 실패 시 성공한 단계 결과(예: 슬롯)는 오류코드와 함께 저장한다
  - 추천 0개 또는 게이트 종료는 오류가 아니라 정상 종료(토스트 없음, 로그만)
  - **전역 예외 핸들러 + 작은 예외 계층**: `AppError(code, status)` 하나와 `NotFoundError` 정도만 둔다. 전역 핸들러가 에러 규약 형식으로 변환하고, 예상 못 한 예외는 500 `internal_error`
  - 백그라운드 작업은 예외를 잡아 recommendation 레코드에 오류코드로 기록한다 (BackgroundTasks의 예외는 HTTP 응답으로 전달되지 않으므로)
- 결정일: 2026-11-25

### 로깅 규칙
- 상태: ✅ 결정
- 결정:
  - 요청마다 단계별 처리시간·토큰·오류코드를 recorder 하나로 모아 recommendation 레코드에 저장. 결과 0개는 "캠프 부족 수요"로 기록
  - 애플리케이션 로그: 표준 `logging`, 기본 INFO, **JSON 구조화 로그**(한 줄에 JSON 하나)로 표준 출력
  - **유저 글 본문·제목은 로그에 남기지 않는다.** post_id, rec_id 등 ID만
- 결정일: 2026-11-25

### 환경설정 / 시크릿 관리
- 상태: ✅ 결정
- 선택지: .env + gitignore / 프로파일 분리(application-dev.yml 등) / 환경변수
- 결정: `.env` + `.gitignore`, 형식은 `.env.example`로 공유. 이미 설정된 환경 변수는 덮어쓰지 않는다. 모델 선택 우선순위: `--model` 옵션 > `.env`(GROQ_MODEL, OPENROUTER_MODEL) > 코드 기본값
- 결정일: 2026-11-24

### 유효성 검증 위치
- 상태: ✅ 결정
- 선택지: 컨트롤러(DTO) / 도메인 / 양쪽
- 결정: **양쪽** — 요청 입력은 라우터의 Pydantic 모델, LLM 출력은 JSON 스키마로 강제한 뒤 core의 순수 함수가 다시 검증 (vocab에 있는 값인지, 근거 구절이 원문에 실제로 있는지)
- 이유: LLM 출력 검증은 평가 스크립트에서도 DB·서버 없이 같은 함수로 돌려야 한다
- 결정일: 2026-11-25
