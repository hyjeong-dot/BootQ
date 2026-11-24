"""LLM 경계. 공급자(Groq, OpenRouter 등)가 달라도 같은 반환 타입을 쓴다: 토큰·시간·오류를 같은 방식으로 기록하기 위해서다."""
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class LLMResult:
    text: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0
    error_code: str | None = None      # rate_limited, request_too_large, auth, bad_request, server_error, network, empty_response
    error_message: str = ''
    meta: dict = field(default_factory=dict)   # 공급자가 알려준 남은 한도 등

    @property
    def ok(self) -> bool:
        return self.error_code is None and self.text is not None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str = 'result',
                      max_tokens: int = 3000) -> LLMResult:
        """schema(JSON Schema)를 따르는 JSON 문자열을 text로 돌려준다. 공급자 오류는 예외가 아니라 error_code로 돌려준다."""
        ...
