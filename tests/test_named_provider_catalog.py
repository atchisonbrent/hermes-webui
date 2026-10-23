"""Named provider branding is presentation, never a routing migration."""

from tests.test_issue7404_models_discovered_not_allowlist import _provider_group, _setup_provider


def test_configured_display_name_does_not_change_route(monkeypatch, tmp_path):
    config = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "discover_models": False, "models": {"model-a": {}},
    }, [])
    group = _provider_group(config.get_available_models(force_refresh=True), "custom-llm")
    assert group["provider"] == "Cloud Models"
    assert [m["id"] for m in group["models"]] == ["model-a"]


def test_blank_display_name_keeps_the_default_label(monkeypatch, tmp_path):
    config = _setup_provider(monkeypatch, tmp_path, {
        "name": "   ", "base_url": "https://cloud.example/v1",
        "discover_models": False, "models": {"model-a": {}},
    }, [])
    group = _provider_group(config.get_available_models(force_refresh=True), "custom-llm")
    assert group["provider"] == "Custom Llm"


def test_cross_provider_slash_selection_keeps_route(monkeypatch, tmp_path):
    config = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True, "models": {},
    }, ["vendor/new-model"])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    config.cfg["model"] = {"provider": "anthropic", "default": "claude-test"}
    group = _provider_group(config.get_available_models(force_refresh=True), "custom-llm")
    selected = group["models"][0]["id"]
    assert selected == "@custom-llm:vendor/new-model"
    model, provider, endpoint = config.resolve_model_provider(selected)
    assert model == "vendor/new-model"
    assert provider in {"custom-llm", "custom:custom-llm"}
    assert endpoint == "https://cloud.example/v1"


def test_named_live_catalog_uses_owned_connection(monkeypatch):
    import api.config as config
    import hermes_cli.models as models

    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    monkeypatch.setattr(config, "cfg", {"providers": {"named": {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "extra_headers": {"X-Project": "project-a"},
        "discover_models": True, "models_discovered": True,
    }}})
    calls = []

    def fetch(key, url, **kwargs):
        calls.append((key, url, kwargs))
        return ["fresh-model", "fresh-model", "other-model"]

    monkeypatch.setattr(models, "cached_fetch_api_models", fetch)
    monkeypatch.setattr(models, "provider_model_ids", lambda *a, **kw: ["wrong-native-route"])
    assert config._read_live_provider_model_ids("named") == ["fresh-model", "other-model"]
    assert calls[0][0:2] == ("test-only-key", "https://cloud.example/v1")
    assert calls[0][2]["headers"] == {"X-Project": "project-a"}

    for field in ["api", "url", "base_url"]:
        monkeypatch.setattr(config, "cfg", {"providers": {"NaMeD": {
            field: "https://cloud.example/v1", "key_env": "CATALOG_TEST_KEY",
            "discover_models": "true", "models_discovered": True,
        }}})
        assert config._read_live_provider_model_ids("named") == ["fresh-model", "other-model"]
    monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: None)
    assert config._read_live_provider_model_ids("named") == []  # never try another authority


