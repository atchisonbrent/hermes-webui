#!/usr/bin/env python3
"""Active-turn pagination must not render partial history as a second worklog.

Real page/loadSession; synthetic API/SSE transport, no provider or user state.
"""
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_reconnect_scene_redraw import INIT, fixture

ROOT = Path(__file__).resolve().parent.parent


def main():
    mode=os.environ.get('MODE','compact_worklog')
    thinking_selector='#liveAssistantTurn '+('.tool-worklog-group ' if mode=='compact_worklog' else '')+'[data-anchor-row-role="thinking"]'
    with tempfile.TemporaryDirectory(prefix='webui-active-page-') as temp:
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
                            context.add_init_script(INIT + """
window.registryTimers=[];
const nativeTimeout=window.setTimeout;
window.setTimeout=function(fn,delay,...args){
  if(delay===600000&&String(fn).includes('_anchorRegistryMap')){
    window.registryTimers.push(fn);return -1;
  }
  return nativeTimeout(fn,delay,...args);
};
""")
                            page = context.new_page()
                            errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            snapshot = fixture(40)
                            snapshot['last_assistant_text'] = 'Work in progress.'
                            snapshot['messages'] = [dict(role='assistant', content='Work in progress.', _live=True)]
                            partial_count=int(os.environ.get('PARTIAL_COUNT','90'))
                            partial = [dict(role='assistant', content='', reasoning=f'Partial thinking {i}', timestamp=11+i)
                                       for i in range(partial_count)]
                            snapshot['anchor_activity_scene']['activity_rows'] += [
                                dict(row_id=f'thinking:{i}', local_id=f'thought-{i}', role='thinking', kind='thinking',
                                     source_event_type='reasoning', status='completed', order_index=40+i,
                                     text=f'Partial thinking {i}') for i in range(partial_count)]
                            session = dict(session_id='fixture', title='Active pagination', model='', workspace=temp,
                                           messages=partial, message_count=101+partial_count, tool_calls=[],
                                           _messages_offset=101, _messages_truncated=True,
                                           active_stream_id='run-fixture', pending_user_message='Inspect the fixture',
                                           pending_started_at=10, runtime_journal_snapshot=snapshot,
                                           _active_turn_boundary=dict(stream_id='run-fixture', user_index=100))
                            history = [dict(role='user' if i%2==0 else 'assistant', content=f'History {i}', timestamp=i/100)
                                       for i in range(100)]
                            full = history + [dict(role='user', content='Transport envelope: Inspect the fixture', timestamp=10)] + partial
                            def route_session(route):
                                query = parse_qs(urlsplit(route.request.url).query)
                                before = int(query.get('msg_before', [len(full)])[0])
                                limit = int(query.get('msg_limit', [len(full)])[0])
                                offset = max(0, before-limit)
                                route.fulfill(json={'session': session | dict(messages=full[offset:before],
                                    _messages_offset=offset, _messages_truncated=offset>0)})
                            page.route('**/api/session?*', route_session)
                            page.route('**/api/chat/stream/status?*', lambda r: r.fulfill(json={'active': True}))
                            page.goto(base, wait_until='load')
                            deadline = time.monotonic()+30
                            while not page.evaluate("typeof loadSession==='function' && S._bootReady===true"):
                                assert time.monotonic()<deadline, errors
                                page.wait_for_timeout(50)
                            page.evaluate("mode=>{window._chatActivityDisplayMode=mode;window._showThinking=true;window._simplifiedToolCalling=true;}",mode)
                            page.evaluate("async()=>await loadSession('fixture')")
                            result = page.evaluate("""selector=>({
                              orphan:S.messages.filter(m=>m.role==='assistant'&&!m._live).length,
                              users:S.messages.filter(m=>m.role==='user').length,
                              tools:document.querySelectorAll('#liveAssistantTurn [data-anchor-row-role="tool"]').length,
                              thinking:document.querySelectorAll(selector).length,
                              busy:S.busy
                            })""",thinking_selector)
                            expected_thinking=0 if mode=='hide_all_activity' else partial_count
                            expected_tools=0 if mode=='hide_all_activity' else 40
                            assert result == dict(orphan=0, users=1, tools=expected_tools, thinking=expected_thinking, busy=True), result
                            page.evaluate("""async()=>{
                              const deadline=performance.now()+5000;
                              while((!registryTimers.length||!LIVE_STREAMS.fixture?.source)&&performance.now()<deadline)await new Promise(r=>setTimeout(r,10));
                              if(!registryTimers.length||!LIVE_STREAMS.fixture?.source)throw new Error('stream and cleanup timer not installed');
                              const registry=window._liveAnchorRegistries.get(S.activeStreamId);
                              for(let i=0;i<3;i++){
                                registryTimers.splice(0).forEach(fn=>fn());
                                if(window._liveAnchorRegistries.get(S.activeStreamId)!==registry)throw new Error('running registry expired');
                              }
                              const source=fixtureSources.findLast(s=>s.url.includes('api/chat/stream?')&&s.readyState===1);
                              source.emit('reasoning',{text:'Thinking after thirty minutes'});
                              await new Promise(r=>setTimeout(r,100));
                              const scene=_projectLiveAnchorActivitySceneForStream(S.activeStreamId,chatActivityMode());
                              if(!scene)throw new Error('live scene lost after timer');
                              if(chatActivityMode()==='compact_worklog'&&[...document.querySelectorAll('#liveAssistantTurn .thinking-card')].some(n=>!n.closest('.tool-worklog-group')))throw new Error('thinking escaped worklog');
                            }""")
                            expected_thinking += 0 if mode=='hide_all_activity' else 1
                            page.evaluate("""()=>{
                              window.redundantSceneRepaints=0;
                              let painted=[];
                              const render=_renderLiveAnchorActivitySceneForStream;
                              _renderLiveAnchorActivitySceneForStream=function(...args){
                                const result=render(...args);
                                const row=document.querySelector('#liveAssistantTurn [data-anchor-scene-row]');
                                if(row)painted.push(row);
                                return result;
                              };
                              const messages=renderMessages;
                              renderMessages=function(...args){
                                painted=[];
                                const result=messages(...args);
                                redundantSceneRepaints+=painted.filter(row=>!row.isConnected).length;
                                return result;
                              };
                            }""")
                            older = page.evaluate("""async()=>{
                              for(let i=0;i<8;i++){
                                document.getElementById('messages').scrollTop=0;
                                _scrollPinned=false;
                                const before=S.messages.filter(m=>msgContent(m).startsWith('History ')).length;
                                let prepend=null;
                                const restore=_restoreMessageViewportAnchor;
                                _restoreMessageViewportAnchor=(anchor,count)=>{prepend=count;return restore(anchor,count);};
                                try{await _loadOlderMessages();}finally{_restoreMessageViewportAnchor=restore;}
                                const addedHistory=S.messages.filter(m=>msgContent(m).startsWith('History ')).length-before;
                                if(prepend!==null&&prepend!==addedHistory)throw new Error('scroll anchor did not follow retained history: '+prepend+' vs '+addedHistory);
                                if(S.messages.some(m=>String(m.reasoning||'').startsWith('Partial thinking')))throw new Error('older page orphaned current thinking');
                                if(S.messages.some(m=>msgContent(m)==='History 99'))break;
                              }
                              return {prompts:S.messages.filter(m=>m.role==='user'&&(m.timestamp??m._ts)===10).length,
                                partial:S.messages.filter(m=>String(m.reasoning||'').startsWith('Partial thinking')).length,
                                history:S.messages.some(m=>msgContent(m)==='History 99'),
                                live:!!document.getElementById('liveAssistantTurn')};
                            }""")
                            if older!=dict(prompts=1,partial=0,history=True,live=True):
                                print(page.evaluate("()=>({stream:S.session.active_stream_id,inflight:INFLIGHT[S.session.session_id]?.streamId,offset:_oldestIdx,rows:S.messages.filter(m=>m.role==='user'&&(m.timestamp??m._ts)===10)})"))
                            assert older==dict(prompts=1,partial=0,history=True,live=True),older
                            for operation in ('_ensureAllMessagesLoaded();renderMessages()', 'refreshSession()'):
                                full_result=page.evaluate("""async ([operation,selector])=>{
                                  if(operation.startsWith('_ensureAll')){await _ensureAllMessagesLoaded();renderMessages();}
                                  else await refreshSession();
                                  return {prompts:S.messages.filter(m=>m.role==='user'&&(m.timestamp??m._ts)===10).length,
                                    partial:S.messages.filter(m=>String(m.reasoning||'').startsWith('Partial thinking')).length,
                                    history:S.messages.filter(m=>msgContent(m).startsWith('History ')).length,
                                    thinking:document.querySelectorAll(selector).length,
                                    tools:document.querySelectorAll('#liveAssistantTurn [data-anchor-row-role="tool"]').length};
                                }""",[operation,thinking_selector])
                                assert full_result==dict(prompts=1,partial=0,history=100,thinking=expected_thinking,tools=expected_tools),(operation,full_result)
                            assert page.evaluate('redundantSceneRepaints') == 0
                            assert not errors, errors
                            if os.environ.get('SCREENSHOT_DIR'):
                                folder=Path(os.environ['SCREENSHOT_DIR'])
                                folder.mkdir(parents=True,exist_ok=True)
                                page.evaluate("""()=>{
                                  const group=document.querySelector('#liveAssistantTurn .tool-worklog-group');
                                  if(group?.classList.contains('open'))group.querySelector('.tool-worklog-summary').click();
                                  document.getElementById('liveAssistantTurn').scrollIntoView({block:'end'});
                                }""")
                                page.wait_for_timeout(100)
                                page.screenshot(path=str(folder/f'boundary-{engine}-{width}.png'))
                            page.evaluate("""()=>{
                              closeLiveStream('fixture');
                              registryTimers.splice(0).forEach(fn=>fn());
                              if(window._liveAnchorRegistries.has('run-fixture'))throw new Error('detached registry leaked');
                            }""")
                            print(engine, mode, width, result, flush=True)
                            context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__ == '__main__':
    main()
