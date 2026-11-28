# Memory

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
Every object in C++ is backed by physical memory, and the language classifies how that memory is
managed into four storage durations. A storage duration determines when an object's memory is
obtained, when it is released, and who is responsible for each step. Understanding how the hardware
handles each category explains where performance bottlenecks, lifetime bugs, and memory exhaustion
come from.

| Storage duration | Lifetime managed by | Primary trade-off | Common failure mode |
| ---------------- | ------------------- | ----------------- | ------------------- |
| Automatic (stack) | The enclosing block of code | Near-zero allocation cost, but strictly bounded size | Stack overflow from deep recursion or oversized local buffers |
| Dynamic (heap) | Explicit code (`new`/`delete` or smart pointers) | Flexible size and lifetime, but higher overhead | Leaks, fragmentation, and dangling pointers |
| Static | The whole program run | Always available, but initialization order across source files is unspecified | Using a dependency before it has been initialized |
| Thread-local | Each individual thread | Per-thread state without locks, but teardown order can leave dangling references | Referencing an already-destroyed object while a thread exits |
<!-- --8<-- [end:intro] -->

## 1. Automatic storage (the stack)

<!-- --8<-- [start:automatic] -->
When you declare a local variable inside a function, C++ places it in automatic storage: the
compiler creates it when execution enters its block and destroys it when execution leaves.

```cpp
int sum_three() {
    int values[3] = {1, 2, 3};   // created on the stack when sum_three() is entered
    return values[0] + values[1] + values[2];
}                                // values is destroyed here; no cleanup code needed
```

- Mechanism: each thread has a region of memory called the stack, and the CPU tracks its current top
  in a register called the stack pointer. Reserving space for a function's locals means moving that
  pointer by a fixed amount.
- Cost: releasing the memory happens automatically when the function returns or an exception passes
  through it, because the stack pointer is simply moved back. Recently used stack memory is almost
  always already in the CPU's fastest cache levels, so reading and writing it is as fast as memory
  access gets.
- Limitations: the operating system gives each thread a fixed stack size, typically between 1 and
  8 MB. Very large local arrays, or recursion that never stops or goes too deep, exhaust that space
  and crash the program with a stack overflow.

> An HTTP server typically parses each request into small local objects — a header view, a status
> code, a few counters — inside the handler function. They cost almost nothing to create and vanish
> when the handler returns, so millions of requests leave no memory behind.
<!-- --8<-- [end:automatic] -->

[Go deeper →](../cpp_deep_dive/memory.md#1-automatic-storage-the-stack)

## 2. Dynamic storage (the heap)

<!-- --8<-- [start:dynamic] -->
Dynamic memory is requested at run time, when the required size or lifetime cannot be known at
compile time.

```cpp
std::unique_ptr<int[]> make_buffer(std::size_t n) {
    return std::make_unique<int[]>(n);   // size chosen at run time; outlives this function
}

void manual() {
    int* p = new int(42);   // allocated on the heap
    delete p;               // must be released explicitly, exactly once
}
```

- Allocation cost: `new` or `malloc` asks the memory allocator to find a free block large enough,
  update its bookkeeping, and often coordinate with other threads that are allocating at the same
  time. This is much slower than moving the stack pointer.
- Lifetime ownership: the memory stays allocated until code explicitly releases it. Releasing it too
  early leaves pointers referring to memory that may now hold something else (a dangling pointer);
  never releasing it leaks memory. [Ownership](ownership.md) covers how C++ automates this.
- Fragmentation: in a long-running process, a mix of allocations and frees leaves small, scattered
  gaps between live blocks. Those gaps can be too small to reuse, which wastes memory and slows
  down later allocations. Systems that run for months often use custom pool allocators for this
  reason.

> An image editor cannot know how large a photo is until the user opens it, so it allocates the
> pixel buffer on the heap with the size read from the file, and keeps it alive for as long as the
> document window stays open.
<!-- --8<-- [end:dynamic] -->

[Go deeper →](../cpp_deep_dive/memory.md#2-dynamic-storage-the-heap)

## 3. Static storage

<!-- --8<-- [start:static] -->
Variables declared outside any function, or marked with the `static` keyword, exist for the entire
run of the program.

```cpp
int request_count = 0;            // global: initialized before main()

int next_id() {
    static int id = 0;            // initialized the first time next_id() runs, kept between calls
    return ++id;
}
```

- Lifecycle: their memory is reserved when the program is loaded, globals are normally initialized
  before `main()` starts, and they are destroyed after `main()` returns, in reverse order of
  construction. A `static` variable inside a function is the exception: it is initialized the first
  time execution reaches it.
- Ordering risk: within one source file, static variables are initialized from top to bottom. The
  standard does not define the order across different source files. If a global object in one file
  uses a global object from another file during its own initialization, it may read an object that
  has not been constructed yet. This is known as the static initialization order problem.

> A logging library often keeps one global logger that every file can reach. If another global
> object's constructor writes a log line during startup, it can run before the logger in a different
> source file has been constructed, which is why such loggers are usually created on first use
> instead.
<!-- --8<-- [end:static] -->

[Go deeper →](../cpp_deep_dive/memory.md#3-static-storage)

## 4. Thread-local storage

<!-- --8<-- [start:thread_local] -->
Marking a variable `thread_local` gives each thread its own independent copy.

```cpp
thread_local std::vector<char> scratch;   // each thread gets its own buffer

void format_message() {
    scratch.clear();                      // no lock needed: no other thread sees this vector
    scratch.push_back('x');
}
```

- Purpose: per-thread state such as tracing context, scratch buffers, or caches, which can be used
  without a mutex because no other thread can see it.
- Teardown hazard: each copy is destroyed when its thread exits. If its destructor uses a static
  object that has already been destroyed — for example, because the program is shutting down — the
  behavior is undefined.

> A web server that handles each connection on its own thread can store the current request ID in a
> `thread_local` variable, so every log line written on that thread includes the ID without passing
> it through every function call.
<!-- --8<-- [end:thread_local] -->

[Go deeper →](../cpp_deep_dive/memory.md#4-thread-local-storage)

## Choosing where an object lives

<!-- --8<-- [start:choosing] -->
Default to the stack whenever an object is only needed inside one function call. Use the heap when
an object must outlive the function that created it, or when its size is only known at run time.
Reserve static and thread-local storage for state that genuinely needs to be shared across the whole
program or across all work on one thread.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Storage duration, including `static` and `thread_local`](https://en.cppreference.com/cpp/language/storage_duration)
- [Object lifetime](https://en.cppreference.com/cpp/language/lifetime)
- [Scope](https://en.cppreference.com/cpp/language/scope)
- [`new` expression](https://en.cppreference.com/cpp/language/new)
- [`delete` expression](https://en.cppreference.com/cpp/language/delete)
- [Static initialization order fiasco](https://en.cppreference.com/cpp/language/siof)
- [Initialization](https://en.cppreference.com/cpp/language/initialization)
- [Undefined behavior](https://en.cppreference.com/cpp/language/ub)

Library

- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr)
- [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique)
- [`std::malloc`](https://en.cppreference.com/cpp/memory/c/malloc) and [`std::free`](https://en.cppreference.com/cpp/memory/c/free)
- [`operator new`](https://en.cppreference.com/cpp/memory/new/operator_new) and [`operator delete`](https://en.cppreference.com/cpp/memory/new/operator_delete)
- [`std::vector`](https://en.cppreference.com/cpp/container/vector)