def test_catalog_effort_ladder_is_not_reasoning_boolean(monkeypatch):
    from types import SimpleNamespace
    import sys
    import api.config as config

    monkeypatch.setattr(config, "cfg", {"providers": {"named": {"catalog_provider": "vendor"}}})
    models_dev = SimpleNamespace(get_model_capabilities=lambda **kw: None)
    monkeypatch.setitem(sys.modules, "agent.models_dev", models_dev)
    monkeypatch.setattr(models_dev, "get_model_capabilities", lambda **kw:
                        SimpleNamespace(supports_reasoning=True, reasoning_efforts=("low", "high", "max")))
    assert config._models_dev_reasoning_efforts("new-model", "named") == ["low", "high", "max"]
    monkeypatch.setattr(models_dev, "get_model_capabilities", lambda **kw:
                        SimpleNamespace(supports_reasoning=True, reasoning_efforts=()))
    assert config._models_dev_reasoning_efforts("always-thinking", "named") == []
    calls = []
    def capabilities(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(supports_reasoning=True, reasoning_efforts=None)
    monkeypatch.setattr(models_dev, "get_model_capabilities", capabilities)
    assert config._models_dev_reasoning_efforts("adaptive", "named") == []
    assert calls[-1] == {"provider": "vendor", "model": "adaptive"}
    assert config.coerce_reasoning_effort_for_model("high", "adaptive", provider_id="named") == ""
    monkeypatch.setattr(models_dev, "get_model_capabilities", lambda **kw: None)
    assert config._models_dev_reasoning_efforts("new-unknown", "named") == []
    monkeypatch.setattr(models_dev, "get_model_capabilities", capabilities)
    monkeypatch.setattr(config, "cfg", {"providers": {"named": {}}})
    assert config._models_dev_reasoning_efforts("adaptive", "named") == list(config.VALID_REASONING_EFFORTS)


def test_catalog_efforts_follow_normalized_live_route(monkeypatch):
    import sys
    from types import SimpleNamespace
    import api.config as config

    monkeypatch.setattr(config, "cfg", {"providers": {"NaMeD": {
        "base_url": "https://named.example/v1", "discover_models": True,
        "catalog_provider": "vendor", "models": {"tuned": {"reasoning_efforts": ["high"]}},
    }}})
    calls = []

    def capabilities(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setitem(sys.modules, "agent.models_dev", SimpleNamespace(get_model_capabilities=capabilities))
    for provider in ["named", "custom:named"]:
        assert config._models_dev_reasoning_efforts("unknown", provider) == []
        assert calls[-1] == {"provider": "vendor", "model": "unknown"}
        assert config.coerce_reasoning_effort_for_model("high", "unknown", provider_id=provider) == ""
        assert config.resolve_model_reasoning_efforts("tuned", provider_id=provider) == ["high"]


def test_catalog_failure_does_not_invent_efforts(monkeypatch):
    import sys
    from types import SimpleNamespace
    import api.config as config

    monkeypatch.setattr(config, "cfg", {"providers": {"named": {"catalog_provider": "vendor"}}})
    broken = SimpleNamespace(get_model_capabilities=lambda **kw: (_ for _ in ()).throw(RuntimeError("unavailable")))
    for module in [broken, None]:
        monkeypatch.setitem(sys.modules, "agent.models_dev", module)
        assert config.resolve_model_reasoning_efforts("deepseek/new-model", provider_id="named") == []
        assert config.coerce_reasoning_effort_for_model("high", "deepseek/new-model", provider_id="named") == ""
    config.cfg["providers"]["named"]["models"] = {"deepseek/new-model": {"reasoning_efforts": ["low", "high", "max"]}}
    assert config.resolve_model_reasoning_efforts("deepseek/new-model", provider_id="named") == ["low", "high", "max"]


def test_configured_catalog_failure_never_invents_inventory(monkeypatch, tmp_path):
    import api.config as module
    import hermes_cli.models as models
    reader = module._read_live_provider_model_ids
    config = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True, "models": {"retired-settings-model": {}},
    }, [])
    monkeypatch.setattr(config, "_read_live_provider_model_ids", reader)
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    # Keep this a named provider, not a synthetic entry in the built-in registry.
    # The native fallback still returns a model that must never be requested.
    monkeypatch.setattr(models, "provider_model_ids", lambda *a, **kw: ["wrong-native-model"])
    for response in [None, []]:
        monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: response)
        config.invalidate_models_cache()
        payload = config.get_available_models(force_refresh=True)
        ids = {m["id"] for g in payload["groups"] for key in ["models", "extra_models"] for m in g.get(key, [])}
        assert not {"retired-settings-model", "wrong-native-model"} & ids


def test_discovery_gate_uses_the_selected_record(monkeypatch):
    import api.config as config

    selected = {"name": "named", "base_url": "https://selected.example/v1", "discover_models": False}
    data = {
        "custom_providers": [selected],
        "providers": {"named": {"base_url": "https://shadowed.example/v1", "discover_models": True}},
    }
    assert config._configured_live_provider_record("named", data) is None
    selected["discover_models"] = True
    assert config._configured_live_provider_record("named", data)["base_url"] == "https://selected.example/v1"
    assert config._configured_live_provider_record("custom:named", data)["base_url"] == "https://selected.example/v1"


