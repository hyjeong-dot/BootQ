"""OpenAI chat completions 형식을 쓰는 공급자(Groq, OpenRouter)의 공통 클라이언트 (표준 라이브러리만 사용)."""
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable

from app.llm.base import LLMResult

USER_AGENT = 'bootq/0.1'   # 기본 Python User-Agent는 Cloudflare 앞단에서 막히는 경우가 있다

Transport = Callable[[str, dict, bytes, float], tuple[int, dict, str]]


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, dict, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}, response.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode('utf-8', 'replace')
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, {}, str(e)


def error_code_for(status: int) -> str:
    if status == 0:
        return 'network'
    if status == 429:
        return 'rate_limited'
    if status == 413:
        return 'request_too_large'
    if status == 402:
        return 'insufficient_credits'
    if status in (401, 403):
        return 'auth'
    if 400 <= status < 500:
        return 'bad_request'
    return 'server_error'


class ChatCompletionsClient:
    url: str = ''
    rate_limit_headers: tuple[str, ...] = ()

    def __init__(self, api_key: str, model: str, timeout: float = 90.0, max_retries: int = 3,
                 transport: Transport = urllib_transport, sleep: Callable[[float], None] = time.sleep):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    def extra_body(self) -> dict:
        """공급자별 추가 요청 필드 (추론 강도, 라우팅 등)."""
        return {}

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str = 'result',
                      max_tokens: int = 3000) -> LLMResult:
        body = json.dumps({
            'model': self.model,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            'temperature': 0,
            'response_format': {'type': 'json_schema',
                                'json_schema': {'name': schema_name, 'strict': True, 'schema': schema}},
            **self.extra_body(),
            **self.max_tokens_field(max_tokens),
        }, ensure_ascii=False).encode('utf-8')
        headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json',
                   'User-Agent': USER_AGENT}

        started = time.perf_counter()
        status, response_headers, text = 0, {}, ''
        for attempt in range(self.max_retries + 1):
            status, response_headers, text = self._transport(self.url, headers, body, self.timeout)
            retryable = status == 429 or status >= 500 or status == 0
            if status == 200 or not retryable or attempt == self.max_retries:
                break
            wait = float(response_headers.get('retry-after', 0) or 0) if status == 429 else 0
            self._sleep(min(max(wait, 2.0 * (attempt + 1)), 60.0))
        elapsed = round(time.perf_counter() - started, 2)

        meta = {k: response_headers[k] for k in self.rate_limit_headers if k in response_headers}
        if status != 200:
            return LLMResult(None, elapsed_seconds=elapsed, error_code=error_code_for(status),
                             error_message=text[:500], meta=meta)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return LLMResult(None, elapsed_seconds=elapsed, error_code='empty_response', error_message=text[:500], meta=meta)
        if isinstance(data, dict) and data.get('error'):
            # 일부 공급자는 오류를 HTTP 200 본문에 담아 보낸다
            code = data['error'].get('code') if isinstance(data['error'], dict) else None
            return LLMResult(None, elapsed_seconds=elapsed,
                             error_code=error_code_for(code) if isinstance(code, int) else 'provider_error',
                             error_message=json.dumps(data['error'], ensure_ascii=False)[:500], meta=meta)
        try:
            content = data['choices'][0]['message'].get('content')
            usage = data.get('usage', {})
        except (KeyError, IndexError, TypeError, AttributeError):
            return LLMResult(None, elapsed_seconds=elapsed, error_code='empty_response', error_message=text[:500], meta=meta)
        if not content:
            return LLMResult(None, usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0), elapsed,
                             'empty_response', 'content가 비어 있음', meta)
        return LLMResult(content, usage.get('prompt_tokens', 0), usage.get('completion_tokens', 0), elapsed, meta=meta)

    def max_tokens_field(self, max_tokens: int) -> dict:
        return {'max_tokens': max_tokens}
