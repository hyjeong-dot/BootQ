# 08. 협업 규칙 및 일정 관리 (WBS)

> 문서 상태: ✅ 완료 (2026-11-25) — 4장(WBS)은 산출물로 계속 갱신
> 혼자 개발하더라도 Git 규칙과 WBS는 작성한다. (혼자용은 간소하게)
> 개발 인원은 혼자(00_PROJECT.md). GitHub 원격 저장소 있음.

## 1. Git 규칙

### 브랜치 전략
- 상태: ✅ 결정
- 선택지:
  - **main 단일 브랜치** — 혼자, 빠른 개발
  - **GitHub Flow** — main + 기능 브랜치 + PR (소규모 협업 권장)
  - **Git Flow** — main/develop/feature/release (규모 큰 협업)
- 결정: **dev 통합 브랜치 + 기능 브랜치 + PR**
  - 기능 브랜치 → **dev**로 PR (GitHub 기본 브랜치 = dev)
  - 마일스톤이 끝날 때마다 **dev → main** PR (main = 마일스톤 단위로 안정된 상태)
  - 기능 브랜치 이름은 `{종류}/#{이슈번호}-{설명}` (예: `feat/#12-matching-core`)
- 이유: 이슈 단위 PR로 변경 단위와 CI 결과가 남아 포트폴리오에서 작업 과정이 보인다. 원격 저장소가 이미 dev를 기본 브랜치로 쓰고 있어 그에 맞췄다 (99_DECISIONS.md 변경 이력)
- 비고: 2026-11-25 이전 커밋 9개는 main에 직접 커밋됨 (dev도 같은 커밋에서 시작)
- 결정일: 2026-11-25

### 커밋 컨벤션
- 상태: ✅ 결정
- 선택지: 자유 형식 / Conventional Commits(`feat:`, `fix:`, `docs:` ...) / 한국어 요약
- 결정: **Conventional Commits 접두어 + 한국어 요약** (기존 관례 유지). 접두어: feat / fix / docs / test / refactor / chore. 본문에 파일별 변경 이유
  - 예: `feat: 정규화 v2 — LLM은 추가분만, 기준값은 코드가 유지`
- 결정일: 2026-11-25

### 커밋 금지 대상 (사전 기입 — 기존 설계 메모에서 확정)
- 상태: ✅ 결정
- 결정:
  - 유저 QnA 원문과 회사 원본 데이터 (`data/raw/`)
  - 회사 데이터에서 나온 파일: 사람이 만든 것은 `data/private/`, 스크립트 산출물은 `data/derived/` — 둘 다 git 제외
  - 커밋하는 어휘·관계 파일에는 대표 직무명과 일반적인 근거만 적는다
  - 커밋되는 파일(README, docs, 코드, 주석)에는 인턴십 레포 경로·파일명·함수명을 적지 않는다. 인턴십은 "인턴십 프로젝트"로만 언급
  - `.env`
  - 문서의 수치는 직접 측정한 것만 적는다
- 결정일: 2026-11-24

### PR / 코드 리뷰 규칙
- 상태: ✅ 결정
- 결정:
  - **셀프 머지** (리뷰 승인 불필요)
  - **CI(pytest · `tsc --noEmit`) 통과 필수** — GitHub 브랜치 보호 규칙으로 dev·main에 걸어 둔다 (저장소 설정은 본인이 변경)
  - 기능 브랜치 → dev: **squash 머지** (PR 하나 = dev 커밋 하나). PR 제목은 커밋 컨벤션을 따른다
  - dev → main: **merge commit** (squash하면 dev와 main 이력이 갈라져 다음 마일스톤 PR에서 충돌이 생김)
  - PR 본문: `Closes #이슈번호`, 변경 요약, 관련 결정 문서 링크
- 결정일: 2026-11-25

## 2. 이슈 / 작업 관리

