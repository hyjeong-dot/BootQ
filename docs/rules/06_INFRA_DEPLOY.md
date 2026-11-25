# 06. 배포 / 인프라

> 문서 상태: ✅ 완료 (2026-11-25)

## 1. 배포 대상

### 실행 환경
- 상태: ✅ 결정
- 선택지:
  - **로컬 실행만** — 개인 도구, 배포 없음
  - **클라우드 PaaS** — Vercel, Railway, Cloudtype 등 (간편, 소규모)
  - **클라우드 IaaS** — AWS EC2, GCP, Oracle Free Tier 등 (자유도 높음, 관리 부담)
  - **홈서버 / NAS**
- 결정: **로컬 실행만** (Docker Compose)
- 이유: 공개 배포하면 외부 입력이 무료 LLM 티어로 흘러가 한도가 소진되고, "실제 유저 글을 무료 티어에 보내지 않는다" 원칙과 부딪힌다. 앞서 정한 인증 없음·localhost 노출(02_BACKEND.md)과도 맞는다. 포트폴리오에는 데모 영상·평가 결과로 대신
- 결정일: 2026-11-25

### 컨테이너화 여부
- 상태: ✅ 결정
- 선택지: 사용 안 함 / Docker / Docker Compose(멀티 서비스)
- 결정: Docker Compose (Postgres + API). API 포트는 `127.0.0.1`에만 게시
- 이유: DB까지 명령 하나로 띄워 면접관·리뷰어도 재현 가능
- 결정일: 2026-11-24
- 구성 (2026-11-26, #13 — `compose.yaml`):
  - `db`: `postgres:17`, 볼륨 `pgdata`, `127.0.0.1:${POSTGRES_PORT:-5432}:5432`. 처음 볼륨을 만들 때 `db/init/`이 테스트 DB `bootq_test`를 만든다. healthcheck(`pg_isready`)
  - `api`: `Dockerfile`(`python:3.13-slim` + uv 0.13.9, `uv sync --locked --no-dev`), `127.0.0.1:${API_PORT:-8000}:8000`. db가 healthy가 된 뒤 시작하고, 시작할 때 `scripts/migrate.py`로 마이그레이션을 적용한 다음 uvicorn을 띄운다 (컨테이너 안은 0.0.0.0 바인딩)
  - DB 계정·비밀번호는 `.env`(`POSTGRES_USER`·`POSTGRES_PASSWORD`·`POSTGRES_DB`)에서. 로컬 전용이라 `.env.example`의 기본값(`bootq`)을 그대로 써도 된다 — 포트가 127.0.0.1에만 열리므로
  - 이미지에는 `data/private`·`data/derived`·`data/raw`·`.env`를 넣지 않는다 (`.dockerignore`). DB 적재(BAT-006)는 호스트에서 스크립트로 한다

## 2. 환경 분리

### 환경 구성
- 상태: ✅ 결정
- 선택지: local만 / local + prod / local + dev + prod
- 결정: **local만** (환경 분기 코드 없음. 테스트용 DB는 07_TEST.md에서 별도 결정)
- 결정일: 2026-11-25

### 환경별 설정 관리
- 상태: ✅ 결정
- 결정: `.env`(git 제외) + `.env.example`(커밋). Compose는 같은 `.env`를 읽는다 — 02_BACKEND.md 시크릿 관리와 동일
- 결정일: 2026-11-24

## 3. CI/CD

### CI (빌드/테스트 자동화)
- 상태: ✅ 결정
- 선택지: 없음(수동) / GitHub Actions / GitLab CI
- 결정: **GitHub Actions** — push 시 uv로 설치 후 `pytest`, 프론트는 `tsc --noEmit` 타입 검사. DB 통합 테스트는 07_TEST.md 결정에 따라 Postgres 서비스 컨테이너 사용
- 이유: 원격 저장소가 GitHub. 현재 테스트는 git 제외 데이터(`data/private/`, `data/raw/`)를 읽지 않아 CI에서도 돈다. **앞으로도 테스트는 git 제외 데이터를 읽지 않는다** (고정 픽스처 사용)
- 결정일: 2026-11-25

### CD (배포 자동화)
- 상태: ➖ 해당없음
- 결정: 로컬 실행만이라 배포 없음
- 결정일: 2026-11-25

## 4. 도메인 / 네트워크

### 도메인 및 HTTPS
- 상태: ➖ 해당없음
- 결정: 로컬 실행만 (`http://127.0.0.1`)
- 결정일: 2026-11-25

## 5. 운영

### 모니터링 / 로그 수집
- 상태: ✅ 결정
- 선택지: 없음 / 플랫폼 기본 로그 / Sentry(에러 추적) / 자체 구축
- 결정: **외부 도구 없음.** 요청별 처리시간·토큰·오류코드는 recommendation 테이블에, LLM 호출 기록은 `data/derived/llm_calls.jsonl`에, 애플리케이션 로그는 JSON 구조화 로그로 표준 출력(02_BACKEND.md) → `docker compose logs`로 확인
- 이유: 로컬 데모. 외부 에러 추적 도구는 글 내용이 밖으로 나갈 위험이 있음
- 결정일: 2026-11-25

### 백업 정책
- 상태: ✅ 결정
- 결정:
  - 대상: **`data/private/`** (사람이 만든 매핑·수동 보정·검수 파일 — 스크립트로 다시 만들 수 없는 유일한 사람 작업물) **+ LLM 정규화 결과** (`data/derived/camp_llm.jsonl`, `llm_calls.jsonl`을 백업 저장소의 `llm/`에 복사)
  - 방법: **비공개 별도 git 저장소**에 `data/private/`만 담아 작업이 끝날 때마다 커밋·push. BootQ 저장소와는 분리 (BootQ의 `.gitignore`는 그대로)
  - 제외: DB(스크립트로 재생성), 나머지 `data/derived/`(스크립트 산출물, LLM 없이 다시 만들어짐), `data/raw/`(원본 파일은 받은 곳에 있음)
  - ⚠️ 회사 데이터에서 나온 파일이 외부 서비스(비공개 저장소)에 올라간다. 저장소는 반드시 private로 만들고 공유하지 않는다
- 이유: 변경 이력이 남아 검수 판단을 되돌려 볼 수 있음 (사용자 선택. AI 추천은 개인 클라우드 드라이브 수동 복사였음 — 외부 업로드를 줄이려는 이유). LLM 정규화 결과를 더한 이유: 다시 만들려면 무료 한도로 하루 이상 걸리고, 결과가 조금만 달라져도 결과 해시에 묶인 검수 승인(BAT-003)이 풀려 검수를 다시 해야 한다 (2026-11-25 변경, 99_DECISIONS.md)
- 결정일: 2026-11-25
