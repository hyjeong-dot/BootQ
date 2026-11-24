"""
OpenRouter 클라이언트. 모델 기본값은 두지 않는다: 무료 제공 여부가 자주 바뀌어(예: gpt-oss-120b:free가 사라짐)
기본값이 있으면 뜻하지 않게 유료 모델이 호출되거나 실패할 수 있다. 모델은 .env의 OPENROUTER_MODEL이나 --model로 지정한다.
무료 모델(:free)은 하루 50회(충전 이력이 있으면 1,000회), 분당 20회 제한.
"""
from app.llm.openai_compat import ChatCompletionsClient


class OpenRouterClient(ChatCompletionsClient):
    url = 'https://openrouter.ai/api/v1/chat/completions'
    rate_limit_headers = ('x-ratelimit-remaining', 'x-ratelimit-reset')

    def __init__(self, api_key: str, model: str, reasoning_effort: str = 'low',
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
