"""Drive the page-load stale session-list follow-up from static/sessions.js in node.

The first list request of a page load asks for the server's last cached list
(``allow_stale=1``). A response marked ``stale`` schedules one background
follow-up with ``wait_rebuild=1``, but only once boot is ready and no list
request is in flight, so it never supersedes boot's own refresh.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_extract import extract_function

REPO = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")

_FUNCTIONS = (
    "_sessionListFreshnessQuery",
    "_noteSessionListFreshness",
    "_runSessionListStaleFollowUp",
)

_SCENARIOS = r"""
let _sessionListHasLoadedOnce = false;
let _renderSessionListInFlight = null;
const S = {_bootReady: false};
const timers = [];
function setTimeout(fn, ms){ timers.push({fn, ms}); return timers.length; }
const requests = [];
function _refreshSidebarForBackgroundChurn(){ requests.push(_sessionListFreshnessQuery()); }
function runTimers(){ const due = timers.splice(0); due.forEach(t => t.fn()); return due.length; }
const out = {};

// First page-load request asks for the cached list.
out.firstQuery = _sessionListFreshnessQuery();
_sessionListHasLoadedOnce = true;
out.laterQuery = _sessionListFreshnessQuery();

// A stale response schedules one timer; a second stale response does not add one.
_noteSessionListFreshness({stale: true});
_noteSessionListFreshness({stale: true});
out.timersAfterStale = timers.length;

// Boot not ready: the follow-up re-arms without requesting.
runTimers();
out.requestsBeforeBoot = requests.length;
out.rearmedBeforeBoot = timers.length;

// Boot ready but a list request is in flight: still re-arms.
S._bootReady = true;
_renderSessionListInFlight = Promise.resolve();
runTimers();
out.requestsWhileInFlight = requests.length;
_renderSessionListInFlight = null;

// Now it fires exactly once, with wait_rebuild, and the flag is consumed.
runTimers();
out.followUpRequests = requests.slice();
out.queryAfterFollowUp = _sessionListFreshnessQuery();
out.timersAfterFollowUp = timers.length;

// A fresh response cancels a pending follow-up.
_noteSessionListFreshness({stale: true});
_noteSessionListFreshness({sessions: []});
runTimers();
out.requestsAfterFreshCancel = requests.length;

// Repeated stale responses stop after the cap.
requests.length = 0;
for (let i = 0; i < 10; i++) {
  _noteSessionListFreshness({stale: true});
  runTimers();
}
out.cappedRequests = requests.length;

console.log(JSON.stringify(out));
"""


def _run_scenarios() -> dict:
    src = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")
    decl_start = src.index("let _sessionListServedStale = false;")
    decl_end = src.index("\n", src.index("const _SESSION_LIST_STALE_FOLLOW_UP_MAX"))
    script = "\n".join(
        [src[decl_start:decl_end]]
        + [extract_function(src, name) for name in _FUNCTIONS]
        + [_SCENARIOS]
    )
    proc = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_stale_follow_up_flow():
    out = _run_scenarios()

    assert out["firstQuery"] == "&allow_stale=1"
    assert out["laterQuery"] == ""
    assert out["timersAfterStale"] == 1
    assert out["requestsBeforeBoot"] == 0 and out["rearmedBeforeBoot"] == 1
    assert out["requestsWhileInFlight"] == 0
    assert out["followUpRequests"] == ["&wait_rebuild=1"]
    assert out["queryAfterFollowUp"] == ""
    assert out["timersAfterFollowUp"] == 0
    assert out["requestsAfterFreshCancel"] == 1
    # A fresh response reset the count, so consecutive stale responses get the cap.
    assert out["cappedRequests"] == 3


def test_list_request_appends_freshness_query():
    src = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")
    body = extract_function(src, "_runRenderSessionListRefresh", prefix="async function")
    apply_body = extract_function(src, "_applySessionListPayload")

    assert "_sessionListFreshnessQuery()" in body
    assert body.index("_sessionListQueryString()") < body.index("_sessionListFreshnessQuery()")
    assert "_noteSessionListFreshness(sessData);" in apply_body
