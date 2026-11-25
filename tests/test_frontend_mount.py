"""데모 페이지 정적 서빙 (SCR-001, 03_FRONTEND.md 1장). DB·LLM이 필요 없는 요청만 보낸다 (lifespan을 돌리지 않음)."""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def make_frontend(tmp_path: Path) -> Path:
    d = tmp_path / 'frontend'
    (d / 'dist').mkdir(parents=True)
    (d / 'index.html').write_text('<!doctype html><title>BootQ 데모</title>', encoding='utf-8')
    (d / 'dist' / 'main.js').write_text('export {};', encoding='utf-8')
    return d


def test_index_and_assets_served(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dir=make_frontend(tmp_path)))
    r = client.get('/')
    assert r.status_code == 200 and 'BootQ 데모' in r.text
    js = client.get('/dist/main.js')
    assert js.status_code == 200 and 'javascript' in js.headers['content-type']


def test_api_routes_win_over_static_mount(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dir=make_frontend(tmp_path)))
    assert client.get('/openapi.json').status_code == 200
    # 없는 API 경로도 에러 규약 JSON으로 (정적 마운트가 가로채도 전역 핸들러를 거친다)
    r = client.get('/api/nope')
    assert r.status_code == 404
    assert r.json()['error']['code'] == 'not_found'


def test_no_frontend_dir_means_api_only(tmp_path: Path) -> None:
    client = TestClient(create_app(frontend_dir=tmp_path / 'missing'))
    assert client.get('/').status_code == 404
    assert client.get('/openapi.json').status_code == 200
