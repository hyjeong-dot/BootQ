"""
슬롯필링 호출: 프롬프트 조립(core) → LLM 1회 → 응답 검증(core).

요청 시점 호출이라 타임아웃 15초·재시도 1회로 만든 클라이언트를 쓴다 (05_AI.md 3장).
LLM 클라이언트가 동기(urllib)라 이 함수도 동기다. async 서비스에서는 asyncio.to_thread로 부른다.
최종 실패면 error_code가 채워진 SlotResult를 돌려주고, 호출자는 추천 없음으로 끝낸다 (입력 필드만으로 매칭을 계속하지 않는다).
"""
from app.core.slot_filling import SlotInput, SlotResult, SlotVocab, build_schema, build_system_prompt, build_user_prompt, \
    failed, parse_response
from app.llm.base import LLMClient
from app.llm.groq import GroqClient

SLOT_TIMEOUT_SECONDS = 15.0
SLOT_MAX_RETRIES = 1
SLOT_MAX_TOKENS = 1000      # 출력은 직무·산업 각 3개와 발췌 몇 개뿐이다
SCHEMA_NAME = 'slots'


def make_slot_client(api_key: str, model: str, **kwargs) -> GroqClient:
    """슬롯필링용 Groq 클라이언트 (타임아웃 15초·재시도 1회). kwargs는 테스트용 transport·sleep."""
    return GroqClient(api_key, model, timeout=SLOT_TIMEOUT_SECONDS, max_retries=SLOT_MAX_RETRIES, **kwargs)


def fill_slots(client: LLMClient, slot_input: SlotInput, vocab: SlotVocab, template: str) -> tuple[SlotResult, dict]:
    """(슬롯 결과, 측정값). 측정값은 recorder가 recommendation에 남길 토큰·시간·한도 정보."""
    result = client.complete_json(build_system_prompt(vocab, template), build_user_prompt(slot_input),
                                  build_schema(vocab), SCHEMA_NAME, SLOT_MAX_TOKENS)
    metrics = {'input_tokens': result.input_tokens, 'output_tokens': result.output_tokens,
               'elapsed_seconds': result.elapsed_seconds, 'meta': result.meta}
    if not result.ok:
        return failed(result.error_code or 'empty_response', result.error_message), metrics
    return parse_response(result.text, slot_input, vocab), metrics
