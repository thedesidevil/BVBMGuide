"""Cooperative cancellation: the UI sets the token, every paid call and every pipeline stage checks it first.
An HTTP call already in flight cannot be aborted; it finishes and the next check stops the run."""
import threading

_EVENT = threading.Event()


class RunCancelled(BaseException):  # not Exception: broad "except Exception" fallbacks must not swallow it
    """The team cancelled the run; work done so far is kept."""


def request() -> None:
    _EVENT.set()


def clear() -> None:
    _EVENT.clear()


def is_set() -> bool:
    return _EVENT.is_set()


def check() -> None:
    if _EVENT.is_set():
        raise RunCancelled("run was cancelled")
