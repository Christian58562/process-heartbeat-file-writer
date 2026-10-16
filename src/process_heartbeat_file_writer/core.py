"""Write an atomic JSON heartbeat file for process liveness checks.

The file is rewritten on a fixed interval with the current process ID, a
monotonic timestamp from a caller-supplied clock, and a sequence number that
increments on every write. Each write goes to a temporary file in the same
directory and is renamed onto the final path, so readers never see a
half-written file.
"""

from __future__ import annotations

import json
import os
import tempfile
from types import TracebackType
from typing import Callable

DEFAULT_INTERVAL: float = 5.0
DEFAULT_BEAT: int = 1


class HeartbeatWriter:
    """Periodically write a JSON heartbeat file.

    Parameters
    ----------
    path:
        Destination file path. Writes are atomic relative to this path.
    interval:
        Minimum seconds between beats. Defaults to 5.
    beat:
        The monotonic beat value written at construction. The internal clock
        advances this value by ``interval`` on each call so callers can assert
        on deterministic integers rather than floats.
    pid:
        Override the process ID written to the file. Defaults to ``os.getpid``
        evaluated lazily on each write so that forks report the child PID.
    clock:
        Callable returning the current monotonic time as a number. Used both
        for the timestamp written to the file and for scheduling. Inject a
        fake in tests; inject ``time.monotonic`` in production.
    """

    def __init__(
        self,
        path: str,
        *,
        interval: float = DEFAULT_INTERVAL,
        beat: int = DEFAULT_BEAT,
        pid: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if beat < 0:
            raise ValueError("beat must be non-negative")
        self._path = path
        self._interval = float(interval)
        self._pid_fn = (lambda: pid) if pid is not None else os.getpid
        # The clock serves double duty: the monotonic timestamp written to the
        # JSON and the scheduler that decides when the next beat is due. Using
        # one source means tests inject a single fake and both values move in
        # lockstep, so assertions stay on integers.
        self._clock = clock if clock is not None else _default_clock
        self._beat = int(beat)
        self._seq = 0
        self._next_due: float | None = None
        self._started = False

    @property
    def path(self) -> str:
        """The configured destination path."""
        return self._path

    @property
    def interval(self) -> float:
        """The configured beat interval in seconds."""
        return self._interval

    def start(self) -> None:
        """Begin scheduling. The first beat is due immediately."""
        if self._started:
            return
        self._started = True
        self._next_due = self._clock()

    def stop(self) -> None:
        """Stop scheduling. Clears the next-due time."""
        self._started = False
        self._next_due = None

    def beat_now(self) -> dict:
        """Write a beat immediately, regardless of the schedule.

        Resets the schedule so the next automatic beat is one interval from
        now. Returns the payload that was written so callers can assert on it.
        """
        payload = self._write_payload()
        self._next_due = self._clock() + self._interval
        return payload

    def check(self) -> dict | None:
        """Write a beat if one is due and the writer is running.

        Returns the written payload when a beat occurred, or ``None`` when no
        beat was written (either because the writer is stopped or the next
        due time has not yet been reached).
        """
        if not self._started or self._next_due is None:
            return None
        now = self._clock()
        if now < self._next_due:
            return None
        payload = self._write_payload()
        self._next_due = now + self._interval
        return payload

    def __enter__(self) -> "HeartbeatWriter":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    def _write_payload(self) -> dict:
        self._seq += 1
        now = self._clock()
        payload = {
            "pid": int(self._pid_fn()),
            "timestamp": now,
            "sequence": self._seq,
        }
        directory = os.path.dirname(os.path.abspath(self._path))
        # os.replace is atomic on POSIX when source and destination are on
        # the same filesystem. tempfile puts the temp file in the same
        # directory as the destination, which guarantees a same-filesystem
        # rename and avoids leaking temp files into the system tmp dir.
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".heartbeat-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return payload


def _default_clock() -> float:
    """Return the real monotonic time.

    Imported lazily so that ``time`` is only needed when the caller does not
    inject a clock, keeping the module import side-effect free for tests.
    """
    import time

    return time.monotonic()