### 이슈 관리 도구
- 상태: ✅ 결정
- 선택지: 없음(이 문서의 WBS로만 관리) / GitHub Issues / Jira / Notion
- 결정: **GitHub Issues + GitHub Milestones**. 작업 목록의 **원본은 Issues**이고, 이 문서 4장에는 마일스톤 요약과 이슈 링크만 유지한다
- 이유: 커밋·PR·이슈가 서로 연결되어 작업 이력이 저장소에 남음 (사용자 선택. AI 추천은 이 문서의 WBS만 쓰는 것이었음)
- 결정일: 2026-11-25

### 이슈 작성 규칙
- 상태: ✅ 결정
- 결정:
  - 제목: `[M{번호}] 작업 한 줄` (예: `[M3] 매칭 core 구현`)
  - 본문: 완료 조건 체크리스트
  - 라벨: `feat` / `fix` / `docs` / `eval`. 마일스톤: GitHub Milestones의 M1~M7 (M7 고도화는 마감 없이 MVP 이후로 미뤄도 되는 일을 모은다)
  - 브랜치: `{종류}/#{이슈번호}-{설명}`, PR 본문에 `Closes #{이슈번호}`
  - 이슈·PR에는 유저 원문·회사 원본 데이터·인턴십 레포 경로를 적지 않는다 (커밋 금지 대상과 같은 기준)
- 결정일: 2026-11-25

## 3. 커뮤니케이션 (협업 시)

### 소통 채널 / 회의 주기
- 상태: ✅ 결정
- 결정: 소통 채널·회의 없음(혼자). 대신 **매일 마무리 기록** — 하루 끝에 그날의 진행·결정·다음 할 일을 해당 마일스톤의 추적 이슈에 코멘트로 짧게 남긴다
- 이유: 3일 일정의 진행 상황과 판단 근거가 저장소에 남아 회고·면접 설명에 쓸 수 있음
- 결정일: 2026-11-25

### 작업 진행 방식 (사전 기입 — 기존 설계 메모에서 확정)
- 상태: ✅ 결정
- 결정: 단계마다 결과를 보여주고 확인받은 뒤 다음 단계로 넘어간다
- 결정일: 2026-11-24

---

## 4. WBS (작업 분해 구조 — 산출물, 개발하며 갱신)

> **원본은 GitHub Issues·Milestones** (2장 결정, 2026-11-25 이전). 이 장에는 마일스톤 요약과 이슈 링크, 이슈에 담기 어려운 선행 관계만 둔다.
> 작업 상태: ⬜ 대기 / 🔄 진행중 / ✅ 완료 (마일스톤 상태만 여기서 관리)

### 마일스톤

