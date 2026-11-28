# Memory

> Part of the [C++ Deep Dive](README.md) · Overview: [Memory](../cpp_overview/memory.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/memory.md:intro"

This page follows each storage duration down to the mechanism underneath it — stack frames, the
allocator, the startup code that initializes statics, and the runtime's per-thread blocks — then
covers the failure modes that only appear over time, leaks and fragmentation, and how the operating
system's handling of memory and I/O shapes systems code.

## 1. Automatic storage (the stack)

??? note "Overview"

    --8<-- "guides/cpp_overview/memory.md:automatic"

### Destruction order

Automatic objects are destroyed in exactly the reverse order of their construction, whenever their
block is left.

```cpp
struct Trace {
    const char* name;
    explicit Trace(const char* n) : name(n) { std::printf("enter %s\n", name); }
    ~Trace() { std::printf("leave %s\n", name); }
};

void nested() {
    Trace outer("outer");
    {
        Trace inner("inner");
    }                          // prints "leave inner" here
    Trace last("last");
}                              // prints "leave last", then "leave outer": reverse order
```

- Reverse order: later objects may depend on earlier ones, so tearing down newest-first guarantees
  every object is destroyed while the objects it was built from still exist.
- Every exit path: the guarantee holds for normal exit, `return`, `break`, `goto` out of a block, and
  an exception propagating through, which is what makes [RAII](ownership.md) reliable.
- Exception: `std::exit` and `std::abort` do not unwind the stack, so automatic objects in active
  frames are never destroyed.

### Stack frames

A call creates a stack frame: the block of stack memory that belongs to one invocation of a function.

```cpp
int square(int x) {
    int result = x * x;        // lives in square's frame
    return result;
}

int caller() {
    int base = 7;              // lives in caller's frame
    return square(base);       // square's frame is pushed below caller's, then popped on return
}
```

- Contents: the return address (where to continue after the call), saved register values the calling
  convention requires, and space for local variables and temporaries. With optimization, many locals
  never touch memory at all and live only in registers.
- Direction: on mainstream platforms the stack grows toward lower addresses, so each nested call's
  frame sits below its caller's.
- Red zone: the x86-64 System V calling convention lets a function that calls nothing use 128 bytes
  below the stack pointer without moving it, saving the adjustment entirely.

### Returning pointers to locals

A frame's memory is reused by the next call as soon as the function returns.

```cpp
int* dangling() {
    int value = 42;
    return &value;             // compiles with a warning; the pointer is invalid immediately
}

const std::string& also_dangling() {
    std::string text = "temporary";
    return text;               // same bug through a reference
}
```

- Effect: reading through the returned pointer is undefined behavior. It may appear to work until
  another call overwrites that stack region.
- Detection: compilers warn (`-Wreturn-stack-address` in Clang, `-Wreturn-local-addr` in GCC), and
  AddressSanitizer with `detect_stack_use_after_return` catches the less obvious cases at run time.

### Stack size limits

The stack's size is fixed when the thread is created.

```cpp
int depth(int n) {
    char buffer[4096];         // 4 KB per call
    buffer[0] = static_cast<char>(n);
    return n == 0 ? buffer[0] : depth(n - 1) + 1;
}
// depth(10'000) needs about 40 MB of stack: far past a typical 8 MB limit, so it crashes

void safer(std::size_t n) {
    std::vector<char> buffer(n);   // large or run-time-sized buffers belong on the heap
    (void)buffer;
}
```

- Typical sizes: on Linux the main thread's limit comes from `ulimit -s`, commonly 8 MB, and glibc
  uses the same value for new threads by default. macOS gives the main thread 8 MB and other threads
  512 KB; Windows defaults to 1 MB.
- Overflow: the operating system places an unmapped guard page past the end of the stack. Touching it
  raises a segmentation fault instead of silently corrupting other memory.
- Thread stacks: `std::thread` offers no way to set the stack size; platform APIs such as
  `pthread_attr_setstacksize` do.
- Variable-length arrays such as `int buf[n];` with a run-time `n` are not standard C++. Some
  compilers accept them as an extension, and they make stack usage unbounded.

> A recursive JSON or XML parser that descends one function call per nesting level can be crashed by a
> maliciously deep document. Robust parsers cap the nesting depth or switch to an explicit heap-allocated
> stack of pending work.

## 2. Dynamic storage (the heap)

??? note "Overview"

    --8<-- "guides/cpp_overview/memory.md:dynamic"

### What `new` and `delete` do

A `new` expression performs two separate steps, and `delete` reverses them.

```cpp
struct Session {
    std::string user;
    explicit Session(std::string u) : user(std::move(u)) {}
};

void two_steps() {
    void* memory = ::operator new(sizeof(Session));          // step 1: raw memory, no object yet
    Session* s = ::new (memory) Session("placement");        // step 2: construct in that memory
    s->~Session();                                           // reverse step 2: destroy
    ::operator delete(memory);                               // reverse step 1: release memory

    int* many = new int[16];
    delete[] many;                                           // arrays must use delete[]
}
```

- Allocation: `operator new` obtains raw memory, normally by calling into the same allocator as
  `malloc`. If it cannot, it throws `std::bad_alloc`; `new (std::nothrow) T` returns `nullptr`
  instead.
- Construction: the constructor then runs in that memory. The placement form `new (ptr) T` performs
  only this step, which is how containers construct elements inside buffers they already own.
- Release: `delete` runs the destructor, then `operator delete` returns the memory. Mixing forms —
  `delete` on memory from `new[]`, or `free` on memory from `new` — is undefined behavior.
- `malloc` versus `new`: `malloc` returns raw bytes and runs no constructor, so it is only correct for
  types with no initialization requirements.

### Inside the allocator

The general-purpose allocator sits between the program and the operating system, turning a few large
requests to the operating system into many small blocks.

- Size classes: requests are rounded up to one of a set of fixed sizes, and each size class keeps a
  free list of released blocks ready for reuse.
- Thread caches: allocators such as tcmalloc and jemalloc, and glibc's per-thread arenas, keep free
  blocks per thread so most allocations need no lock. Contention appears when threads free memory
  that other threads allocated.
- Large blocks: very large requests bypass the free lists and are mapped directly from the operating
  system. In glibc the threshold starts at 128 KB and adjusts itself at run time.
- Overcommit: on Linux's default settings, a large allocation can succeed even when physical memory
  is short, because pages are only backed when first touched. The failure then arrives later as the
  kernel's out-of-memory killer terminating a process, not as `std::bad_alloc`.

### Heap failure modes

```cpp
void heap_bugs() {
    int* p = new int(1);
    delete p;
    // *p = 2;                 // use-after-free: undefined behavior
    // delete p;               // double free: corrupts allocator state

    std::vector<int> v{1, 2, 3};
    int* first = &v[0];
    v.push_back(4);            // may reallocate: first now points into freed memory
    (void)first;
}
```

- Use-after-free and double free: both corrupt the allocator's internal lists or overwrite whatever
  reused the memory, and the crash often appears far from the bug.
- Invalidated pointers: any pointer into a container's buffer is invalid after the buffer reallocates.
  See [Containers](containers.md).
- Detection: AddressSanitizer (`-fsanitize=address`) reports each of these at the faulting line;
  Valgrind finds them without recompiling, at a much larger slowdown.

> A heavily multithreaded service that switches its allocator from the system `malloc` to jemalloc or
> tcmalloc — usually by linking or preloading a library, with no code changes — can reduce lock
> contention and memory growth, because those allocators keep per-thread caches and size-class free
> lists.

## 3. Static storage

??? note "Overview"

    --8<-- "guides/cpp_overview/memory.md:static"

### How static objects are initialized

Initialization happens in two phases, and which phase an object gets determines whether ordering can
ever go wrong.

```cpp
int request_count;                          // zero-initialized: stored in .bss
constexpr int max_clients = 64;             // constant: may never occupy memory at all
const char* banner = "ready";               // constant-initialized pointer: stored in .data
std::string greeting = "hello";             // dynamically initialized: its constructor runs before main
```

- Static initialization: objects initialized with zero or with a constant expression are set up
  before any code runs. Zero-initialized objects are placed in the `.bss` segment, which occupies no
  space in the executable file; constant-initialized ones are written into `.data` or `.rodata`.
- Dynamic initialization: objects whose initializer must run code, such as a `std::string` built from
  a literal or a call to `load()`, have their constructors run at startup by code the compiler emits
  for each source file.
- Function-local statics: the compiler protects the first initialization with a guard, so concurrent
  first calls are safe (on the Itanium C++ ABI this is `__cxa_guard_acquire`). Every later call pays
  only a check of the guard.

### The static initialization order problem

Within one source file, dynamically initialized objects are constructed in declaration order. Across
source files the order is unspecified, because each file is compiled separately and the linker's
ordering of their initializers can change with the build.

```cpp
// logger.cpp
struct Logger { std::vector<std::string> lines; void write(std::string s) { lines.push_back(std::move(s)); } };
Logger g_logger;

// config.cpp
struct Config { Config() { /* g_logger.write("loading config"); */ } };
Config g_config;              // if config.cpp's initializers run first, g_logger is not constructed yet
```

- Symptom: the program may appear to work, because static memory starts zeroed, and then crash when
  the unconstructed object is used in a way that needs real state. A reordered list of source files in
  the build is enough to change the outcome.
- Destruction order: the mirror problem occurs at shutdown. Objects are destroyed in reverse
  construction order, so an object whose destructor uses another global may run after that global is
  gone — and other threads may still be running at that point.

### Fixes, in order of preference

<!-- needs: 8 -->
```cpp
Logger& logger() {
    static Logger instance;        // construct on first use: always initialized before it is returned
    return instance;
}

constinit int log_level = 2;       // C++20: guaranteed static initialization, so no ordering at all

Logger& leaked_logger() {
    static Logger& instance = *new Logger;   // never destroyed: usable during any other destructor
    return instance;
}
```

1. Construct on first use: replace the global with a function returning a function-local static.
   Initialization order then follows the order of first use, which is always correct.
2. `constinit`: requires the variable to be initialized at compile time and fails the build otherwise,
   so the order question never arises.
3. Explicit startup and shutdown: create global services from `main` in a written-out order and tear
   them down in reverse. Common in embedded code because the order is visible and testable.
4. Remove the global: pass the dependency to the code that uses it. The ordering problem is a symptom
   of hidden dependencies between globals, and removing the global removes the dependency.
5. For destruction specifically: intentionally never destroy the object (as in `leaked_logger`),
   register ordered cleanup with `std::atexit`, or hand out `std::shared_ptr`/`std::weak_ptr` so every
   user keeps the object alive while using it.

> Programs built from many independently linked libraries often replace every mutable global with an
> accessor function, and some projects enforce it: Clang's `-Wglobal-constructors` warning flags any
> global that needs code to run before `main`, which is where initialization order bugs begin.

## 4. Thread-local storage

??? note "Overview"

    --8<-- "guides/cpp_overview/memory.md:thread_local"

### How thread-local variables are implemented

```cpp
thread_local int calls_on_this_thread = 0;    // trivial type: set when the thread's block is created

struct Cache {
    static thread_local std::vector<int> recent;   // static data member: one per thread
};

int count_calls() {
    thread_local int local_count = 0;         // local: implies static, one per thread
    return ++local_count + ++calls_on_this_thread;
}
```

- Where it applies: `thread_local` can be used on namespace-scope variables, `static` data members,
  and local variables, where it implies `static`.
- Layout: when a thread starts, the runtime allocates a block containing that thread's copy of every
  thread-local variable. On x86-64 Linux, the `fs` segment register points at the current thread's
  block, so reading a thread-local variable in the main executable is a single offset from that
  register.
- Shared libraries: a library loaded at run time with `dlopen` cannot know its block's offset in
  advance, so access goes through a helper call (`__tls_get_addr`), which is slower in tight loops.
- Trivial types: an `int` or pointer is initialized when the block is created. Types with
  constructors are typically initialized on the first use in each thread, behind a guard check.

### Destruction timing

<!-- needs: 8 9 -->
```cpp
struct Flusher {
    ~Flusher() { logger().write("thread exiting"); }   // uses a static object from section 3
};
thread_local Flusher flusher;                          // destroyed when each thread exits
```

- Order: a thread's thread-local objects are destroyed when the thread exits, in reverse order of
  construction. For the main thread, they are destroyed before any static object.
- Hazard: a thread that is still running — for example, a detached thread — can exit after `main` has
  returned and static objects have been destroyed. Its thread-local destructors then use destroyed
  statics, which is undefined behavior. Joining all threads before `main` returns avoids it.

> Thread pools make thread-local state outlive the work that set it: a request ID stored in a
> `thread_local` by one task is still there when the pool runs the next task on that thread. Libraries
> that keep per-request context this way reset it at the start and end of every task.

## 5. Leaks, fragmentation, and custom allocators

Memory problems in long-running processes rarely come from a single bad line. They accumulate: memory
that is never returned, or memory that is returned but can no longer be reused.

```cpp
struct Node {
    std::shared_ptr<Node> peer;
};

void reachable_leak() {
    auto a = std::make_shared<Node>();
    auto b = std::make_shared<Node>();
    a->peer = b;
    b->peer = a;              // cycle: both counts stay at 1 after a and b go out of scope
}

std::unordered_map<std::string, std::string> cache;   // grows forever if nothing evicts entries
```

- Unreachable memory: the program lost its last pointer to a block, so nothing can ever free it. Leak
  detectors find these by scanning for heap blocks no live pointer refers to.
- Reachable but unwanted memory: every byte is still referenced — by a `shared_ptr` cycle or an
  unbounded cache — so leak detectors report a clean run while the process keeps growing.

### Kinds of leak and how to find them

| Problem | Cause | How it is detected |
| ------- | ----- | ------------------ |
| Forgotten release | An early return or exception between allocation and release | AddressSanitizer's leak checker, Valgrind |
| Ownership cycle | Two objects holding `shared_ptr`s to each other | Not reported by leak checkers; found by design review or heap-graph tools |
| Unbounded container | A cache or map with no eviction policy | Memory usage trending upward; heap profilers such as `heaptrack` or Valgrind's `massif` |
| Fragmentation | Mixed allocation sizes over a long run | Resident memory grows while live allocated bytes stay flat |
| Non-memory resources | File descriptors, sockets, or locks never released | Descriptor counts in `/proc/<pid>/fd`, `lsof` |

### Fragmentation

The allocator carves blocks out of larger regions obtained from the operating system, and it can
only return a region when every block inside it is free.

- How it happens: a process allocates a million small objects, frees 99% of them, and the surviving 1%
  are scattered across every region. The free memory is real, but it is split into gaps that are in
  the wrong places and sizes to satisfy new requests, and no region can be given back.
- Symptom: a heap profiler shows live bytes staying flat while the process's resident memory keeps
  climbing. Nothing leaked, yet memory is effectively lost.
- Why it matters: in a process that runs for months, fragmentation can exhaust memory even when the
  code has no leaks at all.

### Pools, arenas, and `std::pmr`

Replacing general-purpose allocation for specific workloads bounds both allocation cost and
fragmentation.

```cpp
void handle_request() {
    std::array<std::byte, 64 * 1024> stack_buffer;
    std::pmr::monotonic_buffer_resource arena(stack_buffer.data(), stack_buffer.size());

    std::pmr::vector<std::pmr::string> fields(&arena);   // all allocations come from the arena
    fields.emplace_back("method");
    fields.emplace_back("path");
}   // the arena releases everything at once; no per-object frees
```

- Pool (slab) allocators: keep a free list of identically sized slots per object type. A freed slot
  always fits the next request exactly, so fragmentation is bounded by construction, and allocation
  and release are constant time.
- Arena (bump) allocators: hand out memory by advancing a pointer and release the whole arena at once,
  which suits memory whose lifetime matches a request, a frame, or a transaction.
- `std::pmr` (C++17): polymorphic memory resources let standard containers use a custom allocator
  selected at run time. `std::pmr::vector<T>` is one type no matter which resource backs it, so
  functions do not need a template parameter for the allocator. The library provides
  `monotonic_buffer_resource` (an arena) and `unsynchronized_pool_resource` (pools).

> A game engine allocates everything needed for one frame — visible object lists, temporary geometry,
> sort keys — from a per-frame arena, and resets the arena at the start of the next frame. No
> per-object frees happen, and the heap cannot fragment across frames.

## 6. Memory and the operating system

Every allocation ultimately rests on memory the operating system has mapped into the process, and
every file or network operation crosses into the operating system's kernel.

```cpp
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

std::size_t count_newlines(const char* path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    struct stat info {};
    fstat(fd, &info);
    auto size = static_cast<std::size_t>(info.st_size);
    void* mapped = mmap(nullptr, size, PROT_READ, MAP_PRIVATE, fd, 0);   // file appears as memory
    close(fd);
    if (mapped == MAP_FAILED) return 0;

    auto* data = static_cast<const char*>(mapped);
    std::size_t lines = static_cast<std::size_t>(std::count(data, data + size, '\n'));   // pages load on first touch
    munmap(mapped, size);
    return lines;
}
```

- Virtual memory: each process sees its own address space. The kernel maps virtual pages — 4 KB on
  most x86-64 systems, 16 KB on Apple Silicon — onto physical memory only when they are first touched.
- Page faults: the first access to an unbacked page traps into the kernel, which supplies a zeroed
  page or reads file data, then resumes the program. This is how large allocations and `mmap`ed files
  cost nothing until used.
- Resident set size (RSS): the physical memory currently backing a process's pages. It is the number
  that grows with leaks and fragmentation, and it differs from virtual size, which counts reserved but
  untouched memory too.

### The cost of a system call

A system call is a controlled transition into the kernel: the CPU switches privilege level, saves and
restores register state, and on many systems applies mitigations for speculative-execution attacks
that add further work.

- Magnitude: the overhead before any real work is commonly between about a hundred nanoseconds and a
  microsecond, depending on the operating system, CPU, and call. A trivial `write` to `/dev/null` on
  an Apple Silicon Mac takes about 500 ns, while one step of a simple loop takes about 2 ns.
- Consequence: high-performance I/O designs aim for more work per transition, fewer transitions per
  unit of work, or no transitions at all.

### I/O models

| Model | How it works | Typical use |
| ----- | ------------ | ----------- |
| Blocking | `read` and `write` wait until data is transferred; one thread per in-flight operation | Simple tools, low concurrency |
| Readiness | `epoll` (Linux) or `kqueue` (BSD, macOS) report which descriptors are ready; one thread serves many | Network servers |
| Completion | `io_uring` (Linux) or IOCP (Windows) share submission and completion queues with the kernel, batching many operations per call | High-throughput storage and network services |
| Memory mapping | `mmap` maps a file into the address space; I/O happens through page faults | Random reads of large files; awkward error handling |
| Direct I/O | `O_DIRECT` bypasses the kernel's page cache; requires buffers aligned to the device's block size | Databases and storage engines that manage their own cache |

- Evolution: blocking I/O limits concurrency to the number of threads. Readiness models let one thread
  wait on many descriptors but still make a system call per operation. Completion queues in shared
  memory let a batch of operations cost one transition, or none in `io_uring`'s polling mode.
- Page cache: by default, file data read or written passes through the kernel's page cache. An
  application that keeps its own cache — a database, for example — uses `O_DIRECT` to avoid caching
  the same data twice and paying an extra copy.
- Aligned buffers: `O_DIRECT` requires memory aligned to the block size, which C++ can request with
  `std::aligned_alloc` or `operator new` with `std::align_val_t`.
- Fewer copies: `sendfile`, `splice`, and scatter-gather I/O (`readv`, `writev`) reduce copying between
  kernel and user memory.

### When data is durable

```cpp
#include <fcntl.h>
#include <unistd.h>                 // Linux; macOS does not declare fdatasync

bool append_record(int fd, const char* data, std::size_t size) {
    if (write(fd, data, size) != static_cast<ssize_t>(size)) return false;   // reached the page cache
    return fdatasync(fd) == 0;   // on stable storage; skips metadata not needed to read the data back
}
```

- `write` returning success means the data reached the page cache, not the disk. A power failure can
  still lose it.
- `fsync` flushes the file's data and metadata to stable storage; `fdatasync` skips metadata that is
  not needed to read the data back, such as the modification time, saving a device write.
- Device caches: drives may hold data in their own volatile caches, so durable systems rely on flush
  commands honored by the device or on battery- or capacitor-backed memory that survives power loss.

> A database's write-ahead log calls `fdatasync` after appending each committed transaction, and only
> then reports the commit as successful. To limit the cost, it groups several transactions into one
> flush ("group commit"), trading a few milliseconds of latency for far fewer device writes.

## Choosing where an object lives

??? note "Overview"

    --8<-- "guides/cpp_overview/memory.md:choosing"

Construct any static state on first use, and make sure every thread has stopped before static
objects are destroyed. For long-running processes, watch resident memory over time rather than only
leak reports, and consider pools or arenas where allocation patterns are predictable.

## C++ References

Language

- [Storage duration and linkage](https://en.cppreference.com/cpp/language/storage_duration)
- [Object lifetime](https://en.cppreference.com/cpp/language/lifetime)
- [Scope](https://en.cppreference.com/cpp/language/scope)
- [Destructors](https://en.cppreference.com/cpp/language/destructor)
- [`new` expression, including placement new](https://en.cppreference.com/cpp/language/new)
- [`delete` expression](https://en.cppreference.com/cpp/language/delete)
- [Initialization](https://en.cppreference.com/cpp/language/initialization), [zero initialization](https://en.cppreference.com/cpp/language/zero_initialization), and [constant initialization](https://en.cppreference.com/cpp/language/constant_initialization)
- [Static initialization order fiasco](https://en.cppreference.com/cpp/language/siof)
- [`constinit`](https://en.cppreference.com/cpp/language/constinit) and [`constexpr`](https://en.cppreference.com/cpp/language/constexpr)
- [Arrays](https://en.cppreference.com/cpp/language/array)
- [Undefined behavior](https://en.cppreference.com/cpp/language/ub)

Library

- [`operator new`](https://en.cppreference.com/cpp/memory/new/operator_new), [`operator delete`](https://en.cppreference.com/cpp/memory/new/operator_delete), [`std::nothrow`](https://en.cppreference.com/cpp/memory/new/nothrow), [`std::bad_alloc`](https://en.cppreference.com/cpp/memory/new/bad_alloc), [`std::align_val_t`](https://en.cppreference.com/cpp/memory/new/align_val_t)
- [`std::malloc`](https://en.cppreference.com/cpp/memory/c/malloc), [`std::free`](https://en.cppreference.com/cpp/memory/c/free), [`std::aligned_alloc`](https://en.cppreference.com/cpp/memory/c/aligned_alloc)
- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr), [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique), [`std::shared_ptr`](https://en.cppreference.com/cpp/memory/shared_ptr), [`std::weak_ptr`](https://en.cppreference.com/cpp/memory/weak_ptr)
- [`std::atexit`](https://en.cppreference.com/cpp/utility/program/atexit)
- [`std::thread`](https://en.cppreference.com/cpp/thread/thread)
- [`std::pmr::memory_resource`](https://en.cppreference.com/cpp/memory/memory_resource), [`std::pmr::monotonic_buffer_resource`](https://en.cppreference.com/cpp/memory/monotonic_buffer_resource), [`std::pmr::unsynchronized_pool_resource`](https://en.cppreference.com/cpp/memory/unsynchronized_pool_resource), [`std::pmr::polymorphic_allocator`](https://en.cppreference.com/cpp/memory/polymorphic_allocator)
- [`std::vector`](https://en.cppreference.com/cpp/container/vector), [`std::unordered_map`](https://en.cppreference.com/cpp/container/unordered_map), [`std::array`](https://en.cppreference.com/cpp/container/array)
- [`std::byte`](https://en.cppreference.com/cpp/types/byte)
- [`std::count`](https://en.cppreference.com/cpp/algorithm/count)
