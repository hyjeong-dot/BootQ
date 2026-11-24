"""설정: .env 읽기와 공급자별 모델 선택. 모델은 --model 옵션 > .env(GROQ_MODEL, OPENROUTER_MODEL) > 코드 기본값 순으로 정한다."""
import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

from app.llm import groq

ROOT = Path(__file__).resolve().parents[1]
MODEL_ENV = {'groq': 'GROQ_MODEL', 'openrouter': 'OPENROUTER_MODEL'}
DEFAULT_MODEL: dict[str, str | None] = {'groq': groq.DEFAULT_MODEL, 'openrouter': None}   # OpenRouter는 기본값 없음


def load_env(path: Path | None = None, environ: MutableMapping[str, str] | None = None) -> None:
    """.env의 KEY=VALUE를 환경 변수로 읽는다. 이미 설정된 환경 변수는 덮어쓰지 않는다. 이름·값 주위 공백과 따옴표는 제거한다."""
    environ = os.environ if environ is None else environ
    env_path = path or ROOT / '.env'
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            environ.setdefault(key.strip(), value.strip().strip('"\''))


def resolve_model(provider: str, cli_model: str | None = None, environ: Mapping[str, str] | None = None) -> str | None:
    """정해진 모델 이름. 기본값이 없는 공급자(OpenRouter)에서 아무것도 지정하지 않았으면 None."""
    environ = os.environ if environ is None else environ
    return cli_model or environ.get(MODEL_ENV[provider], '').strip() or DEFAULT_MODEL[provider]
