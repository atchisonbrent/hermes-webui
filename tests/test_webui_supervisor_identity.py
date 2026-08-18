from __future__ import annotations

import os
from types import SimpleNamespace

from api import routes


def health_payload(monkeypatch):
    captured = []
    monkeypatch.setattr(
        routes,
        "_streams_lock_health",
        lambda: {"status": "ok", "active_streams": 0},
    )
    monkeypatch.setattr(
        routes,
        "_run_lifecycle_health",
        lambda: {"active_runs": 0, "runs": [], "last_run_finished_at": None},
    )
    monkeypatch.setattr(routes, "_accept_loop_health", lambda _handler: {"status": "ok"})
    monkeypatch.setattr(
        routes,
        "j",
        lambda _handler, payload, **_kwargs: captured.append(payload) or True,
    )
    routes._handle_health(object(), SimpleNamespace(query=""))
    return captured[0]


def test_health_omits_deployment_identity_when_release_is_unconfigured(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_RELEASE_ID", raising=False)

    payload = health_payload(monkeypatch)

    assert "deployment" not in payload


def test_health_exposes_exact_release_and_process_identity(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_RELEASE_ID", "release-2026.08.17-1")

    payload = health_payload(monkeypatch)

    assert payload["deployment"] == {
        "release_id": "release-2026.08.17-1",
        "pid": os.getpid(),
    }


def test_health_omits_malformed_release_identity(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_RELEASE_ID", "../private/path")

    payload = health_payload(monkeypatch)

    assert "deployment" not in payload
