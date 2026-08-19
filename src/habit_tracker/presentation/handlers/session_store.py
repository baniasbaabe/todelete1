"""Read and write the in-flight check-in session in PTB's ``user_data``.

Both the check-in and proof handlers touch this state. Keeping the key and the
decode-failure policy in one place stops them from drifting apart — the
"drop an unreadable session" rule used to live only in the proof handler, so
``/checkin`` still crashed on one.
"""

from __future__ import annotations

from telegram.ext import ContextTypes

from habit_tracker.application.checkin_session import CheckinSession
from habit_tracker.infrastructure.observability.tracing import TRACE_CARRIER_KEY

SESSION_KEY = "checkin_session"


def load_session(context: ContextTypes.DEFAULT_TYPE) -> CheckinSession | None:
    """Return the in-flight session, dropping it if finished, expired, or unreadable."""
    if context.user_data is None:
        return None

    data = context.user_data.get(SESSION_KEY)
    if not data:
        return None

    try:
        session = CheckinSession.from_dict(data)
    except (KeyError, TypeError, ValueError):
        # A session persisted by an older release may no longer match the
        # current shape. Drop it rather than trapping the user in a broken
        # check-in they cannot restart.
        clear_session(context)
        return None

    if session.is_complete() or session.is_expired():
        clear_session(context)
        return None
    return session


def save_session(context: ContextTypes.DEFAULT_TYPE, session: CheckinSession) -> None:
    if context.user_data is not None:
        context.user_data[SESSION_KEY] = session.to_dict()


def clear_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data is not None:
        context.user_data.pop(SESSION_KEY, None)
        context.user_data.pop(TRACE_CARRIER_KEY, None)
