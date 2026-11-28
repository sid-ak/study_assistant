# Concurrency

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
A thread is an independent sequence of execution within a process, and all threads in a process
share the same memory. Sharing memory makes communication between threads cheap, but it also means
two threads can read and write the same data at the same moment. C++ gives programs several tools to
coordinate that access, ranging from simple locks to lock-free atomic operations, each trading
simplicity against performance.

| Tool | How it coordinates threads | Cost | Main risk |
| ---- | -------------------------- | ---- | --------- |
| `std::mutex` with a lock wrapper | Only one thread at a time may run the protected code | Cheap when uncontended; a waiting thread sleeps | Deadlock; contention limiting throughput |
| `std::shared_mutex` | Many readers or one writer | Higher per-operation cost than a mutex | Writers waiting behind a steady stream of readers |
| `std::atomic<T>` | Individual reads and updates are indivisible CPU operations | Very cheap for single values | Composing several atomic steps is not itself atomic |
| `std::condition_variable` | A thread sleeps until another signals that something changed | Requires a mutex | Missed or spurious wake-ups |
| `std::async`, `std::future` | Run a task and retrieve its result later | Thread creation and a shared state | Blocking unexpectedly in a future's destructor |
<!-- --8<-- [end:intro] -->

## 1. Data races

<!-- --8<-- [start:races] -->
A data race occurs when two threads access the same memory at the same time, at least one of them
writes, and nothing synchronizes the access.

```cpp
int hits = 0;

void data_race() {
    std::thread a([] { for (int i = 0; i < 100000; ++i) ++hits; });
    std::thread b([] { for (int i = 0; i < 100000; ++i) ++hits; });
    a.join();
    b.join();
    // hits can end up below 200000: ++hits is a read, an add, and a write,
    // and the two threads' steps interleave. Formally, the behavior is undefined.
}
```

- Why it is undefined behavior: the compiler optimizes each thread assuming no other thread changes
  its data mid-operation. A race can therefore produce results that no ordering of the two threads'
  steps would explain, not just one of the expected values.
- Race condition versus data race: a race condition is a logic error where the outcome depends on
  timing, such as two threads both checking that a file does not exist and then both creating it.
  It can occur even when every individual access is properly synchronized.
- Detection: ThreadSanitizer (`-fsanitize=thread`) reports data races at run time. See
  [Compiler](compiler.md).

> A web server counting total requests with a plain `int` shared by worker threads under-reports
> traffic under load, because increments from different threads overwrite each other.
> ThreadSanitizer flags the line in a single test run.
<!-- --8<-- [end:races] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#1-data-races)

## 2. Mutexes and lock wrappers

<!-- --8<-- [start:mutexes] -->
A mutex (mutual exclusion) is a lock that only one thread can hold at a time; other threads that try
to lock it wait.

```cpp
class Counter {
public:
    void add(int n) {
        std::lock_guard<std::mutex> lock(mutex_);   // unlocked when add() returns or throws
        total_ += n;
    }
    int read() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return total_;
    }
private:
    mutable std::mutex mutex_;                      // mutable so const read() can lock it
    int total_ = 0;
};

class Settings {
public:
    std::string get() const {
        std::shared_lock lock(mutex_);              // many readers at once
        return value_;
    }
    void set(std::string v) {
        std::unique_lock lock(mutex_);              // one writer, no readers
        value_ = std::move(v);
    }
private:
    mutable std::shared_mutex mutex_;
    std::string value_;
};
```

- Always lock through RAII: `std::lock_guard` locks in its constructor and unlocks in its
  destructor, so an exception or early return cannot leave the mutex locked. See
  [Ownership](ownership.md).
- `std::scoped_lock`: locks several mutexes at once using a deadlock-avoidance algorithm.
- `std::unique_lock`: can be unlocked and relocked, which `std::condition_variable` requires.
- `std::shared_mutex`: lets many readers hold a `std::shared_lock` at once, while a writer needs
  exclusive access.
- Granularity: holding a lock for less time, or protecting smaller pieces of data with separate
  locks, lets more threads make progress. It also adds more opportunities for deadlock.

> An in-memory cache shared by request threads protects its map with a `std::shared_mutex`: many
> requests read cached entries concurrently, and only a cache refresh takes the exclusive lock.
<!-- --8<-- [end:mutexes] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#2-mutexes-and-lock-wrappers)

