"""A prose-only completion has no temporary worklog to collapse."""
import subprocess
from pathlib import Path

from tests.test_issue2768_workspace_links import _extract_function

ROOT = Path(__file__).resolve().parents[1]


def test_no_worklog_skips_second_render_but_transparent_activity_keeps_fallback():
    source = (ROOT / 'static/ui.js').read_text()
    fn = _extract_function(source, '_collapseJustSettledWorklogInPlace')
    worthy = _extract_function(source, '_anchorSceneSceneHasWorklogWorthyRows')
    script = """
const assert=require('node:assert/strict');
const inner={querySelectorAll:()=>[]};
const $=()=>inner;
const S={messages:[{role:'assistant',content:'Download the EPUB'}]};
""" + worthy + fn + """
assert.equal(_collapseJustSettledWorklogInPlace('run-1'),true);
assert.equal(_collapseJustSettledWorklogInPlace(''),false);
const scene={stream_id:'run-1',activity_rows:[{role:'tool',tool:{name:'read_file'}}]};
S.messages.push({role:'assistant',_anchor_activity_scene:scene});
assert.equal(_collapseJustSettledWorklogInPlace('run-1'),false);
assert.equal(_collapseJustSettledWorklogInPlace('run-2'),true);
scene.stream_id='';scene.identity={stream_id:'run-1'};
assert.equal(_collapseJustSettledWorklogInPlace('run-1'),false);
S.messages[1]._anchor_stream_id='run-2';
assert.equal(_collapseJustSettledWorklogInPlace('run-2'),false);
console.log('ok');
"""
    result = subprocess.run(['node','-e',script],capture_output=True,text=True,cwd=ROOT)
    assert result.returncode == 0, result.stderr