| 마일스톤 | 목표 | 기한 | 상태 | 이슈 (진행 기록) |
|---|---|---|---|---|
| [M1](https://github.com/hyjeong-dot/BootQ/milestone/1) | 오프라인 정규화: 어휘·매핑·기준선·LLM 정규화 v2 | 2026-11-24 | ✅ (2026-11-25 종료) | [#7](https://github.com/hyjeong-dot/BootQ/issues/7)✅ [#8](https://github.com/hyjeong-dot/BootQ/issues/8)✅ [#18](https://github.com/hyjeong-dot/BootQ/issues/18)✅ ([#19](https://github.com/hyjeong-dot/BootQ/issues/19)✅) |
| [M2](https://github.com/hyjeong-dot/BootQ/milestone/2) | 평가 준비: 정답 셋 판정·고정 | 2026-11-25 | ✅ (2026-11-25 종료) | [#9](https://github.com/hyjeong-dot/BootQ/issues/9)✅ ([#20](https://github.com/hyjeong-dot/BootQ/issues/20)✅) |
| [M3](https://github.com/hyjeong-dot/BootQ/milestone/3) | 요청 파이프라인 core + 평가 스크립트 | 2026-11-25 | ✅ (2026-11-26 종료) | [#1](https://github.com/hyjeong-dot/BootQ/issues/1)✅ [#3](https://github.com/hyjeong-dot/BootQ/issues/3)✅ [#5](https://github.com/hyjeong-dot/BootQ/issues/5)✅ [#22](https://github.com/hyjeong-dot/BootQ/issues/22)✅ [#10](https://github.com/hyjeong-dot/BootQ/issues/10)✅ [#11](https://github.com/hyjeong-dot/BootQ/issues/11)✅ [#12](https://github.com/hyjeong-dot/BootQ/issues/12)✅ ([#21](https://github.com/hyjeong-dot/BootQ/issues/21)✅) |
| [M4](https://github.com/hyjeong-dot/BootQ/milestone/4) | DB·API·SSE | 2026-11-26 | ✅ (2026-11-26 종료) | [#13](https://github.com/hyjeong-dot/BootQ/issues/13)✅ [#14](https://github.com/hyjeong-dot/BootQ/issues/14)✅ |
| [M5](https://github.com/hyjeong-dot/BootQ/milestone/5) | 데모 페이지 | 2026-11-26 | ⬜ | [#15](https://github.com/hyjeong-dot/BootQ/issues/15) |
| [M6](https://github.com/hyjeong-dot/BootQ/milestone/6) | 평가 실행과 결과·문서 정리, README | 2026-11-27 | ⬜ | [#16](https://github.com/hyjeong-dot/BootQ/issues/16)✅ [#17](https://github.com/hyjeong-dot/BootQ/issues/17) [#35](https://github.com/hyjeong-dot/BootQ/issues/35)✅ [#36](https://github.com/hyjeong-dot/BootQ/issues/36)✅ |
| [M7](https://github.com/hyjeong-dot/BootQ/milestone/7) | 고도화: MVP 이후로 미뤄도 되는 개선 (평가에서 보류한 규칙, `99_DECISIONS.md`의 보류 방안 재검토) | 없음 | ⬜ | [#40](https://github.com/hyjeong-dot/BootQ/issues/40) |

### 선행 관계

| 이슈 | 먼저 끝나야 하는 이슈 |
|---|---|
| [#10](https://github.com/hyjeong-dot/BootQ/issues/10) 매칭 core | [#7](https://github.com/hyjeong-dot/BootQ/issues/7) 정규화 검수, [#8](https://github.com/hyjeong-dot/BootQ/issues/8) 매칭용 어휘 |
| [#11](https://github.com/hyjeong-dot/BootQ/issues/11) 평가 스크립트 | [#9](https://github.com/hyjeong-dot/BootQ/issues/9) 정답 셋, [#10](https://github.com/hyjeong-dot/BootQ/issues/10) 매칭 core |
| [#12](https://github.com/hyjeong-dot/BootQ/issues/12) 슬롯필링 | [#8](https://github.com/hyjeong-dot/BootQ/issues/8) 매칭용 어휘 |
| [#14](https://github.com/hyjeong-dot/BootQ/issues/14) API | [#10](https://github.com/hyjeong-dot/BootQ/issues/10) 매칭 core, [#13](https://github.com/hyjeong-dot/BootQ/issues/13) DB |
| [#15](https://github.com/hyjeong-dot/BootQ/issues/15) 데모 페이지 | [#14](https://github.com/hyjeong-dot/BootQ/issues/14) API |
| [#16](https://github.com/hyjeong-dot/BootQ/issues/16) 3갈래 평가 | [#11](https://github.com/hyjeong-dot/BootQ/issues/11) 평가 스크립트, [#12](https://github.com/hyjeong-dot/BootQ/issues/12) 슬롯필링 |
| [#17](https://github.com/hyjeong-dot/BootQ/issues/17) README | [#16](https://github.com/hyjeong-dot/BootQ/issues/16) 3갈래 평가 |

### 이슈 도입 전 완료한 작업 (git 이력)
- M1: 캠프 원본 정리·대표 직무 어휘, 대표 산업 어휘·계열·산업 등급 판정, 상세분류 검사·스킬 어휘·2차전지 산업, 캠프 ID(캠프명 해시)·기준 프로파일, LLM 경계(Groq·OpenRouter), LLM 정규화 v1 → v2
- M2: 평가 설계 문서(`docs/EVAL.md`)·정답 셋 템플릿

### WBS 운영 규칙
- 작업 상태는 GitHub Issues(열림/닫힘)와 Milestones 진행률이 원본이다. 이 문서의 마일스톤 상태는 마일스톤을 닫을 때 갱신한다.
- 계획에 없던 작업이 생기면 이슈를 먼저 만든 후 진행한다.
