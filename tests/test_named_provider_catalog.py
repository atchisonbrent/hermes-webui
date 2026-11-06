"""Named provider branding is presentation, never a routing migration."""

from tests.test_issue7404_models_discovered_not_allowlist import (
    _provider_group,
    _setup_provider as _setup_upstream_provider,
)


def _setup_provider(monkeypatch, tmp_path, provider_cfg, live_ids):
    config, urllib_requests = _setup_upstream_provider(
        monkeypatch, tmp_path, provider_cfg, live_ids,
    )
    import hermes_cli.models as models

    def owned_catalog_fetch(_key, _url, **_kwargs):
        return list(live_ids)

    # The selected authority's transport is synthetic here. Do not delegate
    # native records to their configured public URLs during this unit suite.
    monkeypatch.setattr(models, "cached_fetch_api_models", owned_catalog_fetch)
    return config, urllib_requests


def test_discoverable_native_catalog_is_authoritative(monkeypatch, tmp_path):
    config, urllib_requests = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True,
        "models": {"retired-model": {}},
        "extra_headers": {"X-Project": "project-a"},
        "api_mode": "chat_completions",
    }, [])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    config.cfg["model"]["default"] = "live-model-a"
    import hermes_cli.models as models
    calls = []

    def fetch(_key, url, **kwargs):
        calls.append({"url": url, "headers": kwargs.get("headers"), "api_mode": kwargs.get("api_mode")})
        return ["live-model-a", "live-model-b"]

    def forbidden(*args, **kwargs):
        raise AssertionError("native authority must not use a different discovery path")

    monkeypatch.setattr(models, "cached_fetch_api_models", fetch)
    monkeypatch.setattr(models, "provider_model_ids", forbidden)
    group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
    assert [m["id"] for m in group["models"]] == ["live-model-a", "live-model-b"]
    assert calls == [{
        "url": "https://cloud.example/v1",
        "headers": {"X-Project": "project-a"},
        "api_mode": "chat_completions",
    }]
    from urllib.parse import urlparse

    # The shared fixture also records unrelated built-in Copilot/token reads.
    # The catalog contract concerns the selected provider's legacy endpoint.
    assert not any(
        urlparse(url).hostname == "cloud.example" for url in urllib_requests
    )


def test_budget_cut_authority_catalog_is_not_published_as_empty(monkeypatch, tmp_path):
    import threading
    import hermes_cli.models as models

    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True, "models": {},
    }, [])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    monkeypatch.setattr(config, "_LIVE_REBUILD_BUDGET_SECONDS", 5.0)
    config.cfg["model"]["default"] = "fresh-model"
    retry_started = threading.Event()
    release_retry = threading.Event()
    published = threading.Event()
    attempts = []
    publications = []
    original_publish = config._save_models_cache_to_disk

    def fetch(_key, _url, **kwargs):
        if kwargs.get("cache_only"):
            return None
        attempts.append(kwargs["timeout"])
        if len(attempts) == 1:
            return None  # Agent reports an unavailable budget-sliced attempt.
        retry_started.set()
        assert release_retry.wait(5)
        return ["fresh-model"]

    def publish(payload, **kwargs):
        publications.append(payload)
        result = original_publish(payload, **kwargs)
        published.set()
        return result

    monkeypatch.setattr(models, "cached_fetch_api_models", fetch)
    monkeypatch.setattr(config._CustomProbeSchedule, "next_timeout", lambda _self:
                        0.01 if not attempts else config.CUSTOM_MODELS_ENDPOINT_TIMEOUT_SECONDS)
    monkeypatch.setattr(config, "_save_models_cache_to_disk", publish)
    try:
        config.get_available_models(force_refresh=True)
        assert retry_started.wait(2), "budget-truncated authority was never retried"
        assert not publications, "partial empty authority entered the long-lived cache"
        assert not (tmp_path / "models_cache.json").exists()
    finally:
        release_retry.set()
    assert published.wait(5)
    assert len(attempts) == 2
    assert attempts == [0.01, config.CUSTOM_MODELS_ENDPOINT_TIMEOUT_SECONDS]
    group = _provider_group(publications[-1], "custom:custom-llm")
    assert [m["id"] for m in group["models"]] == ["fresh-model"]


def test_configured_display_name_does_not_change_route(monkeypatch, tmp_path):
    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "discover_models": False, "models": {"model-a": {}},
    }, [])
    group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
    assert group["provider"] == "Cloud Models"
    assert [m["id"] for m in group["models"]] == ["model-a"]


def test_blank_display_name_keeps_the_default_label(monkeypatch, tmp_path):
    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "   ", "base_url": "https://cloud.example/v1",
        "discover_models": False, "models": {"model-a": {}},
    }, [])
    group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
    assert group["provider"] == "Custom Llm"


def test_cross_provider_slash_selection_keeps_route(monkeypatch, tmp_path):
    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True, "models": {},
    }, ["vendor/new-model"])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    config.cfg["model"] = {"provider": "anthropic", "default": "claude-test"}
    group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
    selected = group["models"][0]["id"]
    assert selected == "@custom:custom-llm:vendor/new-model"
    model, provider, endpoint = config.resolve_model_provider(selected)
    assert model == "vendor/new-model"
    assert provider in {"custom-llm", "custom:custom-llm"}
    assert endpoint == "https://cloud.example/v1"


