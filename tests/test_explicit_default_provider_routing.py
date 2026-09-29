"""A selected provider must survive a stale static catalog and overlapping IDs."""
import pytest
from api import config


@pytest.mark.parametrize('overlap', ['providers', 'custom_providers'])
@pytest.mark.parametrize('base_url', [None, 'https://proxy.example/v1'])
def test_default_provider_selection_survives_catalog_lag(monkeypatch, overlap, base_url):
    cfg = {
        'model': {'provider': 'openai-codex', 'default': 'different-model'},
        'providers': {}, 'custom_providers': [],
    }
    if base_url:
        cfg['model']['base_url'] = base_url
    if overlap == 'providers':
        cfg['providers'] = {'openai-api': {'models': {'gpt-6-astra': {}}}}
    else:
        cfg['custom_providers'] = [{'name': 'other', 'base_url': 'https://other.example/v1',
                                    'models': {'gpt-6-astra': {}}}]
    monkeypatch.setattr(config, 'cfg', cfg)
    monkeypatch.setitem(config._PROVIDER_MODELS, 'openai-codex', [])
    monkeypatch.setattr(config, '_is_plugin_model_provider', lambda _: False)
    encoded = config.model_with_provider_context('gpt-6-astra', 'openai-codex')
    model, provider, resolved_url = config.resolve_model_provider(encoded, explicitly_picked=True)
    assert model == 'gpt-6-astra'
    assert provider == 'openai-codex'
    assert resolved_url == base_url


@pytest.mark.parametrize('provider', ['custom', 'local'])
def test_local_tagged_model_keeps_legacy_endpoint_normalization(monkeypatch, provider):
    monkeypatch.setattr(config, 'cfg', {
        'model': {'provider': provider, 'default': 'other',
                  'base_url': 'http://127.0.0.1:11434/v1'},
    })
    monkeypatch.setattr(config, '_is_plugin_model_provider', lambda _: False)
    encoded = config.model_with_provider_context('qwen2.5-coder:14b', provider)
    assert config.resolve_model_provider(encoded) == (
        'qwen2.5-coder:14b', 'custom', 'http://127.0.0.1:11434/v1')


def test_bare_custom_keeps_named_endpoint_identity(monkeypatch):
    monkeypatch.setattr(config, 'cfg', {
        'model': {'provider': 'custom', 'default': 'other',
                  'base_url': 'http://127.0.0.1:11434/v1'},
        'custom_providers': [{'name': 'local-endpoint',
                              'base_url': 'http://127.0.0.1:11434/v1',
                              'models': {'qwen:14b': {}}}],
    })
    monkeypatch.setattr(config, '_is_plugin_model_provider', lambda _: False)
    encoded = config.model_with_provider_context('qwen:14b', 'custom')
    model, provider, base = config.resolve_model_provider(encoded)
    assert model == 'qwen:14b'
    assert provider == 'custom:local-endpoint'
    assert base == 'http://127.0.0.1:11434/v1'


def test_same_provider_uses_its_own_endpoint_when_global_url_absent(monkeypatch):
    monkeypatch.setattr(config, 'cfg', {
        'model': {'provider': 'openai-codex', 'default': 'other'},
        'providers': {'openai-codex': {'base_url': 'https://proxy.example/v1'}},
    })
    monkeypatch.setattr(config, '_is_plugin_model_provider', lambda _: False)
    encoded = config.model_with_provider_context('gpt-6-astra', 'openai-codex')
    assert config.resolve_model_provider(encoded) == (
        'gpt-6-astra', 'openai-codex', 'https://proxy.example/v1')


def test_named_custom_default_preserves_multi_colon_model(monkeypatch):
    monkeypatch.setattr(config, 'cfg', {
        'model': {'provider': 'custom:agg', 'default': 'other'},
        'custom_providers': [{'name': 'agg', 'base_url': 'https://agg.example/v1',
                              'models': {'foo:bar:baz': {}}}],
    })
    monkeypatch.setattr(config, '_is_plugin_model_provider', lambda _: False)
    encoded = config.model_with_provider_context('foo:bar:baz', 'custom:agg')
    assert config.resolve_model_provider(encoded) == (
        'foo:bar:baz', 'custom:agg', 'https://agg.example/v1')


def test_deliberate_api_selection_remains_api(monkeypatch):
    monkeypatch.setattr(config, 'cfg', {
        'model': {'provider': 'openai-codex', 'default': 'different-model'},
        'providers': {'openai-api': {'base_url': 'https://api.example/v1',
                                     'models': {'gpt-6-astra': {}}}},
    })
    monkeypatch.setattr(config, '_is_plugin_model_provider', lambda _: False)
    encoded = config.model_with_provider_context('gpt-6-astra', 'openai-api')
    assert config.resolve_model_provider(encoded) == (
        'gpt-6-astra', 'openai-api', 'https://api.example/v1')
