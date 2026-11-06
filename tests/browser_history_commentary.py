#!/usr/bin/env python3
"""Real session GET -> compact history, using an isolated agent home.

Requires an installed agent exposing agent.history_commentary. No inference,
production state, credentials, or session-route mocks are used.
"""
import json
import os
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_reconnect_scene_redraw import INIT

ROOT = Path(os.environ.get('WEBUI_TEST_ROOT', Path(__file__).resolve().parents[1]))
UPDATES = ['Checking the first component.', 'Checking the second component.']


def commentary(text):
    return dict(type='message', role='assistant', phase='commentary',
                content=[dict(type='output_text', text=text)])


def fixture(sid, scene=False, saved=False, steer=False):
    messages: list[dict] = [dict(role='user', content='Check both', timestamp=1)]
    for index, text in enumerate(UPDATES):
        tid=f'call-{index}'
        messages.extend([
            dict(role='assistant', content='', timestamp=2+index*2,
                 reasoning=f'Thought {index}.',
                 codex_message_items=[commentary(text)],
                 tool_calls=[dict(id=tid, type='function', function=dict(name='terminal', arguments='{}'))]),
            dict(role='tool', tool_call_id=tid, content='ok', timestamp=3+index*2),
        ])
    messages.append(dict(role='assistant', content='All checks complete.', timestamp=7,
                         codex_message_items=[commentary('Verification is complete.')]))
    if steer:
        messages.insert(3,dict(role='user',content='Also check the second one.',display_kind='steer',timestamp=3.5))
    data: dict=dict(session_id=sid, title='Commentary regression', messages=messages,
              context_messages=messages, tool_calls=[], profile='default', created_at=1, updated_at=7)
    if scene:
        data['anchor_activity_scenes']={'fixture': dict(message_index=len(messages)-1, stream_id=sid+'-run',
            scene=dict(version='activity_scene_v1', final_answer='All checks complete.',
                       activity_rows=[dict(role='tool',row_id='tool-0',tool=dict(id='call-0',name='terminal'),status='completed')]))}
    if steer and os.environ.get('CONTENT_STEER')=='1':
        messages[1]['content']=UPDATES[0]
        messages[1].pop('codex_message_items')
        saved=False  # cropped scene: no pre-steer prose provenance
    if scene and saved:
        data['anchor_activity_scenes']['fixture']['scene']['activity_rows'].extend(
            dict(role='prose',row_id=f'live-{i}',text=text,source_event_type='interim_assistant',timestamp=2+i*2)
            for i,text in enumerate(UPDATES))
    prefix=[dict(role=role,content='Earlier exchange '+str(i),timestamp=0.5) for i in range(45) for role in ['user','assistant']]
    data['messages']=prefix+messages
    data['context_messages']=prefix+messages
    if scene:
        data['anchor_activity_scenes']['fixture']['message_index']+=len(prefix)
    if os.environ.get('NO_REASONING')=='1':
        for message in data['messages']:
            message.pop('reasoning',None)
    if os.environ.get('COMMENTARY_ONLY')=='1':
        data['messages']=[m for m in data['messages'] if m.get('role')!='tool']
        data['context_messages']=data['messages']
        for message in data['messages']:
            message.pop('tool_calls',None)
            message.pop('reasoning',None)
    field=os.environ.get('THINKING_FIELD')
    if field:
        for message in data['messages']:
            if 'reasoning' in message:
                message[field]=message.pop('reasoning')
    return data


