# 01. 기술 스택 및 버전

> 문서 상태: ✅ 완료 (2026-11-25)
> 버전을 명시하지 않으면 AI마다 다른 버전을 가정해 코드가 꼬인다. 반드시 구체적인 버전까지 결정한다.
> 사전 기입(2026-11-24): 기존 설계 메모에서 정해진 종류(언어·프레임워크·DB)는 기록했고, **버전은 아직 정해진 적이 없어 ❓로 남겼다.** (이후 모두 결정됨)

## 1. 개발 환경

### 개발 OS / 환경
- 상태: ✅ 결정
- 선택지: Windows / WSL(Ubuntu) / macOS / Linux — 혼용 시 각각 기재
- 결정: macOS (로컬 개발), DB·API 실행은 Docker Compose
- 이유: 현재 개발 환경. 컨테이너로 실행 환경 차이를 줄인다
- 결정일: 2026-11-24

## 2. 백엔드

### 언어 및 버전
- 상태: ✅ 결정
- 결정: **Python 3.13**
- 이유: 현재 `.venv`가 3.13.15이고 기존 테스트 57개가 이 버전에서 통과함. 재설치·재검증 비용 없음
- 결정일: 2026-11-25

### 프레임워크 및 버전
- 상태: ✅ 결정
- 결정: **FastAPI + Pydantic, 설치 시점 최신 안정판을 lockfile로 고정**. 설치 후 실제 버전을 5장 요약표에 기록한다
- 이유: 특정 구버전을 써야 할 이유가 없음
- 결정일: 2026-11-25

### 빌드 도구 / 패키지 매니저
- 상태: ✅ 결정
- 선택지 예: uv(pyproject.toml + uv.lock) / pip + requirements.txt / poetry
- 결정: **uv** (`pyproject.toml` + `uv.lock`)
- 이유: lockfile로 버전 고정이 쉽고 Docker 이미지 빌드가 빠름. 기존에는 의존성 파일이 없었으므로(`.venv`에 pytest만, HTTP는 표준 라이브러리 `urllib`) 전환 비용이 없음
- 결정일: 2026-11-25

## 3. 프론트엔드

### 언어 및 버전
- 상태: ✅ 결정
- 결정: **TypeScript + 빌드 도구** (버전·빌드 도구는 아래 Node.js 항목에서 결정)
- 이유: 사용자 선택 (AI 추천은 바닐라 JS였음 — 페이지 한 장이라 빌드 도구가 과하다는 이유). 타입 안전성 확보
- 결정일: 2026-11-25

### 프레임워크 및 버전
- 상태: ✅ 결정
- 결정: 없음 — 인턴십 프로젝트의 팝업 목업(HTML·CSS)을 재사용한 정적 데모 페이지
- 이유: 핵심은 추천 로직과 평가. 데모는 토스트 표시만 필요
- 결정일: 2026-11-24

### Node.js 버전 / 패키지 매니저
- 상태: ✅ 결정
- 결정: **Node 26 LTS + npm** (`package-lock.json` 커밋). 빌드는 **`tsc`만 사용** (번들러 없음)
- 이유: 2026-10부터 Active LTS(24는 Maintenance LTS로 내려감, 25는 LTS가 되지 않는 홀수 버전이고 지원 종료). npm은 Node 기본 포함. 페이지 한 장이라 번들러 없이 TS → JS 컴파일만 한다 (의존성 최소)
- Node 26.13.1 설치 (2026-11-26, #15). `frontend/.nvmrc`와 `package.json`의 `engines`(`>=26 <27`)로 고정. 처음엔 24로 정했다가 같은 날 26으로 바꿈 (99_DECISIONS.md)
- 결정일: 2026-11-25

## 4. 데이터베이스 (버전만 — 상세 규칙은 04_DATABASE.md)

### DBMS 및 버전
- 상태: ✅ 결정
- 결정: **PostgreSQL 17** (Docker 이미지 `postgres:17`). JSONB에 LLM 원본 출력·출처 원본 행 저장, 관계 테이블 조인. pgvector는 필요해질 때만 (`pgvector/pgvector:pg17` 이미지로 교체)
- 이유: 출시 1년이 넘은 안정 버전, pgvector 이미지 제공. 18의 신기능이 이 프로젝트에 필요하지 않음
- 결정일: 2026-11-25

## 5. 필수 도구 버전 요약표

> 모든 결정이 끝나면 AI가 아래 표를 채운다. 개발 시작 시 AI는 이 표의 버전을 기준으로 코드를 작성한다.

| 구분 | 도구 | 버전 | 확인 명령어 |
|---|---|---|---|
| 백엔드 언어 | Python | 3.13 (`.python-version`, 로컬 3.13.15) | `uv run python --version` |
| 백엔드 프레임워크 | FastAPI | 0.165.0 (`uv.lock`, 2026-11-26 설치) | `uv pip show fastapi` |
| ASGI 서버 | uvicorn | 0.54.0 (`uv.lock`) | `uv pip show uvicorn` |
| DB 드라이버 | psycopg 3 (`psycopg[binary]`, libpq 포함) | 3.3.9 (`uv.lock`), 커넥션 풀 `psycopg-pool` 3.3.3 | `uv pip show psycopg` |
| 빌드 도구 | uv | 0.13.9 (로컬·CI 동일하게 고정) | `uv --version` |
| 프론트 언어 | TypeScript | 7.0.2 (`frontend/package-lock.json`) | `npx tsc --version` |
| 프론트 빌드 | tsc (번들러 없음) | TypeScript와 동일 | - |
| 프론트 프레임워크 | 없음 | - | - |
| Node.js | Node.js + npm | 26 LTS (26.13.1, npm 11.20.0. `frontend/.nvmrc`, `engines`) | `node --version` |
| DBMS | PostgreSQL | 17 (`postgres:17`) | `psql --version` |
| 컨테이너 | Docker | 현재 29.4.0 | `docker --version` |
| 테스트 | pytest | 9.2.0 (`uv.lock`) | `uv run pytest --version` |
| 비동기 테스트 | anyio pytest 플러그인 | anyio 4.16.0 (`uv.lock`) | `uv pip show anyio` |
| API 테스트 클라이언트 | httpx2 (Starlette TestClient가 요구) | 2.16.2 (`uv.lock`, dev) | `uv pip show httpx2` |
| CI | GitHub Actions | `actions/checkout@v7`, `astral-sh/setup-uv@v10.4.0`, 서비스 컨테이너 `postgres:17` | `.github/workflows/ci.yml` |
| API 이미지 | Python + uv | `python:3.13-slim`, `ghcr.io/astral-sh/uv:0.13.9` | `Dockerfile` |

## 6. 버전 정책

### 버전 고정 방식
- 상태: ✅ 결정
- 선택지: lockfile 커밋 필수 / 마이너 버전까지 고정 / LTS만 사용
- 결정: **lockfile 커밋 필수** — 백엔드 `uv.lock`, 프론트 패키지 매니저의 lockfile. Docker 이미지 태그도 메이저 버전까지 고정(`postgres:17`, `python:3.13-slim`)
- 이유: 재현 가능한 실행 (면접관·리뷰어가 같은 버전으로 실행)
- 결정일: 2026-11-25
