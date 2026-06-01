"""Concurrent-run protection via a simple PID lockfile.

Invariant: the lockfile is always removed in a finally block so a crash never
permanently locks the pipeline. Use as a context manager:

    with LockFile():
        run_pipeline()
"""
import logging
import os

import config

log = logging.getLogger(__name__)


class LockExists(Exception):
    """Raised when another run already holds the lock."""


class LockFile:
    def __init__(self, path=None):
        self.path = path or config.LOCKFILE_PATH

    def _stale(self):
        """A lock is stale if its PID is no longer running."""
        try:
            with open(self.path) as f:
                pid = int(f.read().strip())
        except (ValueError, OSError):
            return True
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        return False

    def acquire(self):
        if os.path.exists(self.path):
            if self._stale():
                log.warning("Removing stale lockfile at %s", self.path)
                self.release()
            else:
                raise LockExists(f"Lockfile present at {self.path}; run in progress")
        with open(self.path, "w") as f:
            f.write(str(os.getpid()))

    def release(self):
        try:
            os.remove(self.path)
        except OSError:
            pass

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
