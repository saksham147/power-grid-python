"""Composition root for the grid app: the one concrete piece of process-wide state
behind ``state.py``/``status.py``.

``GridStateTracker`` is genuinely process-wide in-memory state -- there is exactly
one, built lazily on first use, so the messaging listeners (once connected, see
``connect`` below) and every HTTP view read and write the very same tracked totals
rather than each starting from an empty tracker of its own.
"""
import functools

from .kafka import connect_listeners as _connect_listeners
from .state import GridStateTracker


@functools.cache
def state_tracker() -> GridStateTracker:
    return GridStateTracker()


def connect() -> None:
    """Starts driving ``state_tracker()`` from producer output and distributor zone
    balance.

    Not called automatically anywhere in this project yet -- see
    ``grid.kafka.connect_listeners`` for why every app here leaves that to an
    explicit call rather than a side effect of import.
    """
    _connect_listeners(state_tracker())
