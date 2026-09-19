#!/usr/bin/env python3
"""Durable user input rows survive real reload/render without changing turns."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT, fixture, session_route
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(os.environ.get('WEBUI_TEST_ROOT', Path(__file__).resolve().parents[1]))


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
                        for mode in os.environ.get('MODES',os.environ.get('MODE','compact_worklog,transparent_stream,hide_all_activity')).split(','):
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
                                    page.evaluate("async mode=>{window._chatActivityDisplayMode=mode;await loadSession('fixture');renderMessages();renderMessages()}",mode)
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
                                # The accepted answers must not trail a growing live turn.
                                # Real SSE callbacks create later prose/tool rows; repeated
                                # redraws and reload must preserve the receipt boundary.
                                page.evaluate("""async()=>{
                                  const end=performance.now()+5000;
                                  while(!LIVE_STREAMS.fixture?.source&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                                  const source=LIVE_STREAMS.fixture.source;
                                  source.emit('interim_assistant',{text:'Work before the answer',timestamp:4,event_id:'run-fixture:1001'});
                                  if(document.querySelectorAll('.user-input-receipt').length!==4)throw new Error('first scene paint duplicated receipts');
                                  _renderUserInputReceipts();
                                  source.emit('interim_assistant',{text:'Work after the answer',timestamp:10,event_id:'run-fixture:1002'});
                                  source.emit('tool',{name:'terminal',tid:'later-tool',args:{command:'printf later'},timestamp:11});
                                  source.emit('tool_complete',{name:'terminal',tid:'later-tool',result:'later',timestamp:12});
                                }""")
                                timeline=page.evaluate("""mode=>{
                                  const answer=document.querySelector('[data-user-input-id="accepted-answer"]');
                                  const later=Array.from(document.querySelectorAll(mode==='hide_all_activity'?'.assistant-segment':'[data-anchor-scene-row="1"]')).find(n=>n.textContent.includes('Work after the answer'));
                                  const before=Array.from(document.querySelectorAll('[data-anchor-scene-row="1"]')).find(n=>n.textContent.includes('Work before the answer'));
                                  const tool=document.querySelector('[data-anchor-local-id="later-tool"]');
                                  return {afterEarlierProse:mode==='hide_all_activity'?null:!!before&&!!(before.compareDocumentPosition(answer)&Node.DOCUMENT_POSITION_FOLLOWING),answerBeforeProse:!!later&&!!(answer.compareDocumentPosition(later)&Node.DOCUMENT_POSITION_FOLLOWING),
                                    answerBeforeTool:mode!=='transparent_stream'?null:!!tool&&!!(answer.compareDocumentPosition(tool)&Node.DOCUMENT_POSITION_FOLLOWING),
                                    rows:document.querySelectorAll('.user-input-receipt').length};
                                }""",mode)
                                assert timeline==dict(afterEarlierProse=None if mode=='hide_all_activity' else True,answerBeforeProse=True,answerBeforeTool=True if mode=='transparent_stream' else None,rows=4),timeline
                                page.evaluate("""mode=>{
                                  for(const next of ['transparent_stream','hide_all_activity','compact_worklog',mode]){
                                    window._chatActivityDisplayMode=next;renderMessages();_renderUserInputReceipts();
                                    if(document.querySelectorAll('.user-input-receipt').length!==4)throw new Error('receipt count after mode switch '+next);
                                  }
                                }""",mode)
                                screenshots=os.environ.get('SCREENSHOT_DIR')
                                if screenshots:
                                    Path(screenshots).mkdir(parents=True,exist_ok=True)
                                    page.screenshot(path=str(Path(screenshots)/f'live-input-{mode}-{engine}-{width}.png'))
                                growth=page.evaluate("""async mode=>{
                                  const source=LIVE_STREAMS.fixture.source;
                                  const receiptNodes=Array.from(document.querySelectorAll('.user-input-receipt'));
                                  for(let i=0;i<20;i++){
                                    source.emit('tool',{name:'terminal',tid:'growth-'+i,args:{command:'printf progress'},timestamp:20+i*3});
                                    source.emit('tool_complete',{name:'terminal',tid:'growth-'+i,result:'ok',timestamp:21+i*3});
                                    source.emit('interim_assistant',{text:'Later progress '+i+' '+('Continuing work. '.repeat(30)),timestamp:22+i*3,event_id:'run-fixture:'+(1010+i*3)});
                                  }
                                  if(mode!=='hide_all_activity'&&receiptNodes.some(n=>!n.isConnected))throw new Error('streaming rebuilt receipt DOM');
                                  if(mode==='hide_all_activity'){
                                    source.emit('token',{text:'Visible answer continues. '.repeat(500)});
                                    await new Promise(r=>setTimeout(r,150));
                                  }
                                  renderMessages();_renderUserInputReceipts();
                                  for(const g of document.querySelectorAll('.tool-worklog-group')){if(!g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();g.querySelectorAll('.compact-ai-update').forEach(n=>n.open=true);}
                                  const pane=document.getElementById('messages');
                                  pane.scrollTop=pane.scrollHeight;
                                  await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
                                  return {offscreen:Array.from(document.querySelectorAll('.user-input-receipt')).every(n=>n.getBoundingClientRect().bottom<pane.getBoundingClientRect().top),
                                    rows:document.querySelectorAll('.user-input-receipt').length,
                                    nativeUsers:S.messages.filter(m=>m.role==='user').length,
                                    polluted:_projectLiveAnchorActivitySceneForStream(S.activeStreamId).activity_rows.some(r=>r.role==='user_input')};
                                }""",mode)
                                assert growth==dict(offscreen=True,rows=4,nativeUsers=1,polluted=False),growth
                                data['runtime_journal_snapshot']['anchor_activity_scene']=page.evaluate("_projectLiveAnchorActivitySceneForStream(S.activeStreamId)")
                                page.reload(wait_until='load')
                                deadline=time.monotonic()+30
                                while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                    assert time.monotonic()<deadline
                                    page.wait_for_timeout(50)
                                page.evaluate("async mode=>{window._chatActivityDisplayMode=mode;await loadSession('fixture');}",mode)
                                if mode!='hide_all_activity':
                                    assert page.evaluate("""()=>{
                                      const answer=document.querySelector('[data-user-input-id="accepted-answer"]');
                                      const later=Array.from(document.querySelectorAll('[data-anchor-scene-row="1"]')).find(n=>n.textContent.includes('Later progress 19'));
                                      return document.querySelectorAll('.user-input-receipt').length===4&&!!later&&!!(answer.compareDocumentPosition(later)&Node.DOCUMENT_POSITION_FOLLOWING);
                                    }"""),'receipt placement lost on snapshot reload'
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
                                  for(const g of document.querySelectorAll('.tool-worklog-group')){if(!g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();}
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
                                page.evaluate("async()=>{await loadSession('fixture');renderMessages();for(const g of document.querySelectorAll('.tool-worklog-group')){if(!g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();}}")
                                assert page.locator('.user-input-receipt').count()==4
                                cached=page.evaluate("""()=>{
                                  renderMessages();
                                  if(!_sessionHtmlCache.has('fixture'))throw new Error('fixture did not populate HTML cache');
                                  S.session._user_inputs=[...S.session._user_inputs,{input_id:'other-device',kind:'clarify',content:'Other device answer',stream_id:'run-fixture',timestamp:5}];
                                  _sessionHtmlCacheSid='different-session';
                                  let hits=0;const hydrate=_rehydrateTransparentStreamDom;
                                  _rehydrateTransparentStreamDom=(...args)=>{hits++;return hydrate(...args);};
                                  renderMessages();_rehydrateTransparentStreamDom=hydrate;
                                  for(const g of document.querySelectorAll('.tool-worklog-group')){if(!g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();}
                                  return {hits,rows:document.querySelectorAll('.user-input-receipt').length};
                                }""")
                                assert cached==dict(hits=1,rows=5),cached
                                screenshots=os.environ.get('SCREENSHOT_DIR')
                                if screenshots:
                                    Path(screenshots).mkdir(parents=True,exist_ok=True)
                                    page.screenshot(path=str(Path(screenshots)/f'user-input-{engine}-{width}.png'))
                                print(engine,mode,width,result,settled,flush=True)
                                context.close()
                    finally:browser.close()
        finally:
            _terminate_process(process)
            log.close()


if __name__=='__main__':main()
