"""Failure-path coverage for external review identities."""

import json
from types import SimpleNamespace
import pytest
from tests.test_antigravity_sessions import fixture, ID


@pytest.mark.parametrize(
    "field,value",
    [
        ("native_conversation_id", 123),
        ("native_conversation_id", []),
        ("updated_at", 10**400),
    ],
)
def test_bad_sibling_does_not_hide_good_record(tmp_path, field, value):
    from api.antigravity_sessions import list_sessions

    good = fixture(tmp_path)
    bad = dict(good)
    bad["native_conversation_id"] = "22222222-2222-4222-8222-222222222222"
    bad[field] = value
    (tmp_path / "22222222-2222-4222-8222-222222222222.json").write_text(json.dumps(bad))
    assert [r["session_id"] for r in list_sessions(tmp_path)] == ["antigravity_" + ID]


def test_alias_parent_is_supported_but_leaf_symlink_is_not(tmp_path):
    from api.antigravity_sessions import list_sessions

    real = tmp_path / "real"
    fixture(real / "records")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert len(list_sessions(alias / "records")) == 1
    p = real / "records" / (ID + ".json")
    copy = real / "copy.json"
    p.rename(copy)
    p.symlink_to(copy)
    assert list_sessions(alias / "records") == []


@pytest.mark.parametrize("sid", ["antigravity_" + ID, "claude_code_external_fixture"])
def test_missing_metadata_still_cannot_claim_external_identity(
    monkeypatch, tmp_path, sid
):
    import api.routes as routes

    monkeypatch.setattr(routes, "get_cli_sessions", lambda **kw: [])
    monkeypatch.setattr(routes, "_session_index_marks_was_webui", lambda sid: False)
    monkeypatch.setattr(
        routes,
        "get_cli_session_messages",
        lambda *a, **kw: [{"role": "user", "content": "fixture"}],
    )
    monkeypatch.setattr(routes, "_lookup_cli_session_metadata", lambda *a, **kw: {})
    session, reason = routes._claim_or_synthesize_cli_session(sid, cli_meta={})
    assert reason == "not_claimable"
    assert session.read_only is True


@pytest.mark.parametrize("sid", ["antigravity_" + ID, "claude_code_external_fixture"])
def test_lookup_failure_and_profile_mismatch_remain_read_only(monkeypatch, sid):
    import api.routes as routes

    monkeypatch.setattr(
        routes,
        "get_cli_sessions",
        lambda **kw: (_ for _ in ()).throw(OSError("synthetic failure")),
    )
    assert routes._lookup_cli_session_metadata(sid)["read_only"] is True
    assert (
        routes._resolve_cli_import_metadata(sid, requested_profile="work")["read_only"]
        is True
    )


@pytest.mark.parametrize("sid", ["antigravity_" + ID, "claude_code_external_fixture"])
def test_mutation_rejects_external_id_even_if_sidecar_is_writable(monkeypatch, sid):
    import api.routes as routes

    monkeypatch.setattr(
        routes, "get_session", lambda sid: SimpleNamespace(read_only=False)
    )
    with pytest.raises(PermissionError):
        routes._get_or_materialize_session(sid)


@pytest.mark.parametrize(
    "metadata,db_source", [({"source_tag": "antigravity"}, ""), ({}, "antigravity")]
)
def test_antigravity_source_is_nonclaimable_without_extra_flags(metadata, db_source):
    import api.routes as routes

    claimable, reason = routes._is_claimable_cli_source(metadata, db_source)
    assert claimable is False
    assert "antigravity" in reason


def test_reviews_do_not_evict_the_normal_cli_window():
    import api.routes as routes

    reviews = [{"session_id": f"antigravity_{i}", "source_tag": "antigravity",
                "session_source": "external_agent", "is_cli_session": True}
               for i in range(25)]
    cli = [{"session_id": f"cli_{i}", "session_source": "cli"} for i in range(25)]
    retained = routes._cap_recent_cli_sessions(reviews + cli)
    assert [r["session_id"] for r in retained if r in cli] == [r["session_id"] for r in cli[:20]]
    assert [r["session_id"] for r in retained if r in reviews] == [r["session_id"] for r in reviews[:20]]


