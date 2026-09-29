"""Execute the production display-correction branches, without an agent call."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

STREAMING = Path(__file__).resolve().parents[1] / 'api' / 'streaming.py'


def _branch(prefix):
    tree = ast.parse(STREAMING.read_text())
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.If)
               and (ast.unparse(n.test) == prefix or
                    (prefix.endswith(' and') and ast.unparse(n.test).startswith(prefix)))]
    assert len(matches) == 1
    return ast.Module(body=[matches[0]], type_ignores=[])


@pytest.mark.parametrize('branch', ['live', 'save', 'done'])
def test_metadata_window_correction_preserves_runtime_trigger(branch):
    compressor = SimpleNamespace(context_length=1050000, threshold_tokens=450000,
                                 last_prompt_tokens=325000)
    session = SimpleNamespace(context_length=272000, threshold_tokens=450000)
    env = dict(_cc=compressor, _real_ctx_cache=[272000], _usage={},
               _skip_cc_cl=True, _cc_cl=1050000, s=session,
               _dropped_stale_cap_sse=True, _orig_cc_cl_sse=1050000,
               _orig_cc_thresh_sse=450000, _fb_cl=272000, usage={})
    prefix = {'live': '_real_ctx_cache[0]', 'save': '_skip_cc_cl',
              'done': '_dropped_stale_cap_sse and'}[branch]
    exec(compile(_branch(prefix), str(STREAMING), 'exec'), env)
    observed = {'live': lambda: env['_usage']['threshold_tokens'],
                'save': lambda: session.threshold_tokens,
                'done': lambda: env['usage']['threshold_tokens']}[branch]()
    assert observed == compressor.threshold_tokens


def test_done_payload_writes_the_observed_trigger_before_and_after_fallback():
    tree = ast.parse(STREAMING.read_text())
    writes = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
              and any(ast.unparse(t) == "usage['threshold_tokens']" for t in node.targets)]
    assert writes
    for node in writes:
        env = {'_cc': SimpleNamespace(threshold_tokens=450000),
               '_orig_cc_thresh_sse': 450000, 'usage': {}}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(STREAMING), 'exec'), env)
        assert env['usage']['threshold_tokens'] == 450000


def test_reload_context_refresh_does_not_invent_a_new_trigger():
    from api import routes
    # Hydration knows only the last observed trigger, not a new runtime policy.
    assert routes._observed_threshold_tokens_for_context_window(450000, 1050000, 272000) == 450000
