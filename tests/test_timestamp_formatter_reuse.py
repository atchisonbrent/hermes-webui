"""Long transcripts must not construct locale machinery per timestamp."""
import json
import subprocess
from pathlib import Path

from tests.test_issue2768_workspace_links import _extract_function

ROOT = Path(__file__).resolve().parents[1]


def test_server_timestamp_formatting_reuses_formatter_without_changing_output():
    source = (ROOT / 'static/sessions.js').read_text()
    function = _extract_function(source, '_formatInServerTz')
    script = '''
let _serverTz='-0500';
const nativeLocale=Date.prototype.toLocaleString;
let localeCalls=0;
Date.prototype.toLocaleString=function(...args){localeCalls++;return nativeLocale.apply(this,args);};
''' + function + '''
const options={year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'};
let mismatch=0;
for(const tz of ['-0500','+0530','+0545','+0000','bad',null]){
  _serverTz=tz;
  for(let i=0;i<100;i++){
    const date=new Date(Date.UTC(2026,8,10,0,i));
    const m=(tz||'').match(/^([+-])(\\d{2})(\\d{2})$/);
    const shifted=m&&tz!=='+0000';
    const offset=shifted?(m[1]==='+'?1:-1)*(+m[2]*60 + +m[3]):0;
    const expected=nativeLocale.call(new Date(+date+offset*60000),undefined,shifted?{...options,timeZone:'UTC'}:options);
    if(_formatInServerTz(date,options)!==expected)mismatch++;
  }
}
console.log(JSON.stringify({localeCalls,mismatch}));
'''
    result = subprocess.run(['node', '-e', script], text=True, capture_output=True, check=True, cwd=ROOT)
    stats = json.loads(result.stdout)
    assert stats['mismatch'] == 0
    # Browser-local fallbacks retain native semantics; server-offset calls reuse
    # the UTC formatter instead of allocating ICU state for each historical row.
    assert stats['localeCalls'] <= 301, stats
