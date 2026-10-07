"""Read-only projection of native Antigravity review records."""

import json

ID = "11111111-1111-4111-8111-111111111111"


def fixture(root, status="completed"):
    root.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "source": "antigravity",
        "native_conversation_id": ID,
        "model": "gemini-3.8-flash-high",
        "role": "review",
        "effort": "high",
        "workspace": "/fixture",
        "status": status,
        "created_at": 10,
        "updated_at": 20,
        "messages": [
            {"role": "user", "content": "Review all changes"},
            {"role": "assistant", "content": "Verified review report"},
        ],
    }
    (root / (ID + ".json")).write_text(json.dumps(data))
    return data


def test_default_scan_does_not_read_real_home_during_tests(monkeypatch):
    from api.antigravity_sessions import list_sessions

    monkeypatch.delenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR", raising=False)
    assert list_sessions() == []


def test_default_root_respects_configured_hermes_home(monkeypatch, tmp_path):
    from api.antigravity_sessions import list_sessions
    import api.config as config
    from pathlib import Path

    monkeypatch.setattr(
        Path, "home", classmethod(lambda cls: tmp_path / "unrelated-os-home")
    )
    home = tmp_path / "configured-home"
    fixture(home / "review-sessions/antigravity")
    monkeypatch.delenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_TEST_STATE_DIR", raising=False)
    monkeypatch.setattr(config, "_DEFAULT_STATE_HOME", home)
    assert len(list_sessions()) == 1


def test_native_identity_read_only_messages_and_updates(tmp_path):
    from api.antigravity_sessions import list_sessions, session_messages

    root = tmp_path / "reviews"
    expected = fixture(root)
    rows = list_sessions(root)
    assert len(rows) == 1
    row = rows[0]
    assert row["source_tag"] == "antigravity"
    assert row["read_only"] is True
    assert row["can_resume"] is False
    assert row["model"] == "gemini-3.8-flash-high"
    assert session_messages(row["session_id"], root) == expected["messages"]
    expected["messages"][-1]["content"] = "Updated report"
    (root / (ID + ".json")).write_text(json.dumps(expected))
    assert session_messages(row["session_id"], root)[-1]["content"] == "Updated report"


def test_invalid_identity_symlink_and_nonregular_sources_are_skipped(tmp_path):
    from api.antigravity_sessions import list_sessions, session_messages

    root = tmp_path / "reviews"
    data = fixture(root)
    path = root / (ID + ".json")
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(data))
    path.symlink_to(outside)
    assert list_sessions(root) == []
    path.unlink()
    data["native_conversation_id"] = "../../private"
    path.write_text(json.dumps(data))
    assert list_sessions(root) == []
    assert session_messages("antigravity_../../private", root) == []
    import os

    if hasattr(os, "mkfifo"):
        path.unlink()
        os.mkfifo(path)
        assert list_sessions(root) == []


def test_failed_external_scan_preserves_other_cli_sources(monkeypatch, tmp_path):
    import api.models as models
    import api.antigravity_sessions as native

    monkeypatch.setenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setattr(
        native,
        "list_sessions",
        lambda: (_ for _ in ()).throw(OSError("synthetic inaccessible store")),
    )
    monkeypatch.setattr(
        models,
        "get_claude_code_sessions",
        lambda: [
            {
                "session_id": "claude_fixture",
                "source_tag": "claude_code",
                "message_count": 1,
            }
        ],
    )
    models.clear_cli_sessions_cache()
    assert any(
        row["session_id"] == "claude_fixture" for row in models.get_cli_sessions()
    )


def test_import_endpoint_returns_read_only_view_without_persisting(
    monkeypatch, tmp_path
):
    import api.models as models
    import api.routes as routes

    root = tmp_path / "reviews"
    expected = fixture(root)
    monkeypatch.setenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR", str(root))
    models.clear_cli_sessions_cache()
    monkeypatch.setattr(routes.Session, "load", classmethod(lambda cls, sid: None))
    monkeypatch.setattr(routes, "j", lambda handler, payload, **kwargs: payload)
    monkeypatch.setattr(
        routes,
        "import_cli_session",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must remain external")),
    )
    response = routes._handle_session_import_cli(
        object(), {"session_id": "antigravity_" + ID}
    )
    assert response["imported"] is False
    assert response["session"]["read_only"] is True
    assert response["session"]["source_label"] == "Antigravity"
    assert response["session"]["messages"] == expected["messages"]


def test_all_profiles_does_not_duplicate_native_records(monkeypatch, tmp_path):
    import api.models as models

    root = tmp_path / "reviews"
    fixture(root)
    monkeypatch.setenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR", str(root))
    monkeypatch.setattr(
        models,
        "_all_profiles_cli_contexts",
        lambda: (
            [
                (tmp_path / "a", tmp_path / "a.db", "a"),
                (tmp_path / "b", tmp_path / "b.db", "b"),
            ],
            ("fixture",),
        ),
    )
    models.clear_cli_sessions_cache()
    assert (
        len(models.get_cli_sessions(source_filter="antigravity", all_profiles=True))
        == 1
    )


def test_cli_listing_and_detail_dispatch_use_same_adapter(monkeypatch, tmp_path):
    import api.models as models

    root = tmp_path / "reviews"
    expected = fixture(root)
    monkeypatch.setenv("HERMES_WEBUI_ANTIGRAVITY_SESSIONS_DIR", str(root))
    rows = models.get_cli_sessions(source_filter="antigravity")
    assert len(rows) == 1
    assert (
        models.get_cli_session_messages(rows[0]["session_id"]) == expected["messages"]
    )
