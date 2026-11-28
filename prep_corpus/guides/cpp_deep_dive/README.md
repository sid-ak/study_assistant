# C++ Deep Dive

The C++ Deep Dive covers the same topics as the [C++ Overview](../cpp_overview/README.md), one page
per topic, in more depth. Where an Overview page explains what a feature is and when to use it, the
matching Deep Dive page follows it down to the mechanism: how the compiler implements it, what it
costs at run time, how it interacts with the operating system and hardware, and the less obvious ways
it goes wrong. Each page stands on its own, but they build on each other in the order listed.

Project-specific material that used to live in these pages is collected on the
[Application](../application/README.md) page.

---

## Pages

| Page | What it covers |
| ---- | -------------- |
| [Versions](versions.md) | Each standard from C++98 to C++23 and beyond: what it added, what it removed, and how codebases adopt it |
| [Memory](memory.md) | Storage durations down to stack frames and allocators, initialization order, leaks, fragmentation, and the operating system's view of memory and I/O |
| [Ownership](ownership.md) | RAII, `unique_ptr`, `shared_ptr`, `weak_ptr`, and the Rule of Zero, Three, and Five |
| [Value Semantics](value-semantics.md) | Value categories, move semantics, forwarding, copy elision, parameter passing, and views |
| [Objects](objects.md) | Virtual dispatch and vtables, slicing, object layout, padding, alignment, and byte order |
| [Keywords](keywords.md) | What `const`, `static`, `inline`, `explicit`, and `noexcept` control, and why |
| [Templates](templates.md) | Instantiation, specialization, CRTP, SFINAE, concepts, `constexpr`, and type traits |
| [Containers](containers.md) | Container internals, iterator invalidation, `reserve`, and why CPU caches decide performance |
| [Concurrency](concurrency.md) | Data races, locks, deadlock, atomics, memory ordering, lock-free code, and false sharing |
| [Errors](errors.md) | Exceptions and their costs, error codes, `optional`, `variant`, and structured error types |
| [Compiler](compiler.md) | Undefined behavior, optimization, profiling, and debugging |
| [Build & Toolchain](build-toolchain.md) | Preprocessing, symbols, libraries, the loader, ABI, cross-compilation, and build systems |
