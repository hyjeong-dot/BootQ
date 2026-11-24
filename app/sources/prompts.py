"""프롬프트 본문(prompts/*.md) 읽기. 조립(어휘 끼워 넣기)은 core가 하고, 파일 입출력은 여기서 한다."""
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parents[2] / 'prompts'


def load_prompt(name: str, directory: Path | None = None) -> str:
    """prompts/{name}.md의 본문. 편집기가 붙이는 파일 끝 줄바꿈 하나는 프롬프트에 넣지 않는다."""
    text = ((directory or PROMPT_DIR) / f'{name}.md').read_text(encoding='utf-8')
    return text.removesuffix('\n')
