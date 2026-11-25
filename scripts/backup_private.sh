#!/usr/bin/env bash
# data/private/(별도 비공개 git 저장소)를 커밋·push한다. 다시 만들기 비싼 LLM 정규화 결과도 llm/에 복사해 함께 백업한다.
# 사용: scripts/backup_private.sh "무엇을 바꿨는지"
# 복구 절차는 docs/specs/13_OPERATIONS.md 3장
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PRIVATE="$ROOT/data/private"
DERIVED="$ROOT/data/derived"

if [ ! -d "$PRIVATE/.git" ]; then
  echo "data/private/가 git 저장소가 아닙니다. 13_OPERATIONS.md 3장의 복구 절차로 먼저 clone하세요" >&2
  exit 1
fi

mkdir -p "$PRIVATE/llm"
for f in camp_llm.jsonl llm_calls.jsonl; do
  [ -f "$DERIVED/$f" ] && cp "$DERIVED/$f" "$PRIVATE/llm/$f"
done

cd "$PRIVATE"
git add -A
if git diff --cached --quiet; then
  echo "바뀐 것이 없어 백업하지 않습니다"
  exit 0
fi
git commit -q -m "backup: $(date +%F) ${1:-작업 마무리}"
git push -q
echo "백업 완료: $(git log --oneline -1)"
