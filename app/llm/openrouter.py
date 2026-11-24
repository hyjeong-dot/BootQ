"""OpenRouter 클라이언트. 무료 모델(:free)은 하루 50회(충전 이력이 있으면 1,000회), 분당 20회 제한."""
from app.llm.openai_compat import ChatCompletionsClient

DEFAULT_MODEL = 'openai/gpt-oss-120b:free'


class OpenRouterClient(ChatCompletionsClient):
    url = 'https://openrouter.ai/api/v1/chat/completions'
    rate_limit_headers = ('x-ratelimit-remaining', 'x-ratelimit-reset')

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, reasoning_effort: str = 'low',
                 data_collection: str = 'deny', **kwargs):
        super().__init__(api_key, model, **kwargs)
        self.reasoning_effort = reasoning_effort
        self.data_collection = data_collection

    def extra_body(self) -> dict:
        return {
            'reasoning': {'effort': self.reasoning_effort, 'exclude': True},
            # 구조화 출력을 지원하지 않는 공급자로는 보내지 않고, 프롬프트를 수집하는 공급자는 기본적으로 제외한다
            'provider': {'require_parameters': True, 'data_collection': self.data_collection},
        }
