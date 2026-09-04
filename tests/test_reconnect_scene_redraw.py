"""Execute the production reconnect replay seam, not a source-string assertion.

Browser coverage in browser_reconnect_scene_redraw.py exercises loadSession and
real DOM rendering; these cheap Node checks pin fallback and redraw counts.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def replay_probe(restored_scene, count, skip_unkeyed=True, has_rows=True):
    sessions = (ROOT / 'static/sessions.js').read_text()
    ui = (ROOT / 'static/ui.js').read_text()
    start = sessions.index('const liveToolReplayId=(tc)=>')
    replay = sessions[start:sessions.index('    let didReconnect=false;', start)]
    start = ui.index('function appendLiveToolCard(')
    append = ui[start:ui.index('\nfunction _findLatestLiveAssistantByBurst', start)]
    script = r"""
const vm=require('node:vm');
const opts=JSON.parse(process.argv[1]);
const tools=Array.from({length:opts.count},(_,i)=>({name:'terminal',tid:'tool-'+i,done:true}));
tools.push({name:'read_file',done:true});
let redraws=0, appended=[];
const sandbox={
  S:{session:{session_id:'session'},activeStreamId:'run',toolCalls:tools},
  sid:'session',activeStreamId:'run',INFLIGHT:{},restoredAnchorScene:opts.restored_scene,
  document:{getElementById:()=>({querySelector:()=>opts.has_rows?{}:null})},
  isFinalAnswerOnlyMode:()=>false,
  isLiveAnchorActivitySceneOwner:()=>true,
  _renderLiveAnchorActivitySceneForStream:()=>{redraws++;return true;},
};
vm.createContext(sandbox);
vm.runInContext(APPEND,sandbox);
// The actual append function proves the amplification when a scene owns DOM.
// For legacy fallback, observe arguments at the append boundary instead.
if(!opts.restored_scene) sandbox.appendLiveToolCard=(tc)=>appended.push(tc.tid||'unkeyed');
vm.runInContext(REPLAY+'\nreplayPersistedLiveToolCards('+JSON.stringify({skipUnkeyedRestoredDuplicates:opts.skip_unkeyed})+');',sandbox);
console.log(JSON.stringify({redraws,appended,tools:tools.length}));
""".replace('APPEND', json.dumps(append)).replace('REPLAY', json.dumps(replay))
    result = subprocess.run(
        [shutil.which('node') or 'node', '-e', script, json.dumps({
            'restored_scene': restored_scene, 'count': count,
            'skip_unkeyed': skip_unkeyed, 'has_rows': has_rows,
        })], capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize('count', [0, 1, 470])
def test_restored_complete_scene_is_not_redrawn_per_saved_tool(count):
    result = replay_probe(True, count)
    assert result['redraws'] == 0, result
    assert result['tools'] == count + 1  # No stored activity was dropped.


def test_legacy_restored_html_still_replays_keyed_tools():
    result = replay_probe(False, 3)
    assert result['appended'] == ['tool-0', 'tool-1', 'tool-2']


@pytest.mark.parametrize('skip_unkeyed,has_rows', [(False, True), (True, False)])
def test_failed_scene_or_empty_html_keeps_unkeyed_fallback(skip_unkeyed, has_rows):
    result = replay_probe(False, 3, skip_unkeyed, has_rows)
    assert result['appended'] == ['tool-0', 'tool-1', 'tool-2', 'unkeyed']
