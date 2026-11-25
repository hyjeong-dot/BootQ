from app.config import DEFAULT_MODEL, load_env, resolve_model


def test_model_priority_is_cli_then_env_then_default():
    assert resolve_model('groq', 'cli-model', {'GROQ_MODEL': 'env-model'}) == 'cli-model'
    assert resolve_model('groq', None, {'GROQ_MODEL': 'env-model'}) == 'env-model'
    assert resolve_model('groq', None, {}) == DEFAULT_MODEL['groq']
    assert resolve_model('groq', None, {'GROQ_MODEL': '  '}) == DEFAULT_MODEL['groq']


def test_openrouter_has_no_default_model():
    assert resolve_model('openrouter', None, {}) is None
    assert resolve_model('openrouter', None, {'OPENROUTER_MODEL': 'x/y:free'}) == 'x/y:free'


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


def test_database_urls_use_env_then_default_and_stay_separate():
    from app.config import DEFAULT_DATABASE_URL, DEFAULT_TEST_DATABASE_URL, database_url, testing_database_url
    assert database_url({}) == DEFAULT_DATABASE_URL
    assert testing_database_url({}) == DEFAULT_TEST_DATABASE_URL != DEFAULT_DATABASE_URL
    env = {'DATABASE_URL': 'postgresql://a/dev', 'TEST_DATABASE_URL': ' postgresql://a/test '}
    assert database_url(env) == 'postgresql://a/dev'
    assert testing_database_url(env) == 'postgresql://a/test'
