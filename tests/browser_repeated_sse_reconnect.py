#!/usr/bin/env python3
"""Real SSE handlers survive repeated transport drops without losing a live run."""
import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_reconnect_scene_redraw import INIT, fixture, session_route

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='webui-repeat-sse-') as temp:
        state = Path(temp)
        env = {k: os.environ[k] for k in ('PATH', 'SYSTEMROOT', 'TMPDIR') if k in os.environ}
        env.update(HOME=temp, HERMES_HOME=temp, HERMES_BASE_HOME=temp,
                   HERMES_WEBUI_STATE_DIR=str(state/'webui'), HERMES_CONFIG_PATH=str(state/'config.yaml'),
                   HERMES_WEBUI_HOST='127.0.0.1', HERMES_WEBUI_SKIP_ONBOARDING='1',
                   HERMES_WEBUI_AGENT_DIR=str(state/'no-agent'))
        proc, log, _, base = _start_webui_server(ROOT, env, state)
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS', 'chromium,webkit').split(','):
                    browser = getattr(pw, engine).launch(headless=True)
                    try:
                        for width in (1280, 390):
                            context = browser.new_context(viewport={'width': width, 'height': 844}, bypass_csp=True)
                            context.add_init_script(INIT)
                            page = context.new_page()
                            errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            session = dict(session_id='fixture', messages=[], message_count=0, tool_calls=[], workspace=temp,
                                           active_stream_id='run-fixture', pending_user_message='Inspect the fixture',
                                           pending_started_at=1, runtime_journal_snapshot=fixture(470))
                            page.route('**/api/session?*', session_route(session, 'fixture', temp))
                            page.route('**/api/chat/stream/status?*', lambda r: r.fulfill(json={'active': True}))
                            page.goto(base, wait_until='load')
                            deadline = time.monotonic()+30
                            while not page.evaluate("typeof loadSession==='function' && S._bootReady===true"):
                                assert time.monotonic()<deadline, errors
                                page.wait_for_timeout(50)
                            page.evaluate("async()=>{window._chatActivityDisplayMode='compact_worklog';await loadSession('fixture');}")
                            result=page.evaluate("""async()=>{
                              const wait=async test=>{const end=performance.now()+5000;while(!test()&&performance.now()<end)await new Promise(r=>setTimeout(r,20));if(!test())throw new Error('transport failed to reconnect');};
                              await wait(()=>!!LIVE_STREAMS.fixture?.source);
                              let old;
                              for(let i=0;i<3;i++){
                                const source=LIVE_STREAMS.fixture.source;
                                source.emit('open',{});
                                source.readyState=2;
                                source.emit('error',{});
                                await wait(()=>!!LIVE_STREAMS.fixture?.source&&LIVE_STREAMS.fixture.source!==source);
                                const fresh=LIVE_STREAMS.fixture.source;
                                fresh.emit('open',{});
                                if(!S.busy||S.activeStreamId!=='run-fixture')throw new Error('live run was marked interrupted');
                                // A late event from an obsolete source cannot tear down its successor.
                                if(old){old.emit('error',{});await new Promise(r=>setTimeout(r,50));}
                                if(LIVE_STREAMS.fixture?.source!==fresh)throw new Error('stale transport displaced current source');
                                fresh.emit('tool',{name:'terminal',tid:'after-drop-'+i,args:{command:'printf recovered'},preview:'recovered'});
                                fresh.emit('tool_complete',{name:'terminal',tid:'after-drop-'+i,preview:'recovered',duration:1});
                                old=source;
                              }
                              return {busy:S.busy,tools:document.querySelectorAll('#liveAssistantTurn [data-anchor-row-role="tool"]').length,
                                interrupted:document.getElementById('msgInner').textContent.includes('Connection interrupted:')};
                            }""")
                            assert result == dict(busy=True, tools=473, interrupted=False), result
                            assert not errors, errors
                            print(engine, width, result, flush=True)
                            context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__ == '__main__':
    main()