## 3. Deadlock

<!-- --8<-- [start:deadlock] -->
A deadlock happens when threads wait on each other in a cycle, so none can ever continue.

```cpp
struct Account {
    std::mutex m;
    int balance = 0;
};

void transfer(Account& from, Account& to, int amount) {
    // Deadlock-prone: transfer(a, b) and transfer(b, a) can each hold one lock and wait forever
    // std::lock_guard l1(from.m);
    // std::lock_guard l2(to.m);

    std::scoped_lock lock(from.m, to.m);   // acquires both without deadlocking
    from.balance -= amount;
    to.balance += amount;
}
```

- Classic case: thread A holds lock 1 and waits for lock 2, while thread B holds lock 2 and waits for
  lock 1.
- Prevention: acquire multiple locks in one consistent global order, lock them together with
  `std::scoped_lock`, and avoid calling unknown code (such as callbacks) while holding a lock.

> A banking service transferring money between two accounts locks both accounts. If it locks them in
> argument order, two opposite transfers can deadlock; locking with `std::scoped_lock`, or always
> locking the lower account number first, prevents it.
<!-- --8<-- [end:deadlock] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#3-deadlock)

## 4. Atomics

<!-- --8<-- [start:atomics] -->
`std::atomic<T>` wraps a value so that each operation on it — load, store, increment,
compare-and-swap — completes as one indivisible step that other threads cannot interrupt.

```cpp
std::atomic<int> requests{0};

void on_request() { requests.fetch_add(1); }        // safe from any thread, no lock

std::atomic<int> peak{0};

void record(int value) {
    int current = peak.load();
    // Retry until no other thread changed peak between the load and the store
    while (value > current && !peak.compare_exchange_weak(current, value)) {}
}
```

- Mechanism: the operations map to special CPU instructions, so no thread is ever put to sleep.
- Compare-and-swap (CAS): `compare_exchange_weak` and `compare_exchange_strong` set the value to the
  desired one only if it still equals the expected one; otherwise they load the current value so the
  caller can retry. CAS is the building block of lock-free data structures.
- Limitation: two atomic operations in a row are not atomic together. Checking a value and then
  updating it with a separate `store` can still race, which is why `record` uses a CAS loop.

> A rate limiter tracking requests per second can use `std::atomic<int>` for its counter, so every
> request thread increments it without waiting on a lock in the hot path.
<!-- --8<-- [end:atomics] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#4-atomics)

## 5. Memory ordering in atomics

<!-- --8<-- [start:ordering] -->
Atomic operations accept a memory ordering argument that tells the compiler and CPU how strictly
other threads must observe the operation's effects.

```cpp
std::atomic<bool> ready{false};

void publish() { ready.store(true, std::memory_order_seq_cst); }   // the default, spelled out
bool check()   { return ready.load(std::memory_order_seq_cst); }
```

- `std::memory_order_seq_cst`: the default and the strongest guarantee. All threads see operations as
  if they happened in a single sequence.
- Weaker orderings (`acquire`, `release`, `relaxed`): allow more optimization, but are only correct
  with a precise argument about which threads read and write the value.
- Guideline: use the default unless profiling shows a real cost and the weaker ordering can be proven
  correct.

> A shutdown flag checked by worker threads, `std::atomic<bool> stopping`, is almost always left at
> the default ordering: the cost difference is unmeasurable for a flag read once per loop, and the
> default is always correct.
<!-- --8<-- [end:ordering] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#5-memory-ordering-in-atomics)

## 6. Waiting and results

<!-- --8<-- [start:waiting] -->
Some work does not need a shared variable at all: one thread waits for a signal, or a task simply
returns a value.

```cpp
std::mutex queue_mutex;
std::condition_variable queue_ready;
std::queue<int> jobs;

int wait_for_job() {
    std::unique_lock lock(queue_mutex);
    queue_ready.wait(lock, [] { return !jobs.empty(); });   // re-checks after every wake-up
    int job = jobs.front();
    jobs.pop();
    return job;
}

int compute() {
    std::future<int> result = std::async(std::launch::async, [] { return 6 * 7; });
    return result.get();                                    // blocks until the task finishes
}
```

- Condition variables: `wait` releases the mutex while sleeping and reacquires it before returning.
  Passing a predicate handles spurious wake-ups (waking with nothing to do) and signals sent before
  the thread started waiting.