def test_invalid_native_root_keeps_other_cli_sources(monkeypatch, tmp_path):
    import api.models as models
    import api.antigravity_sessions as native

    expected = [{"session_id": "healthy-cli", "session_source": "cli"}]
    monkeypatch.setattr(models, "_resolve_cli_sessions_context",
                        lambda *a, **kw: (tmp_path, tmp_path / "state.db", None, (str(tmp_path),)))
    monkeypatch.setattr(models, "_load_cli_sessions_uncached", lambda *a, **kw: expected)
    def invalid_root():
        raise RuntimeError("configured home cannot resolve")
    monkeypatch.setattr(native, "_root", invalid_root)
    assert models.get_cli_sessions() == expected


@pytest.mark.parametrize("action", ["create", "revoke"])
def test_share_routes_refuse_projection_before_writes(monkeypatch, action):
    import api.routes as routes
    from urllib.parse import urlparse

    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "_handle_extension_sidecar_proxy", lambda *a, **kw: False)
    monkeypatch.setattr(routes, "_guard_request_session_visibility", lambda *a, **kw: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: {"session_id": "antigravity_" + ID})
    monkeypatch.setattr(routes, "bad", lambda handler, message, status=400: {"status": status})
    def no_write(*args, **kwargs):
        raise AssertionError("native projection must not write a share or sidecar")
    monkeypatch.setattr(routes, "create_or_refresh_share", no_write)
    monkeypatch.setattr(routes, "_build_share_metadata_sidecar", no_write)
    assert routes.handle_post(object(), urlparse("/api/share/" + action)) == {"status": 403}


def test_share_does_not_mislabel_unrelated_permission_error(monkeypatch):
    import api.routes as routes
    from urllib.parse import urlparse

    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "_handle_extension_sidecar_proxy", lambda *a, **kw: False)
    monkeypatch.setattr(routes, "_guard_request_session_visibility", lambda *a, **kw: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: {"session_id": "ordinary"})
    monkeypatch.setattr(routes, "bad", lambda handler, message, status=400: {"status": status})
    def inaccessible(*args, **kwargs):
        raise PermissionError("ordinary storage error")
    monkeypatch.setattr(routes, "_resolve_share_session_pair", inaccessible)
    with pytest.raises(PermissionError, match="ordinary storage"):
        routes.handle_post(object(), urlparse("/api/share/create"))


@pytest.mark.parametrize("sid", ["antigravity_" + ID, "claude_code_legacy"])
def test_public_payload_keeps_legacy_native_identity_read_only(sid):
    from api.helpers import public_session_projection

    original = {"session_id": sid, "read_only": False, "can_resume": True, "title": "Legacy title"}
    result = public_session_projection(original)
    assert result["read_only"] is True
    assert result["can_resume"] is False
    assert result["title"] == "Legacy title"
    assert original["read_only"] is False


@pytest.mark.parametrize("path", [
    "/api/personality/set", "/api/session/toolsets", "/api/session/draft",
    "/api/session/archive", "/api/chat", "/api/chat/start", "/api/session/clear",
    "/api/session/truncate", "/api/session/retry", "/api/session/undo",
    "/api/session/pin", "/api/session/duplicate", "/api/btw", "/api/background",
    "/api/session/delete", "/api/session/worktree/remove", "/api/future-mutator",
])
@pytest.mark.parametrize("sid", ["antigravity_" + ID, "claude_code_legacy"])
def test_direct_metadata_mutators_refuse_native_namespace(monkeypatch, path, sid):
    import api.routes as routes
    from urllib.parse import urlparse

    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "_handle_extension_sidecar_proxy", lambda *a, **kw: False)
    monkeypatch.setattr(routes, "_guard_request_session_visibility", lambda *a, **kw: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: {"session_id": sid, "name": "", "text": "fixture"})
    monkeypatch.setattr(routes, "bad", lambda handler, message, status=400: {"status": status})
    def forbidden(*args, **kwargs):
        raise AssertionError("native metadata mutation must stop before session load")
    monkeypatch.setattr(routes, "get_session", forbidden)
    assert routes.handle_post(SimpleNamespace(command="POST"), urlparse(path)) == {"status": 403}


