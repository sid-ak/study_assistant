# C++ Overview

The C++ Overview is a set of short pages, one per topic, that explain how the language works from
first principles. Each page starts from the problem a feature solves, defines its terms before using
them, and describes the mechanism underneath — what the compiler, the runtime, or the hardware is
actually doing. When a page raises a question it does not answer, it links to the matching section
of the [C++ Deep Dive](../cpp_deep_dive/README.md).

A suggested reading order is top to bottom: the early pages (memory, ownership, value semantics)
introduce ideas that almost every later page builds on.

---

## Pages

| Page | What it covers |
| ---- | -------------- |
| [Versions](versions.md) | The design goal behind C++ and what each standard, from C++98 to C++23, added toward it |
| [Memory](memory.md) | The four storage durations, and how the hardware handles each one |
| [Ownership](ownership.md) | How C++ decides who releases a resource, using RAII and smart pointers |
| [Value Semantics](value-semantics.md) | Copies, moves, value categories, and how to pass parameters |
| [Objects](objects.md) | Polymorphism, virtual functions, and how objects are laid out in memory |
| [Keywords](keywords.md) | What `const`, `static`, `inline`, `explicit`, and `noexcept` each control |
| [Templates](templates.md) | Generating code per type at compile time, and constraining it with concepts |
| [Containers](containers.md) | Choosing a standard container based on how memory is accessed |
| [Concurrency](concurrency.md) | Threads, data races, mutexes, atomics, and deadlock |
| [Errors](errors.md) | Exceptions, error codes, and value-based error types |
| [Compiler](compiler.md) | What a compiler does to one source file, and how to read what it tells you |
| [Build & Toolchain](build-toolchain.md) | The pipeline around the compiler: preprocessing, linking, libraries, and loading |
