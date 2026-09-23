#!/usr/bin/env python3
"""Older-page loading keeps complete settled turns, content and actions intact.

Real loadSession/loader/renderer; deterministic API transport, isolated state.
"""
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright
from browser_conversation_lifecycle import _start_webui_server, _terminate_process
from browser_settled_turn_reuse import INIT, fixture

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix='older-turn-test-') as temp:
        env = {k: os.environ[k] for k in ('PATH', 'TMPDIR', 'SYSTEMROOT') if k in os.environ}
        env.update(HOME=temp, HERMES_HOME=temp, HERMES_BASE_HOME=temp,
                   HERMES_CONFIG_PATH=temp+'/config.yaml', HERMES_WEBUI_STATE_DIR=temp+'/webui',
                   HERMES_WEBUI_HOST='127.0.0.1', HERMES_WEBUI_SKIP_ONBOARDING='1',
                   HERMES_WEBUI_AGENT_DIR=temp+'/no-agent')
        proc, log, _, base = _start_webui_server(ROOT, env, Path(temp))
        try:
            with sync_playwright() as pw:
                for engine in os.environ.get('BROWSERS', 'chromium,webkit').split(','):
                    browser = getattr(pw, engine).launch()
                    try:
                        for width in (1280, 390):
                            context = browser.new_context(viewport={'width': width, 'height': 844}, bypass_csp=True)
                            context.add_init_script(INIT)
                            page = context.new_page()
                            errors = []
                            page.on('pageerror', lambda e: errors.append(str(e)))
                            shape=os.environ.get('SHAPE','scene')
                            messages = []
                            for i in range(80):
                                scene = fixture(12)['anchor_activity_scene']
                                scene['identity'].update(stream_id=f'old-{i}', run_id=f'old-{i}')
                                for row in scene['activity_rows']:
                                    row['row_id'] = f'{i}-'+row['row_id']
                                    row['tool']['tid'] = f'{i}-'+row['tool']['tid']
                                    row['tool']['snippet'] = f'DETAIL {i}'
                                messages.append(dict(role='user', content=f'Question {i}', timestamp=1000+i*10))
                                if shape=='legacy':
                                    messages.extend([dict(role='assistant',content=f'Inspecting {i}',reasoning=f'Thought {i}',_turnDuration=2.5,
                                        tool_calls=[dict(id=f'tool-{i}',function=dict(name='terminal',arguments='{}'))]),
                                        dict(role='tool',tool_call_id=f'tool-{i}',content=f'DETAIL {i}')])
                                answer=dict(role='assistant',content=f'## Answer {i}\n\nSearchable prose {i}',timestamp=1001+i*10)
                                if shape=='scene':answer['_anchor_activity_scene']=scene
                                messages.append(answer)
                            def route_session(route):
                                q = parse_qs(urlsplit(route.request.url).query)
                                before = int(q.get('msg_before', [len(messages)])[0])
                                limit = int(q.get('msg_limit', [30])[0])
                                offset = max(0, before-limit)
                                route.fulfill(json={'session': dict(session_id='fixture', title='Older turns',
                                    model='', workspace=temp, messages=messages[offset:before],
                                    message_count=len(messages), tool_calls=[],
                                    _messages_offset=offset, _messages_truncated=offset>0)})
                            page.route('**/api/session?*', route_session)
                            page.goto(base, wait_until='load')
                            deadline = time.monotonic()+30
                            while not page.evaluate("typeof S!=='undefined'&&S._bootReady"):
                                assert time.monotonic() < deadline, 'boot timeout'
                                page.wait_for_timeout(50)
                            page.evaluate("()=>{window._chatActivityDisplayMode='compact_worklog';window._virtualizeTranscript=false;window._sessionEndlessScrollEnabled=false;window._showThinking=true;window._simplifiedToolCalling=true;}")
                            page.evaluate("async()=>await loadSession('fixture')")
                            mutation=os.environ.get('MUTATION','')
                            if mutation=='badge':
                                page.evaluate("""()=>{const original=_settledTurnMemoInput;
                                    _settledTurnMemoInput=function(start,visible,tools,indices){
                                        const result=original(start,visible,tools,indices);
                                        if(result&&indices===undefined){
                                            const turn=[...document.querySelectorAll('#msgInner > .assistant-turn')].find(n=>n._settledTurnMemo&&n._settledTurnMemo.start+n._settledTurnMemo.base===start+_oldestIdx);
                                            if(turn)result.toolGate=turn._settledTurnMemo.toolGate;
                                        }
                                        return result;
                                    };
                                }""")
                            elif mutation=='rebase':
                                page.evaluate("_rebaseSettledTurn=()=>{}")
                            elif mutation=='reuse':
                                page.evaluate("_canRebaseSettledTurn=()=>false")
                            page.wait_for_timeout(300)
                            result = page.evaluate("""async()=>{
                                const old=[...document.querySelectorAll('#msgInner .assistant-turn')][2];
                                const first=[...old.querySelectorAll('.assistant-segment[data-msg-idx]')].find(n=>n.querySelector('h2'));
                                const oldIdx=Number(first.dataset.msgIdx), absolute=_oldestIdx+oldIdx;
                                window.retainedProbeTurn=old;
                                _scrollPinned=false;_messageUserUnpinned=true;
                                first.scrollIntoView({block:'center'});
                                await new Promise(resolve=>setTimeout(resolve,200));
                                const priorContent=S.messages[oldIdx].content;
                                const summary=old.querySelector('.tool-worklog-summary');
                                if(summary)summary.click();
                                const group=old.querySelector('.tool-worklog-group');
                                const disclosure=group?.className;
                                first.scrollIntoView({block:'center'});
                                await new Promise(resolve=>setTimeout(resolve,200));
                                const position=first.getBoundingClientRect().top;
                                const descendants=[...old.querySelectorAll('*')];
                                const changes=new MutationObserver(()=>{});
                                changes.observe($('msgInner'),{childList:true});
                                const start=performance.now();
                                await _loadOlderMessages();
                                const ms=performance.now()-start;
                                const removed=changes.takeRecords().flatMap(r=>[...r.removedNodes]);changes.disconnect();
                                if(!old.isConnected||removed.includes(old))throw new Error('older load rebuilt unchanged settled turn');
                                if(descendants.some(node=>!node.isConnected))throw new Error('retained shell hid a rebuilt subtree');
                                const idx=Number(first.dataset.msgIdx);
                                if(_oldestIdx+idx!==absolute||S.messages[idx].content!==priorContent)throw new Error('retained index points at another message');
                                if(group&&group.className!==disclosure)throw new Error('open disclosure lost');
                                if(Math.abs(first.getBoundingClientRect().top-position)>3)throw new Error('prepend moved the reading anchor');
                                const fork=first.querySelector('[onclick^="forkFromMessage("]');
                                if(!fork||fork.getAttribute('onclick')!==`forkFromMessage(${idx+1})`)throw new Error('fork index stale');
                                const q=S.messages.findLastIndex((m,i)=>i<idx&&m.role==='user');
                                const jump=first.querySelector('[onclick^="jumpToTurnQuestion("]');
                                if(!jump||jump.getAttribute('onclick')!==`jumpToTurnQuestion(${q},${q+1})`)throw new Error('jump index stale');
                                const answers=[...document.querySelectorAll('#msgInner h2')].map(n=>n.textContent);
                                const expected=S.messages.filter(m=>m.role==='assistant'&&m.content.startsWith('## Answer')).map(m=>m.content.split('\\n')[0].slice(3));
                                if(JSON.stringify(answers)!==JSON.stringify(expected))throw new Error('missing or duplicated searchable history');
                                const beforeCorrection=old;
                                S.messages[idx].content='## Corrected answer';
                                renderMessages({reuseSettledTurns:true});
                                if(beforeCorrection.isConnected)throw new Error('changed turn reused');
                                return {ms,answers:answers.length};
                            }""")
                            before_manual=page.evaluate('_oldestIdx')
                            page.locator('#loadOlderIndicator').click()
                            page.wait_for_function('(before)=>!_loadingOlder&&_oldestIdx<before',arg=before_manual)
                            before_auto=page.evaluate("()=>{window._sessionEndlessScrollEnabled=true;return _oldestIdx}")
                            page.locator('#messages').hover()
                            page.mouse.wheel(0,-100000)
                            page.wait_for_function('(before)=>!_loadingOlder&&_oldestIdx<before',arg=before_auto)
                            page.evaluate("window._sessionEndlessScrollEnabled=false")
                            if shape=='legacy':
                                page.evaluate("""async()=>{
                                    renderMessages({preserveScroll:true});
                                    const old=[...document.querySelectorAll('#msgInner > .assistant-turn')].find(n=>n._settledTurnMemo?.toolGate!=='[]'&&n._settledTurnMemo);
                                    if(!old)throw new Error('badge gate control did not select a tool-bearing turn');
                                    await _loadOlderMessages();
                                    if(old.isConnected)throw new Error('changed render-start tool gate reused stale decorations');
                                    const snapshot=()=>[...document.querySelectorAll('#msgInner .assistant-turn')].map(n=>({
                                        text:n.textContent,foot:n.querySelectorAll('.msg-duration-inline,.msg-usage-inline').length
                                    }));
                                    const before=snapshot();
                                    S.toolCalls=[];renderMessages({preserveScroll:true});
                                    const after=snapshot();
                                    if(JSON.stringify(before)!==JSON.stringify(after))throw new Error('reuse differs from full render with identical render-start metadata');
                                }""")
                            if shape=='scene':
                                page.evaluate("""()=>{
                                    const scene=S.messages.find(m=>m._anchor_activity_scene)._anchor_activity_scene;
                                    S.messages=[{role:'user',content:'Question'},
                                        {role:'assistant',content:'Persisted update not in the scene'},
                                        {role:'assistant',content:'Final answer',_anchor_activity_scene:scene},
                                        {role:'user',content:'Next question'},{role:'assistant',content:'Next answer'}];
                                    _oldestIdx=0;renderMessages();
                                    const turn=document.querySelector('#msgInner .assistant-turn');
                                    if(_canRebaseSettledTurn(turn,1,_getVisibleMessagesWithIdx()))throw new Error('generated deferred indices must fall back');
                                    turn.querySelector('.tool-worklog-summary')?.click();
                                    if(_canRebaseSettledTurn(turn,1,_getVisibleMessagesWithIdx()))throw new Error('generated expanded indices must fall back');
                                    const button=document.createElement('button');button.setAttribute('onclick','jumpToTurnQuestion(-1,3)');turn.appendChild(button);
                                    const malformed=document.createElement('span');malformed.setAttribute('data-msg-idx','not-an-index');turn.appendChild(malformed);
                                    _rebaseSettledTurn(turn,5);
                                    if(malformed.getAttribute('data-msg-idx')!=='not-an-index')throw new Error('malformed attribute was rewritten');
                                    if(button.getAttribute('onclick')!=='jumpToTurnQuestion(-1,8)')throw new Error('jump sentinel rebased');
                                }""")
                            assert not errors, errors
                            print(json.dumps(dict(engine=engine, width=width, shape=shape, manual=True, auto=True, **result)), flush=True)
                            context.close()
                    finally:
                        browser.close()
        finally:
            _terminate_process(proc)
            log.close()


if __name__ == '__main__':
    main()
