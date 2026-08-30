from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from foundry.errors import WindowBusy

try:  # POSIX only; the foundry targets macOS and Linux hosts.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]

DEFAULT_TIMEOUT = 10.0

_HELD_GUARD = threading.Lock()
_HELD: set[tuple[str, int]] = set()
"""Locks each thread is already inside, so self-deadlock refuses immediately.

``flock`` ties the lock to the open file description and this module opens a
fresh descriptor per acquisition, so a thread that re-entered its own lock
would wait out the whole timeout and then blame a foreign process that does not
exist. Nesting stays refused -- a lifecycle step is one step -- but it now says
what actually happened, at once. Keyed per thread: another thread in this
process still contends through flock, for real.
"""


def _key(lock_path: Path) -> tuple[str, int]:
    return str(lock_path.resolve()), threading.get_ident()


@contextmanager
def _tracked(key: tuple[str, int]) -> Iterator[None]:
    with _HELD_GUARD:
        _HELD.add(key)
    try:
        yield
    finally:
        with _HELD_GUARD:
            _HELD.discard(key)


@contextmanager
def exclusive(lock_path: Path, *, timeout: float = DEFAULT_TIMEOUT) -> Iterator[None]:
    """Hold an exclusive advisory lock on ``lock_path`` for the block.

    The lock covers a whole window lifecycle step -- read state, replace the
    catalog, write the manifest, write state -- so a second process cannot
    interleave and leave state, manifest, and catalog disagreeing.

    Refuses loudly rather than proceeding unlocked: a host without ``fcntl``
    raises instead of silently running without mutual exclusion, and a thread
    that already holds this lock is told so at once instead of stalling for the
    whole timeout and then naming a process that does not exist.
    """
    if fcntl is None:  # pragma: no cover - exercised only on non-POSIX hosts
        raise WindowBusy(
            "advisory file locking is unavailable on this platform; "
            "the foundry requires a POSIX host"
        )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    key = _key(lock_path)
    with _HELD_GUARD:
        already_held = key in _HELD
    if already_held:
        raise WindowBusy(
            f"this thread already holds {lock_path.parent.name}; "
            "a lifecycle step must not nest inside another"
        )
    handle = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise WindowBusy(
                        f"another foundry process holds {lock_path.parent.name}; "
                        f"waited {timeout:g}s"
                    ) from exc
                time.sleep(0.05)
        try:
            with _tracked(key):
                yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)
