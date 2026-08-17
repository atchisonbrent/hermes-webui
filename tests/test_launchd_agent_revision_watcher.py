from pathlib import Path


START = Path(__file__).resolve().parents[1] / "start.sh"


def test_launchd_webui_starts_quiet_agent_revision_watcher():
    script = START.read_text()
    assert 'XPC_SERVICE_NAME:-' in script
    assert 'com.parantoux.hermes-webui' in script
    assert '.hermes/scripts/webui-agent-update-watch.py' in script
    assert 'HERMES_WEBUI_AGENT_WATCH_INTERVAL:-60' in script
    assert 'ps -o lstart=' in script
    assert '_hermes_server_started' in script
    assert '_hermes_current_started' in script
