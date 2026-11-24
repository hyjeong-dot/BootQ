# 13. 운영 / 런북 (Runbook)

> 문서 상태: 산출물 문서 — **간단한 로컬 런북** (2026-11-25 결정: 로컬 실행만이라 실행·중지·DB 재생성·LLM 한도 대응만 다룬다)
> 명령어·경로 중 `(구현 후 확인)` 표시는 아직 코드가 없는 계획값이다. 해당 기능을 구현하는 작업 안에서 실제 값으로 고친다.

## 1. 서비스 운영 정보

| 항목 | 내용 |
|---|---|
| 실행 위치 (서버/PC) | 개발 PC (macOS) 로컬 Docker Compose |
| 시작 방법 (명령어/바로가기) | `docker compose up -d` (구현 후 확인) |
| 중지 방법 | `docker compose down` (DB 볼륨 유지) |
| 정상 동작 확인 방법 (URL, 헬스체크) | `http://127.0.0.1:{포트}/docs` 열림, 데모 페이지 `/`에서 샘플 글 등록 → 토스트 표시 (포트는 구현 후 확인) |
| 로그 위치 | `docker compose logs api` (JSON 구조화 로그), 요청별 처리시간·토큰·오류코드는 DB `recommendation` 테이블, LLM 호출 기록은 `data/derived/llm_calls.jsonl` |
| 설정 파일 위치 | `.env` (형식은 `.env.example`), `docker-compose.yml` (구현 후 확인) |
| 의존 외부 서비스 (API 키, DB 등) | Groq API(`GROQ_API_KEY`), OpenRouter API(`OPENROUTER_API_KEY`, 평가 ③만), PostgreSQL 17 컨테이너 |

## 2. 장애 대응 절차

> 증상별로 "확인 → 조치" 순서를 적는다. 새 장애를 겪을 때마다 여기에 추가한다.

### 증상: 서비스가 응답하지 않음
1. 확인: `docker compose ps`로 api·db 컨테이너 상태, `docker compose logs api --tail 100`
2. 조치: 컨테이너가 내려가 있으면 아래 "공통 재시작 절차". DB 연결 오류면 db 컨테이너가 healthy인지 먼저 확인

### 증상: 글을 올려도 토스트가 안 뜸
1. 확인: DB `recommendation` 테이블에서 해당 post의 `error_code` 확인
   - 오류코드 없음 + 결과 0개 → 정상 동작 (게이트 종료 또는 캠프 부족. 추천 없음 = 토스트 미표시)
   - `rate_limited` → 아래 "LLM 한도 초과"
   - `auth` → `.env`의 API 키 확인
   - `network` / `server_error` → 공급자 상태 확인 후 재시도
2. 조치: 원인 해결 후 같은 글을 다시 등록 (BackgroundTasks는 재시작 시 유실·재시도 없음 — 한계)

### 증상: LLM 한도 초과 (`rate_limited`, 정규화 중단)
1. 확인: `data/derived/llm_calls.jsonl` 마지막 기록의 남은 한도(meta), Groq 콘솔의 일일 사용량 (200K TPD, 1K RPD)
2. 조치: 분당 한도면 잠시 후 재실행, 일일 한도면 다음 날 같은 명령으로 재실행 (정규화는 해시로 멱등 — 처리한 캠프는 건너뜀)

### 공통 재시작 절차
1. `docker compose restart api` (DB는 유지)
2. 그래도 안 되면 `docker compose down && docker compose up -d`
3. 서버 시작 시 어휘·관계를 메모리에 다시 읽으므로 정규화 결과도 반영된다. 서버를 끄지 않고 반영하려면 `POST /api/admin/vocab/reload`

## 3. 백업 / 복구

| 항목 | 내용 |
|---|---|
| 백업 대상 | `data/private/`만 (사람이 만든 매핑·수동 보정·검수 파일) |
| 백업 주기 / 방법 | 작업이 끝날 때마다 비공개 별도 git 저장소에 커밋·push (06_INFRA_DEPLOY.md) |
| 백업 보관 위치 | 비공개 GitHub 저장소 (구현 후 저장소 이름 기록) |
| 복구 절차 | ① 비공개 저장소를 clone해 `data/private/`로 복사 ② DB는 백업하지 않고 재생성: 볼륨 삭제(`docker compose down -v`) → 마이그레이션 적용 → 어휘·캠프 적재 배치(BAT-006) 실행 (명령어는 구현 후 확인) |
| 복구 테스트 마지막 확인일 | (미실시) |

## 4. 정기 점검 항목

| 주기 | 점검 내용 |
|---|---|
| 매일 (작업 종료 시) | `data/private/` 백업 push, 마일스톤 이슈에 마무리 기록 (08_COLLABORATION.md) |

## 5. 장애 회고 (포스트모템)

> 실제 장애가 발생했을 때마다 아래 형식으로 기록한다. 같은 장애를 두 번 겪지 않기 위한 기록이다.

### YYYY-MM-DD. (장애 제목)
- **증상 / 영향**:
- **원인**:
- **조치**:
- **재발 방지**: (코드 수정, 알림 추가, 이 문서의 대응 절차 갱신 등)
