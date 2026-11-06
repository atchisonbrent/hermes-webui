"""Selected-model writes retain the fork's per-model persistence boundary."""
from urllib.parse import urlparse

import pytest
import yaml

from api import config, models, profiles, routes
from tests.test_session_reasoning_effort import _DummyHandler


def test_new_session_snapshots_its_model_override(tmp_path, monkeypatch):
    cfg = {"agent": {"reasoning_effort": "low", "reasoning_overrides": {"example-model": "high"}}}
    monkeypatch.setattr(config, "get_config_for_profile_home", lambda *args, **kwargs: cfg)
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda profile: str(tmp_path))
    session = models.new_session(workspace=str(tmp_path), model="example-model", profile="default")
    try:
        assert session.reasoning_effort == "high"
    finally:
        models.SESSIONS.pop(session.session_id, None)


def test_explicit_session_choice_wins_even_when_it_equals_profile_default():
    cfg = {"agent": {"reasoning_effort": "low", "reasoning_overrides": {"example-model": "high"}}}
    assert config.resolve_session_reasoning_effort(cfg, session_effort="low", model_id="example-model") == "low"


@pytest.mark.parametrize("selected_model", [None, "example-model"])
def test_session_reasoning_post_preserves_unrelated_model_defaults(tmp_path, monkeypatch, selected_model):
    home = tmp_path / "profile"
    home.mkdir()
    config_path = home / "config.yaml"
    config_path.write_text("agent:\n  reasoning_effort: low\n  reasoning_overrides:\n    other-model: high\n")
    session_dir = home / "sessions"
    session_dir.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", session_dir / "_index.json")
    monkeypatch.setattr(profiles, "get_active_hermes_home", lambda: str(home))
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    monkeypatch.setattr(profiles, "get_hermes_home_for_profile", lambda profile: str(home))
    monkeypatch.setattr(config, "_get_config_path", lambda: config_path)
    monkeypatch.setattr(routes, "_lookup_cli_session_metadata", lambda sid: None)
    monkeypatch.setattr(routes, "get_reasoning_status", lambda **kwargs: {"reasoning_effort": kwargs.get("effort_override", "medium")})
    session = models.Session(session_id="model-reasoning-scope", profile="default", model="example-model", reasoning_effort="low")
    session.save(touch_updated_at=False)
    monkeypatch.setattr(routes, "_get_or_materialize_session", lambda sid: session)
    body = {"session_id": session.session_id, "effort": "medium"}
    if selected_model:
        body["model"] = selected_model
    handler = _DummyHandler(body, command="POST")
    try:
        routes.handle_post(handler, urlparse("/api/reasoning"))
        assert handler.status == 200, handler.payload()
        saved = yaml.safe_load(config_path.read_text())["agent"]
        assert saved["reasoning_overrides"]["other-model"] == "high"
        assert saved["reasoning_effort"] == ("low" if selected_model else "medium")
        if selected_model:
            assert saved["reasoning_overrides"][selected_model] == "medium"
        assert models.Session.load(session.session_id).reasoning_effort == "medium"
    finally:
        models.SESSIONS.pop(session.session_id, None)
        handler.rfile.close()
        handler.wfile.close()