@pytest.mark.parametrize("sid", ["antigravity_" + ID, "claude_code_legacy"])
@pytest.mark.parametrize("messages", [0, 1])
def test_detail_endpoint_keeps_legacy_native_sidecar_read_only(monkeypatch, sid, messages):
    import api.routes as routes
    import api.session_ops as ops
    from unittest.mock import MagicMock
    from urllib.parse import urlparse

    sidecar = routes.Session(session_id=sid, title="legacy", workspace="", model="fixture",
        messages=[{"role": "user", "content": "native task"}], read_only=False)
    def forbidden(*args, **kwargs):
        raise AssertionError("native detail must not grant regeneration")
    monkeypatch.setattr(routes, "get_session", lambda *a, **kw: sidecar)
    monkeypatch.setattr(routes, "_session_visible_to_active_profile", lambda *a: True)
    monkeypatch.setattr(routes, "_clear_stale_stream_state", lambda *a: None)
    monkeypatch.setattr(routes, "_lookup_cli_session_metadata", lambda *a: {})
    monkeypatch.setattr(routes, "get_cli_session_messages", lambda *a, **kw: [])
    monkeypatch.setattr(ops, "regeneration_authority", forbidden)
    monkeypatch.setattr(routes, "j", lambda handler, payload, **kw: payload)
    result = routes.handle_get(MagicMock(), urlparse(f"/api/session?session_id={sid}&messages={messages}&resolve_model=0"))
    assert result["session"]["read_only"] is True
    assert result["session"]["can_resume"] is False
    assert "regeneration_revision" not in result["session"]


def test_import_refresh_of_legacy_native_sidecar_does_not_save(monkeypatch):
    import api.routes as routes

    sid = "claude_code_legacy"
    def forbidden_save(*args, **kwargs):
        raise AssertionError("native import refresh must not persist a sidecar")
    existing = SimpleNamespace(profile=None, messages=[], source_tag="claude_code",
        raw_source="claude_code", session_source="external_agent", source_label="Claude Code",
        parent_session_id=None, is_cli_session=True, read_only=False, save=forbidden_save,
        compact=lambda: {"session_id": sid, "read_only": False})
    monkeypatch.setattr(routes.Session, "load", classmethod(lambda cls, value: existing))
    monkeypatch.setattr(routes, "_session_visible_to_active_profile", lambda *a: True)
    monkeypatch.setattr(routes, "_resolve_cli_import_metadata", lambda *a, **kw: routes._external_review_identity(sid))
    monkeypatch.setattr(routes, "get_cli_session_messages", lambda *a, **kw: [{"role": "user", "content": "actual native task"}])
    monkeypatch.setattr(routes, "j", lambda handler, payload, **kw: payload)
    result = routes._handle_session_import_cli(object(), {"session_id": sid})
    assert result["session"]["read_only"] is True
    assert result["session"]["can_resume"] is False
    assert result["imported"] is False


@pytest.mark.parametrize("loader", ["load", "load_metadata_only"])
@pytest.mark.parametrize("stored_sid", ["claude_code_legacy", "antigravity_" + ID, "ordinary"])
def test_sidecar_loader_refuses_record_identity_alias(monkeypatch, tmp_path, loader, stored_sid):
    import api.models as models
    monkeypatch.setattr(models, "SESSION_DIR", tmp_path)
    record = {"session_id": stored_sid, "title": "fixture", "created_at": 1,
              "updated_at": 1, "message_count": 0, "messages": []}
    # Same file contents that case-insensitive lookup would return, portable to CI.
    alias = stored_sid.upper()
    (tmp_path / (alias + ".json")).write_text(json.dumps(record))
    assert getattr(models.Session, loader)(alias) is None
    (tmp_path / (stored_sid + ".json")).write_text(json.dumps(record))
    assert getattr(models.Session, loader)(stored_sid).session_id == stored_sid


@pytest.mark.parametrize("sid", [" claude_code_legacy", "antigravity_" + ID + " ",
                                 "CLAUDE_CODE_legacy", "Antigravity_" + ID])
