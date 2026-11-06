#!/usr/bin/env python3
"""Internal retries are not user turns; quoted warnings remain visible."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_reconnect_scene_redraw import INIT, session_route
from test_issue4875_recovery_prompt_filter import RECOVERY_NUDGE
ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory(prefix='nudge-display-') as temp:
        state=Path(temp)
        env={k:os.environ[k] for k in ('PATH','SYSTEMROOT','TMPDIR') if k in os.environ}
        env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,HERMES_WEBUI_STATE_DIR=str(state/'webui'),HERMES_CONFIG_PATH=str(state/'config.yaml'),HERMES_WEBUI_HOST='127.0.0.1',HERMES_WEBUI_SKIP_ONBOARDING='1',HERMES_WEBUI_AGENT_DIR=str(state/'no-agent'))
        proc,log,_,base=_start_webui_server(ROOT,env,state)
        messages=[dict(role='user',content='Investigate'),dict(role='assistant',content='',reasoning='First observation'),dict(role='user',content=RECOVERY_NUDGE),dict(role='assistant',content='Completed',reasoning='Second observation'),dict(role='user',content='Why did I see '+RECOVERY_NUDGE)]
        session=dict(session_id='fixture',messages=messages,message_count=len(messages),tool_calls=[],workspace=temp,active_stream_id=None)
        try:
            with sync_playwright() as pw:
                for engine in ('chromium','webkit'):
                    browser=getattr(pw,engine).launch()
                    try:
                        for width in (1280,390):
                            page=browser.new_page(viewport={'width':width,'height':844})
                            errors=[]
                            page.on('pageerror',lambda error: errors.append(str(error)))
                            page.add_init_script(INIT)
                            page.route('**/api/session?*',session_route(session,'fixture',temp))
                            page.goto(base,wait_until='load')
                            deadline=time.monotonic()+30
                            while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                assert time.monotonic()<deadline
                                page.wait_for_timeout(50)
                            result=page.evaluate("""async(nudge)=>{
                              window._chatActivityDisplayMode='compact_worklog';await loadSession('fixture');
                              const rows=_getVisibleMessagesWithIdx();
                              const standalone=[...document.querySelectorAll('#msgInner .msg-row')].filter(r=>r.textContent.trim()===nudge).length;
                              return {standalone,users:rows.filter(r=>r.m.role==='user').length,final:document.getElementById('msgInner').textContent.includes('Completed'),quote:document.getElementById('msgInner').textContent.includes('Why did I see'),raw:S.messages.length,thinking:document.querySelectorAll('.thinking-card').length};
                            }""",RECOVERY_NUDGE)
                            assert result==dict(standalone=0,users=2,final=True,quote=True,raw=5,thinking=2),result
                            assert not errors,errors
                            print(engine,width,result,flush=True)
                            page.close()
                    finally:browser.close()
        finally:
            _terminate_process(proc)
            log.close()
if __name__=='__main__':main()
