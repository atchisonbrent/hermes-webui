"""Boot overlaps independent requests instead of serializing them.

Two round trips no longer sit on the page-load path before the restored
conversation paints:

* /api/profile/active starts alongside /api/settings, and the profile bootstrap
  consumes that same in-flight request (same options, same error handling);
* the saved-session sidebar-only check starts before the conversation list is
  awaited, and the check itself consumes the in-flight result for the same
  session id (one-shot; older than 2 s it is re-checked, so the #1694
  sidebar-only decision stays based on a near-current read).
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_extract import extract_function

REPO = Path(__file__).resolve().parent.parent
BOOT_JS = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
NODE = shutil.which("node")

_HELPERS = (
    "_startBootActiveProfileRequest",
    "_takeBootActiveProfileRequest",
    "_prefetchSavedSessionSidebarOnlyState",
    "_takeSavedSessionSidebarOnlyStatePrefetch",
)

_SCENARIOS = r"""
let now = 1000;
const Date = { now: () => now };
const calls = [];
let failProfile = false;
function api(url, opts) {
  calls.push(url);
  if (url.startsWith('/api/profile/active')) {
    return failProfile ? Promise.reject(Object.assign(new Error('401'), {status: 401}))
                       : Promise.resolve({name: 'default', is_default: true});
  }
  const sid = decodeURIComponent(/session_id=([^&]+)/.exec(url)[1]);
  return Promise.resolve({session: {session_id: sid, archived: sid === 'arch'}});
}
(async () => {
  const out = {};

  _startBootActiveProfileRequest();
  const profileRequest = _takeBootActiveProfileRequest();
  out.profileCalls = calls.filter(u => u.startsWith('/api/profile/active')).length;
  out.profile = await profileRequest;
  out.profileSecondTake = _takeBootActiveProfileRequest();

  // A rejected early request must not surface as an unhandled rejection
  // (node would exit non-zero) before the bootstrap awaits it.
  failProfile = true;
  _startBootActiveProfileRequest();
  await new Promise(r => setTimeout(r, 20));
  try { await _takeBootActiveProfileRequest(); out.rejected = false; }
  catch (e) { out.rejected = e.status; }

  calls.length = 0;
  _prefetchSavedSessionSidebarOnlyState('a');
  out.prefetchCalls = calls.length;
  out.stateA = await _savedSessionSidebarOnlyState('a');
  out.callsAfterConsume = calls.length;
  await _savedSessionSidebarOnlyState('a');
  out.callsAfterSecondCheck = calls.length;

  calls.length = 0;
  _prefetchSavedSessionSidebarOnlyState('a');
  out.stateOther = await _savedSessionSidebarOnlyState('arch');
  out.callsOtherSid = calls.length;
  out.leftoverAfterOtherSid = _takeSavedSessionSidebarOnlyStatePrefetch('a');

  calls.length = 0;
  _prefetchSavedSessionSidebarOnlyState('a');
  now += _BOOT_SAVED_SESSION_PREFETCH_MAX_AGE_MS + 1;
  await _savedSessionSidebarOnlyState('a');
  out.callsExpired = calls.length;

  calls.length = 0;
  _prefetchSavedSessionSidebarOnlyState(null);
  out.callsNullSid = calls.length;

  console.log(JSON.stringify(out));
})();
"""


def _declaration(name: str) -> str:
    start = BOOT_JS.index(f"let {name}=")
    return BOOT_JS[start:BOOT_JS.index("\n", start)]


@pytest.mark.skipif(NODE is None, reason="node not on PATH")
def test_prefetch_helpers_are_one_shot_matched_and_bounded():
    script = "\n".join(
        [
            _declaration("_bootActiveProfileRequest"),
            _declaration("_bootSavedSessionStatePrefetch"),
            _declaration("_bootSavedSessionMetadata"),
            BOOT_JS[BOOT_JS.index("const _BOOT_SAVED_SESSION_PREFETCH_MAX_AGE_MS"):].split("\n", 1)[0],
        ]
        + [extract_function(BOOT_JS, name) for name in _HELPERS]
        + [extract_function(BOOT_JS, "_savedSessionSidebarOnlyState", prefix="async function"), _SCENARIOS]
    )
    proc = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert out["profileCalls"] == 1
    assert out["profile"] == {"name": "default", "is_default": True}
    assert out["profileSecondTake"] is None
    assert out["rejected"] == 401, "the consumer still sees the original rejection"
    assert out["prefetchCalls"] == 1
    assert out["stateA"] == {"sidebarOnly": False, "archived": False}
    assert out["callsAfterConsume"] == 1, "the check must reuse the in-flight prefetch"
    assert out["callsAfterSecondCheck"] == 2, "the prefetch is one-shot"
    assert out["stateOther"] == {"sidebarOnly": True, "archived": True}
    assert out["callsOtherSid"] == 2, "a different session id fetches its own state"
    assert out["leftoverAfterOtherSid"] is None, "any check clears the prefetch"
    assert out["callsExpired"] == 2, "an expired prefetch is refetched"
    assert out["callsNullSid"] == 0


def test_prefetch_trust_window_stays_short():
    """#1694: the sidebar-only decision must not rest on a read from seconds earlier."""
    start = BOOT_JS.index("const _BOOT_SAVED_SESSION_PREFETCH_MAX_AGE_MS=")
    value = int(BOOT_JS[start:BOOT_JS.index(";", start)].split("=")[1])
    assert 0 < value <= 3000


def _boot_iife() -> str:
    start = BOOT_JS.index("(async()=>{\n  // Load send key preference")
    return BOOT_JS[start:]


def test_profile_request_starts_before_settings_and_bootstrap_consumes_it():
    boot = _boot_iife()
    assert boot.index("_startBootActiveProfileRequest();") < boot.index("await api('/api/settings')")
    resolver = boot[boot.index("async function _resolveActiveProfileBootstrapState("):]
    resolver = resolver[: resolver.index("const alreadyAttempted")]
    assert "_takeBootActiveProfileRequest()" in resolver
    assert "|| api('/api/profile/active', {redirect401: false})" in resolver


def test_saved_session_check_prefetch_precedes_list_and_is_guarded():
    boot = _boot_iife()
    prefetch = boot.index("_prefetchSavedSessionSidebarOnlyState(localStorage.getItem('hermes-webui-session'))")
    list_await = boot.index("await renderSessionList();")
    assert prefetch < list_await
    guard = boot[boot.rindex("if(", 0, prefetch):prefetch]
    assert "!_prefetchUrlSession" in guard
    assert "!(profileIntent&&profileIntent.hasParam)" in guard
    assert "!_shouldStartFreshPwaChat(_prefetchLaunchAction,_prefetchUrlSession)" in guard
    # The restore still goes through the same check, which consumes the prefetch.
    assert "? await _savedSessionSidebarOnlyState(savedLocal)" in boot
