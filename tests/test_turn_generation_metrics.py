"""Turn TPS uses only the current turn's completed model calls, not tool/user wait time."""

import sys
from collections import deque
from types import SimpleNamespace

import pytest

from api.models import _merge_session_display_metadata

from api.turn_metrics import (
    MAX_TURN_HISTORY_CALLS,
    begin_turn_generation_history,
    restore_turn_generation_history,
    track_turn_generation_history,
    turn_tps_from_generation_history,
)


def _agent():
    return SimpleNamespace(
        _api_latency_history=deque([90.0, 95.0], maxlen=2),
        _api_output_history=deque([30, 40], maxlen=2),
        session_api_calls=2,
        max_iterations=3,
    )


def test_unavailable_turn_marker_does_not_inherit_an_old_positive_value():
    target = {'role': 'assistant', '_turnGenerationRecorded': True}
    stale = {'role': 'assistant', '_turnGenerationTps': 88.0}
    _merge_session_display_metadata(target, stale)
    assert '_turnGenerationTps' not in target
    _merge_session_display_metadata(
        target, {'role': 'assistant', '_turnGenerationRecorded': True, '_turnGenerationTps': 25.0}
    )
    assert target['_turnGenerationTps'] == 25.0


def test_turn_tps_excludes_prior_waits_and_retains_every_turn_call():
    agent = _agent()

    baseline = begin_turn_generation_history(agent)
    # Extend beyond the old last-2 history cap so the current turn proves its
    # first call is still retained rather than silently disappearing.
    # 99 seconds spent on tools after the first model response is not an API
    # duration and must not enter the denominator.
    for duration, tokens in ((4.0, 100), (8.0, 200)):
        agent._api_latency_history.append(duration)
        agent._api_output_history.append(tokens)
        agent.session_api_calls += 1

    assert turn_tps_from_generation_history(agent, baseline) == 25.0


def test_turn_tps_is_unavailable_when_provider_usage_is_incomplete():
    agent = _agent()
    baseline = begin_turn_generation_history(agent)

    # Provider returned success without usage: session_api_calls advances, but
    # the paired API histories do not. A wall-clock fallback would be misleading.
    agent.session_api_calls += 1

    assert turn_tps_from_generation_history(agent, baseline) is None


def test_histories_are_restored_to_their_original_rolling_cap_across_turns():
    agent = _agent()

    for durations, outputs in (((4.0, 8.0), (100, 200)), ((5.0, 2.0), (50, 100))):
        starts = []
        begin = track_turn_generation_history(agent, starts)
        for duration, tokens in zip(durations, outputs, strict=True):
            agent._api_latency_history.append(duration)
            agent._api_output_history.append(tokens)
            agent.session_api_calls += 1
        try:
            assert turn_tps_from_generation_history(agent, begin) == round(sum(outputs) / sum(durations), 1)
        finally:
            for start in reversed(starts):
                restore_turn_generation_history(start)
        assert agent._api_latency_history == deque(durations, maxlen=2)
        assert agent._api_output_history == deque(outputs, maxlen=2)
        assert agent._api_latency_history.maxlen == 2
        assert agent._api_output_history.maxlen == 2


def test_replacement_agent_gets_a_fresh_baseline_and_each_owner_is_restored():
    starts = []
    original = _agent()
    original_start = track_turn_generation_history(original, starts)
    replacement = SimpleNamespace(
        _api_latency_history=deque(maxlen=2),
        _api_output_history=deque(maxlen=2),
        session_api_calls=0,
        max_iterations=3,
    )
    replacement_start = track_turn_generation_history(replacement, starts)

    assert replacement_start is not original_start
    replacement._api_latency_history.append(4.0)
    replacement._api_output_history.append(100)
    replacement.session_api_calls += 1
    assert turn_tps_from_generation_history(replacement, replacement_start) == 25.0
    assert track_turn_generation_history(replacement, starts) is replacement_start

    for start in reversed(starts):
        restore_turn_generation_history(start)
    for owner in (original, replacement):
        assert owner._api_latency_history.maxlen == 2
        assert owner._api_output_history.maxlen == 2
        assert len(owner._api_latency_history) <= 2
        assert len(owner._api_output_history) <= 2


def test_overlapping_turns_restore_only_after_the_last_owner_finishes():
    agent = _agent()
    agent.max_iterations = 3
    first = track_turn_generation_history(agent, [])
    second = track_turn_generation_history(agent, [])
    temporary_maxlen = agent._api_latency_history.maxlen
    assert temporary_maxlen > 2

    restore_turn_generation_history(first)
    # The newer turn still needs every paired API history entry. An earlier
    # turn finishing must neither truncate its data nor shrink the working cap.
    assert agent._api_latency_history.maxlen == temporary_maxlen
    assert agent._api_output_history.maxlen == temporary_maxlen

    restore_turn_generation_history(second)
    assert agent._api_latency_history.maxlen == 2
    assert agent._api_output_history.maxlen == 2
    assert agent._api_latency_history == deque([90.0, 95.0], maxlen=2)
    assert agent._api_output_history == deque([30, 40], maxlen=2)

    restore_turn_generation_history(second)
    assert agent._api_latency_history.maxlen == 2
    assert agent._api_output_history.maxlen == 2


