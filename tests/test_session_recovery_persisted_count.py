"""Recovery must compare persisted counts, not stale resident session metadata."""

import json

import pytest

from api import background_process as bp
from api import models


@pytest.fixture(autouse=True)
def isolated_sidecars(monkeypatch, tmp_path):
    monkeypatch.setattr(models, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", tmp_path / "_index.json")


def test_recovery_ignores_stale_cached_count_after_sidecar_replacement(monkeypatch):
    sid = "recovery-stale-count"
    persisted = models.Session(session_id=sid, messages=[{"role": "user", "content": "kept"}])
    persisted.save(skip_index=True)
    stale = models.Session(session_id=sid, message_count=80)
    monkeypatch.setitem(models.SESSIONS, sid, stale)

    count = bp.persisted_message_count_for_session(sid)

    assert count == 1
    assert not bp.should_emit_session_updated(1, count)
    assert models.SESSIONS[sid] is stale  # Read-only: do not replace active owners.


def test_recovery_detects_persisted_growth_despite_stale_cached_count(monkeypatch):
    sid = "recovery-new-count"
    persisted = models.Session(session_id=sid, messages=[
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "finished while disconnected"},
    ])
    persisted.save(skip_index=True)
    monkeypatch.setitem(models.SESSIONS, sid, models.Session(session_id=sid, message_count=1))

    count = bp.persisted_message_count_for_session(sid)

    assert count == 2
    assert bp.should_emit_session_updated(1, count)


def test_recovery_rejects_legacy_count_until_vouched_replacement():
    sid = "recovery-legacy-count"
    path = models.SESSION_DIR / f"{sid}.json"
    data = {"session_id": sid, "title": "Legacy", "created_at": 1, "updated_at": 2,
            "messages": [{"role": "user", "content": "first"}]}
    path.write_text(json.dumps(data))
    # The reconnect probe must not parse full legacy transcripts or trust an
    # unmarked count. Normal session loading still preserves the legacy rows.
    assert bp.persisted_message_count_for_session(sid) is None
    assert bp.persisted_message_count_for_session(sid) is None
    loaded = models.Session.load(sid)
    assert loaded is not None
    assert loaded.messages == data["messages"]
    loaded.messages.append({"role": "assistant", "content": "second"})
    loaded.save(skip_index=True)
    assert bp.persisted_message_count_for_session(sid) == 2


def test_recovery_missing_corrupt_and_unsafe_sidecars():
    assert bp.persisted_message_count_for_session("missing-sidecar") is None
    path = models.SESSION_DIR / "corrupt-sidecar.json"
    path.write_text("{invalid")
    assert bp.persisted_message_count_for_session("corrupt-sidecar") is None
    assert bp.persisted_message_count_for_session("../unsafe-sidecar") is None
