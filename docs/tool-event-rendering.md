# Tool-event rendering

A tool start or completion updates pending prose and tool state in the Anchor registry before painting the combined scene once, synchronously. The HTML snapshot follows that paint. No timer, debounce, or new throttle is involved.

`_upsertAnchorProcessProse` accepts the existing render option used by `_applyToAnchor`; callers outside tool boundaries retain immediate rendering. Tool-boundary flushes still finish pending Markdown but do not reapply prose already sealed in the registry. Legacy tool rendering remains the fallback when the Anchor renderer declines ownership.

The former `tests/browser_live_scene_energy.py` regression enforced paint-count and DOM-retention guarantees for the retired fork renderer. It was removed during the upstream-first v0.52.458 reconciliation; those are not current presentation guarantees. Current native presentation and history coverage lives in `browser_upstream_worklog.py`, `browser_history_commentary.py`, and `browser_user_input_receipts.py`. `browser_reconnect_scene_redraw.py` and `browser_conversation_lifecycle.py` cover reconnect and settlement separately.

This change does not optimize prose-only scene projection, add activity revisions, virtualize active turns, change recovery durability, or alter streaming cadence. Browser operation counts are not physical-device battery measurements.
