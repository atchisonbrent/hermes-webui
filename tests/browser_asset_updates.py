#!/usr/bin/env python3
"""Real WebUI + real service worker + a deliberately sticky immutable edge.

Run with a Playwright-equipped venv. Chromium and WebKit retain one browser
context across a file-only hot edit. No routed browser fixtures, disabled SW,
production state, provider calls, purges, or backend restarts. The edge shim
caches only immutable static responses by URL and content encoding; other
routes use the real isolated server. This is not physical iPad validation.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(static_root):
    """Launch real routes with an in-memory CDN shim at the static boundary."""
    import runpy
    import api.config as config
    config.get_static_root = lambda: Path(static_root)
    config.get_index_html_path = lambda: Path(static_root) / 'index.html'
    import api.routes as routes
    original = routes._serve_static
    edge = {}

    class Capture:
        def __init__(self, headers):
            self.headers = headers
            self.sent = []
            self.body = bytearray()
            self.wfile = self
            self.status = None

        def send_response(self, status):
            self.status = status

        def send_header(self, name, value):
            self.sent.append((name, value))

        def end_headers(self):
            pass

        def write(self, value):
            self.body.extend(value)

    def cached_static(handler: BaseHTTPRequestHandler, parsed):
        key = (parsed.path, parsed.query, handler.headers.get('Accept-Encoding', ''))
        cached = edge.get(key)
        hit = cached is not None
        if not hit:
            captured = Capture(handler.headers)
            original(captured, parsed)
            cached = (captured.status, captured.sent, bytes(captured.body))
            if captured.status == 200 and any(
                k.lower() == 'cache-control' and 'immutable' in v for k, v in captured.sent
            ):
                edge[key] = cached
        status, headers, body = cached
        handler.send_response(status)
        for key, value in headers:
            handler.send_header(key, value)
        handler.send_header('X-Test-Edge', 'HIT' if hit else 'MISS')
        handler.end_headers()
        handler.wfile.write(body)
        return True

    routes._serve_static = cached_static
    runpy.run_path(str(ROOT / 'server.py'), run_name='__main__')


def unused_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_health(url, process):
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        assert process.poll() is None, 'isolated server exited before health'
        try:
            with urllib.request.urlopen(url + '/health', timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(.1)
    raise AssertionError('isolated server did not become healthy')


def wait_js(page, expression, arg=None):
    # wait_for_function compiles a string inside the page (blocked by real CSP).
    # Direct debugger evaluations preserve the application's CSP unchanged.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if page.evaluate(expression, arg):
            return
        time.sleep(.1)
    raise AssertionError('Browser condition timed out: ' + expression)


def main():
    from playwright.sync_api import sync_playwright
    results = []
    with tempfile.TemporaryDirectory(prefix='webui-asset-update-') as temp:
        temp = Path(temp)
        static = temp / 'static'
        shutil.copytree(ROOT / 'static', static)
        asset = static / 'sessions.js'
        original = asset.read_bytes()
        port = unused_port()
        url = f'http://127.0.0.1:{port}'
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SYSTEMROOT') if k in os.environ}
        env.update({
            'HOME': str(temp), 'HERMES_HOME': str(temp / 'state'),
            'HERMES_BASE_HOME': str(temp / 'state'),
            'HERMES_WEBUI_STATE_DIR': str(temp / 'state'),
            'HERMES_WEBUI_HOST': '127.0.0.1', 'HERMES_WEBUI_PORT': str(port),
            'HERMES_WEBUI_SKIP_ONBOARDING': '1',
            'HERMES_WEBUI_AGENT_DIR': str(temp / 'no-agent'),
        })
        with (temp / 'server.log').open('w') as log:
            process = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--serve', str(static)],
                cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            )
            try:
                wait_health(url, process)
                with sync_playwright() as playwright:
                    for engine in os.getenv('BROWSERS', 'chromium,webkit').split(','):
                        asset.write_bytes(original + b"\nwindow.__assetProbe = 'old';\n")
                        browser = getattr(playwright, engine).launch(headless=True)
                        context = browser.new_context(viewport={'width': 1024, 'height': 768})
                        try:
                            page = context.new_page()
                            errors = []
                            phase = {'reload': False}
                            page.on('pageerror', lambda error, errors=errors, phase=phase: errors.append((phase['reload'], str(error))))
                            page.goto(url, wait_until='load')
                            wait_js(page, "window.__assetProbe === 'old' && typeof S !== 'undefined' && S._bootReady === true")
                            page.evaluate('navigator.serviceWorker.ready')
                            wait_js(page, 'navigator.serviceWorker.controller !== null')
                            wait_js(page, "caches.keys().then(keys => keys.some(k => k.startsWith('hermes-shell-sha256-')))")
                            old_keys = page.evaluate('caches.keys()')
                            old_url = page.locator('script[src*="sessions.js"]').get_attribute('src')
                            # Populate/check a browser-fetch entry in the synthetic edge.
                            page.evaluate('(u) => fetch(u).then(r => r.text())', old_url)
                            unchanged = page.locator('script[src*="ui.js"]').get_attribute('src')
                            asset.write_bytes(original + b"\nwindow.__assetProbe = 'new';\n")
                            # The old URL really is stale upstream of the browser.
                            stale = page.evaluate("(u) => fetch(u).then(async r => ({edge:r.headers.get('X-Test-Edge'), body:await r.text()}))", old_url)
                            assert stale['edge'] == 'HIT' and "window.__assetProbe = 'old'" in stale['body']
                            phase['reload'] = True
                            page.reload(wait_until='load')
                            phase['reload'] = False
                            wait_js(page, "window.__assetProbe === 'new' && S._bootReady === true")
                            new_url = page.locator('script[src*="sessions.js"]').get_attribute('src')
                            assert old_url != new_url and '?v=sha256-' in new_url
                            assert unchanged == page.locator('script[src*="ui.js"]').get_attribute('src')
                            wait_js(page, '(old) => caches.keys().then(keys => keys.some(k => !old.includes(k)))', arg=old_keys)
                            assert process.poll() is None
                            # WebKit reports a cancelled old-document health probe
                            # as an access-control error during reload. Allow only
                            # that exact lifecycle case and prove current health.
                            meaningful = [(during_reload, message) for during_reload, message in errors
                                          if not (engine == 'webkit' and during_reload
                                                  and '/health?offline_probe=' in message
                                                  and message.endswith('due to access control checks.'))]
                            assert not meaningful, meaningful
                            assert page.evaluate("fetch('health', {cache:'no-store'}).then(r => r.status)") == 200
                            # Closing/reopening a Home-Screen-like window retains storage.
                            page.close()
                            reopened = context.new_page()
                            reopened.goto(url + '/?source=pwa', wait_until='load')
                            wait_js(reopened, "window.__assetProbe === 'new' && S._bootReady === true")
                            results.append({'engine': engine, 'hot_edit': True, 'sticky_edge_proven': True,
                                            'service_worker_enabled': True, 'reopen': True,
                                            'backend_pid': process.pid, 'page_errors': len(meaningful),
                                            'reload_probe_cancellations': len(errors) - len(meaningful)})
                            print(json.dumps(results[-1]), flush=True)
                        finally:
                            context.close()
                            browser.close()
            except Exception:
                log.flush()
                print((temp / 'server.log').read_text()[-4000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                assert process.poll() is not None
    print(json.dumps({'passed': len(results), 'results': results}), flush=True)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--serve':
        serve(sys.argv[2])
    else:
        main()
