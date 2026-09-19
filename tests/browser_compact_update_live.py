#!/usr/bin/env python3
"""Real stream-entrypoint proof of compact update ownership through done/reload."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT, fixture, session_route
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT=Path(__file__).resolve().parents[1]
CHECK="""()=>{
 const turn=$('liveAssistantTurn')||document.querySelector('.assistant-turn');
 const group=turn.querySelector('.tool-worklog-group');
 if(!group)throw new Error('Missing worklog');
 if(!group.classList.contains('open'))group.querySelector('.tool-worklog-summary').click();
 const updates=[...group.querySelectorAll('.compact-ai-update')];
 if(!updates.length)throw new Error('No AI updates');
 const rows=[...group.querySelectorAll('[data-anchor-row-role]')];
 if(rows.some(n=>!n.closest('.compact-ai-update')))throw new Error('Orphan activity');
 const update=updates.find(n=>n.textContent.includes('Checking component A.'));
 if(!update||!update.querySelector('.tool-card-row'))throw new Error('Tool detached from update');
 return {updates:updates.length,rows:rows.length,busy:S.busy};
}"""


def main():
 with tempfile.TemporaryDirectory(prefix='compact-live-hierarchy-') as temp:
  home=Path(temp)
  env={k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT') if k in os.environ}
  env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,HERMES_WEBUI_STATE_DIR=str(home/'webui'),HERMES_CONFIG_PATH=str(home/'config.yaml'),HERMES_WEBUI_HOST='127.0.0.1',HERMES_WEBUI_SKIP_ONBOARDING='1',HERMES_WEBUI_AGENT_DIR=str(home/'no-agent'))
  process,log,_,base=_start_webui_server(ROOT,env,home)
  try:
   with sync_playwright() as pw:
    for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
     browser=getattr(pw,engine).launch()
     try:
      for width in [390,1280]:
       data: dict=dict(session_id='fixture',messages=[dict(role='user',content='Check components',timestamp=1)],message_count=1,tool_calls=[],workspace=temp,active_stream_id='run-fixture',pending_user_message='Check components',pending_started_at=1,runtime_journal_snapshot=fixture(2))
       context=browser.new_context(viewport={'width':width,'height':844},has_touch=True,bypass_csp=True)
       context.add_init_script(INIT)
       page=context.new_page();errors=[]
       page.on('pageerror',lambda e:errors.append(str(e)))
       page.route('**/api/session?*',session_route(data,'fixture',temp))
       page.route('**/api/session/status?*',lambda r:r.fulfill(json={'active_stream_id':data['active_stream_id']}))
       page.route('**/api/chat/stream/status?*',lambda r:r.fulfill(json={'active':bool(data['active_stream_id'])}))
       def persist(route):
        body=route.request.post_data_json
        data['messages'][-1]['_anchor_activity_scene']=body['scene']
        data['messages'][-1]['_anchor_stream_id']=body['stream_id']
        route.fulfill(json={'ok':True})
       page.route('**/api/session/anchor-scene',persist)
       page.goto(base,wait_until='load')
       deadline=time.monotonic()+30
       while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
        assert time.monotonic()<deadline;page.wait_for_timeout(50)
       page.evaluate("async()=>{window._chatActivityDisplayMode='compact_worklog';await loadSession('fixture');}")
       page.evaluate("""async()=>{
        const end=performance.now()+5000;
        while(!LIVE_STREAMS.fixture?.source&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
        const s=LIVE_STREAMS.fixture.source;
        s.emit('reasoning',{text:'Thinking before component A.',timestamp:2,event_id:'run-fixture:1000a'});
        s.emit('interim_assistant',{text:'Checking component A.',timestamp:3,event_id:'run-fixture:1002'});
        s.emit('tool',{name:'terminal',tid:'a',args:{command:'check'},timestamp:4,event_id:'run-fixture:1003'});
        s.emit('tool_complete',{name:'terminal',tid:'a',result:'checked',timestamp:5,event_id:'run-fixture:1004'});
        for(let i=0;i<60;i++)s.emit('interim_assistant',{text:`Progress ${i}: verified.`,timestamp:6+i/100,event_id:`run-fixture:long-${i}`});
        await new Promise(r=>setTimeout(r,150));
       }""")
       print(engine,width,'live',page.evaluate(CHECK),flush=True)
       page.evaluate("""()=>{
        const nodes=[...$('liveAssistantTurn').querySelectorAll('[data-anchor-row-role="prose"]')];
        const update=document.querySelector('.compact-ai-update');update.open=true;
        _renderLiveAnchorActivitySceneForStream(S.activeStreamId,S.session.session_id);
        if(!update.isConnected||!update.open||nodes.some(n=>!n.isConnected))throw new Error('Live redraw lost identity/open state');
       }""")
       data.update(active_stream_id=None,runtime_journal_snapshot=None,pending_user_message='',messages=[dict(role='user',content='Check components',timestamp=1),dict(role='assistant',content='Checking component A.',timestamp=3,tool_calls=[dict(id='a',type='function',function=dict(name='terminal',arguments='{}'))]),dict(role='tool',tool_call_id='a',content='checked',timestamp=5),dict(role='assistant',content='Final confirmation.',timestamp=9)],message_count=4)
       page.evaluate("data=>LIVE_STREAMS.fixture.source.emit('done',{session:data})",data)
       page.wait_for_timeout(150)
       for stage in ['done','rerender','reload']:
        if stage=='rerender':page.evaluate('clearMessageRenderCache();renderMessages();')
        if stage=='reload':
         page.reload(wait_until='load')
         deadline=time.monotonic()+30
         while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
          assert time.monotonic()<deadline;page.wait_for_timeout(50)
         page.evaluate("async()=>{window._chatActivityDisplayMode='compact_worklog';await loadSession('fixture');}")
        print(engine,width,stage,page.evaluate(CHECK),flush=True)
        assert page.locator('.assistant-segment').filter(has_text='Final confirmation.').last.is_visible()
        assert page.locator('.anchor-conversation').count()==0
       assert not [e for e in errors if not (('/api/session/status?' in e or '/health?offline_probe=' in e) and 'due to access control checks' in e)],errors
       context.close()
     finally:browser.close()
  finally:_terminate_process(process);log.close()

if __name__=='__main__':main()
