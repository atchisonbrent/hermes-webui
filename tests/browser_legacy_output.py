#!/usr/bin/env python3
"""Older conversations without an Anchor scene retain delivered assistant prose."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(os.environ.get('WEBUI_TEST_ROOT', Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='legacy-output-') as temp:
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp, HERMES_HOME=temp, HERMES_BASE_HOME=temp,
                   HERMES_CONFIG_PATH=str(Path(temp)/'config.yaml'), HERMES_WEBUI_STATE_DIR=str(Path(temp)/'webui'),
                   HERMES_WEBUI_SKIP_ONBOARDING='1', HERMES_WEBUI_AGENT_DIR=str(Path(temp)/'no-agent'), HERMES_WEBUI_HOST='127.0.0.1')
        data = dict(session_id='fixture', messages=[
            dict(role='user', content='Fix the display', timestamp=1),
            dict(role='assistant', content='Delivered important result.', reasoning='Checked the result.', timestamp=4),
            dict(role='assistant', content='Verifying the remaining branch.', timestamp=5,
                 tool_calls=[dict(id='verify',type='function',function=dict(name='terminal',arguments='{}'))]),
            dict(role='tool', tool_call_id='verify', content='checked', timestamp=6),
            dict(role='assistant', content='Verification complete.', timestamp=8)],
            tool_calls=[], message_count=5, workspace=temp,
            _user_inputs=[dict(input_id='steer',kind='steer',content='Include steers too',timestamp=3,stream_id='old-run')])
        proc, log, _, base = _start_webui_server(ROOT, env, Path(temp))
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
                    browser = getattr(pw,engine).launch()
                    try:
                        for mode in ['compact_worklog','transparent_stream','hide_all_activity']:
                            context = browser.new_context(viewport={'width':390,'height':844},bypass_csp=True)
                            context.add_init_script(INIT)
                            page = context.new_page()
                            page.route('**/api/session?*',lambda r:r.fulfill(json={'session':data}))
                            page.route('**/api/chat/stream/status?*',lambda r:r.fulfill(json={'active':False}))
                            page.goto(base,wait_until='load')
                            deadline=time.monotonic()+30
                            while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                assert time.monotonic()<deadline
                                page.wait_for_timeout(50)
                            page.evaluate("async mode=>{window._chatActivityDisplayMode=mode;await loadSession('fixture');renderMessages();}",mode)
                            for stage in ['collapsed','expanded','rerender']:
                                if stage=='rerender':page.evaluate('renderMessages()')
                                result=page.evaluate("""stage=>{
                                  const inner=$('msgInner');
                                  for(const group of inner.querySelectorAll('.tool-worklog-group')){
                                    if(group.classList.contains('open')!==(stage==='expanded'))group.querySelector('.tool-worklog-summary').click();
                                  }
                                  const text=inner.innerText;
                                  const a=text.indexOf('Delivered important result.');
                                  const b=text.indexOf('Verifying the remaining branch.');
                                  const c=text.indexOf('Verification complete.');
                                  return {visible:a>=0&&b>=0,ordered:a<b&&b<c,steerBeforeOutput:text.indexOf('Include steers too')<a,
                                    copies:text.split('Delivered important result.').length-1,busy:S.busy};
                                }""",stage)
                                print(engine,mode,stage,result,flush=True)
                                assert result==dict(visible=True,ordered=True,steerBeforeOutput=True,copies=1,busy=False),result
                            context.close()
                    finally:browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__=='__main__':main()
