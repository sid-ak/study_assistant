# CI failure: ThreadSanitizer data race in the connection pool

The nightly ThreadSanitizer job failed intermittently in `ConnectionPoolTest.ConcurrentRelease`.
The same test always passed in the normal and AddressSanitizer jobs.

## Symptom

```text
WARNING: ThreadSanitizer: data race (pid=4127)
  Write of size 8 at 0x7b0c00001230 by thread T3:
    #0 orbit::ConnectionPool::release(orbit::Connection*) src/pool.cpp:88
  Previous read of size 8 at 0x7b0c00001230 by thread T5:
    #0 orbit::ConnectionPool::acquire() src/pool.cpp:61
SUMMARY: ThreadSanitizer: data race src/pool.cpp:88 in orbit::ConnectionPool::release(orbit::Connection*)
```

## Cause

`release()` took the pool's mutex to mark the connection idle, but the lock went out of scope one
line early, so the push onto the idle list ran unlocked. A concurrent `acquire()` could read the
list while it was being modified, and two threads could receive the same connection. The race
only shows up under particular thread interleavings, which is why the test failed intermittently
and only ThreadSanitizer, which tracks every memory access, reported it reliably.

## Fix

The idle-list update now happens inside the locked scope:

```cpp
void ConnectionPool::release(Connection* connection) {
    std::lock_guard<std::mutex> lock(mutex_);
    connection->mark_idle();
    idle_.push_back(connection);
}
```

The fix shipped in Orbit 4.2.

## Prevention

`idle_` is now annotated `GUARDED_BY(mutex_)`, and the Clang build enables `-Wthread-safety`, so
an unlocked access to it is a compile-time warning, which CI treats as an error.