def main():
    mode=os.environ.get('ACTIVITY_MODE','compact_worklog')
    kinds=os.environ.get('KINDS','legacy,scene,saved,steer').split(',')
    agent_dir=os.environ.get('HERMES_WEBUI_AGENT_DIR')
    assert agent_dir, 'Set HERMES_WEBUI_AGENT_DIR to a qualified installed agent checkout'
    with tempfile.TemporaryDirectory(prefix='commentary-history-') as temp:
        home=Path(temp)
        sessions=home/'webui'/'sessions'
        sessions.mkdir(parents=True)
        enabled=os.environ.get('COMMENTARY_DISABLED')!='1'
        (home/'config.yaml').write_text('display:\n  show_commentary: '+str(enabled).lower()+'\n  interim_assistant_messages: true\n')
        for kind in kinds:
            sid='commentary-'+kind
            (sessions/(sid+'.json')).write_text(json.dumps(fixture(sid,scene=kind!='legacy',saved=kind in ('saved','steer'),steer=kind=='steer')))
        env={k:os.environ[k] for k in ('PATH','TMPDIR','SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp,HERMES_HOME=temp,HERMES_BASE_HOME=temp,HERMES_WEBUI_STATE_DIR=str(home/'webui'),
                   HERMES_CONFIG_PATH=str(home/'config.yaml'),HERMES_WEBUI_HOST='127.0.0.1',
                   HERMES_WEBUI_SKIP_ONBOARDING='1',HERMES_WEBUI_AGENT_DIR=agent_dir)
        process, log, _, base=_start_webui_server(ROOT,env,home)
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS','chromium,webkit').split(','):
                    browser=getattr(pw,engine).launch()
                    try:
                        for width in map(int,os.environ.get('WIDTHS','390,1280').split(',')):
                            context=browser.new_context(viewport={'width':width,'height':844},has_touch=True,bypass_csp=True)
                            context.add_init_script(INIT)
                            page=context.new_page()
                            errors=[]
                            page.on('pageerror',lambda e, errors=errors:errors.append(str(e)))
                            page.goto(base,wait_until='load')
                            for kind in kinds:
                                sid='commentary-'+kind
                                for stage in ['load','older','reload','cache']:
                                    if stage=='reload':
                                        page.reload(wait_until='load')
                                    deadline=time.monotonic()+30
                                    while not page.evaluate("typeof S!=='undefined'&&S._bootReady===true"):
                                        assert time.monotonic()<deadline, errors
                                        page.wait_for_timeout(50)
                                    page.evaluate("async ([sid,mode])=>{window._chatActivityDisplayMode=mode;await loadSession(sid);renderMessages();}",[sid,mode])
                                    if stage=='older':
                                        while (before:=page.evaluate('_oldestIdx'))>0:
                                            page.evaluate('async()=>{await _loadOlderMessages();}')
                                            assert page.evaluate('_oldestIdx')<before, 'Older-page cursor did not advance'
                                    if stage=='cache':
                                        page.evaluate("()=>{const html=$('msgInner').innerHTML;$('msgInner').innerHTML=html;_rehydrateDeferredWorklogsFromCache($('msgInner'));}")
                                    # Finish the renderer's scheduled layout/scroll pass
                                    # before taking a cache snapshot or interacting.
                                    page.evaluate('async()=>{await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));}')
                                    group=page.locator('#msgInner .tool-worklog-group').first if mode=='compact_worklog' else page.locator('#msgInner')
                                    if mode=='compact_worklog':
                                        if group.evaluate("g=>g.classList.contains('tool-call-group-collapsed')"):
                                            group.locator('.tool-worklog-summary').click()
                                        assert not group.evaluate("g=>g.classList.contains('tool-call-group-collapsed')"), 'Processed did not expand'
                                    if os.environ.get('SCREENSHOT_DIR'):
                                        dest=Path(os.environ['SCREENSHOT_DIR']);dest.mkdir(parents=True,exist_ok=True)
                                        page.screenshot(path=str(dest/f'{engine}-{width}-{kind}-{stage}.png'))
                                    projected=page.evaluate("S.messages.filter(m=>m.display_commentary?.length).length")
                                    content_steer=kind=='steer' and os.environ.get('CONTENT_STEER')=='1'
                                    assert projected==((2 if content_steer else 3) if enabled else 0), 'Real GET failed to apply commentary policy'
                                    for text in UPDATES+['Verification is complete.']:
                                        selector='[data-anchor-row-role=prose]'
                                        prose=group.locator(selector).filter(has_text=text)
                                        if (not enabled and not (content_steer and text==UPDATES[0])) or mode=='hide_all_activity':
                                            assert prose.count()==0, 'Hidden commentary recovered'
                                            continue
                                        assert prose.count()==1, (kind,stage,text,'missing or duplicated')
                                        assert prose.is_visible(), (kind,stage,text,'not visible')
                                        if mode=='compact_worklog' and text in UPDATES and os.environ.get('NO_REASONING')!='1' and not (content_steer and text==UPDATES[0]):
                                            thought=group.locator('.agent-activity-thinking').filter(has_text=f'Thought {UPDATES.index(text)}.')
                                            assert thought.count()==1, 'Recorded thinking missing or duplicated'
                                            assert f'Thought {UPDATES.index(text)}.' in thought.text_content()
                                            assert group.locator('.tool-card-row').count()==2, 'Recorded tools missing or duplicated'
                                    if enabled and mode=='compact_worklog':
                                        for text in UPDATES:
                                            assert page.locator('#msgInner [data-anchor-row-role=prose]').filter(has_text=text).count()==1, 'Cross-block duplicate commentary'
                                    if content_steer and mode in ('compact_worklog','transparent_stream'):
                                        assert page.locator('#msgInner').inner_text().count(UPDATES[0])==1, 'Pre-steer public text displayed twice'
                                    if mode=='compact_worklog':
                                        assert 'All checks complete.' not in group.inner_text(), 'Final answer was copied into Processed'
                                    if mode=='hide_all_activity':
                                        for text in UPDATES+['Verification is complete.']:
                                            assert text not in page.locator('#msgInner').inner_text()
                                        if os.environ.get('COMMENTARY_ONLY')=='1':
                                            assert page.locator('#msgInner .tool-worklog-group').count()==0, 'Empty commentary worklog in final-only mode'
                                    assert page.locator('.assistant-segment').filter(has_text='All checks complete.').last.is_visible()
                                    assert page.evaluate("S.messages.filter(m=>m.tool_calls?.length&&m.codex_message_items?.length).every(m=>m.content==='')"), 'Provider content mutated'
                                    if mode=='compact_worklog':
                                        group.locator('.tool-worklog-summary').click()
                                    print(engine,width,kind,stage,'PASS',flush=True)
                            # WebKit reports cancelled status probes during reload
                            # as access-control errors (the lifecycle harness has the
                            # same allowance). All other page errors remain failures.
                            unexpected=[e for e in errors if not ('/api/session/status?' in e and 'due to access control checks' in e)]
                            assert not unexpected, unexpected
                            context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(process)
            log.close()


if __name__=='__main__':
    main()
