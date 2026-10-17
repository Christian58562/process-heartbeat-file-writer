# process-heartbeat-file-writer

Atomically writes a JSON file with the current process ID, a monotonic timestamp, and an incrementing sequence number on a fixed interval, so a watchdog can confirm the process is alive.

```python
from process_heartbeat_file_writer import HeartbeatWriter

with HeartbeatWriter("myapp.heartbeat", interval=5.0) as hb:
    # ... your long-running work ...
    # call hb.check() in your main loop; it returns the payload when due
    result = hb.check()
    if result is not None:
        # beat was just written
        pass
```

The file is written with `os.replace` over a temporary file in the same directory, so readers never observe a partially written JSON document. Each beat contains `{"pid":<int>,"timestamp":<float>,"sequence":<int>}`.

## Why this exists

A common liveness pattern is for a long-running process to touch a file periodically; a supervisor reads the file and restarts the process if it has gone stale. Writing the file naively—open, truncate, write—exposes a window where readers see an empty or partial file, which looks exactly like a dead process. This library closes that window by writing to a temp file and renaming it into place atomically.

The trade-off: each beat calls `fsync` before the rename, so correctness under crash comes at the cost of disk I/O. If you need higher frequency than a few beats per second, this is the wrong tool.

## Edge you will hit

The atomicity guarantee depends on the temp file and destination living on the same filesystem. This library handles that for you by creating the temp file in the destination's directory. It does **not** handle a destination directory that does not exist—`tempfile.mkstemp` will raise `FileNotFoundError`. Create the directory before constructing the writer, or wrap construction in a check that suits your deployment.

## Scheduling model

The clock is a constructor argument. In production pass `time.monotonic` (the default). In tests pass a fake that returns deterministic values. `check()` writes a beat only when the clock has reached the next due time and returns the payload when a beat was written, or `None` otherwise, so it is safe to call in a tight loop. `beat_now()` writes unconditionally, returns the payload, and resets the schedule.
