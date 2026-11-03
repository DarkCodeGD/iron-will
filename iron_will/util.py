"""Small Qt-free helpers: logging setup and single-instance locks."""

from __future__ import annotations

import fcntl
import logging
import os
import sys

from . import paths


def setup_logging() -> None:
    """Log to stderr. Under systemd (JOURNAL_STREAM set) skip timestamps — the
    journal adds its own. ``IRON_WILL_DEBUG=1`` turns on debug output."""
    level = logging.DEBUG if os.environ.get("IRON_WILL_DEBUG") else logging.INFO
    fmt = "%(levelname)s %(name)s: %(message)s"
    if not os.environ.get("JOURNAL_STREAM"):
        fmt = "%(asctime)s " + fmt
    logging.basicConfig(level=level, format=fmt, datefmt="%H:%M:%S", stream=sys.stderr)


def acquire_lock(name: str) -> int | None:
    """Take an exclusive, non-blocking ``flock`` on ``<runtime>/<name>.lock``.

    Returns the open fd (keep it alive for the lifetime of the process — the
    kernel drops the lock automatically when the process dies, even on
    SIGKILL, so there are no stale PID files to clean up) or ``None`` if
    another instance already holds it.
    """
    fd = os.open(paths.runtime_dir() / f"{name}.lock", os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd
