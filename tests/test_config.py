from app.config import DEFAULT_MODEL, load_env, resolve_model


def test_model_priority_is_cli_then_env_then_default():
    assert resolve_model('groq', 'cli-model', {'GROQ_MODEL': 'env-model'}) == 'cli-model'
    assert resolve_model('groq', None, {'GROQ_MODEL': 'env-model'}) == 'env-model'
    assert resolve_model('groq', None, {}) == DEFAULT_MODEL['groq']
    assert resolve_model('groq', None, {'GROQ_MODEL': '  '}) == DEFAULT_MODEL['groq']


def test_each_provider_reads_its_own_variable():
    env = {'GROQ_MODEL': 'g', 'OPENROUTER_MODEL': 'o'}
    assert resolve_model('groq', None, env) == 'g'
    assert resolve_model('openrouter', None, env) == 'o'


def test_load_env_handles_spaces_quotes_comments_and_keeps_existing(tmp_path):
    path = tmp_path / '.env'
    path.write_text('# 주석\nGROQ_API_KEY = abc \nOPENROUTER_MODEL="m:free"\nKEEP=new\n\nBAD LINE\n', encoding='utf-8')
    env = {'KEEP': 'old'}
    load_env(path, env)
    assert env == {'KEEP': 'old', 'GROQ_API_KEY': 'abc', 'OPENROUTER_MODEL': 'm:free'}


def test_load_env_without_file_does_nothing(tmp_path):
    env = {}
    load_env(tmp_path / 'missing', env)
    assert env == {}
