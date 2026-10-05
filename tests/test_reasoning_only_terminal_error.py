"""Classify a reasoning-only clean stop without inventing a rate limit."""
from api.streaming import _classify_provider_error


def test_reasoning_only_clean_stop_is_not_silent_rate_limit():
    # Recorded failure shape: tool work followed by stop, empty content,
    # reasoning and api_content sidecar; agent promotes final_response only.
    result = {
        'final_response': 'I need to inspect the renderer.',
        'messages': [
            {'role': 'user', 'content': 'Show the image inline.'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 't1'}]},
            {'role': 'tool', 'content': 'Inspection complete', 'tool_call_id': 't1'},
            {'role': 'assistant', 'content': '', 'finish_reason': 'stop',
             'reasoning': 'I need to inspect the renderer.',
             'api_content': 'I need to inspect the renderer.'},
        ],
    }
    error = _classify_provider_error('', silent_failure=True, result=result)
    assert error['type'] == 'reasoning_only'
    assert 'final answer' in error['hint']
    assert 'rate limit' not in error['hint'].lower()


def test_real_provider_error_takes_precedence_over_reasoning_metadata():
    result = {'messages': [{'role': 'assistant', 'content': '', 'reasoning': 'Thinking'}]}
    error = _classify_provider_error('HTTP 401 invalid API key', result=result)
    assert error['type'] == 'auth_mismatch'


def test_empty_output_does_not_invent_rate_limit():
    error = _classify_provider_error('', silent_failure=True, result={'messages': []})
    assert error['type'] == 'no_response'
    assert 'rate limit' not in error['hint'].lower()


def test_blank_reasoning_is_not_reported_as_reasoning():
    result = {'messages': [{'role': 'assistant', 'content': '', 'reasoning': '   ', 'finish_reason': 'stop'}]}
    assert _classify_provider_error('', silent_failure=True, result=result)['type'] == 'no_response'


def test_nonterminal_reasoning_is_not_reported_as_clean_stop():
    result = {'messages': [{'role': 'assistant', 'content': '', 'reasoning': 'Old thought'}]}
    assert _classify_provider_error('', silent_failure=True, result=result)['type'] == 'no_response'


def test_historical_reasoning_does_not_label_current_empty_stop():
    result = {'messages': [
        {'role': 'assistant', 'content': '', 'reasoning': 'Old reasoning'},
        {'role': 'user', 'content': 'New turn'},
        {'role': 'assistant', 'content': '', 'finish_reason': 'stop'},
    ]}
    assert _classify_provider_error('', silent_failure=True, result=result)['type'] == 'no_response'
