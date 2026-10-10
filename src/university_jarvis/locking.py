"""Cross-process advisory file lock for read-modify-write of local records.

The lock is held on a sidecar ``<record>.lock`` file (never on the record
itself, which is replaced atomically) and is released by the operating system
if the holder dies, so a crashed process cannot leave a stale lock behind.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .state import StateError

LOCK_TIMEOUT_SECONDS = 30.0
_held = threading.local()  # lock paths held by the current thread
_POLL_SECONDS = 0.05

try:  # POSIX
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)

except ImportError:  # Windows
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


@contextmanager
def record_lock(
    record_path: Path, *, timeout: float = LOCK_TIMEOUT_SECONDS, create_dir: bool = False
) -> Iterator[None]:
    """Hold an exclusive lock for ``record_path`` across a read-modify-write.

    Re-entrant within one thread (a nested acquisition of the same path is a
    no-op), so a locked operation may call another locked operation. Raises ``StateError`` if
    the lock cannot be obtained within ``timeout`` seconds. The record's
    directory is only created when ``create_dir`` is true (first creation of a
    record); otherwise a missing directory means there is nothing to protect
    and the caller's own "record not found" handling applies, with no side effects.
    """
    lock_path = record_path.with_name(record_path.name + ".lock")
    held = getattr(_held, "paths", None)
    if held is None:
        held = _held.paths = set()
    if lock_path in held:
        yield
        return
    if create_dir:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    elif not lock_path.parent.is_dir():
        yield
        return
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise StateError(
                    "Another Serapis operation is updating this record; try again shortly."
                )
            time.sleep(_POLL_SECONDS)
        held.add(lock_path)
        try:
            yield
        finally:
            held.discard(lock_path)
            _unlock(fd)
    finally:
        os.close(fd)
