"""Cooperative cancellation: the UI sets the token, every paid call and every pipeline stage checks it first.
An HTTP call already in flight cannot be aborted; it finishes and the next check stops the run.

On Lambda the cancel request arrives in a different invocation than the one doing the work, so a worker can install
an external probe (a flag in S3). It is polled at most once per EXTERNAL_POLL_SECONDS: check() runs before every paid
call and an S3 request each time would be wasteful."""
import threading
from time import monotonic
from typing import Callable, Optional

EXTERNAL_POLL_SECONDS = 2.0

_EVENT = threading.Event()
_external: Optional[Callable[[], bool]] = None
_last_poll = 0.0


class RunCancelled(BaseException):  # not Exception: broad "except Exception" fallbacks must not swallow it
    """The team cancelled the run; work done so far is kept."""


def set_external(probe: Optional[Callable[[], bool]]) -> None:
    global _external, _last_poll
    _external, _last_poll = probe, 0.0


def request() -> None:
    _EVENT.set()


def clear() -> None:
    _EVENT.clear()


def is_set() -> bool:
    global _last_poll
    if _EVENT.is_set():
        return True
    if _external is not None and monotonic() - _last_poll >= EXTERNAL_POLL_SECONDS:
        _last_poll = monotonic()
        try:
            if _external():
                _EVENT.set()
        except Exception:  # noqa: BLE001 - a failed probe must not stop (or crash) a run
            pass
    return _EVENT.is_set()


def check() -> None:
    if is_set():
        raise RunCancelled("run was cancelled")
