from pathlib import Path

import pytest

from app.core.normalize_v2 import build_system_prompt
from app.sources.prompts import load_prompt
from tests.test_normalize_v2 import VOCAB

FIXTURES = Path(__file__).parent / 'fixtures'


def test_prompt_file_reproduces_prompt_from_before_moving_it():
    # 고정 파일은 본문을 prompts/로 옮기기 직전 코드(f-string)의 출력이다. 같아야 정규화 캐시(content_hash)도 그대로 유지된다
    expected = (FIXTURES / 'normalize_v2_system_prompt.txt').read_text(encoding='utf-8')
    assert build_system_prompt(VOCAB, load_prompt('normalize_v2')) == expected


def test_unknown_placeholder_is_an_error():
    with pytest.raises(KeyError):
        build_system_prompt(VOCAB, '${jobs} ${typo}')


def test_load_prompt_drops_only_the_final_newline(tmp_path):
    (tmp_path / 'p.md').write_text('본문\n\n끝\n', encoding='utf-8')
    assert load_prompt('p', tmp_path) == '본문\n\n끝'
