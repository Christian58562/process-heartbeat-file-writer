import json
import os
import tempfile
import unittest

from process_heartbeat_file_writer.core import HeartbeatWriter


class _FakeClock:
    """Monotonic clock that only moves when told to.

    Returns the current beat value and advances it by ``interval`` each call.
    This lets tests assert exact integer timestamps without touching the wall
    clock.
    """

    def __init__(self, interval):
        self._interval = interval
        self._beat = 0

    def __call__(self):
        current = self._beat
        self._beat += self._interval
        return current


class TestHeartbeatWriter(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)
        self.path = tmp.name

    def _read_payload(self):
        with open(self.path, "r", encoding="utf-8") as f:
            content = f.read()
        return json.loads(content), content

    def test_beat_now_writes_initial_payload(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        payload = writer.beat_now()
        self.assertEqual(payload, {"pid": os.getpid(), "timestamp": 0, "sequence": 1})
        on_disk, _ = self._read_payload()
        self.assertEqual(payload, on_disk)

    def test_sequence_increments_on_each_beat(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        first = writer.beat_now()
        second = writer.beat_now()
        third = writer.beat_now()
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(third["sequence"], 3)

    def test_timestamp_uses_clock_value(self):
        clock = _FakeClock(7)
        writer = HeartbeatWriter(self.path, interval=7, clock=clock)
        p1 = writer.beat_now()
        p2 = writer.beat_now()
        self.assertEqual(p1["timestamp"], 0)
        self.assertEqual(p2["timestamp"], 14)

    def test_custom_pid_is_written(self):
        clock = _FakeClock(1)
        writer = HeartbeatWriter(self.path, interval=1, pid=4242, clock=clock)
        payload = writer.beat_now()
        self.assertEqual(payload["pid"], 4242)

    def test_check_does_not_write_when_stopped(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        result = writer.check()
        self.assertIsNone(result)

    def test_check_writes_first_beat_after_start(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        writer.start()
        result = writer.check()
        self.assertIsNotNone(result)
        self.assertEqual(result["sequence"], 1)

    def test_check_skips_until_interval_elapses(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        writer.start()
        first = writer.check()
        self.assertIsNotNone(first)
        # start() consumed one clock tick (now=0 at start, clock advances to 5).
        # check() consumed one tick: now=5, due=0, beat written, next due=10,
        # clock advances to 10.
        second = writer.check()
        # now==10, due==10, so beat.
        self.assertIsNotNone(second)
        self.assertEqual(second["sequence"], 2)
        third = writer.check()
        # now==15, due==15, so beat.
        self.assertIsNotNone(third)
        self.assertEqual(third["sequence"], 3)

    def test_stop_clears_schedule(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        writer.start()
        writer.stop()
        self.assertIsNone(writer.check())

    def test_start_is_idempotent(self):
        clock = _FakeClock(5)
        writer = HeartbeatWriter(self.path, interval=5, clock=clock)
        writer.start()
        first_due = writer._next_due
        writer.start()
        self.assertEqual(writer._next_due, first_due)

    def test_context_manager_starts_and_stops(self):
        clock = _FakeClock(5)
        with HeartbeatWriter(self.path, interval=5, clock=clock) as writer:
            result = writer.check()
            self.assertIsNotNone(result)
        self.assertIsNone(writer.check())

    def test_file_is_valid_json_after_overwrite(self):
        clock = _FakeClock(3)
        writer = HeartbeatWriter(self.path, interval=3, clock=clock)
        for _ in range(10):
            writer.beat_now()
        payload, _ = self._read_payload()
        self.assertEqual(payload["sequence"], 10)

    def test_invalid_interval_raises(self):
        with self.assertRaises(ValueError):
            HeartbeatWriter(self.path, interval=0)
        with self.assertRaises(ValueError):
            HeartbeatWriter(self.path, interval=-1)

    def test_invalid_beat_raises(self):
        with self.assertRaises(ValueError):
            HeartbeatWriter(self.path, beat=-1)

    def test_default_interval_constant(self):
        from process_heartbeat_file_writer.core import DEFAULT_INTERVAL
        self.assertEqual(DEFAULT_INTERVAL, 5.0)

    def test_default_beat_constant(self):
        from process_heartbeat_file_writer.core import DEFAULT_BEAT
        self.assertEqual(DEFAULT_BEAT, 1)

    def test_exports_from_package_init(self):
        import process_heartbeat_file_writer as pkg
        self.assertIn("HeartbeatWriter", pkg.__all__)
        self.assertIn("DEFAULT_INTERVAL", pkg.__all__)
        self.assertIn("DEFAULT_BEAT", pkg.__all__)


if __name__ == "__main__":
    unittest.main()
