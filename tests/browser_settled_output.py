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
                                  // Exceed the incremental parser's 32-entry cache: unchanged
                                  // conversation DOM must not be rebuilt on each live redraw.
                                  for(let i=0;i<60;i++)source.emit('interim_assistant',{
                                    text:`Extended progress ${i}. `+'Verification continues. '.repeat(25),
                                    timestamp:1.6+i/1000,event_id:`run-fixture:long-${i}`});
                                  source.emit('interim_assistant',{text:'Earlier progress',timestamp:2,event_id:'run-fixture:1001'});
                                  source.emit('interim_assistant',{text:'The requested fix is deployed. Here is the important result.',timestamp:4,event_id:'run-fixture:1002'});
                                  source.emit('tool',{name:'terminal',tid:'verify',args:{command:'printf checked'},timestamp:5});
                                  source.emit('tool_complete',{name:'terminal',tid:'verify',result:'checked',timestamp:6});
                                  source.emit('interim_assistant',{text:'Additional verification passed.',timestamp:7,event_id:'run-fixture:1005'});
                                  source.emit('token',{text:'Final test confirmation.',timestamp:8,event_id:'run-fixture:final-token'});
                                  await new Promise(r=>setTimeout(r,100));
                                }""")
                                if mode == 'compact_worklog':
                                    live = page.evaluate("""()=>{
                                      const group=document.querySelector('#liveAssistantTurn .tool-worklog-group');
                                      if(!group.classList.contains('open'))group.querySelector('.tool-worklog-summary').click();
                                      group.querySelectorAll('.compact-ai-update').forEach(n=>n.open=true);
                                      return {visible:$('msgInner').innerText.includes('The requested fix is deployed.'),
                                        rows:document.querySelectorAll('.user-input-receipt').length};
                                    }""")
                                    assert live == dict(visible=True, rows=2), live
                                    retained = page.evaluate("""()=>{
                                      const turn=$('liveAssistantTurn');
                                      const group=turn.querySelector('.tool-worklog-group');
                                      const conversation=group.querySelector('.tool-worklog-list');
                                      const nodes=[...conversation.children];
                                      // A later parser anchor exists when a cached live turn is restored.
                                      const anchor=document.createElement('div');
                                      anchor.className='assistant-segment';
                                      anchor.dataset.liveAssistant='1';anchor.hidden=true;
                                      anchor.textContent='Later parser anchor';
                                      _assistantTurnBlocks(turn).appendChild(anchor);
                                      normalizeLiveActivityGroupPlacement(turn);
                                      _renderLiveAnchorActivitySceneForStream(S.activeStreamId,S.session.session_id);
                                      return {containers:turn.querySelectorAll('.tool-worklog-list').length,
                                        retained:nodes.every(n=>n.isConnected&&n.parentElement===conversation),
                                        adjacent:group.contains(conversation)};
                                    }""")
                                    assert retained == dict(containers=1,retained=True,adjacent=True),retained
                                    page.evaluate("""()=>{
                                      const host=document.createElement('div');
                                      const group=document.createElement('div');group.innerHTML='<div class="tool-worklog-list"></div>';host.appendChild(group);
                                      const row={role:'prose',row_id:'retention-check',text:'Original **content**'};
                                      _renderCompactUpdateRows(group,[row],{settled:true});
                                      const original=host.querySelector('[data-anchor-row-id]');
                                      _renderCompactUpdateRows(group,[{...row}],{settled:true});
                                      if(host.querySelector('[data-anchor-row-id]')!==original)throw new Error('Unchanged prose rebuilt');
                                      _renderCompactUpdateRows(group,[{...row,text:'Corrected **content**'}],{settled:true});
                                      const changed=host.querySelector('[data-anchor-row-id]');
                                      if(changed===original||!changed.textContent.includes('Corrected content'))throw new Error('Prose correction stale');
                                      _renderCompactUpdateRows(group,[],{settled:true});
                                      if(host.querySelector('[data-anchor-row-id]'))throw new Error('Removed prose retained');
                                      const anonymous={role:'prose',text:'Anonymous repeated update'};
                                      _renderCompactUpdateRows(group,[anonymous,{...anonymous}],{settled:true});
                                      _renderCompactUpdateRows(group,[anonymous,{...anonymous}],{settled:true});
                                      if(host.querySelectorAll('.compact-ai-update').length!==2)throw new Error('Anonymous prose collapsed');
                                      const savedFade=window._fadeTextEffect;
                                      const liveRow={role:'prose',row_id:'fade-check',text:'Live fade check'};
                                      try{
                                        window._fadeTextEffect=false;
                                        _renderCompactUpdateRows(group,[liveRow],{settled:false});
                                        if(host.querySelector('.stream-fade-active'))throw new Error('Fade unexpectedly active');
                                        window._fadeTextEffect=true;
                                        _renderCompactUpdateRows(group,[liveRow],{settled:false});
                                        if(!host.querySelector('.stream-fade-active'))throw new Error('Fade toggle did not invalidate retained prose');
                                      }finally{window._fadeTextEffect=savedFade;}
                                    }""")
                                    cleanup=page.evaluate("""()=>{
                                      const original=$('liveAssistantTurn').querySelector('.tool-worklog-group');
                                      clearLiveToolCards({preserveDom:true});
                                      const preserved=original.isConnected;
                                      clearLiveToolCards();
                                      const remaining=$('liveAssistantTurn').querySelectorAll('.tool-worklog-group').length;
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
                                if mode=='compact_worklog':
                                    page.evaluate("""()=>{
                                      _rememberUserInputReceipt('fixture',{input_id:'late-receipt',kind:'steer',content:'Late receipt',stream_id:'run-fixture',timestamp:7.9});
                                      const row=document.querySelector('[data-user-input-id="late-receipt"]');
                                      const group=document.querySelector('[data-anchor-settled-scene-owner="1"]');
                                      if(!group)throw new Error('Settled disclosure missing before late receipt check');
                                      if(!row||(!group.contains(row)&&!(row.compareDocumentPosition(group)&Node.DOCUMENT_POSITION_FOLLOWING)))throw new Error('Late receipt stranded after disclosure');
                                      S._userInputs.delete('late-receipt');row.remove();
                                    }""")
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
                                    # Compact updates are hidden while Processed is closed, then fully recover on expansion.
                                    page.evaluate("""stage=>{
                                      for(const group of document.querySelectorAll('.tool-worklog-group')){
                                        if(!group.classList.contains('open'))group.querySelector('.tool-worklog-summary').click();
                                        group.querySelectorAll('.compact-ai-update').forEach(n=>n.open=true);
                                        group.querySelectorAll('.thinking-card:not(.open) .thinking-card-header').forEach(n=>n.click());
                                      }
                                    }""",stage)
                                    if mode=='compact_worklog':
                                        page.evaluate("""()=>{
                                          for(const g of document.querySelectorAll('.tool-worklog-group'))if(g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();
                                          if($('msgInner').innerText.includes('The requested fix is deployed.'))throw new Error('Collapsed worklog leaked an update');
                                          if(!$('msgInner').innerText.includes('Final test confirmation.'))throw new Error('Collapsed worklog hid final');
                                          for(const g of document.querySelectorAll('.tool-worklog-group')){
                                            if(!g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();
                                            g.querySelectorAll('.compact-ai-update').forEach(n=>n.open=true);
                                            g.querySelectorAll('.thinking-card:not(.open) .thinking-card-header').forEach(n=>n.click());
                                          }
                                        }""")
                                        page.evaluate("""async()=>{
                                          await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
                                          document.querySelectorAll('.thinking-card:not(.open) .thinking-card-header').forEach(n=>n.click());
                                        }""")
                                        page.wait_for_function("$('msgInner').innerText.includes('Internal reasoning fixture.')")
                                    result = page.evaluate("""()=>{
                                      const inner=$('msgInner');
                                      const receipt=inner.querySelector('.user-input-receipt');
                                      const visible=n=>!!n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden';
                                      const prose=[...inner.querySelectorAll('.msg-body,.wl-reason,[data-anchor-row-role="prose"]')].filter(visible);
                                      const output=prose.find(n=>n.textContent.includes('The requested fix is deployed.'));
                                      return {busy:S.busy,outputVisible:!!output,receiptBeforeOutput:!!output&&!!receipt&&!!(receipt.compareDocumentPosition(output)&Node.DOCUMENT_POSITION_FOLLOWING),
                                        answerAfterUpdate:!!output&&!!(output.compareDocumentPosition(inner.querySelector('[data-user-input-id="answer"]'))&Node.DOCUMENT_POSITION_FOLLOWING),
                                        outputCopies:prose.filter(n=>n.textContent.includes('The requested fix is deployed.')&&!n.parentElement.closest('.msg-body,[data-anchor-row-role="prose"]')).length,
                                        finalCopies:inner.innerText.split('Final test confirmation.').length-1,
                                        earlierVisible:inner.innerText.includes('Earlier progress'),
                                        thinkingExposed:inner.innerText.includes('Internal reasoning fixture.'),
                                        receiptsVisible:[...inner.querySelectorAll('.user-input-receipt')].every(n=>visible(n)),
                                        receipts:inner.querySelectorAll('.user-input-receipt').length};
                                    }""")
                                    if mode=='compact_worklog':
                                        placement=page.evaluate("""()=>{
                                          const group=document.querySelector('[data-anchor-settled-scene-owner="1"]');
                                          const final=[...document.querySelectorAll('.assistant-segment')].find(n=>!n.hidden&&n.innerText.includes('Final test confirmation.'));
                                          const updates=group?.querySelector('.compact-ai-update');
                                          return {atConclusion:!!group&&!!final&&group.nextElementSibling===final,
                                            nestedUpdates:!!updates&&group.contains(updates)};
                                        }""")
                                        assert placement==dict(atConclusion=True,nestedUpdates=True),placement
                                    print(engine, mode, width, stage, result, flush=True)
                                    assert result['outputVisible'], 'Produced answer vanished'
                                    if mode=='compact_worklog':assert result['thinkingExposed'],(result,page.locator('.thinking-card-body').all_inner_texts())
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
                                      for(const g of document.querySelectorAll('.tool-worklog-group')){if(!g.classList.contains('open'))g.querySelector('.tool-worklog-summary').click();g.querySelectorAll('.compact-ai-update').forEach(n=>n.open=true);}
                                      return {copies:[...$('msgInner').querySelectorAll('.compact-ai-update-body')].filter(n=>n.textContent.includes('The requested fix is deployed.')).length,
                                        sceneOwner:!!$('msgInner').querySelector('[data-anchor-settled-scene-owner="1"]'),
                                        conversation:!!$('msgInner').querySelector('.compact-ai-update'),
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
                                        disclosureVisible:!!group&&!!group.getClientRects().length,
                                        settledInPlace:_collapseJustSettledWorklogInPlace(message._anchor_stream_id)};
                                    }""")
                                    assert compression==dict(update=True,disclosureVisible=True,settledInPlace=True),compression
                                context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(process)
            log.close()


if __name__ == '__main__':
    main()
