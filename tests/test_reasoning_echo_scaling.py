from __future__ import annotations

import json
import shutil
import subprocess

from tests.test_issue2613_render_cache_signature import _collect_functions


NODE = shutil.which("node")


_SCENARIO = r"""
const sourceReasoning = 'R '.repeat(2500);
const message = {role: 'assistant', reasoning: sourceReasoning};
const echoCache = new Map();
let sanitizeCalls = 0;
let normalizeCalls = 0;
const nativeSanitize = _sanitizeThinkingDisplayText;
const nativeNormalize = _normalizeThinkingEchoCompare;
_sanitizeThinkingDisplayText = function(text) {
  sanitizeCalls++;
  return nativeSanitize(text);
};
_normalizeThinkingEchoCompare = function(text) {
  normalizeCalls++;
  return nativeNormalize(text);
};
function callWorklog(index, reasoning = sourceReasoning) {
  const msg = {role: 'assistant', reasoning};
  const visible = `answer-${index}`;
  return _worklogReasoningTextFromMessage(
    msg, 0, new Set(), visible, visible, [visible], echoCache,
  );
}
const expected = callWorklog('expected');
const outputs = [];
for (let i = 0; i < 50; i++) outputs.push(callWorklog(i));
const sanitizeAfterFirstSource = sanitizeCalls;
const normalizeAfterFirstSource = normalizeCalls;
const changed = callWorklog(999, sourceReasoning + 'x');
console.log(JSON.stringify({
  outputsIdentical: outputs.every(value => value === expected),
  sanitizeCalls,
  normalizeCalls,
  sanitizeAfterFirstSource,
  normalizeAfterFirstSource,
  changedSourceSanitizedOnceMore: sanitizeCalls === sanitizeAfterFirstSource + 1,
  changedSourceReturned: changed === nativeSanitize(sourceReasoning + 'x'),
}));
"""


def test_worklog_reasoning_echo_is_memoized_per_distinct_source():
    """Different visible prose must not reprocess the same huge reasoning text.

    Live activity bursts share one reasoning source but each carries its own
    visible commentary. The rendering cache is scoped to this computation, so
    changed source text must still be cleaned and normalized afresh.
    """
    assert NODE, "node is required for the reasoning-echo scaling harness"
    functions = _collect_functions([
        "_worklogReasoningTextFromMessage",
        "_assistantReasoningPayloadText",
        "_stripVisibleAssistantEchoFromThinking",
        "_stripVisibleAssistantEchoFromThinkingCached",
        "_sanitizeThinkingDisplayTextCached",
        "_normalizeThinkingEchoCompareCached",
        "_thinkingEchoMemoized",
        "_sanitizeThinkingDisplayText",
        "_stripXmlToolCallsDisplay",
        "_normalizeThinkingEchoCompare",
    ])
    result = subprocess.run(
        [NODE, "-e", f"const window = {{}};\n{functions}\n{_SCENARIO}"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["outputsIdentical"]
    assert out["sanitizeAfterFirstSource"] == 1, out
    assert out["normalizeAfterFirstSource"] < 60, out
    assert out["changedSourceSanitizedOnceMore"]
    assert out["changedSourceReturned"]


_DIFFERENTIAL_SCENARIO = r"""
const cases = [
  {reasoning: '', visible: '', final: '', all: []},
  {reasoning: 'alpha beta', visible: 'alpha \n beta', final: 'alpha \n beta', all: ['alpha \n beta']},
  {reasoning: 'only the final matches', visible: 'different prose', final: 'only the final matches', all: ['different prose']},
  {reasoning: 'the second visible matches', visible: 'different prose', final: 'another conclusion', all: ['different prose', 'the second visible matches']},
  {reasoning: 'shared conclusion extended', visible: 'shared conclusion', final: 'shared conclusion', all: ['shared conclusion']},
  {reasoning: 'shared', visible: 'shared conclusion', final: 'shared conclusion', all: ['shared conclusion']},
  {reasoning: 'alpha \n beta', visible: 'alpha beta', final: 'alpha beta', all: ['alpha beta']},
  {reasoning: '<function_calls><tool>x</tool></function_calls> preserve this', visible: 'answer', final: 'answer', all: ['answer']},
  {reasoning: '<｜DSML |function_calls>discard</｜DSML |function_calls> kept', visible: 'different', final: 'different', all: ['different']},
  {reasoning: '  trim the outside only  ', visible: 'other', final: 'other', all: ['other']},
];
const expectedOutcomes = [
  '', // no reasoning
  '', // normalized exact echo
  '', // final-only echo
  '', // second-visible echo
  'shared conclusion extended', // visible is a strict prefix, not an echo
  'shared', // reasoning is a strict prefix, not an echo
  '', // whitespace-equivalent echo
  'preserve this', // function_calls strips only the tool payload
  'kept', // DSML variant strips only the tool payload
  'trim the outside only', // outer whitespace cleanup
];
const sharedCache = new Map();
function uncached(row, index) {
  const visible = row.visible;
  return _worklogReasoningTextFromMessage(
    {role: 'assistant', reasoning: row.reasoning}, index, new Set(), visible,
    row.final, row.all,
  );
}
function cached(row, index) {
  const visible = row.visible;
  return _worklogReasoningTextFromMessage(
    {role: 'assistant', reasoning: row.reasoning}, index, new Set(), visible,
    row.final, row.all, sharedCache,
  );
}
const mismatches = [];
cases.forEach((row, index) => {
  const expected = uncached(row, index);
  const actual = cached(row, index);
  if (actual !== expectedOutcomes[index] || expected !== actual) {
    mismatches.push({index, expected, actual, required: expectedOutcomes[index]});
  }
});
let reversedOrderMatches = true;
[...cases].reverse().forEach((row, index) => {
  if (cached(row, cases.length - 1 - index) !== uncached(row, index)) reversedOrderMatches = false;
});
console.log(JSON.stringify({mismatches, reversedOrderMatches}));
"""


def _run_node_scenario(scenario: str) -> dict:
    assert NODE, "node is required for the reasoning-echo differential harness"
    functions = _collect_functions([
        "_worklogReasoningTextFromMessage",
        "_assistantReasoningPayloadText",
        "_stripVisibleAssistantEchoFromThinking",
        "_stripVisibleAssistantEchoFromThinkingCached",
        "_sanitizeThinkingDisplayTextCached",
        "_normalizeThinkingEchoCompareCached",
        "_thinkingEchoMemoized",
        "_sanitizeThinkingDisplayText",
        "_stripXmlToolCallsDisplay",
        "_normalizeThinkingEchoCompare",
    ])
    result = subprocess.run(
        [NODE, "-e", f"const window = {{}};\n{functions}\n{scenario}"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_cached_and_uncached_reasoning_echo_results_are_identical():
    """The cache covers both return-empty and content-producing paths.

    Reusing one computation across inputs and in different orders must not
    leak content between burst messages, XML variants, or whitespace echoes.
    """
    out = _run_node_scenario(_DIFFERENTIAL_SCENARIO)
    assert out["mismatches"] == [], out
    assert out["reversedOrderMatches"]
