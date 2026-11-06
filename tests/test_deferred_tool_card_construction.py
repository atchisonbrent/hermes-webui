"""A deferred transparent card must not build detail that is discarded next."""
import json
import subprocess
import pytest

from tests.test_issue4622_tool_card_restore_guard import _DRIVER_SRC, UI_JS_PATH, NODE


def test_deferred_tool_card_keeps_header_and_data_without_detail_html(tmp_path):
    if NODE is None:
        pytest.skip('node not on PATH')
    script = _DRIVER_SRC.replace('buildToolCard(payload).innerHTML', 'buildToolCard(payload,{deferDetail:true}).innerHTML')
    driver = tmp_path / 'driver.js'
    driver.write_text(script)
    tool = {'name':'terminal','done':True,'args':{'command':'printf detail'},'snippet':'OUTPUT_SENTINEL ' * 5000}
    result = subprocess.run([NODE,str(driver),str(UI_JS_PATH),'direct',json.dumps(tool)], text=True,capture_output=True,check=True)
    output = json.loads(result.stdout)
    assert 'tool-card-header' in output['html']
    assert 'tool-card-toggle' in output['html']
    assert 'tool-card-detail' not in output['html']
    assert 'data-full=' not in output['html']
    assert output['snippet_len'] == len(tool['snippet'])
