# Concurrency

> Part of the [C++ Deep Dive](README.md) · Overview: [Concurrency](../cpp_overview/concurrency.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:intro"

This page covers what makes threaded code hard at the level of the compiler and CPU, what locks cost
and how to structure them, how deadlocks form and are found, how atomics are implemented and what memory
orderings actually do, the traps in condition variables and `std::async`, safe shutdown, lock-free
programming, and false sharing.

## 1. Data races

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:races"

### Why threads break sequential reasoning

- Operations that look indivisible are not: `++counter` is a load, an add, and a store, and another
  thread can run between any two of them.
- Code does not execute in the order it was written: the compiler reorders and removes operations during
  optimization, and the CPU executes instructions out of order. Both are invisible to a single thread
  but observable by a second one.
- Happens-before: two threads' operations have a defined order only when something establishes one —
  locking and unlocking a mutex, an atomic operation, or creating and joining a thread. Without such an
  edge, there is no guarantee one thread ever sees another's writes.

### What the optimizer assumes

```cpp
bool done = false;          // written by another thread, but not atomic
int work = 0;

void spin() {
    while (!done) {
        ++work;
    }
}
```

- Assumption: the compiler may assume no other thread modifies `done` without synchronization, because
  that would be a data race and therefore undefined behavior.
- Result: with Clang at `-O2`, `spin` compiles to a bare return. Nothing the compiler can see changes
  `done` inside the loop, so it is free to read `done` once or not at all, and a write from another
  thread has no defined effect.
- Consequence: a data race is not "one of two values". The compiled program may not correspond to any
  ordering of the source's operations.

### Race conditions without data races

```cpp
class Registry {
public:
    bool contains(int key) const { std::scoped_lock lock(m_); return items_.contains(key); }
    void erase(int key) { std::scoped_lock lock(m_); items_.erase(key); }

    bool erase_if_present(int key) {          // correct: check and act under one lock
        std::scoped_lock lock(m_);
        return items_.erase(key) > 0;
    }
private:
    mutable std::mutex m_;
    std::set<int> items_;
};

void caller(Registry& r) {
    if (r.contains(7)) {   // another thread may erase 7 here
        r.erase(7);        // no data race, but the check is already stale (time-of-check to time-of-use)
    }
}
```

- Every method is individually synchronized, yet the pair is not atomic. Thread safety composes at the
  level of invariants, not individual methods.
- Fix: perform the check and the action under one lock, or offer an operation that does both.

### `volatile` does not make code thread-safe

```cpp
volatile int ticks = 0;     // for memory-mapped hardware or signal handlers, not for threads

void tick() {
    ticks = ticks + 1;      // still a separate load and store: increments can be lost
}
```

- Purpose: `volatile` tells the compiler that a variable can change outside the program's control, as a
  memory-mapped hardware register can, so every read and write in the source must actually happen.
- What it does not provide: atomicity, ordering between threads, or any happens-before edge. It removes
  one compiler optimization and nothing else.
- Java's `volatile` does guarantee visibility between threads, which is the source of the confusion. In
  C++, use `std::atomic`.

### Detecting races

- ThreadSanitizer (`-fsanitize=thread`) records happens-before relationships at run time and reports
  unsynchronized accesses even on runs where the timing happened to work out. It slows programs by
  roughly 5–15× and cannot be combined with AddressSanitizer in one build.
- Helgrind and DRD (Valgrind tools) find races without recompiling, at a much greater slowdown.

> A service that counts requests with a plain `int` passes every functional test, because tests run with
> little concurrency. Running the same test suite under ThreadSanitizer in continuous integration reports
> the race on the first run, long before the undercounting would ever be noticed in production metrics.

## 2. Mutexes and lock wrappers

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:mutexes"

### Mutex types

| Type | Behavior |
| ---- | -------- |
| `std::mutex` | Non-recursive: locking it again from the thread that holds it is undefined behavior, typically a deadlock |
| `std::recursive_mutex` | The owning thread may lock it repeatedly and must unlock it as many times |
| `std::timed_mutex` | Adds `try_lock_for` and `try_lock_until` |
| `std::shared_mutex` (C++17) | Many shared (reader) owners or one exclusive (writer) owner |

- `recursive_mutex` usually indicates an unclear call graph: a function holding the lock calls another
  that locks again. Splitting such functions into a public locking wrapper and a private
  "already locked" implementation removes the need.

### What a lock costs

- Uncontended: on Linux, `std::mutex` is built on a futex ("fast userspace mutex"). Taking a free lock is
  one atomic compare-and-swap in user space, with no system call.
- Contended: a thread that must wait makes a system call and is descheduled until the holder releases the
  lock and the scheduler runs it again, which costs microseconds — thousands of times the uncontended
  path.
- Implication: locks are not slow; contention is. Optimization means holding locks for less time and
  having fewer threads want the same lock.
- `shared_mutex` caveat: even shared locking updates a reader count, so readers still write to shared
  memory. For short critical sections, a plain `std::mutex` is often faster.

### Lock wrappers compared

| Wrapper | Since | Adds |
| ------- | ----- | ---- |
| `std::lock_guard` | C++11 | Nothing: locks in the constructor, unlocks in the destructor, cannot be moved |
| `std::unique_lock` | C++11 | Deferred locking, early `unlock()`, relocking, timed locking, movable; required by `std::condition_variable` |
| `std::scoped_lock` | C++17 | Locks several mutexes at once without deadlock |
| `std::shared_lock` | C++14 | Holds a shared mutex in shared mode |

```cpp
std::mutex m1, m2;

void wrappers() {
    std::unique_lock deferred(m1, std::defer_lock);   // does not lock yet
    std::scoped_lock both(m2);                        // ordinary single lock
    deferred.lock();                                  // lock when ready
    deferred.unlock();                                // release early
}
```

- `unique_lock` stores a flag recording whether it currently owns the lock, because it may have been
  unlocked or moved before destruction. `lock_guard` always owns its mutex and needs no flag.

### Lock granularity

```cpp
class StripedCounter {
public:
    void add(std::size_t key) {
        auto& stripe = stripes_[key % stripes_.size()];
        std::scoped_lock lock(stripe.m);           // only one stripe's lock, never two
        ++stripe.count;
    }
private:
    struct Stripe { std::mutex m; long count = 0; };
    std::array<Stripe, 16> stripes_;
};
```

- Coarse-grained locking (one lock for everything) is simple and obviously correct but serializes every
  thread.
- Fine-grained locking (one lock per bucket or object) scales but introduces lock ordering problems.
- Lock striping takes N locks and picks one by hashing the key. Contention drops roughly N-fold, and each
  operation still takes exactly one lock, so there is no ordering to get wrong.
- Rules: keep critical sections short, never call unknown code (callbacks, virtual functions from other
  modules) while holding a lock, and never block on I/O while holding one.

> Java's original `ConcurrentHashMap` used lock striping with 16 segments by default, so up to 16 threads
> could write to different parts of the map concurrently while each write took only one lock.

## 3. Deadlock

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:deadlock"

### The four conditions

A deadlock requires all four Coffman conditions at the same time:

1. Mutual exclusion: a resource can be held by only one thread.
2. Hold and wait: a thread holds one resource while waiting for another.
3. No preemption: a resource cannot be taken away from its holder.
4. Circular wait: the threads' waits form a cycle.

- Breaking any one condition prevents deadlock. Mutexes exist to provide the first, code usually needs the
  second, and forcibly taking a lock from a thread mid-update would corrupt data, so practical techniques
  break circular wait.

### How `std::scoped_lock` avoids deadlock

- Algorithm: for several mutexes, `std::lock` (used by `scoped_lock`) locks one, then tries to lock the
  others without blocking. If any attempt fails, it releases everything and starts again, beginning with
  the mutex that was busy.
- Why it works: a thread never blocks on one mutex while holding another, so no cycle of waiting threads can
  form, whatever order the mutexes are passed in.

### Lock hierarchies

```cpp
class HierarchicalMutex {
public:
    explicit HierarchicalMutex(unsigned level) : level_(level) {}
    void lock() {
        if (current_level_ <= level_) throw std::logic_error("lock order violation");
        inner_.lock();
        previous_ = std::exchange(current_level_, level_);
    }
    void unlock() {
        current_level_ = previous_;
        inner_.unlock();
    }
private:
    std::mutex inner_;
    const unsigned level_;
    unsigned previous_ = 0;
    inline static thread_local unsigned current_level_ = std::numeric_limits<unsigned>::max();
};
```

- Idea: every mutex gets a level, and a thread may only acquire a mutex with a lower level than any it
  already holds. A consistent global order makes cycles impossible.
- Benefit: a lock ordering mistake that would deadlock once in a million runs becomes an immediate error the
  first time the wrong order is executed in testing.
- Livelock: retrying with `try_lock` and backing off can leave two threads repeatedly acquiring and
  releasing in step. Randomized back-off breaks the symmetry.

### Finding deadlocks

- In a hung process: attach a debugger and print every thread's stack (`thread apply all bt` in GDB). A
  deadlock shows as threads blocked in lock calls, each holding what another waits for.
- Before it happens: ThreadSanitizer's lock-order checking reports inconsistent acquisition orders even on
  runs that did not deadlock.

> The Linux kernel's `lockdep` validator records the order in which every class of lock is taken while the
> kernel runs, and reports a potential deadlock the first time two code paths take the same pair of locks in
> opposite orders, even if the deadlock never actually occurs.

## 4. Atomics

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:atomics"

### How atomic operations are implemented

- Hardware support: on x86, operations such as `fetch_add` and `compare_exchange` compile to instructions
  with a `lock` prefix (`lock xadd`, `lock cmpxchg`). On ARM they use either load-exclusive and
  store-exclusive instruction pairs or, on newer cores, dedicated atomic instructions.
- No kernel involvement: nothing sleeps and nothing waits on the operating system.
- Size limits: only types that fit the hardware's atomic instructions are lock-free. For larger types the
  library falls back to an internal lock.

```cpp
struct Big { char data[40]; };

static_assert(std::atomic<int>::is_always_lock_free);
static_assert(!std::atomic<Big>::is_always_lock_free);   // no instruction updates 40 bytes atomically
```

### `compare_exchange_weak` and `compare_exchange_strong`

```cpp
std::atomic<int> value{0};

int update(int (*transform)(int)) {
    int expected = value.load();
    while (!value.compare_exchange_weak(expected, transform(expected))) {
        // on failure, expected now holds the current value; recompute and retry
    }
    return expected;
}
```

- `compare_exchange_weak` may fail spuriously, even when the value matched, on architectures whose
  exclusive-store instructions can lose their reservation. In a retry loop that only costs one more
  iteration, and it can be cheaper.
- `compare_exchange_strong` never fails spuriously, so it is the right choice for a single attempt outside
  a loop.
- Not copyable: `std::atomic` has deleted copy operations, because copying would read one location and
  write another, which cannot be a single atomic step.

### When a mutex is still the right tool

- Multi-variable invariants: two atomics cannot be updated together atomically, so a pointer and a size
  kept in separate atomics can be observed out of sync.
- Contention still costs: every atomic write takes exclusive ownership of a cache line, so a single hot
  atomic counter shared by many cores can be slower than per-thread counters. See section 9.

> Reference counts are the canonical atomic use: `std::shared_ptr`'s control block increments and
> decrements its counts with atomic operations, so copying a `shared_ptr` from many threads needs no lock.

## 5. Memory ordering in atomics

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:ordering"

### What the standard says and what compilers do

`std::memory_order` has four standard values: `relaxed`, `acquire`, `release`, and `seq_cst`. The standard
names them but leaves their effect to the implementation, which may treat them as hints.

```cpp
std::atomic<int> shared{0};

void store_seq(int v)     { shared.store(v, std::memory_order_seq_cst); }
void store_release(int v) { shared.store(v, std::memory_order_release); }
void store_relaxed(int v) { shared.store(v, std::memory_order_relaxed); }
int  load_acquire()       { return shared.load(std::memory_order_acquire); }
int  load_relaxed()       { return shared.load(std::memory_order_relaxed); }
```

| Operation | Clang `-O2` on x86-64 | Clang `-O2` on AArch64 (Apple) |
| --------- | --------------------- | ------------------------------ |
| `seq_cst` store | `xchg` | `stlr` |
| `release` store | `mov` | `stlr` |
| `relaxed` store | `mov` | `str` |
| `seq_cst` load | `mov` | `ldar` |
| `acquire` load | `mov` | `ldapr` |
| `relaxed` load | `mov` | `ldr` |

- x86-64: its processor memory model is already strong, so only a sequentially consistent store differs;
  `xchg` forces the write to take effect before the next instruction runs.
- AArch64: the instruction set has distinct load and store variants, and Clang uses them for the stronger
  orders while `relaxed` gets the plain `ldr` and `str`. The ordering argument is therefore not merely
  documentation on every platform.
- libc++ also accepts `consume` and `acq_rel`; these are library extensions, not standard values.

### The publication pattern

```cpp
std::vector<int> config;                                  // plain data, not atomic
std::atomic<bool> config_ready{false};

void producer() {
    config = {1, 2, 3};                                    // (1) ordinary writes
    config_ready.store(true, std::memory_order_release);   // (2) everything before this is published
}

void consumer() {
    if (config_ready.load(std::memory_order_acquire)) {    // (3) observes everything published by (2)
        int first = config[0];                             // (4) sees the writes from (1)
        (void)first;
    }
}
```

- Model: a `release` store acts as a boundary that earlier operations cannot move past, and an `acquire`
  load acts as a boundary that later operations cannot move before. Together they carry the visibility of
  arbitrarily many ordinary writes across threads through one atomic flag.
- Mutexes use the same pattern internally: unlocking publishes, locking observes.
- `relaxed` gives atomicity of the single operation and no ordering with anything else, so it suits a
  statistics counter read once at the end and never a flag that guards other data.
- Default: `seq_cst` is always correct. Weaker orders belong in measured hot paths, with the reasoning
  documented next to the code.

> Metrics libraries commonly update hot statistics counters with `memory_order_relaxed`, because each
> counter is read in isolation and only its eventual total matters, while flags that hand data from one
> thread to another keep the default `seq_cst` ordering.

## 6. Waiting and results

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:waiting"

### The two condition variable traps

```cpp
std::mutex m;
std::condition_variable cv;
bool ready = false;

void waiter() {
    std::unique_lock lock(m);
    cv.wait(lock, [] { return ready; });   // predicate form: rechecks after every wake-up
}

void notifier() {
    {
        std::scoped_lock lock(m);
        ready = true;                      // the state change happens under the lock
    }
    cv.notify_one();                       // notifying after unlocking is fine
}
```

- Spurious wake-ups: `wait` may return without any notification, a concession to efficient implementations.
  The predicate overload loops until the condition is really true.
- Lost wake-ups: if the notifier changed `ready` without the mutex, it could set the flag and notify between
  the waiter's check and its going to sleep, and the waiter would sleep forever. Changing the state under the
  lock closes that window.
- Why `unique_lock`: `wait` must release the mutex while sleeping and reacquire it before returning.
  `std::condition_variable_any` works with other lock types at some extra cost.

### `std::async` and futures

```cpp
int compute();

void async_traps() {
    std::async(std::launch::async, compute);   // the discarded future's destructor waits right here
    std::async(std::launch::async, compute);   // so these two run one after the other

    auto deferred = std::async(compute);       // default policy: may run lazily inside get(), on this thread
    auto a = std::async(std::launch::async, compute);
    auto b = std::async(std::launch::async, compute);
    int total = a.get() + b.get();             // these two really run concurrently
    (void)deferred;
    (void)total;
}
```

- Blocking destructor: a future returned by `std::async` waits for its task in its destructor, so ignoring
  the returned future makes calls sequential.
- Default launch policy: the implementation may choose deferred execution, running the task only when
  `get()` or `wait()` is called. Passing `std::launch::async` forces a new thread.
- Other building blocks: `std::promise` is the writing end of a one-shot channel whose reading end is a
  `std::future`, and `std::packaged_task` wraps a callable so its result feeds a future.

### Thread pools

- Why pools: creating a thread takes tens of microseconds and reserves a full stack, so systems create a
  fixed set of threads sized to the hardware and feed them work from a queue.
- Scaling further: per-core queues avoid contention on one shared queue, work stealing rebalances load when
  one queue runs dry, and pinning threads to cores keeps their data in that core's cache.

> Intel's oneTBB schedules tasks with work stealing: each worker thread pushes new tasks onto its own
> queue, and idle workers steal from other threads' queues, so most queue operations never contend with
> another thread.

## 7. Initialization and shutdown

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:shutdown"

### Cooperative cancellation with `std::jthread`

```cpp
void run_worker() {
    std::jthread worker([](std::stop_token stop) {
        while (!stop.stop_requested()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));   // do a unit of work
        }
    });
}   // the destructor calls request_stop(), then join()
```

- `std::thread`: destroying a still-joinable thread calls `std::terminate`, because silently joining could
  hang and silently detaching could leave the thread using destroyed objects.
- `std::jthread`: its destructor requests a stop through a `std::stop_token` and then joins. The thread
  function checks the token at safe points.
- `std::condition_variable_any::wait` accepts a stop token, so a sleeping worker wakes up when a stop is
  requested.

### Sharing a global with running threads

```cpp
struct Telemetry { void emit(const char*) {} };

std::shared_ptr<Telemetry> telemetry() {
    static std::mutex m;
    static std::weak_ptr<Telemetry> current;
    std::scoped_lock lock(m);
    if (auto existing = current.lock()) return existing;
    auto created = std::make_shared<Telemetry>();
    current = created;
    return created;
}

void worker_step() {
    if (auto t = telemetry()) t->emit("step");   // this thread keeps the object alive while using it
}
```

- The problem with a reference-returning accessor: `static T instance; return instance;` fixes
  initialization order but hands out access without ownership. At exit, static destructors can run while
  other threads still use the object. See [Memory](memory.md) for initialization and destruction order.
- `shared_ptr` accessor: each user holds a strong reference while it works, so the object is destroyed only
  after the last user finishes, never in the middle of a call. The function-local `weak_ptr` does not keep
  it alive on its own.
- Explicit shutdown: the most robust design stops and joins every thread before `main` returns, so no
  thread is running when static destruction begins.

> Tracing and metrics libraries, which are called from every thread, are a common source of crashes that
> only happen at process exit. Their shutdown functions typically flush and disable the global provider
> explicitly from `main`, rather than relying on static destructors running in a safe order.

## 8. Lock-free programming

Lock-free data structures coordinate threads with atomic operations alone, so no thread can prevent others
from making progress by holding a lock.

```cpp
struct Node {
    int value;
    Node* next;
};

std::atomic<Node*> head{nullptr};

void push(int value) {
    Node* n = new Node{value, head.load(std::memory_order_relaxed)};
    while (!head.compare_exchange_weak(n->next, n,
                                       std::memory_order_release,
                                       std::memory_order_relaxed)) {
        // on failure n->next already holds the current head, so simply retry
    }
}
```

| Guarantee | Meaning |
| --------- | ------- |
| Obstruction-free | A thread makes progress if it runs alone |
| Lock-free | Some thread always makes progress; an individual thread may retry forever |
| Wait-free | Every thread finishes in a bounded number of steps |

- The appeal is not raw speed but the absence of blocking: a thread holding a lock can be descheduled,
  page-fault, or stall, and every waiter stalls with it. Lock-free code has no such window, which matters
  in real-time and signal-handling contexts.
- Optimistic retry: read the current state, compute the new one, and commit with a compare-and-swap only if
  nothing changed; otherwise retry.

### The ABA problem

- Scenario: thread 1 reads `head == A`. Thread 2 pops A, pops B, frees B, and pushes A back. Thread 1's
  compare-and-swap sees A again and succeeds, but its saved `A->next` points to freed memory.
- Cause: compare-and-swap compares a value, not a history.
- Fixes: tagged pointers that pair the pointer with a counter updated on every change, or a memory
  reclamation scheme that prevents A from being reused while any thread might still hold it.

### Memory reclamation

- The hard part: a node can be unlinked atomically, but a thread that read a pointer to it just before may
  still be using it, and nothing tells the remover when that thread is done.
- Hazard pointers: each thread publishes the pointers it is currently using, and nodes are freed only when
  no published hazard pointer refers to them.
- Epoch-based reclamation: threads announce which epoch they are reading in, and retired nodes are freed once
  every thread has moved past the epoch in which they were removed.
- Read-copy-update (RCU): readers take no locks and write nothing; writers publish a modified copy and free
  the old version after a grace period in which every pre-existing reader has finished. It dominates
  read-mostly data in the Linux kernel. C++26 adds `<hazard_pointer>` and `<rcu>` to the standard library.

> A single-producer, single-consumer ring buffer is the most widely used lock-free structure: one thread
> only moves the tail and the other only moves the head, so each index needs a single atomic write. Audio
> applications use it to pass samples from a real-time audio thread, which must never block, to the rest of
> the program.

## 9. False sharing

False sharing happens when threads write to different variables that happen to share a cache line.

```cpp
struct SharedLine {                               // both counters likely share one cache line
    std::atomic<std::uint64_t> reads{0};
    std::atomic<std::uint64_t> writes{0};
};

struct SeparateLines {                            // each counter starts its own cache line
    alignas(std::hardware_destructive_interference_size) std::atomic<std::uint64_t> reads{0};
    alignas(std::hardware_destructive_interference_size) std::atomic<std::uint64_t> writes{0};
};

static_assert(sizeof(SeparateLines) >= 2 * std::hardware_destructive_interference_size);
```

- Mechanism: CPU caches track ownership per cache line, not per variable. When two cores write to the same
  line, each write invalidates the other core's copy, and the line moves back and forth between cores on
  every update.
- Symptom: code with no shared variables and no locks slows down as threads are added, and profiles show
  time spent on instructions that should be nearly free.
- Fix: separate independently written data onto different cache lines with padding or `alignas`.
  `std::hardware_destructive_interference_size` gives a portable padding size (64 on this toolchain, even
  though Apple Silicon reports 128-byte cache lines).
- Detection: `perf c2c` on Linux reports cache lines contended between cores.

### True sharing

- When threads genuinely write the same variable, such as one global counter, padding cannot help because
  the conflict is real.
- Sharding: give each thread or core its own counter and sum them when reading. The reader gets a value that
  is slightly out of date, which statistics almost always tolerate, in exchange for writes that never
  contend.

> The Linux kernel's per-CPU variables apply sharding throughout: network and block-layer statistics are
> incremented in per-CPU copies with no locks and no shared cache lines, and summed only when a tool such as
> `/proc` or `ethtool` reads them.

## Choosing a concurrency tool

??? note "Overview"

    --8<-- "guides/cpp_overview/concurrency.md:choosing"

Run tests under ThreadSanitizer, give every mutex a documented place in a lock order, keep independently
updated data on separate cache lines, and design thread shutdown before static destruction so no thread
outlives the objects it uses.

## C++ References

Language

- [Memory model and data races](https://en.cppreference.com/cpp/language/memory_model)
- [`volatile`](https://en.cppreference.com/cpp/language/cv)
- [`thread_local` and static local variables](https://en.cppreference.com/cpp/language/storage_duration)
- [`alignas`](https://en.cppreference.com/cpp/language/alignas)

Threads and cancellation

- [Concurrency support library](https://en.cppreference.com/cpp/thread)
- [`std::thread`](https://en.cppreference.com/cpp/thread/thread), [`std::jthread`](https://en.cppreference.com/cpp/thread/jthread), [`std::stop_token`](https://en.cppreference.com/cpp/thread/stop_token)
- [`std::this_thread::sleep_for`](https://en.cppreference.com/cpp/thread/sleep_for)

Mutual exclusion

- [`std::mutex`](https://en.cppreference.com/cpp/thread/mutex), [`std::recursive_mutex`](https://en.cppreference.com/cpp/thread/recursive_mutex), [`std::timed_mutex`](https://en.cppreference.com/cpp/thread/timed_mutex), [`std::shared_mutex`](https://en.cppreference.com/cpp/thread/shared_mutex)
- [`std::lock_guard`](https://en.cppreference.com/cpp/thread/lock_guard), [`std::unique_lock`](https://en.cppreference.com/cpp/thread/unique_lock), [`std::scoped_lock`](https://en.cppreference.com/cpp/thread/scoped_lock), [`std::shared_lock`](https://en.cppreference.com/cpp/thread/shared_lock)
- [`std::lock`](https://en.cppreference.com/cpp/thread/lock) and [`std::defer_lock`](https://en.cppreference.com/cpp/thread/lock_tag)
- [`std::condition_variable`](https://en.cppreference.com/cpp/thread/condition_variable) and [`std::condition_variable_any`](https://en.cppreference.com/cpp/thread/condition_variable_any)

Atomics

- [`std::atomic`](https://en.cppreference.com/cpp/atomic/atomic): [`is_always_lock_free`](https://en.cppreference.com/cpp/atomic/atomic/is_always_lock_free), [`compare_exchange_weak` and `compare_exchange_strong`](https://en.cppreference.com/cpp/atomic/atomic/compare_exchange)
- [`std::memory_order`](https://en.cppreference.com/cpp/atomic/memory_order)
- [`std::hardware_destructive_interference_size`](https://en.cppreference.com/cpp/thread/hardware_destructive_interference_size)

Tasks

- [`std::async`](https://en.cppreference.com/cpp/thread/async) and [`std::launch`](https://en.cppreference.com/cpp/thread/launch)
- [`std::future`](https://en.cppreference.com/cpp/thread/future), [`std::promise`](https://en.cppreference.com/cpp/thread/promise), [`std::packaged_task`](https://en.cppreference.com/cpp/thread/packaged_task)

Related

- [`std::shared_ptr`](https://en.cppreference.com/cpp/memory/shared_ptr) and [`std::weak_ptr`](https://en.cppreference.com/cpp/memory/weak_ptr)
- [`std::numeric_limits`](https://en.cppreference.com/cpp/types/numeric_limits) and [`std::logic_error`](https://en.cppreference.com/cpp/error/logic_error)
- [Hazard pointers](https://en.cppreference.com/cpp/header/hazard_pointer) and [RCU](https://en.cppreference.com/cpp/header/rcu)