def test_turn_retention_is_additive_when_iteration_budget_equals_rolling_cap():
    agent = _agent()
    agent.max_iterations = 2
    start = begin_turn_generation_history(agent)
    for duration, tokens in ((4.0, 100), (8.0, 200)):
        agent._api_latency_history.append(duration)
        agent._api_output_history.append(tokens)
        agent.session_api_calls += 1
    try:
        assert turn_tps_from_generation_history(agent, start) == 25.0
    finally:
        restore_turn_generation_history(start)
    assert agent._api_latency_history.maxlen == 2
    assert agent._api_output_history.maxlen == 2


@pytest.mark.parametrize('budget', [sys.maxsize, sys.maxsize - 1, 2**80, float('inf')])
def test_unlimited_iteration_budget_is_bounded_not_a_deque_overflow(budget):
    """AIAgent's default budget is sys.maxsize; that must not fail the turn.

    Regression: ``deque(maxlen=cap + sys.maxsize)`` raised ``OverflowError:
    Python int too large to convert to C ssize_t`` before the first model call,
    so every turn on an unlimited budget ended in an error card.
    """
    agent = _agent()
    agent.max_iterations = budget
    starts = []
    start = track_turn_generation_history(agent, starts)

    assert start.available
    assert agent._api_latency_history.maxlen == 2 + MAX_TURN_HISTORY_CALLS
    assert agent._api_output_history.maxlen == 2 + MAX_TURN_HISTORY_CALLS
    for duration, tokens in ((4.0, 100), (8.0, 200)):
        agent._api_latency_history.append(duration)
        agent._api_output_history.append(tokens)
        agent.session_api_calls += 1
    assert turn_tps_from_generation_history(agent, start) == 25.0

    for item in reversed(starts):
        restore_turn_generation_history(item)
    assert agent._api_latency_history == deque([4.0, 8.0], maxlen=2)
    assert agent._api_output_history == deque([100, 200], maxlen=2)


def test_turn_longer_than_the_retention_bound_reports_no_rate(monkeypatch):
    monkeypatch.setattr('api.turn_metrics.MAX_TURN_HISTORY_CALLS', 3)
    agent = _agent()
    agent.max_iterations = sys.maxsize
    start = begin_turn_generation_history(agent)
    assert agent._api_latency_history.maxlen == 2 + 3

    # Three calls fit beside the two inherited entries: exact rate.
    for _ in range(3):
        agent._api_latency_history.append(2.0)
        agent._api_output_history.append(50)
        agent.session_api_calls += 1
    assert turn_tps_from_generation_history(agent, start) == 25.0

    # A fourth evicts only an entry inherited from before the turn: the
    # remaining inherited entry still anchors where this turn begins.
    agent._api_latency_history.append(2.0)
    agent._api_output_history.append(50)
    agent.session_api_calls += 1
    assert turn_tps_from_generation_history(agent, start) == 25.0

    # Past the bound this turn's own first calls are evicted: no partial rate.
    for _ in range(2):
        agent._api_latency_history.append(2.0)
        agent._api_output_history.append(50)
        agent.session_api_calls += 1
    assert len(agent._api_latency_history) == 5
    assert turn_tps_from_generation_history(agent, start) is None

    restore_turn_generation_history(start)
    assert agent._api_latency_history.maxlen == 2
    assert agent._api_output_history.maxlen == 2


def test_baseline_failure_never_fails_the_turn_and_leaves_the_agent_untouched():
    agent = _agent()
    agent.session_api_calls = 'not-a-number'
    latency_history = agent._api_latency_history
    output_history = agent._api_output_history
    starts = []

    start = track_turn_generation_history(agent, starts)

    assert not start.available
    assert starts == [start]
    assert track_turn_generation_history(agent, starts) is start
    assert agent._api_latency_history is latency_history
    assert agent._api_output_history is output_history
    assert not hasattr(agent, '_webui_generation_history_state')
    agent.session_api_calls = 3
    agent._api_latency_history.append(4.0)
    agent._api_output_history.append(100)
    assert turn_tps_from_generation_history(agent, start) is None
    restore_turn_generation_history(start)
    assert agent._api_latency_history.maxlen == 2


def test_rate_computation_failure_reports_no_rate():
    agent = _agent()
    start = begin_turn_generation_history(agent)
    agent._api_latency_history.append(4.0)
    agent._api_output_history.append(None)
    agent.session_api_calls += 1
    try:
        assert turn_tps_from_generation_history(agent, start) is None
    finally:
        restore_turn_generation_history(start)


def test_restoring_an_unavailable_baseline_does_not_trim_a_concurrent_turn():
    agent = _agent()
    live = begin_turn_generation_history(agent)
    widened = agent._api_latency_history.maxlen
    agent.session_api_calls = 'not-a-number'
    failed = track_turn_generation_history(agent, [])
    assert not failed.available
    agent.session_api_calls = 2

    restore_turn_generation_history(failed)

    assert agent._api_latency_history.maxlen == widened
    assert agent._api_output_history.maxlen == widened
    restore_turn_generation_history(live)
    assert agent._api_latency_history.maxlen == 2