def test_native_catalogs_keep_their_existing_reader(monkeypatch):
    import api.config as config
    import hermes_cli.models as models

    monkeypatch.setattr(models, "provider_model_ids", lambda *a, **kw: ["native-model"])
    monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("native providers must not use the named custom reader")))
    monkeypatch.setattr(config, "_is_plugin_model_provider", lambda pid: pid == "test-plugin")
    for provider in ["openrouter", "anthropic", "ollama-cloud", "test-plugin"]:
        monkeypatch.setattr(config, "cfg", {"providers": {provider: {
            "base_url": "https://native.example/v1", "discover_models": True,
        }}})
        assert config._read_live_provider_model_ids(provider) == ["native-model"]


def test_ambiguous_catalog_does_not_break_other_providers(monkeypatch, tmp_path):
    import api.config as module
    import hermes_cli.models as models

    reader = module._read_live_provider_model_ids
    config = _setup_provider(monkeypatch, tmp_path, {
        "base_url": "https://healthy.example/v1", "discover_models": True,
        "models_discovered": True,
    }, [])
    config.cfg["providers"].update({
        "named": {"base_url": "https://first.example/v1", "models": {"ambiguous-model": {}}},
        "NaMeD": {"base_url": "https://second.example/v1", "models": {"ambiguous-model": {}}},
    })
    monkeypatch.setattr(config, "_read_live_provider_model_ids", reader)
    monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: ["healthy-model"])
    monkeypatch.setattr(models, "provider_model_ids", lambda *a, **kw: (_ for _ in ()).throw(
        AssertionError("ambiguous route must not fall through")))
    assert reader("named") == []
    payload = config.get_available_models(force_refresh=True)
    group = _provider_group(payload, "custom-llm")
    assert "healthy-model" in {m["id"] for m in group["models"]}
    assert not any("ambiguous-model" in m["id"] for g in payload["groups"] for m in g["models"])


def test_over_budget_catalog_does_not_resurrect_settings(monkeypatch, tmp_path):
    import threading

    config = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "discover_models": True, "models_discovered": True,
        "models": {"retired-settings-model": {}},
    }, [])
    monkeypatch.setattr(config, "_LIVE_REBUILD_BUDGET_SECONDS", 0.01)
    original = config._read_live_provider_model_ids
    release = threading.Event()
    workers = []

    def slow_read(provider):
        workers.append(threading.current_thread())
        assert release.wait(5)
        return original(provider)

    monkeypatch.setattr(config, "_read_live_provider_model_ids", slow_read)
    try:
        payload = config.get_available_models(force_refresh=True)
        group = _provider_group(payload, "custom-llm")
        assert [m["id"] for m in group["models"]] == ["model-a"]
        assert group["provider"] == "Cloud Models"
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
        config.invalidate_models_cache()


def test_default_injection_uses_route_id_not_display_name(monkeypatch, tmp_path):
    config = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "discover_models": True, "models_discovered": True,
    }, ["model-b"])
    groups = [g for g in config.get_available_models(force_refresh=True)["groups"] if g["provider_id"] == "custom-llm"]
    assert len(groups) == 1
    assert groups[0]["provider"] == "Cloud Models"
    assert [m["id"] for m in groups[0]["models"]] == ["model-a", "model-b"]


def test_live_route_refresh_and_failure_stay_on_configured_provider(monkeypatch):
    from urllib.parse import urlparse
    import api.config as config
    import api.routes as routes
    from tests.test_live_models_ttl_cache import _install_provider_model_ids, _patch_live_models_basics

    _patch_live_models_basics(monkeypatch, routes)
    cfg = {"providers": {"named": {"base_url": "https://cloud.example/v1", "discover_models": True}}}
    monkeypatch.setattr(config, "get_config", lambda: cfg)
    _install_provider_model_ids(monkeypatch, lambda *a: (_ for _ in ()).throw(AssertionError("native route forbidden")))
    inventory = ["model-a"]
    monkeypatch.setattr(config, "_read_live_provider_model_ids", lambda pid: list(inventory))
    parsed = urlparse("/api/models/live?provider=named")
    first = routes._handle_live_models(object(), parsed)
    assert [m["id"] for m in first["models"]] == [f"@named:{mid}" for mid in inventory]
    inventory.append("new-model")
    routes._clear_live_models_cache()
    assert [m["id"] for m in routes._handle_live_models(object(), parsed)["models"]] == [f"@named:{mid}" for mid in inventory]
    inventory.clear()
    routes._clear_live_models_cache()
    assert routes._handle_live_models(object(), parsed)["models"] == []
