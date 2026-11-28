# Compiler

> Part of the [C++ Deep Dive](README.md) · Overview: [Compiler](../cpp_overview/compiler.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:intro"

This page follows the compiler's stages in more depth — how names are found, why undefined behavior lets
the optimizer delete code, how code is tailored to a CPU, how sanitizers and hardening work — and then
covers the two practices that depend most on understanding the compiler: debugging and performance
profiling.

## 1. The front end: understanding the code

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:frontend"

### Argument-dependent lookup

```cpp
namespace storage {
    struct Block { int id; };
    void print(const Block& b) { std::printf("block %d\n", b.id); }
    void swap(Block& a, Block& b) noexcept { std::swap(a.id, b.id); }
}

template <typename T>
void exchange_values(T& a, T& b) {
    using std::swap;     // make std::swap a candidate
    swap(a, b);          // unqualified: argument-dependent lookup also finds storage::swap for Blocks
}

void use() {
    storage::Block a{1}, b{2};
    print(a);            // found without storage:: because the argument's type lives in storage
    exchange_values(a, b);
}
```

- Rule: for an unqualified function call, the compiler also searches the namespaces of the arguments'
  types. This argument-dependent lookup (ADL) is what makes `std::cout << value` find an `operator<<`
  declared next to a user's type.
- The `using std::swap;` idiom: generic code brings the standard version into scope and calls `swap`
  unqualified, so a type's own, faster `swap` is chosen when it exists.
- Hazard: ADL can pick up unexpected functions from an argument's namespace, which is why library code
  qualifies calls such as `std::move` explicitly.

### Parsing surprises

```cpp
struct Timer { Timer() = default; };

void parse() {
    Timer t1();          // declares a function named t1 returning Timer, not an object
    Timer t2{};          // an object: braces cannot be read as a function declaration
    Timer t3;            // also an object
    (void)t2;
    (void)t3;
}
```

- The "most vexing parse": when a statement could be read as either a declaration or an expression, C++
  treats it as a declaration. Clang warns with `-Wvexing-parse`.
- Braced initialization avoids the ambiguity, which is one reason modern code prefers it.

### Where compile time goes

- Header expansion: every included header is parsed again in every translation unit that includes it.
- Template instantiation: each distinct instantiation is compiled, and deeply nested templates multiply.
- Measuring: Clang's `-ftime-trace` writes a per-file timeline showing time spent in each header and
  template instantiation, viewable in a browser's tracing tool. See [Build & Toolchain](build-toolchain.md)
  for reducing it.

> Teams working on large C++ codebases aggregate `-ftime-trace` output across every file with tools such
> as ClangBuildAnalyzer, which ranks the headers and templates that cost the most total compile time, so
> build-speed work starts from measurements rather than guesses.

## 2. The middle end: optimization

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:middle"

### What "no requirements" means

The standard imposes no requirements at all on a program that executes undefined behavior. It is not
"an unpredictable value" and not implementation-defined behavior.

- Optimizers reason from premises: every operation whose use would be undefined in some case becomes a
  fact the optimizer may assume. Dereferencing a pointer implies it is not null; adding to a signed
  integer implies no overflow.
- Facts propagate: once the compiler has concluded something, it removes code that only matters if the
  conclusion is false.
- Contrast: unspecified behavior lets the implementation choose among allowed outcomes, and
  implementation-defined behavior requires it to choose and document. Only undefined behavior lets the
  optimizer assume the situation never occurs.

### How a null check disappears

```cpp
void log_null();

int store(int* p) {
    *p = 5;                  // after this line, the compiler may assume p is not null
    if (p == nullptr) {      // so this condition is always false
        log_null();
        return -1;
    }
    return 0;
}
```

- Result: Clang at `-O2` compiles `store` to a write followed by `return 0`. The check and the call to
  `log_null` are deleted.
- Direction of the damage: the safety check disappears, not the dangerous dereference.

### Common sources of undefined behavior

| Undefined behavior | Notes |
| ------------------ | ----- |
| Dereferencing a null, dangling, or invalid pointer | Includes use after free and returning pointers to locals |
| Out-of-bounds access | `operator[]` on standard containers does not check |
| Signed integer overflow | Unsigned arithmetic wraps; signed arithmetic does not |
| Reading an uninitialized variable | Its value is indeterminate |
| Data races | See [Concurrency](concurrency.md) |
| Violating strict aliasing | Accessing an object through a pointer to an unrelated type |
| Misaligned access | See [Objects](objects.md) |
| Flowing off the end of a non-`void` function | Except `main` |
| Mismatched `new[]` and `delete` | See [Memory](memory.md) |
| Shifting by a negative amount or by at least the bit width | `1 << 32` for a 32-bit `int` |

### Why signed overflow and strict aliasing are undefined

```cpp
int alias(int* i, float* f) {
    *i = 1;
    *f = 2.0f;
    return *i;              // Clang returns the constant 1: an int* and a float* cannot alias
}

std::uint32_t bits_of(float value) {
    return std::bit_cast<std::uint32_t>(value);   // the defined way to read a float's bytes
}
```

- Signed overflow: because `i` in `for (int i = 0; i < n; ++i)` cannot overflow, the compiler may widen it
  to a 64-bit register and compute trip counts, which enables vectorization.
- Strict aliasing: because pointers to unrelated types are assumed not to refer to the same memory, a write
  through one does not force the compiler to reload values read through the other.
- Defined alternatives: `std::bit_cast` (C++20) or `std::memcpy` read one type's representation as another.
  `-fno-strict-aliasing` disables the assumption, which some low-level codebases such as the Linux kernel
  use.

### Whole-program and profile-guided optimization

- Link-time optimization (LTO, `-flto`): the compiler stores its intermediate representation in object
  files and optimizes again at link time, so calls can be inlined across translation units. ThinLTO keeps
  most of the benefit with parallel, incremental builds.
- Profile-guided optimization (PGO): an instrumented build (`-fprofile-generate` in GCC,
  `-fprofile-instr-generate` in Clang) records which branches and functions are hot on a representative
  workload, and the final build uses that profile to decide inlining, code layout, and branch ordering.

> Web browsers ship with profile-guided and link-time optimization: Chrome and Firefox build their release
> binaries with profiles collected from running benchmark workloads, which yields measurable speedups over
> the same code built with `-O2` alone.

## 3. The back end: generating machine code

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:backend"

### Target instruction sets and SIMD

```cpp
void add_arrays(float* out, const float* a, const float* b, std::size_t n) {
    for (std::size_t i = 0; i < n; ++i) {
        out[i] = a[i] + b[i];             // a vectorizer can process 4, 8, or 16 floats per instruction
    }
}

#if defined(__x86_64__)
[[gnu::target_clones("avx2", "default")]]  // GCC and Clang on x86: one version per target, chosen at load time
#endif
int sum(const int* values, int n) {
    int total = 0;
    for (int i = 0; i < n; ++i) total += values[i];
    return total;
}
```

- SIMD (single instruction, multiple data): vector instructions such as SSE and AVX on x86 and NEON or SVE on
  ARM operate on several values at once. The auto-vectorizer rewrites suitable loops to use them.
- `-march`: `-march=x86-64-v3` or `-march=native` lets the compiler use newer instructions, but the binary
  then crashes with an illegal instruction on older CPUs. Distributed binaries target a conservative baseline
  and use function multiversioning, such as `target_clones`, for hot functions.
- Seeing vectorization: GCC reports it with `-fopt-info-vec`; Clang records optimization decisions with
  `-fsave-optimization-record`. Aliasing between `out` and the inputs can prevent vectorization unless the
  compiler adds a run-time overlap check.

### Debug information in optimized code

- `-g` with `-O2`: the debug information still maps instructions to source lines, but variables may live
  only in registers for part of their lifetime, so debuggers report them as "optimized out", and stepping
  jumps around because code was reordered or inlined.
- `-Og`: optimizes only in ways that keep debugging usable.
- Separate debug files: release builds keep debug information in separate files (`objcopy --only-keep-debug`
  or `.dSYM` bundles on macOS), so production binaries stay small while crashes remain symbolizable.

> Linux distributions such as Fedora and Ubuntu publish debug information for every package through
> `debuginfod` servers. Debuggers and profilers download the matching symbols on demand when analyzing a
> crash or profile, without shipping them in the installed binaries.

## 4. The major compilers

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:compilers"

### Standard library implementations

| Library | Shipped with | Notes |
| ------- | ------------ | ----- |
| libstdc++ | GCC, and used by Clang on most Linux distributions | Debug mode via `-D_GLIBCXX_DEBUG`; lightweight checks via `-D_GLIBCXX_ASSERTIONS` |
| libc++ | LLVM, default on macOS, Android, and FreeBSD | Hardening modes via `-D_LIBCPP_HARDENING_MODE=...` |
| Microsoft STL | MSVC | Checked iterators controlled by `_ITERATOR_DEBUG_LEVEL` |

- The compiler and the standard library are separate components. Clang on Linux usually uses libstdc++
  unless given `-stdlib=libc++`, which is why "supported by Clang" and "supported by the library Clang is
  using" can differ.
- The libraries are not binary-compatible with each other, so all code linked into one program must use the
  same one.

### Portable use of compiler-specific features

```cpp
#if defined(__GNUC__) || defined(__clang__)
#  define PREP_LIKELY(x) __builtin_expect(!!(x), 1)
#  define PREP_NOINLINE [[gnu::noinline]]
#elif defined(_MSC_VER)
#  define PREP_LIKELY(x) (x)
#  define PREP_NOINLINE __declspec(noinline)
#endif

PREP_NOINLINE void report_failure();

int checked(int value) {
    if (PREP_LIKELY(value >= 0)) return value;
    report_failure();
    return 0;
}
```

- Standard attributes first: `[[likely]]`, `[[unlikely]]`, `[[nodiscard]]`, `[[maybe_unused]]`, and
  `[[fallthrough]]` work everywhere. Vendor-specific features are wrapped in macros only where no standard
  form exists.
- Unknown attributes: compilers ignore attributes in namespaces they do not recognize (with a warning), so
  `[[gnu::...]]` attributes are harmless on MSVC but have no effect there.

> CMake projects commonly test compiler behavior at configure time with `check_cxx_source_compiles`, and
> libraries such as Abseil and Folly keep a single portability header that maps each needed feature to the
> right spelling for GCC, Clang, and MSVC.

## 5. Flags that change behavior

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:flags"

### How sanitizers work

```cpp
int main(int argc, char**) {
    int x = INT_MAX;
    x += argc;                          // -fsanitize=undefined reports: signed integer overflow
    return x > 0 ? 0 : 1;
}
```

| Sanitizer | Flag | Finds | Mechanism | Typical slowdown |
| --------- | ---- | ----- | --------- | ---------------- |
| AddressSanitizer | `-fsanitize=address` | Out-of-bounds, use-after-free, double free, leaks | Shadow memory: one byte describes each 8 bytes of application memory, with poisoned red zones around allocations | About 2× |
| UndefinedBehaviorSanitizer | `-fsanitize=undefined` | Signed overflow, invalid shifts, misalignment, null dereferences | Checks inserted at each risky operation | Small |
| ThreadSanitizer | `-fsanitize=thread` | Data races, lock-order inversions | Records every memory access with its thread's history | About 5–15× |
| MemorySanitizer | `-fsanitize=memory` (Clang, Linux) | Reads of uninitialized memory | Tracks initialization of every bit | About 3× |

- Combinations: AddressSanitizer and UndefinedBehaviorSanitizer are commonly combined; ThreadSanitizer and
  MemorySanitizer each need their own build.
- Production use: `-fsanitize=undefined -fsanitize-trap=undefined` replaces reporting with a trap
  instruction and needs no runtime library, which makes it cheap enough for some release builds.

### Hardening flags

| Flag | Protection |
| ---- | ---------- |
| `-D_FORTIFY_SOURCE=2` or `3` (with optimization) | Checks sizes in `memcpy`, `strcpy`, and similar calls when buffer sizes are known |
| `-fstack-protector-strong` | Places a canary value before return addresses and aborts if it is overwritten |
| `-ftrivial-auto-var-init=zero` | Zero-initializes local variables, removing uninitialized-read bugs |
| `-D_GLIBCXX_ASSERTIONS` or libc++ hardening modes | Bounds checks in standard containers |
| `-fPIE -pie` | Position-independent executables, enabling address randomization |

- These catch or blunt memory-safety bugs in shipped binaries at a small cost, and most Linux distributions
  enable several of them by default for their packages.

### Warning policy

- Baseline: `-Wall -Wextra` enable the most useful warnings; `-Wpedantic` warns about non-standard
  extensions; `-Wshadow`, `-Wconversion`, and `-Wsign-conversion` catch subtler mistakes at the cost of more
  noise.
- `-Werror` in continuous integration, not everywhere: new compiler versions add warnings, so treating
  warnings as errors in release builds of source distributed to others can break their builds.

> The Linux kernel's `CONFIG_INIT_STACK_ALL_ZERO` option builds the kernel with
> `-ftrivial-auto-var-init=zero`, and Android enables it in its kernels, trading a small performance cost
> for eliminating a whole class of uninitialized-stack-variable vulnerabilities.

## 6. Reading and debugging compiler output

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:diagnostics"

### A method for hard bugs

A bug means the program's actual behavior has diverged from the model of it in the programmer's head. The
task is to find where, and every step should shrink the set of possible causes.

1. Reproduce, then shrink the reproduction until every remaining part is necessary.
2. Read the evidence first: the core dump, logs, kernel messages (`dmesg`), and the exact error text.
3. Form a hypothesis that predicts something observable, then check that prediction.
4. Bisect: in history with `git bisect`, in code by disabling half, or in configuration.
5. Make the invisible visible: add instrumentation, and keep what proves useful.
6. Fix the cause rather than the symptom, then add a test that would have caught it.

### Tools by symptom

| Symptom | First tools |
| ------- | ----------- |
| Crash | A debugger on the core file: `bt`, `thread apply all bt`, `info locals`, `frame N` |
| Memory corruption or use-after-free | AddressSanitizer; Valgrind when rebuilding is not possible |
| Intermittent failure | ThreadSanitizer; suspect uninitialized memory or destruction order |
| Hang | Attach a debugger and print every thread's stack |
| Crash only at exit | Static destruction order and threads still running. See [Memory](memory.md) |
| Slow | A sampling profiler and a flame graph (section 7) |
| Only in production | Structured logs, metrics, and distributed tracing |

### Tools for bugs that resist observation

- `rr` (Linux) records an execution once and replays it deterministically, including backwards, so a bug
  that appears one run in a thousand can be debugged repeatedly once captured.
- eBPF tools such as `bpftrace` attach probes to a running process or the kernel without restarting it.
- Concurrency bugs often vanish under a debugger because stopping threads changes timing. Timestamped traces
  with thread IDs let the interleaving be reconstructed after the fact.

> Mozilla developed `rr` to debug intermittent Firefox test failures: once a failing run is recorded, an
> engineer can replay that exact execution as many times as needed, stepping backward from the crash to the
> write that corrupted memory.

## 7. Profiling and performance

Performance work follows an order of operations, because intuition about where time goes is usually wrong on
modern hardware: the code that runs is not the code that was written, and a single cache miss can cost more
than hundreds of arithmetic operations.

```sh
perf stat -e cycles,instructions,cache-misses,branch-misses ./server   # counters: why is it slow?
perf record -g ./server                                               # sampling with call stacks
perf report                                                           # where is time spent?
```

1. Define the metric: throughput, median latency, or tail latency such as p99 lead to different work.
2. Make the measurement reproducible, and profile rather than guess.
3. Classify the bottleneck: CPU, memory access, I/O, or lock contention.
4. Fix the largest contributor and measure again. Amdahl's law caps the gain from speeding up any part at
   that part's share of the total.
5. Stop when the target is met; every optimization adds code to maintain.

### Where the gains usually are

1. Algorithms and data structures: changing the complexity class dwarfs every other improvement.
2. Memory: layout, locality, and allocation count. See [Containers](containers.md) and [Memory](memory.md).
3. Concurrency: parallelism first, then contention and false sharing. See [Concurrency](concurrency.md).
4. Micro-optimizations: branch layout, inlining, and SIMD, applied last and only where a profile points.

- The three costs that dominate systems code are cache misses, allocations, and synchronization; most
  effective optimizations remove one of them.

### Tools by question

| Question | Tools |
| -------- | ----- |
| Where is CPU time spent? | `perf record` and `perf report`, flame graphs, Intel VTune, macOS Instruments |
| Why is it slow when CPU use is low? | `perf stat`: instructions per cycle, cache misses, branch misses |
| Where is memory allocated? | `heaptrack`, Valgrind's `massif`, jemalloc's profiler |
| Is there lock contention? | `perf lock`, off-CPU flame graphs |
| Are cache lines contended? | `perf c2c` |
| Where does I/O time go? | `iostat`, `biolatency` and other eBPF tools |
| What system calls are made? | `strace -c`, `bpftrace` |
| What is the latency distribution? | HdrHistogram or similar; report percentiles, not averages |

- Instructions per cycle (IPC): a low value (below about 1) suggests the CPU spends much of its time waiting
  for memory rather than executing.
- Averages hide tails: a service with a good mean and a bad p99 still feels slow to the users who hit the
  tail, so latency is reported as percentiles.

> Brendan Gregg introduced flame graphs while diagnosing a MySQL performance issue at Joyent: stacking every
> sampled call stack and sizing each frame by how often it appears makes the few hot code paths visible at a
> glance, and the technique is now built into most profilers.

## Working with the compiler

??? note "Overview"

    --8<-- "guides/cpp_overview/compiler.md:choosing"

Build tests with sanitizers in separate continuous integration jobs, ship with the hardening flags your
platform supports, keep separate debug information for release binaries, and let profiles rather than
intuition decide where optimization effort goes.

## C++ References

Language

- [Name lookup](https://en.cppreference.com/cpp/language/lookup) and [argument-dependent lookup](https://en.cppreference.com/cpp/language/adl)
- [Declarations and the most vexing parse](https://en.cppreference.com/cpp/language/direct_initialization)
- [Undefined, unspecified, and implementation-defined behavior](https://en.cppreference.com/cpp/language/ub)
- [Arithmetic operators, overflow, and shifts](https://en.cppreference.com/cpp/language/operator_arithmetic)
- [Type aliasing rules (`reinterpret_cast`)](https://en.cppreference.com/cpp/language/reinterpret_cast)
- [Default initialization and indeterminate values](https://en.cppreference.com/cpp/language/default_initialization)
- [Attributes, including `[[likely]]` and `[[unlikely]]`](https://en.cppreference.com/cpp/language/attributes)
- [The as-if rule](https://en.cppreference.com/cpp/language/as_if)
- [Predefined macros](https://en.cppreference.com/cpp/preprocessor/replace)

Library

- [`std::bit_cast`](https://en.cppreference.com/cpp/numeric/bit_cast) and [`std::memcpy`](https://en.cppreference.com/cpp/string/byte/memcpy)
- [`std::swap`](https://en.cppreference.com/cpp/utility/swap)
- [`INT_MAX` and integer limits](https://en.cppreference.com/cpp/types/climits)
- [Compiler support by feature](https://en.cppreference.com/cpp/compiler_support)