@pytest.mark.parametrize("path", ["/api/session/worktree/remove", "/api/session/import_cli"])
def test_native_post_does_not_normalize_malformed_identity(monkeypatch, sid, path):
    import api.routes as routes
    from urllib.parse import urlparse
    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "_handle_extension_sidecar_proxy", lambda *a, **kw: False)
    monkeypatch.setattr(routes, "_guard_request_session_visibility", lambda *a, **kw: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: {"session_id": sid})
    monkeypatch.setattr(routes, "bad", lambda handler, message, status=400: {"status": status})
    def forbidden(*args, **kwargs):
        raise AssertionError("malformed native identity reached session lookup")
    monkeypatch.setattr(routes, "get_session", forbidden)
    monkeypatch.setattr(routes.Session, "load", forbidden)
    assert routes.handle_post(SimpleNamespace(command="POST"), urlparse(path)) == {"status": 403}


@pytest.mark.parametrize("body", [{}, {"session_id": "ordinary"}])
def test_query_native_id_cannot_bypass_post_gate(monkeypatch, body):
    import api.routes as routes
    from urllib.parse import urlparse
    monkeypatch.setattr(routes, "_check_csrf", lambda handler: True)
    monkeypatch.setattr(routes, "_handle_extension_sidecar_proxy", lambda *a, **kw: False)
    monkeypatch.setattr(routes, "_guard_request_session_visibility", lambda *a, **kw: True)
    monkeypatch.setattr(routes, "read_body", lambda handler: body)
    monkeypatch.setattr(routes, "bad", lambda handler, message, status=400: {"status": status})
    def forbidden(*args, **kwargs):
        raise AssertionError("native query identity reached mutation")
    monkeypatch.setattr(routes, "_handle_escape_authorize", forbidden)
    assert routes.handle_post(SimpleNamespace(command="POST"), urlparse(
        "/api/escape/authorize?session_id=CLAUDE_CODE_legacy")) == {"status": 403}


@pytest.mark.parametrize("name", ["handle_upload", "handle_upload_extract", "handle_workspace_upload"])
@pytest.mark.parametrize("sid", ["claude_code_legacy", "Antigravity_" + ID, " CLAUDE_CODE_legacy "])
def test_multipart_native_upload_stops_before_lookup(monkeypatch, name, sid):
    import api.upload as upload
    monkeypatch.setattr(upload, "parse_multipart", lambda *a: (
        {"session_id": sid}, {"file": ("fixture.txt", b"fixture")}))
    monkeypatch.setattr(upload, "j", lambda handler, payload, status=200: {"status": status})
    def forbidden(*args, **kwargs):
        raise AssertionError("native upload reached session lookup")
    monkeypatch.setattr(upload, "get_session", forbidden)
    handler = SimpleNamespace(headers={}, rfile=None)
    assert getattr(upload, name)(handler) == {"status": 403}


@pytest.mark.parametrize("error", [OSError, RuntimeError, ValueError])
def test_native_message_lookup_tolerates_unresolvable_root(monkeypatch, tmp_path, error):
    from api import antigravity_sessions as native
    from pathlib import Path
    def broken(*args, **kwargs):
        raise error("unresolvable test root")
    monkeypatch.setattr(Path, "resolve", broken)
    assert native.session_messages("antigravity_" + ID, tmp_path) == []
    assert native.session_metadata("antigravity_" + ID, tmp_path) is None
    assert native.list_sessions(tmp_path) == []


def test_native_file_view_does_not_persist_workspace_recovery(monkeypatch):
    import api.models as models
    import api.workspace as workspace
    import api.profiles as profiles
    session = SimpleNamespace(session_id='claude_code_legacy', workspace='/missing', profile=None)
    monkeypatch.setattr(models, 'get_session', lambda *a, **kw: session)
    monkeypatch.setattr(profiles, 'get_active_profile_name', lambda: None)
    monkeypatch.setattr(workspace, 'resolve_implicit_workspace_with_recovery', lambda *a: ('/recovered', True))
    def forbidden(*a, **kw):
        raise AssertionError('native read must not rewrite workspace')
    monkeypatch.setattr(models, 'persist_recovered_workspace_binding', forbidden)
    result = models.get_session_for_file_ops(session.session_id)
    assert result.workspace == '/recovered'
    assert session.workspace == '/missing'


def test_native_projection_cannot_create_share_sidecar(monkeypatch):
    import api.routes as routes

    with pytest.raises(PermissionError):
        routes._resolve_share_session_pair("antigravity_" + ID, object())
