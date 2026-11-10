"""Generation-only throughput derived from the Agent's paired API histories."""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GenerationHistoryStart:
    latencies: tuple[float, ...]
    outputs: tuple[int, ...]
    api_calls: int
    owner: Any = field(default=None, repr=False, compare=False)
    history_maxlens: tuple[tuple[str, int], ...] = ()
    # False when the baseline could not be taken: no rate is shown for the turn.
    available: bool = True


logger = logging.getLogger(__name__)

# Extra paired-history entries retained for one turn. AIAgent's default
# iteration budget is ``sys.maxsize`` ("unlimited"), which is not a usable
# ``deque`` maxlen (it must fit a C ssize_t once the rolling cap is added) and
# would not be a bound at all. A turn that makes more model calls than this
# loses its first entries and reports no rate, never a partial one.
MAX_TURN_HISTORY_CALLS = 10_000

_HISTORY_STATE_ATTRIBUTE = '_webui_generation_history_state'
_HISTORY_STATE_LOCK = threading.RLock()
_HISTORY_FIELDS = ('_api_latency_history', '_api_output_history')


def _turn_call_allowance(agent: Any) -> int:
    """Model calls one turn may retain: the iteration budget, bounded."""
    try:
        budget = int(getattr(agent, "max_iterations", 1) or 1)
    except OverflowError:
        # float('inf') is another spelling of "unlimited".
        budget = MAX_TURN_HISTORY_CALLS
    except (TypeError, ValueError):
        budget = 1
    return max(1, min(budget, MAX_TURN_HISTORY_CALLS))


def begin_turn_generation_history(agent: Any) -> GenerationHistoryStart:
    """Retain enough paired API history to cover this turn, including >10 calls.

    Hermes normally bounds these deques at 10 entries for its rolling average. A
    longer turn would evict its first calls before settlement. Keep that rolling
    display policy, but retain a bounded extra turn's worth here so no current
    call disappears from the generation-time denominator.
    """
    max_calls = _turn_call_allowance(agent)

    with _HISTORY_STATE_LOCK:
        state = getattr(agent, _HISTORY_STATE_ATTRIBUTE, None)
        is_first_active_turn = not isinstance(state, dict)
        if is_first_active_turn:
            history_maxlens = []
            for name in _HISTORY_FIELDS:
                prior = getattr(agent, name, None)
                original_maxlen = getattr(prior, 'maxlen', None)
                cap = original_maxlen if isinstance(original_maxlen, int) and original_maxlen > 0 else 10
                history_maxlens.append((name, cap))
            state = {
                'history_maxlens': tuple(history_maxlens),
                'active_starts': set(),
            }

        history_maxlens = state['history_maxlens']
        latencies = list(getattr(agent, '_api_latency_history', ()) or ())
        outputs = list(getattr(agent, '_api_output_history', ()) or ())
        # Do not let an earlier turn's restore trim a newer concurrent turn.
        # A new turn still inherits the TRUE original cap from the shared state.
        # Build everything before touching the agent, so a failure here leaves
        # its histories and caps exactly as they were.
        widened = [
            (name, deque(list(getattr(agent, name, ()) or ()), maxlen=cap + max_calls))
            for name, cap in history_maxlens
        ]
        start = GenerationHistoryStart(
            latencies=tuple(latencies),
            outputs=tuple(outputs),
            api_calls=int(getattr(agent, 'session_api_calls', 0) or 0),
            owner=agent,
            history_maxlens=history_maxlens,
        )
        for name, history in widened:
            setattr(agent, name, history)
        if is_first_active_turn:
            setattr(agent, _HISTORY_STATE_ATTRIBUTE, state)
        state['active_starts'].add(id(start))
        return start


def track_turn_generation_history(
    agent: Any, starts: list[GenerationHistoryStart]
) -> GenerationHistoryStart:
    """Snapshot an agent only once; a replacement gets a fresh baseline."""
    for start in starts:
        if start.owner is agent:
            return start
    try:
        start = begin_turn_generation_history(agent)
    except Exception:
        # The rate is a display nicety; failing to prepare it must never fail
        # the turn. Record an unavailable baseline so nothing is shown.
        logger.warning('Turn generation history unavailable; no rate for this turn', exc_info=True)
        start = GenerationHistoryStart(
            latencies=(), outputs=(), api_calls=0, owner=agent, available=False
        )
    starts.append(start)
    return start


def restore_turn_generation_history(start: GenerationHistoryStart) -> None:
    """Restore an owner's original rolling history after its last active turn."""
    owner = start.owner
    if owner is None:
        return
    with _HISTORY_STATE_LOCK:
        state = getattr(owner, _HISTORY_STATE_ATTRIBUTE, None)
        if not isinstance(state, dict) or id(start) not in state['active_starts']:
            return
        state['active_starts'].remove(id(start))
        if state['active_starts']:
            return
        for name, cap in state['history_maxlens']:
            values = list(getattr(owner, name, ()) or ())
            setattr(owner, name, deque(values[-cap:], maxlen=cap))
        delattr(owner, _HISTORY_STATE_ATTRIBUTE)


def _suffix_since(before: tuple, current: list | None) -> list | None:
    """Return calls appended after ``before``, allowing old bounded-history eviction."""
    if current is None:
        return None
    if not before:
        return current
    if current[: len(before)] == list(before):
        return current[len(before) :]
    for overlap in range(min(len(before), len(current)), 0, -1):
        if list(before[-overlap:]) == current[:overlap]:
            return current[overlap:]
    return None


def turn_tps_from_generation_history(agent: Any, start: GenerationHistoryStart) -> float | None:
    """Weighted output tokens / completed model-call seconds for one turn.

    ``None`` means the provider's usage history cannot account for every
    call, so no rate is shown instead of falling back to turn wall time.
    """
    if not start.available:
        return None
    try:
        return _turn_tps(agent, start)
    except Exception:
        logger.warning('Turn generation rate could not be computed', exc_info=True)
        return None


def _turn_tps(agent: Any, start: GenerationHistoryStart) -> float | None:
    latencies = _suffix_since(
        start.latencies, list(getattr(agent, "_api_latency_history", ()) or ())
    )
    outputs = _suffix_since(
        start.outputs, list(getattr(agent, "_api_output_history", ()) or ())
    )
    expected_calls = int(getattr(agent, "session_api_calls", 0) or 0) - start.api_calls
    if (
        expected_calls <= 0
        or latencies is None
        or outputs is None
        or len(latencies) != expected_calls
        or len(outputs) != expected_calls
    ):
        return None

    generation_seconds = math.fsum(latencies)
    output_tokens = sum(outputs)
    if generation_seconds <= 0 or output_tokens <= 0:
        return None
    return round(output_tokens / generation_seconds, 1)
