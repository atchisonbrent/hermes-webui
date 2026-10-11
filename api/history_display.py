"""Read-only presentation fields; provider replay remains owned by the agent."""
import copy
import logging

_DISPLAY_FIELDS = frozenset({"display_commentary", "display_reasoning", "display_content"})
_log = logging.getLogger(__name__)


def _without_projection(row):
    return {key: value for key, value in row.items() if key not in _DISPLAY_FIELDS} if isinstance(row, dict) else row


def project_history_for_display(messages, *, profile=None):
    """Use the agent's profile-aware, think-stripped commentary projection.

    Never trust stored/imported display fields or decode raw provider items in
    the browser. An absent/incompatible optional API cannot break GET or done.
    """
    clean = [_without_projection(row) for row in messages]
    if not any(isinstance(row, dict) and row.get("codex_message_items") for row in clean):
        return clean
    try:
        from agent.history_commentary import project_history_commentary
        from api.profiles import get_hermes_home_for_profile

        projected = project_history_commentary(
            copy.deepcopy(clean),
            home=get_hermes_home_for_profile(profile),
        )
        if not isinstance(projected, list) or len(projected) != len(clean):
            raise ValueError("projection changed row count")
        if any(_without_projection(row) != original for row, original in zip(projected, clean, strict=True)):
            raise ValueError("projection changed canonical fields or row order")
        return projected
    except ImportError:
        return clean  # Compatibility with agents predating the optional API.
    except Exception:
        # Do not log exception text: provider rows and config can contain secrets.
        _log.warning("Optional history commentary projection failed; retaining canonical display")
        return clean
