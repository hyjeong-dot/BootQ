"""Groq 클라이언트. 구조화 출력은 json_schema strict 모드. 추론 설정은 모델 계열마다 요청 형식이 달라 여기서 고른다."""
from app.llm.openai_compat import ChatCompletionsClient, Transport, urllib_transport  # noqa: F401

DEFAULT_MODEL = 'openai/gpt-oss-120b'


def reasoning_params(model: str) -> dict:
    """
    - gpt-oss: 추론을 끌 수 없어 가장 낮은 low. 추론 내용은 응답에서 뺀다
    - qwen: 추론을 끌 수 있다(none). 구조화 출력과 같이 쓰려면 reasoning_format이 hidden/parsed여야 한다
    - 그 밖: 추가 파라미터 없음
    """
    if model.startswith('openai/gpt-oss'):
        return {'reasoning_effort': 'low', 'include_reasoning': False}
    if model.startswith('qwen/'):
        return {'reasoning_effort': 'none', 'reasoning_format': 'hidden'}
    return {}


class GroqClient(ChatCompletionsClient):
    url = 'https://api.groq.com/openai/v1/chat/completions'
    rate_limit_headers = ('x-ratelimit-remaining-tokens', 'x-ratelimit-remaining-requests', 'x-ratelimit-reset-tokens',
                          'x-ratelimit-reset-requests')

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, **kwargs):
        super().__init__(api_key, model, **kwargs)

    def extra_body(self) -> dict:
        return reasoning_params(self.model)

    def max_tokens_field(self, max_tokens: int) -> dict:
        return {'max_completion_tokens': max_tokens}
