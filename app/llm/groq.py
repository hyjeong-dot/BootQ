"""Groq 클라이언트. 구조화 출력은 json_schema strict 모드."""
from app.llm.openai_compat import ChatCompletionsClient, Transport, urllib_transport  # noqa: F401

DEFAULT_MODEL = 'openai/gpt-oss-120b'


class GroqClient(ChatCompletionsClient):
    url = 'https://api.groq.com/openai/v1/chat/completions'
    rate_limit_headers = ('x-ratelimit-remaining-tokens', 'x-ratelimit-remaining-requests', 'x-ratelimit-reset-tokens')

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, reasoning_effort: str = 'low', **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.reasoning_effort = reasoning_effort

    def extra_body(self) -> dict:
        return {'reasoning_effort': self.reasoning_effort, 'include_reasoning': False}

    def max_tokens_field(self, max_tokens: int) -> dict:
        return {'max_completion_tokens': max_tokens}
