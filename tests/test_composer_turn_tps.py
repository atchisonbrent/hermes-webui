"""The composer owns one visible, generation-only turn TPS readout."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STREAMING = (REPO / "api" / "streaming.py").read_text(encoding="utf-8")
INDEX = (REPO / "static" / "index.html").read_text(encoding="utf-8")
MESSAGES = (REPO / "static" / "messages.js").read_text(encoding="utf-8")
UI = (REPO / "static" / "ui.js").read_text(encoding="utf-8")
CSS = (REPO / "static" / "style.css").read_text(encoding="utf-8")


def test_composer_tps_sits_immediately_before_the_context_widget():
    assert INDEX.index('id="composerTps"') < INDEX.index('id="ctxIndicatorWrap"')
    assert INDEX.index('id="composerTps"') > INDEX.index('id="composerStatus"')
    assert ".composer-tps" in CSS


def test_worker_tracks_each_agent_and_restores_history_on_every_exit():
    assert STREAMING.count(
        "_generation_history_start = track_turn_generation_history(agent, _generation_history_starts)"
    ) == 3
    worker_error_exit = STREAMING.index(
        "        put('apperror', _error_payload)",
        STREAMING.index("def _run_agent_streaming("),
    )
    outer_finally = STREAMING.index("    finally:\n", worker_error_exit)
    assert "for _generation_start in reversed(_generation_history_starts):" in STREAMING[outer_finally:]
    finally_body = STREAMING[outer_finally:]
    assert "restore_turn_generation_history(_generation_start)" in finally_body
    assert finally_body.index("for _generation_start in reversed(_generation_history_starts):") < finally_body.index("_settle_pending_steer()")


def test_new_generation_metric_never_exposes_legacy_wall_clock_history():
    assert "_dm['_turnGenerationTps'] = _turn_tps" in STREAMING
    assert "_dm['_turnGenerationRecorded'] = True" in STREAMING
    assert "_turnGenerationTps" in (REPO / "api" / "models.py").read_text(encoding="utf-8")
    assert "message._turnGenerationTps=tps" in MESSAGES
    assert "_recordTurnGenerationTps(lastAsst,d.usage&&d.usage.tps)" in MESSAGES
    assert "_syncComposerTps()" in MESSAGES
    assert "_syncComposerTps" in UI


def test_composer_ignores_legacy_setting_and_preserves_legacy_header_format():
    assert "isTpsDisplayEnabled()?_setComposerTps" not in UI
    assert "isTpsDisplayEnabled()?_syncComposerTps" not in UI
    assert "${fixed} t/s" in UI
    assert "${fixed} tps" in UI


def test_collapsed_composer_hides_only_inside_its_responsive_scope():
    assert ".composer-footer.cf-burger .composer-tps{display:none!important;}" in CSS
    assert ".composer-footer.cf-burger .ctx-indicator-wrap,.composer-tps" not in CSS
