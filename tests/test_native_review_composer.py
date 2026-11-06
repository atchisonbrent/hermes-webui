"""Exercise real composer functions, including reversal to an ordinary chat."""
from pathlib import Path
import subprocess

from tests.helpers import source_between


def test_read_only_composer_blocks_actions_and_preserves_draft():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'static/ui.js').read_text()
    functions = '\n'.join([
        source_between(source, 'function getComposerPrimaryAction(){', '\nfunction _applyBusyComposerPlaceholder'),
        source_between(source, 'function _applyBusyComposerPlaceholder(){', '\nfunction _setComposerPrimaryButtonIcon'),
        source_between(source, 'function updateSendBtn(){', '\nasync function handleComposerPrimaryAction'),
    ])
    harness = r'''
const assert=require('node:assert/strict');
const S={session:null,busy:false};
const msg={value:'preserved draft',disabled:false,readOnly:false,placeholder:''};
const classes=new Set();
const btn={dataset:{},style:{},setAttribute(){},classList:{toggle(k,v){v?classes.add(k):classes.delete(k)},contains:k=>classes.has(k),add:k=>classes.add(k),remove:k=>classes.delete(k)}};
const $=id=>id==='msg'?msg:id==='btnSend'?btn:null;
const window={};const _compressionPlaceholderSaved=null;
const _composerHasContent=()=>!!msg.value;
const assistantDisplayName=()=> 'Hermes';
const _setComposerPrimaryButtonIcon=()=>{};
const requestAnimationFrame=fn=>fn();
const t=key=>key==='composer_read_only'?'Read-only conversation':key;
'''
    assertions = r'''
updateSendBtn();assert.equal(getComposerPrimaryAction(),'send');
for(const flag of ['read_only','is_read_only']){
 S.session={[flag]:true};updateSendBtn();
 assert.equal(msg.readOnly,true);
 assert.equal(btn.disabled,true);
 assert.equal(btn.title,'Read-only conversation');
 S.busy=true;S.activeStreamId='fixture';
 assert.equal(getComposerPrimaryAction(),'disabled');
 msg.value='';updateSendBtn();assert.equal(msg.placeholder,'Read-only conversation');
 msg.value='preserved draft';S.busy=false;
}
S.session={};updateSendBtn();
assert.equal(msg.readOnly,false);assert.equal(btn.disabled,false);
assert.equal(msg.value,'preserved draft');
msg.disabled=true;updateSendBtn();
assert.equal(msg.disabled,true);assert.equal(btn.disabled,true);
'''
    result = subprocess.run(['node', '-e', harness + functions + assertions], cwd=root,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
