"""core import 경계 (07_TEST.md 우선순위 5).
core는 repositories·llm·sources·services·routers, DB 드라이버, HTTP 클라이언트를 import하지 않고 파일도 읽지 않는다.
평가 스크립트가 DB·LLM 없이 core.matching을 직접 호출하기 위한 규칙이다."""
import ast
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parents[1] / 'app' / 'core'
CORE_FILES = sorted(CORE_DIR.glob('*.py'))

FORBIDDEN_APP = ('app.repositories', 'app.llm', 'app.sources', 'app.services', 'app.routers', 'app.main',
                 'app.config')
FORBIDDEN_TOP = {
    # DB 드라이버
    'psycopg', 'psycopg2', 'psycopg_pool', 'asyncpg', 'sqlite3', 'sqlalchemy',
    # HTTP 클라이언트·네트워크
    'httpx', 'requests', 'aiohttp', 'urllib', 'urllib3', 'http', 'socket',
    # 파일·환경 접근
    'os', 'pathlib', 'io', 'shutil', 'glob', 'tempfile', 'importlib', 'subprocess',
}
FORBIDDEN_CALLS = {'open', '__import__', 'exec', 'eval'}


def _imports(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:                       # 상대 import는 core 밖을 가리킬 수 있어 금지
                names.append('.' * node.level + (node.module or ''))
            elif node.module == 'app':
                names += [f'app.{a.name}' for a in node.names]
            else:
                names.append(node.module or '')
    return names


def test_core_files_found():
    assert {'models.py', 'gate.py', 'merge.py', 'matching.py', 'reason.py'} <= {p.name for p in CORE_FILES}


@pytest.mark.parametrize('path', CORE_FILES, ids=lambda p: p.name)
def test_core_imports_only_allowed_modules(path):
    for name in _imports(ast.parse(path.read_text(encoding='utf-8'))):
        assert not name.startswith('.'), f'{path.name}: 상대 import 금지 ({name})'
        assert not any(name == f or name.startswith(f + '.') for f in FORBIDDEN_APP), f'{path.name}: {name}'
        assert name.split('.')[0] not in FORBIDDEN_TOP, f'{path.name}: {name}'
        if name.startswith('app.'):
            assert name.startswith('app.core'), f'{path.name}: core 밖 app 모듈 ({name})'


@pytest.mark.parametrize('path', CORE_FILES, ids=lambda p: p.name)
def test_core_does_not_read_files(path):
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in FORBIDDEN_CALLS, f'{path.name}:{node.lineno} {node.func.id}()'
        if isinstance(node, ast.Attribute):
            assert node.attr not in {'read_text', 'read_bytes', 'write_text', 'open'}, \
                f'{path.name}:{node.lineno} .{node.attr}'


def test_checker_catches_forbidden_import():
    # 검사기 자체가 동작하는지: 금지 import가 든 코드를 잡아야 한다
    tree = ast.parse('from app.repositories import camps\nimport httpx\nfrom app import llm\n')
    assert _imports(tree) == ['app.repositories', 'httpx', 'app.llm']