- Futures: `std::async` runs a task and returns a `std::future` whose `get()` delivers the result, or
  rethrows the task's exception.

> A thread pool keeps pending jobs in a queue guarded by a mutex; idle worker threads sleep on a
> `std::condition_variable` and are woken when a job is pushed, instead of spinning and burning CPU.
<!-- --8<-- [end:waiting] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#6-waiting-and-results)

## 7. Initialization and shutdown

<!-- --8<-- [start:shutdown] -->
Program startup and shutdown are frequent sources of concurrency bugs.

```cpp
struct Registry { std::vector<std::string> names; };

Registry& registry() {
    static Registry instance;       // initialized exactly once, even with concurrent callers
    return instance;
}

void run_workers() {
    Counter counter;                // the Counter class from section 2
    std::vector<std::jthread> workers;
    for (int i = 0; i < 4; ++i) {
        workers.emplace_back([&counter] { counter.add(1); });
    }
}   // workers is destroyed first, joining every thread before counter is destroyed
```

- Thread-safe local statics: since C++11, a `static` local variable is initialized exactly once even
  if several threads reach it at the same time. This makes a function returning a static local a
  simple, safe way to create a lazily initialized singleton.
- Shutdown order: if background threads are still running while `main()` returns and static objects
  are destroyed, those threads can use destroyed objects. Stop and `join` threads before static
  destruction begins; `std::jthread` joins automatically in its destructor.

> Command-line tools that start several background worker threads for file processing store them in
> `std::jthread` objects, so returning early from `main` on an error still stops and joins every
> worker before shared data is destroyed.
<!-- --8<-- [end:shutdown] -->

[Go deeper →](../cpp_deep_dive/concurrency.md#7-initialization-and-shutdown)

## Choosing a concurrency tool

<!-- --8<-- [start:choosing] -->
Start with a mutex and `std::scoped_lock` around the smallest correct critical section. Move to
atomics only when profiling shows lock contention is a real bottleneck, because lock-free code is
significantly harder to prove correct. Design shutdown explicitly, so that every thread stops before
the objects it uses are destroyed.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Memory model and data races](https://en.cppreference.com/cpp/language/memory_model)
- [Static local variables](https://en.cppreference.com/cpp/language/storage_duration)
- [`thread_local`](https://en.cppreference.com/cpp/keyword/thread_local)
- [Lambda expressions](https://en.cppreference.com/cpp/language/lambda)

Threads

- [Concurrency support library](https://en.cppreference.com/cpp/thread)
- [`std::thread`](https://en.cppreference.com/cpp/thread/thread) and [`join`](https://en.cppreference.com/cpp/thread/thread/join)
- [`std::jthread`](https://en.cppreference.com/cpp/thread/jthread)

Mutual exclusion

- [`std::mutex`](https://en.cppreference.com/cpp/thread/mutex) and [`std::shared_mutex`](https://en.cppreference.com/cpp/thread/shared_mutex)
- [`std::lock_guard`](https://en.cppreference.com/cpp/thread/lock_guard), [`std::scoped_lock`](https://en.cppreference.com/cpp/thread/scoped_lock), [`std::unique_lock`](https://en.cppreference.com/cpp/thread/unique_lock), [`std::shared_lock`](https://en.cppreference.com/cpp/thread/shared_lock)
- [`std::condition_variable`](https://en.cppreference.com/cpp/thread/condition_variable)

Atomics

- [`std::atomic`](https://en.cppreference.com/cpp/atomic/atomic)
- [`fetch_add`](https://en.cppreference.com/cpp/atomic/atomic/fetch_add), [`load`](https://en.cppreference.com/cpp/atomic/atomic/load), [`store`](https://en.cppreference.com/cpp/atomic/atomic/store)
- [`compare_exchange_weak` and `compare_exchange_strong`](https://en.cppreference.com/cpp/atomic/atomic/compare_exchange)
- [`std::memory_order`](https://en.cppreference.com/cpp/atomic/memory_order)

Tasks

- [`std::async`](https://en.cppreference.com/cpp/thread/async) and [`std::launch`](https://en.cppreference.com/cpp/thread/launch)
- [`std::future`](https://en.cppreference.com/cpp/thread/future)
- [`std::queue`](https://en.cppreference.com/cpp/container/queue)
