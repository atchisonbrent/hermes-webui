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
                            context = browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True,bypass_csp=True)
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
                                if mode=='compact_worklog':
                                    page.evaluate("""()=>{
                                      for(const g of document.querySelectorAll('.tool-worklog-group'))if(g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();
                                      if($('msgInner').innerText.includes('Delivered important result.'))throw new Error('Collapsed legacy update leaked');
                                      if(!$('msgInner').innerText.includes('Verification complete.'))throw new Error('Legacy final hidden');
                                    }""")
                                result=page.evaluate("""stage=>{
                                  const inner=$('msgInner');
                                  for(const group of inner.querySelectorAll('.tool-worklog-group')){
                                    if(!group.classList.contains('open'))group.querySelector('.tool-worklog-summary').click();
                                    group.querySelectorAll('.compact-ai-update-activity').forEach(n=>n.open=true);
                                  }
                                  const text=inner.innerText;
                                  const a=text.indexOf('Delivered important result.');
                                  const b=text.indexOf('Verifying the remaining branch.');
                                  const c=text.indexOf('Verification complete.');
                                  return {visible:a>=0&&b>=0,ordered:a<b&&b<c,steerBeforeOutput:text.indexOf('Include steers too')<a,
                                    copies:[...inner.querySelectorAll('.msg-body')].filter(n=>n.textContent.includes('Delivered important result.')&&!n.closest('.assistant-segment-worklog-source')).length,busy:S.busy};
                                }""",stage)
                                if mode=='compact_worklog':
                                    assert page.evaluate("""()=>{
                                      const group=document.querySelector('.tool-worklog-group');
                                      return group.nextElementSibling?.innerText.includes('Verification complete.');
                                    }"""),'Legacy worklog is separated from conclusion'
                                print(engine,mode,stage,result,flush=True)
                                assert result==dict(visible=True,ordered=True,steerBeforeOutput=True,copies=1,busy=False),result
                            if mode=='compact_worklog':
                                # Make updates span many mobile screens without hiding them.
                                page.evaluate("""()=>{
                                  S.messages.splice(2,0,...Array.from({length:40},(_,i)=>({role:'assistant',content:`Progress ${i}. `+'Long update. '.repeat(20),timestamp:4.1+i/100})));
                                  clearMessageRenderCache();renderMessages();
                                }""")
                                summary=page.locator('.tool-worklog-summary').last
                                page.evaluate("$('messages').dispatchEvent(new WheelEvent('wheel',{deltaY:-100,bubbles:true}));")
                                summary.scroll_into_view_if_needed()
                                state = {}
                                initially_open=page.locator('.tool-worklog-group').evaluate("g=>g.classList.contains('open')")
                                for repeat in range(4):
                                    summary.tap()
                                    assert page.locator('.tool-worklog-group').evaluate("g=>g.classList.contains('open')") == (not initially_open if repeat%2==0 else initially_open)
                                    page.wait_for_timeout(1500)
                                    state=page.evaluate("""()=>{
                                      const g=document.querySelector('.tool-worklog-group');
                                      const header=g.querySelector('button').getBoundingClientRect();
                                      return {groups:document.querySelectorAll('.tool-worklog-group').length,
                                        atConclusion:g.nextElementSibling?.innerText.includes('Verification complete.'),
                                        headerVisible:header.bottom>53&&header.top<720,
                                        tools:g.querySelectorAll('.tool-card-row').length};
                                    }""")
                                    assert state==dict(groups=1,atConclusion=True,headerVisible=True,tools=1),state
                                edge=page.evaluate("""()=>{
                                  const group=document.querySelector('.tool-worklog-group');
                                  const blocks=group.parentElement;
                                  const final=group.nextElementSibling;
                                  const empty=document.createElement('div');
                                  empty.className='assistant-segment assistant-segment-anchor';
                                  blocks.appendChild(empty);
                                  _placeSettledCompactWorklogs($('msgInner'));
                                  const excludesPlaceholder=group.nextElementSibling===final;
                                  empty.remove();
                                  const second=group.cloneNode(true);
                                  final.before(second);
                                  _placeSettledCompactWorklogs($('msgInner'));
                                  const observer=new MutationObserver(()=>{});
                                  observer.observe(blocks,{childList:true});
                                  _placeSettledCompactWorklogs($('msgInner'));
                                  const moves=observer.takeRecords().length;
                                  const ordered=group.nextElementSibling===second&&second.nextElementSibling===final;
                                  observer.disconnect();second.remove();
                                  return {excludesPlaceholder,moves,ordered};
                                }""")
                                assert edge==dict(excludesPlaceholder=True,moves=0,ordered=True),edge
                                print(engine,'long-touch',state,'edges',edge,flush=True)
                            context.close()
                    finally:browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__=='__main__':main()
