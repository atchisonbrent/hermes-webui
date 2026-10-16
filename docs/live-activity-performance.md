# Live activity rendering

Presentation follows upstream v0.52.458. The former fork guarantee that every unchanged tool/thinking node retained its DOM identity across live repaints was retired with the custom compact renderer. Upstream worklog rendering may rebuild rows; no zero-rebuild or physical-device energy claim is made.

Current checks cover native worklog presentation, public commentary versus raw provider replay, accepted-input receipts, and live/history mode behavior:

```sh
./scripts/test.sh tests/test_upstream_ui_presentation.py tests/test_running_dot_energy.py -q
.venv/bin/python tests/browser_upstream_worklog.py
.venv/bin/python tests/browser_history_commentary.py
.venv/bin/python tests/browser_user_input_receipts.py
```

The old `browser_live_scene_energy.py` and `browser_completed_thinking_retention.py` checks enforced the retired retention contract and were removed, not used as current acceptance gates. Historical implementation notes remain explicitly marked in `docs/fork-changes/`.
