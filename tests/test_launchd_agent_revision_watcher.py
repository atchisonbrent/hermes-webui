from pathlib import Path


START = Path(__file__).resolve().parents[1] / "start.sh"


def test_launchd_webui_does_not_own_its_revision_watcher():
    """start.sh must serve WebUI, not supervise a process that can restart it."""
    script = START.read_text()

    forbidden = (
        "webui-agent-update-watch.py",
        "launchctl",
        "HERMES_WEBUI_AGENT_WATCH_INTERVAL",
        "ps -o lstart=",
        "_hermes_server_started",
        "_hermes_current_started",
    )
    for token in forbidden:
        assert token not in script
