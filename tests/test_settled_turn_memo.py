"""Turn memoization must conservatively invalidate uncertain metadata."""
import subprocess
from pathlib import Path
from tests.test_issue2768_workspace_links import _extract_function

ROOT = Path(__file__).resolve().parents[1]


def test_turn_memo_tracks_unanchored_tools_and_rejects_partial_turns():
    fn = _extract_function((ROOT/'static/ui.js').read_text(), '_settledTurnMemoInput')
    script = """
const assert=require('node:assert/strict');
const window={};const chatActivityMode=()=> 'transparent_stream';
const S={session:{session_id:'test',workspace:'/example'},toolCalls:[],messages:[
 {role:'user',content:'first'}, {role:'assistant',content:'answer'},
 {role:'user',content:'second'}, {role:'assistant',content:'latest'}]};
const visible=()=>S.messages.map((m,rawIdx)=>({m,rawIdx}));
""" + fn + """
const snapshot=()=>_settledTurnMemoInput(1,visible());
const empty=snapshot().signature;
for(const idx of [undefined,null,-1,'',NaN]){
 S.toolCalls=[{name:'read_file',assistant_msg_idx:idx,snippet:'changed'}];
 assert.notEqual(snapshot().signature,empty,'uncertain tool anchor must invalidate');
}
S.toolCalls=[];
assert.equal(_settledTurnMemoInput(3,visible()),null,'latest turn is never memoized');
for(const flag of ['_live','_partial','_pending']){
 S.messages[1][flag]=true;assert.equal(snapshot(),null);delete S.messages[1][flag];
}
S.messages[1].content='edited';assert.notEqual(snapshot().signature,empty);
S.messages[1].content='answer';
S.session.workspace='/other';assert.notEqual(snapshot().signature,empty);
S.session.workspace='/example';
window._showThinking=false;assert.notEqual(snapshot().signature,empty);
S.messages[1]={role:'assistant',content:'answer'};S.toolCalls=[];
S.messages.splice(2,0,{role:'assistant',content:'wakeup',_source:'process_wakeup'});
assert.equal(snapshot().end,2,'wakeup is a DOM turn boundary');
S.messages.splice(2,1);
S.messages[1]._liveSegmentSeq=9;
assert.equal(snapshot(),null,'routed legacy segments retain ordinary rendering');
delete S.messages[1]._liveSegmentSeq;
S.toolCalls=[{assistant_msg_idx:1,activitySegmentSeq:9,name:'read_file'}];
assert.equal(snapshot(),null,'cross-segment tool routing retains ordinary rendering');
console.log('ok');
"""
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,cwd=ROOT)
    assert result.returncode == 0,result.stderr
