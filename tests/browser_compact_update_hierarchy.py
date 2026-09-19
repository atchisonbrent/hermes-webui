#!/usr/bin/env python3
"""Compact worklogs retain independently collapsible updates and their activity."""
import os
import tempfile
import time
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_reconnect_scene_redraw import INIT, session_route
from browser_conversation_lifecycle import _start_webui_server, _terminate_process

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    dict(role='thinking', row_id='think-a', text='Reasoning A', order_index=1),
    dict(role='prose', row_id='update-a', text='Checking the first component.', order_index=2),
    dict(role='tool', row_id='tool-a', text='First check', order_index=3, tool=dict(name='terminal', id='a', args={'command':'first'}, snippet='First result'), status='completed'),
    dict(role='thinking', row_id='think-b', text='Reasoning B', order_index=4),
    dict(role='prose', row_id='update-b', text='Checking the second component.', order_index=5),
    dict(role='tool', row_id='tool-b', text='Second check', order_index=6, tool=dict(name='terminal', id='b', args={'command':'second'}, snippet='Second result'), status='completed'),
]


def main():
    with tempfile.TemporaryDirectory(prefix='compact-hierarchy-') as temp:
        home = Path(temp)
        env = {k: os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,HERMES_WEBUI_STATE_DIR=str(home/'webui'),HERMES_CONFIG_PATH=str(home/'config.yaml'),HERMES_WEBUI_HOST='127.0.0.1',HERMES_WEBUI_SKIP_ONBOARDING='1',HERMES_WEBUI_AGENT_DIR=str(home/'no-agent'))
        process, log, _, base = _start_webui_server(ROOT, env, home)
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
                    browser = getattr(pw,engine).launch()
                    try:
                        for width in [390,1280]:
                            scene=dict(activity_rows=[dict(r,timestamp=r['order_index']) for r in ROWS], final_answer='All checks complete.', stream_id='hierarchy-run', terminal_state='completed')
                            data: dict=dict(session_id='hierarchy', messages=[dict(role='user',content='Check both',timestamp=1),dict(role='assistant',content='All checks complete.',timestamp=9,_anchor_activity_scene=scene,_anchor_stream_id='hierarchy-run')],message_count=2,tool_calls=[],workspace=temp,active_stream_id=None)
                            if os.environ.get('LEGACY')=='1':
                                data['messages']=[dict(role='user',content='Check both',timestamp=1),
                                    dict(role='assistant',content='Checking the first component.',reasoning='Reasoning A',timestamp=2,tool_calls=[dict(id='a',type='function',function=dict(name='terminal',arguments='{}'))]),
                                    dict(role='tool',tool_call_id='a',content='First result',timestamp=3),
                                    dict(role='assistant',content='Checking the second component.',reasoning='Reasoning B',timestamp=4,tool_calls=[dict(id='b',type='function',function=dict(name='terminal',arguments='{}'))]),
                                    dict(role='tool',tool_call_id='b',content='Second result',timestamp=5),
                                    dict(role='assistant',content='All checks complete.',timestamp=9)]
                                data['message_count']=len(data['messages'])
                            if os.environ.get('MISSING')=='1':
                                data['messages'].insert(-1,dict(role='assistant',content='Persisted update absent from old scene.',timestamp=7))
                                data['message_count']=len(data['messages'])
                            data['_user_inputs']=[dict(input_id='receipt',kind='steer',content='Check the second one too.',timestamp=3.5,stream_id='hierarchy-run')]
                            context=browser.new_context(viewport={'width':width,'height':844},has_touch=True,bypass_csp=True)
                            context.add_init_script(INIT)
                            page=context.new_page()
                            errors=[]
                            page.on('pageerror',lambda e:errors.append(str(e)))
                            page.route('**/api/session?*',session_route(data,'hierarchy',temp))
                            page.route('**/api/session/status?*',lambda r:r.fulfill(json={'active_stream_id':None}))
                            page.goto(base,wait_until='load')
                            deadline=time.monotonic()+30
                            while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                assert time.monotonic()<deadline
                                page.wait_for_timeout(50)
                            for stage in ['load','rerender','reload','cache']:
                                if stage=='reload':
                                    page.reload(wait_until='load')
                                    deadline=time.monotonic()+30
                                    while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                        assert time.monotonic()<deadline
                                        page.wait_for_timeout(50)
                                page.evaluate("async()=>{window._chatActivityDisplayMode='compact_worklog';await loadSession('hierarchy');renderMessages();}")
                                if stage=='cache':
                                    page.evaluate("""legacy=>{
                                        const group=document.querySelector('.tool-worklog-group');
                                        if(!legacy&&!group.hasAttribute('data-worklog-rows-deferred'))throw new Error('Cache fixture did not exercise deferred rows');
                                        const html=$('msgInner').innerHTML;$('msgInner').innerHTML=html;
                                        if(document.querySelector('.tool-worklog-group')._deferredWorklogRows)throw new Error('Cache retained JS stash');
                                        _rehydrateDeferredWorklogsFromCache($('msgInner'));
                                    }""",os.environ.get('LEGACY')=='1')
                                group=page.locator('.tool-worklog-group').first
                                assert group.count()==1, 'Missing Processed'
                                if not group.evaluate("g=>g.classList.contains('open')"):
                                    group.locator('.tool-worklog-summary').tap()
                                updates=group.locator('details.compact-ai-update')
                                expected_updates=3 if os.environ.get('MISSING')=='1' else 2
                                assert updates.count()==expected_updates, f'{stage}: expected {expected_updates} AI-update disclosures, got {updates.count()}'
                                if os.environ.get('MISSING')=='1':
                                    assert 'Persisted update absent from old scene.' in updates.last.locator('.compact-ai-update-body').text_content()
                                assert page.locator('[data-user-input-id="receipt"]').count()==1, 'Receipt duplicated'
                                assert page.evaluate("""()=>{
                                    const r=document.querySelector('[data-user-input-id="receipt"]');
                                    const u=[...document.querySelectorAll('.compact-ai-update')];
                                    return !!(u[0].compareDocumentPosition(r)&Node.DOCUMENT_POSITION_FOLLOWING)&&!!(r.compareDocumentPosition(u[1])&Node.DOCUMENT_POSITION_FOLLOWING);
                                }"""), 'Receipt not between updates'
                                for i, marker in enumerate(['a','b']):
                                    update=updates.nth(i)
                                    thought=update.locator('.agent-activity-thinking')
                                    assert thought.count()==1
                                    assert update.locator('.tool-card-row').count()==1
                                    assert f'Reasoning {marker.upper()}' in thought.text_content()
                                    prose=update.locator('.msg-body').first
                                    assert ['Checking the first component.','Checking the second component.'][i] in prose.text_content()
                                    update.locator('summary').tap()
                                    assert update.evaluate('n=>n.open')
                                    assert prose.is_visible()
                                    if i==0 and stage=='load' and os.environ.get('SCREENSHOT_DIR'):
                                        target=Path(os.environ['SCREENSHOT_DIR']);target.mkdir(parents=True,exist_ok=True)
                                        page.screenshot(path=str(target/(f'{engine}-{width}-'+('legacy' if os.environ.get('LEGACY') else 'scene')+'.png')))
                                    update.locator('summary').tap()
                                    assert not thought.is_visible()
                                updates.first.locator('summary').tap()
                                page.evaluate('clearMessageRenderCache();renderMessages();')
                                group=page.locator('.tool-worklog-group').first
                                if not group.evaluate("g=>g.classList.contains('open')"):
                                    group.locator('.tool-worklog-summary').tap()
                                assert group.locator('details.compact-ai-update').first.evaluate('n=>n.open'), 'Update disclosure lost on rerender'
                                group.locator('details.compact-ai-update').first.locator('summary').tap()
                                assert page.locator('.anchor-conversation').count()==0, 'Detached updates remain'
                                assert page.locator('.assistant-segment').filter(has_text='All checks complete.').last.is_visible()
                                group.locator('.tool-worklog-summary').tap()
                                assert not updates.first.is_visible()
                                print(engine,width,stage,'PASS',flush=True)
                            page.evaluate("""()=>{
                                const host=document.createElement('div');host.innerHTML='<div class="tool-worklog-list"></div>';
                                const a=document.createElement('div');a.className='assistant-segment';a.dataset.msgIdx='1';a.innerHTML='<div class="msg-body">Update</div>';
                                const opts={seenReasons:new Set(),seenTools:new Set()};
                                _appendWorklogStep(host,a,[],'First distinct thought',{...opts,thinkingKey:'first'});
                                _appendWorklogStep(host,a,[],'Second distinct thought',{...opts,thinkingKey:'second'});
                                const b=a.cloneNode(true);b.dataset.msgIdx='2';delete b.dataset.worklogAnchorKey;
                                _appendWorklogStep(host,b,[],'First distinct thought',{...opts,thinkingKey:'first'});
                                if(host.querySelectorAll('.agent-activity-thinking').length!==2||!host.textContent.includes('Second distinct thought')||host.textContent.split('First distinct thought').length!==2)throw new Error('Thought lost or echoed across anchors');
                                for(const [anchor,prefix] of [[a,'a'],[b,'b']]){
                                    _appendWorklogStep(host,anchor,[{name:'terminal',id:prefix+'1',args:{command:'one'}},{name:'terminal',id:prefix+'2',args:{command:'two'}}],'',opts);
                                }
                                const groups=[...host.querySelectorAll('.compact-ai-update .tool-group')];
                                if(groups.length!==2||groups.some(g=>g.querySelectorAll('.tool-card-row').length!==2)||new Set(groups.map(g=>g.dataset.toolGroupDisclosureKey)).size!==2)throw new Error('Legacy update tool grouping lost or disclosure keys collide');
                            }""")
                            assert not [e for e in errors if not (('/api/session/status?' in e or '/health?offline_probe=' in e) and 'due to access control checks' in e)],errors
                            context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(process)
            log.close()

if __name__=='__main__':
    main()
