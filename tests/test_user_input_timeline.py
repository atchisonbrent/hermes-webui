"""Display-only receipt interleaving must not mutate source scenes or leak sessions."""
import shutil
import subprocess
from pathlib import Path

import pytest

import runpy

_extract_function=runpy.run_path(str(Path(__file__).with_name('test_cross_session_message_load_isolation.py')))['_extract_function']


@pytest.mark.skipif(not shutil.which('node'), reason='node required')
def test_receipt_projection_is_ordered_isolated_and_nonmutating():
    source=(Path(__file__).resolve().parents[1]/'static/ui.js').read_text()
    functions='\n'.join(_extract_function(source,name) for name in (
        '_anchorSceneRowTimestampSeconds','_liveSceneRowsWithUserInputs'))
    script=r"""
const assert=require('node:assert/strict');
const receipt=(id,ts,stream='run')=>({input_id:id,kind:'clarify',content:id,timestamp:ts,stream_id:stream});
let S={session:{session_id:'one',_user_inputs:[receipt('answer',3),receipt('steer',2),receipt('other-run',2,'other')]},
  _userInputsSessionId:'one',_userInputs:new Map([['answer',receipt('answer',3)]])};
const rows=[{row_id:'old',timestamp:1},{row_id:'unknown'},{row_id:'new',created_at:4}];
const saved=JSON.stringify(rows);
const project=()=>_liveSceneRowsWithUserInputs(rows,'run');
assert.deepEqual(project().map(r=>r.row_id),['old','unknown','user-input:steer','user-input:answer','new']);
assert.equal(JSON.stringify(rows),saved);
assert.deepEqual(project(),project());
S.session={session_id:'two',_user_inputs:[]};
assert.equal(project(),rows,'previous-session in-memory receipts leaked');
S.session._user_inputs=[receipt('tail',5)];
assert.deepEqual(project().map(r=>r.row_id),['old','unknown','new','user-input:tail']);
assert.equal(JSON.stringify(rows),saved);
S.session._user_inputs=[receipt('milliseconds',1700000002000),receipt('equal',1700000002),receipt('unknown',undefined)];
const timedRows=[{row_id:'earlier',timestamp:1700000001},{row_id:'later',timestamp:1700000003}];
assert.deepEqual(_liveSceneRowsWithUserInputs(timedRows,'run').map(r=>r.row_id),
  ['user-input:unknown','earlier','user-input:milliseconds','user-input:equal','later']);
"""
    node=shutil.which('node')
    assert node is not None
    result=subprocess.run([node,'-e',functions+'\n'+script],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
