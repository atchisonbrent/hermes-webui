#!/usr/bin/env python3
"""Already-open conversation preserves output and receipt chronology at done."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT, fixture, session_route
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(os.environ.get('WEBUI_TEST_ROOT', Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix='settled-output-') as temp:
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
                        for mode in os.environ.get('MODES', 'compact_worklog,transparent_stream,hide_all_activity').split(','):
                            for width in [390, 1280]:
                                data: dict = dict(session_id='fixture', messages=[dict(role='user', content='Fix the display', timestamp=1)],
                                            message_count=1, tool_calls=[], workspace=temp, active_stream_id='run-fixture',
                                            pending_user_message='Fix the display', pending_started_at=1,
                                            runtime_journal_snapshot=fixture(2),
                                            _user_inputs=[dict(input_id='steer', kind='steer', content='Include steers too',
                                                               stream_id='run-fixture', timestamp=3),
                                                          dict(input_id='answer',kind='clarify',content='Later clarification',stream_id='run-fixture',timestamp=7.5)])
                                context = browser.new_context(viewport={'width': width, 'height': 844}, bypass_csp=True)
                                context.add_init_script(INIT)
                                page = context.new_page()
                                errors = []
                                page.on('pageerror', lambda e, errors=errors: errors.append(str(e)))
                                page.route('**/api/session/status?*', lambda r: r.fulfill(json={'active_stream_id':data['active_stream_id']}))
                                page.route('**/api/session?*', session_route(data,'fixture',temp))
                                page.route('**/api/chat/stream/status?*', lambda r: r.fulfill(json={'active': bool(data['active_stream_id'])}))
                                # Emulate persistence for a genuine fresh-document reload.
                                def persist_scene(route):
                                    body = route.request.post_data_json
                                    data['messages'][-1]['_anchor_activity_scene'] = body['scene']
                                    data['messages'][-1]['_anchor_stream_id'] = body['stream_id']
                                    route.fulfill(json={'ok': True})
                                page.route('**/api/session/anchor-scene', persist_scene)
                                page.goto(base, wait_until='load')
                                deadline = time.monotonic()+30
                                while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                    assert time.monotonic()<deadline
                                    page.wait_for_timeout(50)
                                page.evaluate("async mode=>{window._chatActivityDisplayMode=mode;await loadSession('fixture');}", mode)
                                page.evaluate("""async()=>{
                                  const end=performance.now()+5000;
                                  while(!LIVE_STREAMS.fixture?.source&&performance.now()<end)await new Promise(r=>setTimeout(r,10));
                                  const source=LIVE_STREAMS.fixture.source;
                                  source.emit('reasoning',{text:'Internal reasoning fixture.',timestamp:1.5,event_id:'run-fixture:1000a'});
                                  source.emit('interim_assistant',{text:'Earlier progress',timestamp:2,event_id:'run-fixture:1001'});
                                  source.emit('interim_assistant',{text:'The requested fix is deployed. Here is the important result.',timestamp:4,event_id:'run-fixture:1002'});
                                  source.emit('tool',{name:'terminal',tid:'verify',args:{command:'printf checked'},timestamp:5});
                                  source.emit('tool_complete',{name:'terminal',tid:'verify',result:'checked',timestamp:6});
                                  source.emit('interim_assistant',{text:'Additional verification passed.',timestamp:7,event_id:'run-fixture:1005'});
                                  source.emit('token',{text:'Final test confirmation.',timestamp:8});
                                  await new Promise(r=>setTimeout(r,100));
                                }""")
                                if mode == 'compact_worklog':
                                    live = page.evaluate("""()=>{
                                      const group=document.querySelector('#liveAssistantTurn .tool-worklog-group');
                                      if(group.classList.contains('open'))group.querySelector('.tool-worklog-summary').click();
                                      return {visible:$('msgInner').innerText.includes('The requested fix is deployed.'),
                                        rows:document.querySelectorAll('.user-input-receipt').length};
                                    }""")
                                    assert live == dict(visible=True, rows=2), live
                                    retained = page.evaluate("""()=>{
                                      const turn=$('liveAssistantTurn');
                                      const group=turn.querySelector('.tool-worklog-group');
                                      const conversation=turn.querySelector('.anchor-conversation');
                                      const nodes=[...conversation.children];
                                      // A later parser anchor exists when a cached live turn is restored.
                                      const anchor=document.createElement('div');
                                      anchor.className='assistant-segment';
                                      anchor.dataset.liveAssistant='1';anchor.hidden=true;
                                      anchor.textContent='Later parser anchor';
                                      _assistantTurnBlocks(turn).appendChild(anchor);
                                      normalizeLiveActivityGroupPlacement(turn);
                                      _renderLiveAnchorActivitySceneForStream(S.activeStreamId,S.session.session_id);
                                      return {containers:turn.querySelectorAll('.anchor-conversation').length,
                                        retained:nodes.every(n=>n.isConnected&&n.parentElement===conversation),
                                        adjacent:group.nextElementSibling===conversation};
                                    }""")
                                    assert retained == dict(containers=1,retained=True,adjacent=True),retained
                                    cleanup=page.evaluate("""()=>{
                                      const original=$('liveAssistantTurn').querySelector('.anchor-conversation');
                                      clearLiveToolCards({preserveDom:true});
                                      const preserved=original.isConnected;
                                      clearLiveToolCards();
                                      const remaining=$('liveAssistantTurn').querySelectorAll('.anchor-conversation').length;
                                      _renderLiveAnchorActivitySceneForStream(S.activeStreamId,S.session.session_id);
                                      return {preserved,remaining};
                                    }""")
                                    assert cleanup==dict(preserved=True,remaining=0),cleanup
                                data.update(active_stream_id=None, runtime_journal_snapshot=None, pending_user_message='',
                                            messages=[dict(role='user', content='Fix the display', timestamp=1),
                                                      dict(role='assistant', content='Earlier progress', timestamp=2),
                                                      dict(role='assistant', content=[dict(type='text',text='The requested fix is deployed.'),dict(type='tool_use',id='inline',name='terminal',input={}),dict(type='text',text='Here is the important result.')], timestamp=4),
                                                      dict(role='tool',tool_call_id='inline',content='inline result',timestamp=4.5),
                                                      dict(role='assistant', content='', timestamp=5, tool_calls=[dict(id='verify',type='function',function=dict(name='terminal',arguments='{}'))]),
                                                      dict(role='tool', tool_call_id='verify', content='checked', timestamp=6),
                                                      dict(role='assistant', content='Additional verification passed.', timestamp=7),
                                                      dict(role='assistant', content='Final test confirmation.', timestamp=8)], message_count=8)
                                page.evaluate("session=>LIVE_STREAMS.fixture.source.emit('done',{session})", data)
                                page.wait_for_timeout(100)
                                for stage in ['settled', 'expanded', 'rerender', 'reload', 'cache', 'older-scene']:
                                    if stage == 'older-scene':
                                        scene=data['messages'][-1]['_anchor_activity_scene']
                                        scene['activity_rows']=[r for r in scene['activity_rows'] if r.get('text')!='Earlier progress']
                                        scene['activity_rows'].append(dict(role='prose',kind='process_prose',text='Final test confirmation.',row_id='old-final',local_id='old-final',timestamp=8))
                                    if stage == 'cache':
                                        page.evaluate("async()=>{await loadSession('idle-fixture');await loadSession('fixture');}")
                                    if stage == 'rerender':
                                        page.evaluate('renderMessages()')
                                    elif stage in ['reload','older-scene']:
                                        for row in data['messages'][-1]['_anchor_activity_scene']['activity_rows']:
                                            if row.get('role')=='prose':
                                                for key in ['created_at','timestamp','ts','started_at','completed_at']:
                                                    row.pop(key,None)
                                        page.reload(wait_until='load')
                                        deadline = time.monotonic()+30
                                        while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                            assert time.monotonic()<deadline
                                            page.wait_for_timeout(50)
                                        page.evaluate("async mode=>{window._chatActivityDisplayMode=mode;await loadSession('fixture');renderMessages();}",mode)
                                    # Assistant updates must survive collapsed supporting activity.
                                    page.evaluate("""stage=>{
                                      for(const group of document.querySelectorAll('.tool-worklog-group')){
                                        if(group.classList.contains('open')!==(stage==='expanded'))group.querySelector('.tool-worklog-summary').click();
                                      }
                                    }""",stage)
                                    result = page.evaluate("""()=>{
                                      const inner=$('msgInner');
                                      const receipt=inner.querySelector('.user-input-receipt');
                                      const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
                                      const prose=[...inner.querySelectorAll('.msg-body,.wl-reason,[data-anchor-row-role="prose"]')].filter(visible);
                                      const output=prose.find(n=>n.textContent.includes('The requested fix is deployed.'));
                                      return {busy:S.busy,outputVisible:!!output,receiptBeforeOutput:!!output&&!!receipt&&!!(receipt.compareDocumentPosition(output)&Node.DOCUMENT_POSITION_FOLLOWING),
                                        answerAfterUpdate:!!output&&!!(output.compareDocumentPosition(inner.querySelector('[data-user-input-id="answer"]'))&Node.DOCUMENT_POSITION_FOLLOWING),
                                        outputCopies:inner.innerText.split('The requested fix is deployed.').length-1,
                                        finalCopies:inner.innerText.split('Final test confirmation.').length-1,
                                        earlierVisible:inner.innerText.includes('Earlier progress'),
                                        thinkingExposed:inner.innerText.includes('Internal reasoning fixture.'),
                                        receiptsVisible:[...inner.querySelectorAll('.user-input-receipt')].every(n=>visible(n)&&!n.closest('.tool-worklog-group')),
                                        receipts:inner.querySelectorAll('.user-input-receipt').length};
                                    }""")
                                    print(engine, mode, width, stage, result, flush=True)
                                    assert result['outputVisible'], 'Produced answer vanished'
                                    if mode=='compact_worklog' and stage!='expanded':assert not result['thinkingExposed'],result
                                    assert result['receiptBeforeOutput'], 'Earlier steer moved after produced answer'
                                    assert result['answerAfterUpdate'], 'Later clarification moved before earlier output'
                                    assert result['outputCopies'] == 1 and result['receipts'] == 2, result
                                    assert result['finalCopies']==1 and result['earlierVisible'] and result['receiptsVisible'] and not result['busy'],result
                                    # WebKit emits navigation-time access-control errors for these
                                    # background probes on the unchanged baseline too. Record them
                                    # separately; all other JS errors remain fatal.
                                    navigation_errors=[e for e in errors if engine=='webkit' and
                                        (e.startswith('/127.0.0.1:') and e.endswith(' due to access control checks.') and
                                         ('/api/session/status?' in e or '/health?offline_probe=' in e))]
                                    if navigation_errors:print('baseline-navigation-errors',navigation_errors,flush=True)
                                    assert not [e for e in errors if e not in navigation_errors], errors
                                    errors.clear()
                                    if os.environ.get('SCREENSHOT_DIR'):
                                        directory=Path(os.environ['SCREENSHOT_DIR']);directory.mkdir(parents=True,exist_ok=True)
                                        page.screenshot(path=str(directory/f'{engine}-{mode}-{width}-{stage}.png'))
                                if mode=='compact_worklog':
                                    cold=page.evaluate("""()=>{
                                      const message=structuredClone(S.messages.find(m=>Array.isArray(m.content)));
                                      const final=structuredClone(S.messages.at(-1));
                                      final._anchor_activity_scene.activity_rows=final._anchor_activity_scene.activity_rows.filter(r=>r.source_event_type==='settled_message'||r.role==='tool');
                                      if(!final._anchor_activity_scene.activity_rows.some(r=>r.role==='tool')) throw new Error('cold scene needs worklog-worthy activity');
                                      const snapshot=JSON.stringify(final._anchor_activity_scene);
                                      S.messages=[S.messages[0],message,final];S.toolCalls=[];
                                      clearMessageRenderCache();renderMessages();
                                      return {copies:$('msgInner').innerText.split('The requested fix is deployed.').length-1,
                                        sceneOwner:!!$('msgInner').querySelector('[data-anchor-settled-scene-owner="1"]'),
                                        conversation:!!$('msgInner').querySelector('.anchor-conversation'),
                                        sourceUnchanged:JSON.stringify(final._anchor_activity_scene)===snapshot};
                                    }""")
                                    assert cold==dict(copies=1,sceneOwner=True,conversation=True,sourceUnchanged=True),cold
                                    print(engine,mode,width,'cold-scene',cold,flush=True)
                                    compression=page.evaluate("""()=>{
                                      const message=S.messages[S.messages.length-1];
                                      message._anchor_activity_scene.activity_rows=[
                                        {role:'prose',kind:'process_prose',text:'Compression update.',row_id:'compression-prose'},
                                        {role:'lifecycle',source_event_type:'compressed',status:'completed',row_id:'compression-done'}
                                      ];
                                      S.messages=[S.messages[0],message];S.toolCalls=[];
                                      clearMessageRenderCache();renderMessages();
                                      const group=$('msgInner').querySelector('[data-anchor-settled-scene-owner="1"]');
                                      return {update:$('msgInner').innerText.includes('Compression update.'),
                                        emptyDisclosureVisible:!!group&&!!group.getClientRects().length,
                                        settledInPlace:_collapseJustSettledWorklogInPlace(message._anchor_stream_id)};
                                    }""")
                                    assert compression==dict(update=True,emptyDisclosureVisible=False,settledInPlace=True),compression
                                context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(process)
            log.close()


if __name__ == '__main__':
    main()
