"""
정규화 A단계: 캠프 원본 CSV를 정리해 camp_raw 후보 파일을 만든다 (LLM 없음, 표준 라이브러리만 사용).

- 모든 칸의 앞뒤 공백 제거 (예: 상세분류 'GMP '와 'GMP'가 다른 값으로 잡히는 문제)
- 캠프명에 '삭제'가 들어간 더미 행 제외
- source_camp_id 부여: CSV에는 캠프 ID가 없으므로 캠프명 해시로 임시 ID를 만든다.
  같은 캠프가 직무코드만 다른 여러 행으로 들어 있어도(예: 상세분류 N/A 행과 photo공정 행) 같은 캠프로 묶이게
  직무코드는 ID에 넣지 않는다. 캠프명이 바뀌면 새 캠프가 되는 것이 이 임시 ID의 한계다

실행:
    python scripts/prepare_camps.py
입력: data/raw/직무코드_캠프명_매핑.csv
출력: data/derived/camp_raw.csv (git 제외)
"""
import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'data' / 'raw' / '직무코드_캠프명_매핑.csv'
OUT = ROOT / 'data' / 'derived' / 'camp_raw.csv'

SOURCE = 'csv'
DUMMY_MARKER = '삭제'
COLUMNS = ['직무코드', '직무대분류', '직무중분류', '직무소분류', '상세분류', '산업', '캠프명']


def make_source_camp_id(camp_name: str) -> str:
    return hashlib.sha1(camp_name.encode('utf-8')).hexdigest()[:12]


def main() -> int:
    with SRC.open(encoding='utf-8-sig', newline='') as f:
        rows = [{k.strip(): (v or '').strip() for k, v in row.items()} for row in csv.DictReader(f)]

    kept, dropped = [], []
    for row in rows:
        (dropped if DUMMY_MARKER in row['캠프명'] else kept).append(row)

    pairs = Counter()
    out_rows = []
    for row in kept:
        camp_id = make_source_camp_id(row['캠프명'])
        pairs[(camp_id, row['직무코드'])] += 1
        out_rows.append({'source': SOURCE, 'source_camp_id': camp_id, **{c: row[c] for c in COLUMNS}})

    duplicated = [k for k, n in pairs.items() if n > 1]
    if duplicated:
        print(f'같은 캠프명+직무코드 행이 중복 {len(duplicated)}개', file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['source', 'source_camp_id', *COLUMNS])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f'원본 {len(rows)}행 → 더미 제외 {len(dropped)}행 → {len(out_rows)}행 저장')
    print(f'캠프(ID) {len({r["source_camp_id"] for r in out_rows})}개, 고유 캠프명 {len({r["캠프명"] for r in out_rows})}개, 상세분류 고유값 {len({r["상세분류"] for r in out_rows if r["상세분류"]})}개')
    print(f'출력: {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
