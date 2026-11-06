#!/usr/bin/env python3
"""Native worklog presentation with real DOM and isolated synthetic transport."""
import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT, session_route
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    dict(role='thinking', row_id='think-a', text='Reasoning A', order_index=1),
    dict(role='prose', row_id='update-a', text='Checking the first component.', order_index=2),
    dict(role='tool', row_id='tool-a', order_index=3, tool=dict(name='terminal', id='a', args={'command':'first'}, snippet='First result'), status='completed'),
    dict(role='thinking', row_id='think-b', text='Reasoning B', order_index=4),
    dict(role='prose', row_id='update-b', text='Checking the second component.', order_index=5),
    dict(role='tool', row_id='tool-b', order_index=6, tool=dict(name='terminal', id='b', args={'command':'second'}, snippet='Second result'), status='completed'),
]


def main():
    with tempfile.TemporaryDirectory(prefix='upstream-worklog-') as temp:
        home = Path(temp)
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp, HERMES_HOME=temp, HERMES_BASE_HOME=temp,
                   HERMES_WEBUI_STATE_DIR=str(home/'webui'), HERMES_CONFIG_PATH=str(home/'config.yaml'),
                   HERMES_WEBUI_HOST='127.0.0.1', HERMES_WEBUI_SKIP_ONBOARDING='1',
                   HERMES_WEBUI_AGENT_DIR=str(home/'no-agent'))
        process, log, _, base = _start_webui_server(ROOT, env, home)
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS', 'chromium,webkit').split(','):
                    browser = getattr(pw, engine).launch()
                    try:
                        for width in [390, 1280]:
                            scene = dict(activity_rows=[dict(r, timestamp=r['order_index']) for r in ROWS],
                                         final_answer='All checks complete.', stream_id='native-run', terminal_state='completed')
                            data = dict(session_id='native', messages=[
                                dict(role='user', content='Check both', timestamp=1),
                                dict(role='assistant', content='All checks complete.', timestamp=9,
                                     _anchor_activity_scene=scene, _anchor_stream_id='native-run')],
                                message_count=2, tool_calls=[], workspace=temp, active_stream_id=None,
                                _user_inputs=[dict(input_id='receipt', kind='steer', content='Check the second one too.',
                                                   timestamp=3.5, stream_id='native-run')])
                            context = browser.new_context(viewport={'width': width, 'height': 844}, has_touch=True, bypass_csp=True)
                            context.add_init_script(INIT + """
window.worklogTestErrors=[];
window.addEventListener('error',e=>window.worklogTestErrors.push(String(e.message)));
window.addEventListener('unhandledrejection',e=>window.worklogTestErrors.push(String(e.reason)));
""")
                            page = context.new_page()
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            page.route('**/api/session?*', session_route(data, 'native', temp))
                            page.route('**/api/session/status?*', lambda route: route.fulfill(json={'active_stream_id': None}))
                            for stage in ['load', 'rerender', 'reload']:
                                if stage != 'rerender':
                                    page.goto(base, wait_until='load')
                                    deadline = time.monotonic()+30
                                    while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                        assert time.monotonic() < deadline, errors
                                        page.wait_for_timeout(50)
                                page.evaluate("async()=>{window._chatActivityDisplayMode='compact_worklog';await loadSession('native');clearMessageRenderCache();renderMessages();}")
                                group = page.locator('.tool-worklog-group').first
                                assert group.count() == 1
                                if not group.evaluate("node=>node.classList.contains('open')"):
                                    group.locator('.tool-worklog-summary').tap()
                                assert page.locator('.compact-ai-update').count() == 0, 'Fork-only nested update controls remain'
                                assert group.locator('.tool-card-row').count() == 2
                                assert 'Checking the first component.' in group.text_content()
                                assert 'Checking the second component.' in group.text_content()
                                assert page.locator('[data-user-input-id="receipt"]').count() == 1
                                assert page.locator('.assistant-segment').filter(has_text='All checks complete.').last.is_visible()
                                # Reload abandons the previous document's pending
                                # requests. Judge the current document, not a list
                                # accumulating WebKit teardown errors across pages.
                                current_errors = page.evaluate('window.worklogTestErrors')
                                assert not current_errors, current_errors
                                if errors:
                                    print(engine, width, stage, 'cross-navigation browser reports', len(errors),
                                          'current-document errors', len(current_errors), flush=True)
                                    errors.clear()
                                if stage == 'load' and os.environ.get('SCREENSHOT_DIR'):
                                    target = Path(os.environ['SCREENSHOT_DIR'])
                                    target.mkdir(parents=True, exist_ok=True)
                                    page.screenshot(path=str(target/f'{engine}-{width}-native-worklog.png'))
                                print(engine, width, stage, 'PASS', flush=True)
                            # Positive control: a current-document exception must
                            # reach the same collector used by the acceptance gate.
                            observed = page.evaluate("""async()=>{
                              const seen=new Promise(resolve=>window.addEventListener('unhandledrejection',
                                ()=>resolve(window.worklogTestErrors.slice()),{once:true}));
                              setTimeout(()=>{Promise.reject(new Error('worklog-harness-positive-control'));},0);
                              return await seen;
                            }""")
                            assert any('worklog-harness-positive-control' in error for error in observed), observed
                            context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(process)
            log.close()


if __name__ == '__main__':
    main()
