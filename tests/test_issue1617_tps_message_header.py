"""Regression coverage for the TPS readout that began as issue #1617.

Product decision (revised 2026-11-09):
- one readout, in the composer beside the context indicator, for the latest
  completed turn; the assistant message header no longer carries a TPS chip;
- nothing live while streaming: the live meter divided stream deltas by a span
  that included tool execution, so it read low and kept disappearing;
- do not show placeholder or estimated TPS when unavailable.
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CONFIG_PY = (REPO / "api" / "config.py").read_text(encoding="utf-8")
STREAMING_PY = (REPO / "api" / "streaming.py").read_text(encoding="utf-8")
BOOT_JS = (REPO / "static" / "boot.js").read_text(encoding="utf-8")
INDEX_HTML = (REPO / "static" / "index.html").read_text(encoding="utf-8")
MESSAGES_JS = (REPO / "static" / "messages.js").read_text(encoding="utf-8")
PANELS_JS = (REPO / "static" / "panels.js").read_text(encoding="utf-8")
UI_JS = (REPO / "static" / "ui.js").read_text(encoding="utf-8")
CSS = (REPO / "static" / "style.css").read_text(encoding="utf-8")


def test_tps_is_not_rendered_in_message_headers_or_the_global_titlebar():
    for source, name in ((UI_JS, "ui.js"), (CSS, "style.css"), (MESSAGES_JS, "messages.js")):
        assert "msg-tps-inline" not in source, f"{name}: the header TPS chip was removed"
    assert "_assistantRoleHtml(tsTitle='')" in UI_JS, "assistant headers take no TPS text"
    assert "_formatTurnTps" not in UI_JS and "_setLiveAssistantTps" not in UI_JS
    assert "tpsStat" not in MESSAGES_JS, "live TPS must not target the removed/global titlebar chip"


def test_live_metering_never_renders_a_tps_readout():
    listener_start = MESSAGES_JS.find("source.addEventListener('metering'")
    assert listener_start != -1, "messages.js should listen for metering SSE events"
    listener_end = MESSAGES_JS.find("source.addEventListener('apperror'", listener_start)
    assert listener_end != -1, "apperror listener should follow metering listener"
    listener = MESSAGES_JS[listener_start:listener_end]
    assert "d.tps" not in listener and "Tps" not in listener, (
        "the live meter's span includes tool execution; it must not feed any readout"
    )
    assert "_syncCtxIndicator" in listener, "metering still drives the live context indicator"


def test_live_metering_usage_is_provisional_until_done():
    listener_start = MESSAGES_JS.find("source.addEventListener('metering'")
    assert listener_start != -1, "messages.js should listen for metering SSE events"
    listener_end = MESSAGES_JS.find("source.addEventListener('apperror'", listener_start)
    assert listener_end != -1, "apperror listener should follow metering listener"
    listener = MESSAGES_JS[listener_start:listener_end]

    assert "_mergeUsageForCtxIndicator(d.usage,S.lastUsage||{})" in listener, (
        "live usage should merge through the context indicator usage guard"
    )
    assert ": {...(S.lastUsage||{}),...d.usage}" in listener, (
        "live usage should update the transient usage cache for the indicator"
    )
    assert "_syncCtxIndicator(S.lastUsage)" in listener, (
        "live usage should refresh the context indicator"
    )
    assert "S.session.input_tokens=d.usage.input_tokens" not in listener
    assert "S.session.last_prompt_tokens=d.usage.last_prompt_tokens" not in listener


def test_live_prompt_estimate_reanchors_to_fresh_exact_prompt_tokens():
    assert "_live_prompt_exact_tokens = [0]" in STREAMING_PY, (
        "live prompt estimates need a separate exact-token anchor"
    )
    assert "_real_prompt_tokens = int(_usage.get('last_prompt_tokens') or 0)" in STREAMING_PY
    assert "_real_prompt_tokens != _live_prompt_exact_tokens[0]" in STREAMING_PY
    assert "_live_prompt_estimate_tokens[0] = _real_prompt_tokens" in STREAMING_PY


def test_done_payload_persists_final_tps_when_exact_usage_available():
    assert "usage['tps']" in STREAMING_PY, "done usage payload should include final exact TPS when available"
    assert "output_tokens" in STREAMING_PY and "duration_seconds" in STREAMING_PY, (
        "final TPS should use completed model-call durations, not command-wait wall time"
    )
    assert "d.usage.tps" in MESSAGES_JS, "done handler should read final TPS from the usage payload"
    assert "_recordTurnGenerationTps(lastAsst,d.usage&&d.usage.tps)" in MESSAGES_JS, (
        "done handler should write final TPS onto the last assistant message"
    )
    assert "message._turnTps=tps" in MESSAGES_JS, (
        "the helper should keep the settled message's exact final TPS field"
    )


def test_backend_marks_streaming_metering_availability_explicitly():
    assert "tps_available" in STREAMING_PY, "metering SSE payloads must explicitly say whether TPS is displayable"
    assert "estimated" in STREAMING_PY, "metering SSE payloads must explicitly distinguish estimated readings"
    assert "record_token(stream_id, len(STREAM_PARTIAL_TEXT[stream_id]))" not in STREAMING_PY, (
        "live TPS must not be derived from streamed character count / byte-size estimates"
    )


def test_tps_display_setting_is_default_off_and_persisted():
    assert '"show_tps": False' in CONFIG_PY, "TPS display should be disabled by default"
    assert '"show_tps"' in CONFIG_PY and "_SETTINGS_BOOL_KEYS" in CONFIG_PY, (
        "TPS display should be a persisted boolean WebUI setting"
    )
    assert "settingsShowTps" in INDEX_HTML, "Preferences needs a user-facing TPS display toggle"
    assert "payload.show_tps=showTpsCb.checked" in PANELS_JS, (
        "Preferences autosave should persist the TPS display toggle through /api/settings"
    )
    assert "showTpsCb.checked=!!settings.show_tps" in PANELS_JS, (
        "Settings panel should hydrate the TPS toggle from persisted settings"
    )
    assert "window._showTps=!!s.show_tps" in BOOT_JS, (
        "Boot should hydrate show_tps into a runtime flag"
    )
    assert "window._showTps=false" in BOOT_JS, (
        "Boot fallback should keep TPS hidden when settings cannot load"
    )


def test_tps_display_hot_applies_when_preferences_autosave():
    fn_start = PANELS_JS.find("async function _autosavePreferencesSettings")
    assert fn_start != -1, "preferences autosave function should exist"
    fn_end = PANELS_JS.find("function _retryPreferencesAutosave", fn_start)
    assert fn_end != -1, "retry function should follow preferences autosave"
    fn = PANELS_JS[fn_start:fn_end]
    assert "payload&&payload.show_tps!==undefined" in fn, (
        "TPS preference autosave must detect the show_tps field specifically"
    )
    assert "window._showTps=!!(saved&&saved.show_tps)" in fn, (
        "TPS preference autosave should update the runtime flag from the saved response"
    )
    assert "clearMessageRenderCache" in fn and "renderMessages" in fn, (
        "TPS preference autosave should re-render the open transcript without refresh"
    )


def test_tps_readout_respects_display_setting():
    assert "function isTpsDisplayEnabled()" in UI_JS, "TPS visibility should be centralized"
    assert "return window._showTps===true" in UI_JS, "TPS should only render when explicitly enabled"
    assert "const fixed=isTpsDisplayEnabled()&&Number.isFinite(n)&&n>0" in UI_JS, (
        "the composer readout must be suppressed when the setting is off"
    )
    assert "chip.hidden=!fixed" in UI_JS, "no rate must hide the readout, not show a placeholder"
    assert "window._showTps=showTps;\n  if(typeof _syncComposerTps==='function') _syncComposerTps();" in PANELS_JS
    assert "window._showTps=!!s.show_tps;\n    if(typeof _syncComposerTps==='function') _syncComposerTps();" in BOOT_JS
    assert "window._showTps=false;\n    if(typeof _syncComposerTps==='function') _syncComposerTps();" in BOOT_JS


def test_settled_turn_memo_does_not_depend_on_the_tps_preference():
    start = UI_JS.index("function _settledTurnMemoInput(")
    memo_input = UI_JS[start:UI_JS.index("\nfunction ", start + 1)]
    assert "assistantDisplayName()" in memo_input, "sanity: this is the settled-turn memo input"
    assert "isTpsDisplayEnabled" not in memo_input, (
        "message rows no longer render TPS; toggling it must not rebuild every settled turn"
    )
