import json

from app.llm.openrouter import OpenRouterClient

SCHEMA = {'type': 'object', 'properties': {'a': {'type': 'string'}}, 'required': ['a'], 'additionalProperties': False}


def ok_body(content='{"a":"x"}'):
    return json.dumps({'choices': [{'message': {'content': content}}], 'usage': {'prompt_tokens': 8, 'completion_tokens': 4}})


def make_client(responses, **kwargs):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, json.loads(body)))
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return OpenRouterClient('key', transport=transport, sleep=lambda s: None, **kwargs), calls


def test_request_requires_structured_output_support_and_denies_data_collection():
    client, calls = make_client([(200, {}, ok_body())])
    result = client.complete_json('sys', 'user', SCHEMA)
    url, sent = calls[0]
    assert result.ok and (result.input_tokens, result.output_tokens) == (8, 4)
    assert url == 'https://openrouter.ai/api/v1/chat/completions' and sent['model'] == 'openai/gpt-oss-120b:free'
    assert sent['provider'] == {'require_parameters': True, 'data_collection': 'deny'}
    assert sent['reasoning'] == {'effort': 'low', 'exclude': True}
    assert sent['response_format']['json_schema']['strict'] is True and 'max_tokens' in sent


def test_error_inside_a_200_body_is_returned_as_error():
    body = json.dumps({'error': {'code': 429, 'message': 'Rate limit exceeded: free-models-per-day'}})
    client, _ = make_client([(200, {}, body)])
    result = client.complete_json('sys', 'user', SCHEMA)
    assert not result.ok and result.error_code == 'rate_limited' and 'free-models-per-day' in result.error_message


def test_http_errors_are_mapped():
    for status, code in [(402, 'insufficient_credits'), (401, 'auth'), (404, 'bad_request')]:
        client, _ = make_client([(status, {}, 'no')])
        assert client.complete_json('sys', 'user', SCHEMA).error_code == code