def test_legacy_prefix_preserves_api_url_alias(monkeypatch, tmp_path):
    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "api": "https://cloud.example/v1",
        "discover_models": True, "models_discovered": True,
    }, [])
    config.cfg["model"] = {"provider": "anthropic", "default": "claude-test"}
    model, provider, endpoint = config.resolve_model_provider(
        "@custom-llm:vendor/new-model",
    )
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
    status = {}
    assert config._read_live_provider_model_ids("named", probe_status=status) == []
    assert status == {"unavailable": True}  # never try another authority
    monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: [])
    status = {}
    assert config._read_live_provider_model_ids("named", probe_status=status) == []
    assert status == {}  # an actual empty catalog is authoritative, not truncated
    monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw:
                        ["cached-model"] if kw.get("cache_only") else None)
    status = {}
    assert config._read_live_provider_model_ids("named", probe_status=status) == ["cached-model"]
    assert status == {}  # Agent's scoped cache recovered the live miss


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
    config, _ = _setup_provider(monkeypatch, tmp_path, {
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
    config, _ = _setup_provider(monkeypatch, tmp_path, {
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
    group = _provider_group(payload, "custom:custom-llm")
    assert "healthy-model" in {m["id"] for m in group["models"]}
    assert not any("ambiguous-model" in m["id"] for g in payload["groups"] for m in g["models"])


def test_over_budget_catalog_does_not_resurrect_settings(monkeypatch, tmp_path):
    import threading

    config, _ = _setup_provider(monkeypatch, tmp_path, {
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
        group = _provider_group(payload, "custom:custom-llm")
        assert [m["id"] for m in group["models"]] == ["model-a"]
        assert group["provider"] == "Cloud Models"
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
        config.invalidate_models_cache()


def test_default_injection_uses_route_id_not_display_name(monkeypatch, tmp_path):
    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "discover_models": True, "models_discovered": True,
    }, ["model-b"])
    groups = [g for g in config.get_available_models(force_refresh=True)["groups"] if g["provider_id"] == "custom:custom-llm"]
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


def test_authority_fetch_uses_the_probe_schedule_timeout(monkeypatch, tmp_path):
    import hermes_cli.models as models

    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True, "models": {},
    }, [])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    calls = []

    def fetch(_key, _url, **kwargs):
        calls.append(kwargs)
        return ["live-model-a"]

    monkeypatch.setattr(config._CustomProbeSchedule, "next_timeout", lambda _self: 0.123)
    monkeypatch.setattr(models, "cached_fetch_api_models", fetch)
    group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
    assert {model["id"] for model in group["models"]} == {"model-a", "live-model-a"}
    assert calls and calls[-1]["timeout"] == 0.123
    assert calls[-1]["api_mode"] is None


def test_failed_authority_keeps_default_and_reports_error(monkeypatch, tmp_path):
    import hermes_cli.models as models

    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "model": "model-a",
        "discover_models": True, "models_discovered": True,
        "models": {"retired-settings-model": {}},
    }, [])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    for response in [None, []]:
        monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: response)
        config.invalidate_models_cache()
        group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
        assert [model["id"] for model in group["models"]] == ["model-a"]
        assert group["models_endpoint_error"]["kind"] == "network"
        assert "retired-settings-model" not in {
            model["id"] for model in group.get("models", []) + group.get("extra_models", [])
        }


def test_budget_fallback_also_survives_completed_publication(monkeypatch, tmp_path):
    import threading
    import hermes_cli.models as models

    config, _ = _setup_provider(monkeypatch, tmp_path, {
        "name": "Cloud Models", "base_url": "https://cloud.example/v1",
        "key_env": "CATALOG_TEST_KEY", "discover_models": True,
        "models_discovered": True, "models": {"retired-settings-model": {}},
    }, [])
    monkeypatch.setenv("CATALOG_TEST_KEY", "test-only-key")
    monkeypatch.setattr(config, "_LIVE_REBUILD_BUDGET_SECONDS", 0.01)
    monkeypatch.setattr(models, "cached_fetch_api_models", lambda *a, **kw: [])
    original = config._read_live_provider_model_ids
    release = threading.Event()
    workers = []

    def slow_read(provider, **kwargs):
        workers.append(threading.current_thread())
        assert release.wait(5)
        return original(provider, **kwargs)

    monkeypatch.setattr(config, "_read_live_provider_model_ids", slow_read)
    try:
        group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
        assert [model["id"] for model in group["models"]] == ["model-a"]
        assert group["provider"] == "Cloud Models"
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            assert not worker.is_alive()
    assert workers, "the real rebuild worker must execute"
    config.invalidate_models_cache()
    group = _provider_group(config.get_available_models(force_refresh=True), "custom:custom-llm")
    assert [model["id"] for model in group["models"]] == ["model-a"]
    assert "retired-settings-model" not in {
        model["id"] for model in group.get("models", []) + group.get("extra_models", [])
    }
def test_discovery_enabled_provider_card_does_not_reuse_retired_models(monkeypatch):
    import api.providers as providers

    cfg = {
        "model": {"default": "model-a", "provider": "custom-llm"},
        "providers": {"custom-llm": {
            "name": "   ", "base_url": "https://cloud.example/v1",
            "model": "model-a", "models": {"retired-settings-model": {}},
            "discover_models": True, "models_discovered": True,
        }},
    }
    monkeypatch.setattr(providers, "get_config", lambda: cfg)
    card = next(row for row in providers.get_providers()["providers"] if row["id"] == "custom:custom-llm")
    assert card["display_name"] == "Custom Llm"
    assert [model["id"] for model in card["models"]] == ["model-a"]

    cfg["providers"]["custom-llm"]["discover_models"] = False
    cfg["providers"]["custom-llm"].pop("models_discovered", None)
    allowlisted = next(row for row in providers.get_providers()["providers"] if row["id"] == "custom:custom-llm")
    assert "retired-settings-model" in {model["id"] for model in allowlisted["models"]}
