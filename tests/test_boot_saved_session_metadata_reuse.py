"""Boot hands its saved-session metadata response to the loadSession() after it.

The root boot path fetches ``/api/session?...&messages=0&resolve_model=0`` to
decide whether the saved session stays sidebar-only, then loadSession() fetched
the identical metadata again. The snapshot is one-shot, session-matched and
short-lived so no later navigation can consume it.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_extract import extract_function

REPO = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")

_SCENARIOS = r"""
let now = 1000;
const Date = { now: () => now };
const meta = sid => ({session: {session_id: sid}});
const out = {};

_bootSavedSessionMetadata = {sid: 'a', data: meta('a'), at: now};
out.match = _takeBootSavedSessionMetadata('a');
out.secondTake = _takeBootSavedSessionMetadata('a');

_bootSavedSessionMetadata = {sid: 'a', data: meta('a'), at: now};
out.otherSid = _takeBootSavedSessionMetadata('b');
out.afterOtherSid = _takeBootSavedSessionMetadata('a');

_bootSavedSessionMetadata = {sid: 'a', data: meta('a'), at: now};
now += _BOOT_SAVED_SESSION_METADATA_MAX_AGE_MS + 1;
out.expired = _takeBootSavedSessionMetadata('a');

_bootSavedSessionMetadata = {sid: 'a', data: meta('z'), at: now};
out.payloadMismatch = _takeBootSavedSessionMetadata('a');

console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_boot_metadata_snapshot_is_one_shot_matched_and_short_lived():
    src = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
    decl_start = src.index("let _bootSavedSessionMetadata=null;")
    decl_end = src.index("\n", src.index("const _BOOT_SAVED_SESSION_METADATA_MAX_AGE_MS"))
    script = "\n".join([
        src[decl_start:decl_end],
        extract_function(src, "_takeBootSavedSessionMetadata"),
        _SCENARIOS,
    ])
    proc = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["match"] == {"session": {"session_id": "a"}}
    assert out["secondTake"] is None
    assert out["otherSid"] is None
    assert out["afterOtherSid"] is None, "any take clears the snapshot"
    assert out["expired"] is None
    assert out["payloadMismatch"] is None


def test_boot_check_records_and_load_session_consumes_snapshot():
    boot = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
    sessions = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")
    helper = extract_function(boot, "_savedSessionSidebarOnlyState", prefix="async function")
    load_body = extract_function(sessions, "loadSession", prefix="async function")

    fetch = "await api(`/api/session?session_id=${encodeURIComponent(sid)}&messages=0&resolve_model=0`);"
    assert helper.index(fetch) < helper.index("_bootSavedSessionMetadata={sid, data, at:Date.now()};")
    take = load_body.index("_takeBootSavedSessionMetadata(sid)")
    assert take < load_body.index(
        "bootMetadata || await api(`/api/session?session_id=${encodeURIComponent(sid)}&messages=0&resolve_model=0`)"
    )
