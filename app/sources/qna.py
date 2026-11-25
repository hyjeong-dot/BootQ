"""커뮤니티 Q&A 원본(xlsx, git 제외) 읽기. 표준 라이브러리만 쓴다 (openpyxl 없이 시트 XML을 직접 읽는다).

원본은 로컬 검사·평가 준비에만 쓴다. LLM이나 외부 서비스로 보내지 않는다.
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[2] / 'data' / 'raw'
_NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
_T = '{%s}t' % _NS['m']


def _cell_text(cell: ET.Element, shared: list[str]) -> str:
    value = cell.find('m:v', _NS)
    if value is None:                              # 인라인 문자열
        return ''.join(t.text or '' for t in cell.iter(_T))
    return shared[int(value.text)] if cell.get('t') == 's' else (value.text or '')


def find_raw_qna(directory: Path = RAW_DIR) -> Path | None:
    """data/raw/의 Q&A 원본 xlsx (파일명은 커밋하지 않으려고 고정하지 않는다). 없으면 None."""
    files = sorted(directory.glob('*.xlsx')) if directory.exists() else []
    return files[0] if files else None


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    """첫 시트를 머리행 기준 dict 목록으로."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if 'xl/sharedStrings.xml' in names:
            shared = [''.join(t.text or '' for t in si.iter(_T))
                      for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', _NS)]
        sheet = sorted(n for n in names if n.startswith('xl/worksheets/sheet'))[0]
        grid = []
        for row in ET.fromstring(z.read(sheet)).iter('{%s}row' % _NS['m']):
            grid.append({re.match(r'[A-Z]+', c.get('r')).group(): _cell_text(c, shared) for c in row.findall('m:c', _NS)})
    header = grid[0]
    return [{name: (r.get(col) or '').strip() for col, name in header.items()} for r in grid[1:]]
