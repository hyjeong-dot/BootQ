import json

from app.llm.groq import GroqClient, reasoning_params

SCHEMA = {'type': 'object', 'properties': {'a': {'type': 'string'}}, 'required': ['a'], 'additionalProperties': False}


def ok_body(content='{"a":"x"}', prompt=10, completion=5):
    return json.dumps({'choices': [{'message': {'content': content}}],
                       'usage': {'prompt_tokens': prompt, 'completion_tokens': completion}})


def make_client(responses, sleeps=None):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(json.loads(body))
        return responses[min(len(calls) - 1, len(responses) - 1)]

    client = GroqClient('key', transport=transport, sleep=(sleeps.append if sleeps is not None else lambda s: None))
    return client, calls


def test_success_returns_text_tokens_and_remaining_limit():
    client, calls = make_client([(200, {'x-ratelimit-remaining-tokens': '7000'}, ok_body())])
    result = client.complete_json('sys', 'user', SCHEMA)
    assert result.ok and result.text == '{"a":"x"}'
    assert (result.input_tokens, result.output_tokens, result.total_tokens) == (10, 5, 15)
    assert result.meta['x-ratelimit-remaining-tokens'] == '7000'
    sent = calls[0]
    assert sent['response_format']['json_schema']['strict'] is True
    assert sent['include_reasoning'] is False and sent['temperature'] == 0


def test_rate_limit_waits_for_retry_after_then_succeeds():
    sleeps = []
    client, calls = make_client([(429, {'retry-after': '7'}, 'slow down'), (200, {}, ok_body())], sleeps)
    result = client.complete_json('sys', 'user', SCHEMA)
    assert result.ok and len(calls) == 2 and sleeps == [7.0]


def test_errors_are_returned_not_raised():
    for status, code in [(401, 'auth'), (413, 'request_too_large'), (400, 'bad_request'), (0, 'network')]:
        client, _ = make_client([(status, {}, 'boom')])
        result = client.complete_json('sys', 'user', SCHEMA)
        assert not result.ok and result.error_code == code


def test_gives_up_after_max_retries():
    client, calls = make_client([(429, {}, 'limit')])
    result = client.complete_json('sys', 'user', SCHEMA)
    assert result.error_code == 'rate_limited' and len(calls) == client.max_retries + 1


def test_empty_content_is_an_error():
    client, _ = make_client([(200, {}, ok_body(content=''))])
    assert client.complete_json('sys', 'user', SCHEMA).error_code == 'empty_response'


def test_reasoning_params_depend_on_model_family():
    assert reasoning_params('openai/gpt-oss-20b') == {'reasoning_effort': 'low', 'include_reasoning': False}
    assert reasoning_params('qwen/qwen3.8-27b') == {'reasoning_effort': 'none', 'reasoning_format': 'hidden'}
    assert reasoning_params('other/model') == {}
