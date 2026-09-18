#!/usr/bin/env python3
"""Durable user input rows survive real reload/render without changing turns."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT, fixture, session_route
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='input-receipts-') as temp:
        home=Path(temp)
        env={k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,
                   HERMES_WEBUI_STATE_DIR=str(home/'webui'),HERMES_CONFIG_PATH=str(home/'config.yaml'),
                   HERMES_WEBUI_HOST='127.0.0.1',HERMES_WEBUI_SKIP_ONBOARDING='1',
                   HERMES_WEBUI_AGENT_DIR=str(home/'no-agent'))
        process,log,_,base=_start_webui_server(ROOT,env,home)
        try:
            data: dict = dict(session_id='fixture',messages=[dict(role='user',content='Inspect the fixture',timestamp=1)],
                      message_count=1,tool_calls=[],workspace=temp,active_stream_id='run-fixture',
                      pending_user_message='Inspect the fixture',pending_started_at=1,runtime_journal_snapshot=fixture(2))
            data['_user_inputs']=[
                dict(input_id='steer-one',kind='steer',content='Change direction <img src=x onerror="window.bad=true">',stream_id='run-fixture',timestamp=2),
                dict(input_id='answer-one',kind='clarify',content='Yes, save it',stream_id='run-fixture',timestamp=3)]
            initial_inputs=list(data['_user_inputs'])
            other={**data,'session_id':'other','active_stream_id':None,'_user_inputs':[]}
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
                    browser=getattr(pw,engine).launch()
                    try:
                        for width in [1280,390]:
                            data.update(active_stream_id='run-fixture',runtime_journal_snapshot=fixture(2),
                                        messages=[dict(role='user',content='Inspect the fixture',timestamp=1)],message_count=1)
                            data['_user_inputs']=list(initial_inputs)
                            context=browser.new_context(viewport={'width':width,'height':820},bypass_csp=True)
                            context.add_init_script(INIT)
                            page=context.new_page()
                            def get_session(route):
                                payload=dict(data if 'session_id=fixture' in route.request.url else other)
                                if 'messages=0' in route.request.url:payload.pop('_user_inputs',None)
                                route.fulfill(json={'session':payload})
                            def accept(route,kind,input_id,content,timestamp):
                                receipt=dict(input_id=input_id,kind=kind,content=content,stream_id='run-fixture',timestamp=timestamp)
                                data['_user_inputs'].append(receipt)
                                route.fulfill(json={'ok':True,'accepted':True,'display_recorded':True,'user_input':receipt})
                            page.route('**/api/session?*',get_session)
                            page.route('**/api/chat/stream/status?*',lambda r:r.fulfill(json={'active':bool(data['active_stream_id'])}))
                            page.route('**/api/chat/steer',lambda r:accept(r,'steer','accepted-steer','New guidance',4))
                            page.route('**/api/clarify/respond',lambda r:accept(r,'clarify','accepted-answer','New answer',5))
                            for cycle in range(2):
                                page.goto(base,wait_until='load')
                                deadline=time.monotonic()+30
                                while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                    assert time.monotonic()<deadline
                                    page.wait_for_timeout(50)
                                page.evaluate("async()=>{await loadSession('fixture');renderMessages();renderMessages()}")
                                result=page.evaluate("""()=>({rows:document.querySelectorAll('.user-input-receipt').length,
                                  nativeUsers:S.messages.filter(m=>m.role==='user').length,
                                  injected:!!window.bad||!!document.querySelector('.user-input-receipt img')})""")
                                assert result==dict(rows=2,nativeUsers=1,injected=False),result
                            result=page.evaluate("""async()=>{
                              if(!await _trySteer('New guidance',true))throw new Error('steer rejected');
                              _clarifySessionId='fixture';_clarifyId='prompt-one';
                              await respondClarify('New answer');
                              if(S.messages.filter(m=>m.role==='user').length!==1)throw new Error('answer split native turn');
                              _rememberUserInputReceipt('other',{input_id:'foreign',kind:'steer',content:'Wrong session',timestamp:5});
                              S.session={...S.session,_user_inputs:[]};renderMessages();renderMessages();
                              const retained=document.querySelectorAll('.user-input-receipt').length;
                              await loadSession('other');renderMessages();
                              const foreign=document.querySelectorAll('.user-input-receipt').length;
                              await loadSession('fixture');renderMessages();
                              return {retained,foreign,restored:document.querySelectorAll('.user-input-receipt').length};
                            }""")
                            assert result==dict(retained=4,foreign=0,restored=4),result
                            page.evaluate("""async()=>{
                              const end=performance.now()+5000;
                              while(!LIVE_STREAMS.fixture?.source&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                              if(!LIVE_STREAMS.fixture?.source)throw new Error('reattach did not finish '+JSON.stringify({busy:S.busy,stream:S.activeStreamId,live:Object.keys(LIVE_STREAMS),sid:S.session?.session_id,sources:fixtureSources.map(s=>({url:s.url,state:s.readyState}))}));
                            }""")
                            data.update(active_stream_id=None,runtime_journal_snapshot=None,pending_user_message='',
                                        messages=[dict(role='user',content='Inspect the fixture',timestamp=1),dict(role='assistant',content='Complete',timestamp=6)],message_count=2)
                            settled=page.evaluate("""async session=>{
                              const end=performance.now()+5000;let source;
                              while(!(source=LIVE_STREAMS.fixture?.source)&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                              if(!source)throw new Error('no source for terminal event');
                              delete session._user_inputs;
                              source.emit('done',{session});
                              while(S.busy&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                              return {busy:S.busy,rows:document.querySelectorAll('.user-input-receipt').length};
                            }""",data)
                            assert settled==dict(busy=False,rows=4),settled
                            assert page.evaluate("""()=>{
                              const final=Array.from(document.querySelectorAll('.assistant-segment .msg-body')).find(n=>n.textContent.trim()==='Complete');
                              const inputs=Array.from(document.querySelectorAll('.user-input-receipt'));
                              return !!final&&inputs.every(n=>!!(n.compareDocumentPosition(final)&Node.DOCUMENT_POSITION_FOLLOWING));
                            }"""),'accepted inputs must precede final answer'
                            page.reload(wait_until='load')
                            deadline=time.monotonic()+30
                            while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                assert time.monotonic()<deadline
                                page.wait_for_timeout(50)
                            page.evaluate("async()=>{await loadSession('fixture');renderMessages();}")
                            assert page.locator('.user-input-receipt').count()==4
                            cached=page.evaluate("""()=>{
                              renderMessages();
                              if(!_sessionHtmlCache.has('fixture'))throw new Error('fixture did not populate HTML cache');
                              S.session._user_inputs=[...S.session._user_inputs,{input_id:'other-device',kind:'clarify',content:'Other device answer',stream_id:'run-fixture',timestamp:5}];
                              _sessionHtmlCacheSid='different-session';
                              let hits=0;const hydrate=_rehydrateTransparentStreamDom;
                              _rehydrateTransparentStreamDom=(...args)=>{hits++;return hydrate(...args);};
                              renderMessages();_rehydrateTransparentStreamDom=hydrate;
                              return {hits,rows:document.querySelectorAll('.user-input-receipt').length};
                            }""")
                            assert cached==dict(hits=1,rows=5),cached
                            screenshots=os.environ.get('SCREENSHOT_DIR')
                            if screenshots:
                                Path(screenshots).mkdir(parents=True,exist_ok=True)
                                page.screenshot(path=str(Path(screenshots)/f'user-input-{engine}-{width}.png'))
                            print(engine,width,result,settled,flush=True)
                            context.close()
                    finally:browser.close()
        finally:
            _terminate_process(process)
            log.close()


if __name__=='__main__':main()
