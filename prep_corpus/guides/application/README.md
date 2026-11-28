# Application

> Part of the **C++ Deep Dive — NetApp Systems Software Engineer** guide — [back to index](../cpp_deep_dive/README.md)

---

## Mapping

Where each C++ concept shows up in work you actually did. Use these to convert an abstract question
into a concrete story — an interviewer will always remember the answer with evidence attached.

### Compile-Time ORM (TimescaleDB/Postgres telemetry layer)

| Concept                                         | How it showed up                                                                                                                                                                                                                               |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [CRTP](../cpp_deep_dive/objects.md#6-static-polymorphism-with-crtp)                                   | The core design, and chosen for one reason: `Entity<Record>` hands the base class the derived type at compile time, which is what makes Boost Describe + Mp11 reflection over its fields possible. No vtable and full inlining were side wins. |
| [Templates](../cpp_deep_dive/templates.md#1-how-templates-generate-code)                            | Type-safe query construction and row→struct mapping generated per record type — the column list, SQL, and validation all derived from the reflected member list.                                                                               |
| [Traits](../cpp_deep_dive/templates.md#7-type-traits)                               | Compile-time checks that a record type is mappable, and dispatch on field types for SQL type conversion.                                                                                                                                       |
| [Constexpr](../cpp_deep_dive/templates.md#6-constexpr-running-code-at-compile-time) / [Concepts](../cpp_deep_dive/templates.md#5-concepts) | Where I'd take it on a modern toolchain: express the entity contract as a concept for readable failures.                                                                                                                                       |
| [Params](../cpp_deep_dive/value-semantics.md#5-passing-parameters)                               | Avoiding unnecessary allocations and copies in row mapping — `const&` for reads, explicit conversions rather than implicit.                                                                                                                    |
| [Optional](../cpp_deep_dive/errors.md#4-stdoptional)                           | Nullable columns map naturally to `std::optional<T>`.                                                                                                                                                                                          |
| [Vector](../cpp_deep_dive/containers.md#2-stdvector-the-default) / [Reserve](../cpp_deep_dive/containers.md#2-stdvector-the-default)         | Result sets reserved to the row count to avoid repeated reallocation.                                                                                                                                                                          |
| [Exceptions](../cpp_deep_dive/errors.md#1-exceptions) vs [Codes](../cpp_deep_dive/errors.md#3-error-codes)    | Deliberate choice about how query failures surface — compile-time for schema errors, explicit results for runtime ones.                                                                                                                        |

**The one-sentence version:** _"I used CRTP so the base class could reflect over each record type's
fields with Boost Describe and Mp11 — generating the columns, the SQL, and the type checks at build
time — which moved an entire class of errors, schema drift and column-type mismatch, from runtime to
compile time at zero runtime cost."_

### Build, Toolchain & Deployment (across the ADAS work)

**This is the mapping section people forget to prepare, and for this role it's high-value** — a
storage company runs a large, old, slow-building C++ codebase, and cares that you've thought about
it.

| Concept                                   | How it showed up                                                                                                                                                                                                                          |
| ----------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Cross](../cpp_deep_dive/build-toolchain.md#cross)                           | Cross-compiled the telemetry library and collector, and the ORM, from x86-64 hosts for the ARM64 DHU. Sysroot setup, triple-prefixed toolchain, verifying the artifact with `file` and `readelf` rather than assuming.                    |
| [Cross](../cpp_deep_dive/build-toolchain.md#cross) / [Model](../cpp_deep_dive/concurrency.md#5-memory-ordering-in-atomics)         | **The best story here:** x86-64 is TSO, AArch64 is weakly ordered. Insufficient atomic ordering is invisible on the dev machine and real on the target — and QEMU won't reproduce it, so it has to be caught by reasoning or on hardware. |
| [Cross](../cpp_deep_dive/build-toolchain.md#cross) / [Alignment](../cpp_deep_dive/objects.md#7-alignment-beyond-the-struct) | ARM's stricter alignment rules make `reinterpret_cast` over a byte buffer fault where x86 tolerates it — directly relevant to on-wire and on-disk formats.                                                                                |
| [Loader](../cpp_deep_dive/build-toolchain.md#loader)                         | `LD_LIBRARY_PATH` to give the DHU application a private, versioned dependency set without modifying a read-only base image. The isolation model, plus the honest critique and the `$ORIGIN` RPATH answer.                                 |
| [Libraries](../cpp_deep_dive/build-toolchain.md#libraries)                   | Static versus shared on an embedded target: what you ship, what the BSP gives you, and why eager binding (`LD_BIND_NOW`) is the right default in safety-adjacent code — fail at startup, not mid-operation.                               |
| [BuildSys](../cpp_deep_dive/build-toolchain.md#buildsys)                     | Bazel on the ADAS monorepo, and the remote cache and execution work on AKS. Hermeticity as the property that makes a shared cache _sound_ rather than merely fast.                                                                        |
| [Buildspeed](../cpp_deep_dive/build-toolchain.md#buildspeed)                 | Build latency identified as a team-wide velocity problem and solved at the infrastructure layer — the last and heaviest item on the standard list, reached for because it had become a shared bottleneck.                                 |
| [Headers](../cpp_deep_dive/build-toolchain.md#headers) / [Symbols](../cpp_deep_dive/build-toolchain.md#symbols) | Template-heavy code (CRTP ORM, Boost) is where compile time goes; explicit instantiation over a closed set of entity types is the lever.                                                                                                  |
| [ABI](../cpp_deep_dive/build-toolchain.md#abi)                               | The telemetry library shipped in the base system image, consumed by applications built separately — which is exactly the situation where ABI stability stops being academic.                                                              |

**The one-sentence version:** _"I've cross-compiled multi-threaded C++ for ARM64 embedded Linux,
dealt with the dependency isolation and memory-model problems that come with it, and separately took
build latency seriously enough to move the team onto remote caching and execution."_

### OpenTelemetry Library (multi-threaded ADAS, aarch64 embedded Linux)

| Concept                           | How it showed up                                                                                                                                                       |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Fiasco](../cpp_deep_dive/memory.md#the-static-initialization-order-problem)                 | The headline bug. Static destruction order across TUs, in a multi-threaded process.                                                                                    |
| [Singletons](../cpp_deep_dive/concurrency.md#7-initialization-and-shutdown)         | Meyers singleton → weak-pointer singleton + `atexit`. The full arc of understanding what a singleton does and doesn't guarantee.                                       |
| [Weak](../cpp_deep_dive/ownership.md#4-stdweak_ptr-observing-without-owning) / [Shared](../cpp_deep_dive/ownership.md#3-stdshared_ptr-shared-ownership) | The fix mechanism: consumers hold a strong ref while in use, so the provider can't be destroyed mid-call.                                                              |
| [RAII](../cpp_deep_dive/ownership.md#1-raii-tying-cleanup-to-scope)                     | Span scopes — a span starts on construction, ends on destruction. Guarantees no unclosed spans on any exit path, including exceptions.                                 |
| [Races](../cpp_deep_dive/concurrency.md#1-data-races)                   | Thread-safe instrumentation across worker threads; context propagation without a data race.                                                                            |
| [Atomics](../cpp_deep_dive/concurrency.md#4-atomics)               | Counters and histograms updated from many threads without a mutex in the hot path.                                                                                     |
| [Sharing](../cpp_deep_dive/concurrency.md#9-false-sharing)               | Per-thread or padded counters to avoid false sharing on hot metrics.                                                                                                   |
| [Cache](../cpp_deep_dive/containers.md#1-why-memory-layout-dominates) / [Speed](../cpp_deep_dive/compiler.md#7-profiling-and-performance) | Minimal-overhead instrumentation on a CPU- and memory-constrained DHU — telemetry must not perturb safety-critical work.                                               |
| [Exceptions](../cpp_deep_dive/errors.md#1-exceptions)         | Design rule: **telemetry must never crash the app.** Exporters isolated, failures swallowed and counted, back-pressure handled by dropping spans rather than blocking. |
| [Debugging](../cpp_deep_dive/compiler.md#6-reading-and-debugging-compiler-output)           | The whole point of the project — making a multi-threaded system observable so latency and divergence are diagnosable in minutes rather than days.                      |

**The one-sentence version:** _"I built the observability layer for a multi-threaded C++ ADAS stack,
cross-compiled it for aarch64, and fixed a shutdown-order crash by redesigning global resource
lifetime — which then became the team's standard pattern."_

### Python Schema Bridge (C# models → C++ structs)

| Concept                                       | How it showed up                                                                                                                                                                                             |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [Incomplete](../cpp_deep_dive/objects.md#complete-and-incomplete-types)                     | The core technical problem. Structs composed other structs by value, which requires a complete type — so every type had to be emitted after everything it referenced, and the source schemas were unordered. |
| [Padding](../cpp_deep_dive/objects.md#5-memory-layout-and-padding) / [Alignment](../cpp_deep_dive/objects.md#7-alignment-beyond-the-struct) | Why completeness is required at all: the compiler needs a member's size and alignment to place it at an offset. Also why the output had to be memory-aligned and `static_assert`-verified.                   |
| [Layout](../cpp_deep_dive/objects.md#5-memory-layout-and-padding)                             | Generated types had to be standard-layout and trivially copyable to be safely memcpy'd across the boundary.                                                                                                  |
| [Endian](../cpp_deep_dive/objects.md#8-byte-order)                             | Explicit widths and explicit byte order rather than trusting struct layout across machines.                                                                                                                  |
| Algorithms                                    | A recursive traversal of the type reference graph — a topological sort: adjacency list, DFS with a visited set, emit dependencies before dependents, fail the build with the cycle path on a cycle.          |

**The one-sentence version:** _"I wrote a code generator that produced memory-aligned C++ structs
from C# models, which meant solving the type-ordering problem as a graph traversal — a topological
sort over the dependency graph, since a struct can't hold another by value until that type is
complete."_

### External Libraries Sync & Azure Pipelines

Less C++, more systems thinking — use it for automation, scale limits, and debugging platform
behavior. The `git clone --bare` reasoning (metadata only, no working tree, faster and safer in a
pipeline) and the hashtag/auto-resolve incident are both good "I investigated a surprising behavior
at a layer below my code" stories.

### Boost.Beast REST + LEAF

| Concept                               | How it showed up                                                                                                              |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| [LEAF](../cpp_deep_dive/errors.md#structured-error-context-without-exceptions)                         | Structured errors carrying context, so a failure identified its own layer — validation, network, timing, or downstream state. |
| [Codes](../cpp_deep_dive/errors.md#3-error-codes)                       | The alternative I rejected, and why.                                                                                          |
| [Futures](../cpp_deep_dive/concurrency.md#6-waiting-and-results) / [Races](../cpp_deep_dive/concurrency.md#1-data-races) | Correctness under concurrent load: request parsing, timeouts, and lifetime of the connection state.                           |

---

## Stories

Compact, spoken-length versions. These are the ones to have loaded.

**"Tell me about a hard bug."**

> "Non-deterministic crash in a multi-threaded ADAS application, but only during shutdown. Nothing
> wrong in steady state. The debugger was actively unhelpful because attaching changed the timing. I
> reasoned about it structurally instead: what's true at shutdown that isn't true at any other time?
> Answer — static objects are being destroyed while threads are still running. Our OpenTelemetry
> providers were global statics, and worker threads were emitting final spans against objects that
> had already been destructed. My first fix was a Meyers singleton, which fixes _initialization_
> order but does nothing for _destruction_ order — I was solving the adjacent problem. The real fix
> was a weak-pointer singleton, so every caller holds a strong reference for as long as it's using
> the provider, plus `atexit` registration for a deterministic flush. Crashes went to zero, and it
> became the team's standard pattern for global resources."

**"Tell me about a technical disagreement."**

> "A senior lead wanted raw SQL strings for our time-series telemetry layer; I wanted a compile-time
> ORM using CRTP. His concern was legitimate — template-heavy code is 'magic' and hard for junior
> engineers to debug. Rather than argue style, I proposed we first agree on what the primary risk
> was. We landed on: runtime crashes from schema drift, in a vehicle, in the field. Then I built a
> small proof of concept showing a column-type mismatch caught at _build_ time that raw SQL wouldn't
> catch until deployment, and benchmarked it to show static polymorphism added zero runtime
> overhead. I also wrote a thorough GoogleTest suite specifically to address his maintainability
> concern — proving the abstraction was a safety net rather than a liability. He agreed. The thing
> I'd emphasize is that the conversation only moved once we shifted from 'whose approach is better'
> to 'which one reduces project risk.'"

**"Tell me about something you optimized or automated."**

> "Our cross-team library dependencies were drifting because syncs were manual and inconsistent — a
> slow-moving correctness problem nobody owned. I built a fully automated sync using
> `git clone --bare` (metadata only — faster, less disk, and no working tree to accidentally modify
> mid-pipeline) driven through the `az` CLI. Two things made it interesting. First, I hit an
> undocumented 20-repo ceiling in Azure Pipelines YAML, so I generated additional YAML files
> dynamically once the limit was hit rather than bloating the main template. Second, and more
> instructive: after rollout our PM noticed work items closing on their own. Commits in the synced
> repos contained hashtags, and Azure DevOps was parsing them as ticket-close commands. I owned
> that, researched the API, and scripted a temporary toggle of the auto-resolve setting for the
> duration of the sync. Result was fully automated weekly updates with zero manual input — and I
> documented the edge case so the rest of the DevOps org wouldn't rediscover it."

**"Tell me about designing for correctness."**

> "The Python schema bridge. Our Services team worked in C#, the Perception team needed the same
> models as memory-aligned C++ structs, and they were hand-syncing — which meant every schema change
> was a future integration bug. I built a code generator, but the interesting part was that I
> couldn't emit the type definitions in the order the source declared them. The models composed each
> other by value, and C++ needs a complete type for a by-value member — it needs the size and
> alignment to lay out the parent, so a forward declaration doesn't help. The schemas came in
> arbitrary order, so source-order output just didn't compile. So I wrote a recursive traversal of
> the type reference graph — a topological sort, emitting every type after everything it contained,
> with cycle detection that fails the build. What made it actually get adopted, though, was process
> rather than code: I pulled in the lead engineers from both teams early, so the generated output
> respected how each team already worked instead of forcing one of them onto the other's tooling."

---

## Rapidfire

Answer each in under 30 seconds. Drill these out loud.

| Question                                            | Answer                                                                                                                                                                                                                               |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| What does `std::move` do?                           | Nothing at runtime. A compile-time cast from lvalue to rvalue reference, enabling move-constructor selection.                                                                                                                        |
| State of a moved-from vector?                       | Valid but unspecified. Safe to destroy or reassign; don't assume empty.                                                                                                                                                              |
| Why virtual destructor?                             | Deleting a derived object via a base pointer without one is UB — only the base part is destroyed, derived members leak.                                                                                                              |
| How does a virtual call work?                       | Load the object's vptr, index the class's vtable at the function's fixed slot, indirect call.                                                                                                                                        |
| Real cost of virtual?                               | 8 bytes/object, two dependent loads — but the dominant cost is that it blocks inlining.                                                                                                                                              |
| `unique` vs `shared` vs `weak`?                     | Exclusive/move-only/zero-overhead; shared ownership via atomic refcount; non-owning observer that breaks cycles.                                                                                                                     |
| Is `shared_ptr` thread-safe?                        | Refcount yes (atomic). The pointee no. The `shared_ptr` _object itself_ no — concurrent reassignment of the same instance is a race.                                                                                                 |
| Rule of 3/5/0?                                      | 0 is the goal — members that manage themselves. 3 if you write a destructor. 5 adds moves, because declaring a destructor suppresses them.                                                                                           |
| What is RAII?                                       | Bind resource lifetime to object lifetime — acquire in ctor, release in dtor. Guaranteed even on exception unwinding.                                                                                                                |
| Data race vs race condition?                        | Data race: unsynchronized concurrent access with a write — UB. Race condition: correctness depends on timing; can exist with no data race (TOCTOU).                                                                                  |
| Why not `volatile` for threading?                   | It only stops compiler caching of accesses. No atomicity, no ordering, no cross-core visibility. Use `std::atomic`.                                                                                                                  |
| `lock_guard` vs `unique_lock` vs `scoped_lock`?     | Minimal RAII; flexible (defer/unlock/move/timed, required by condvars); multi-mutex with deadlock avoidance — the modern default.                                                                                                    |
| How to prevent deadlock?                            | Global lock ordering, or `scoped_lock`/`std::lock` for atomic multi-acquire. Break one Coffman condition.                                                                                                                            |
| Why `map` over `unordered_map`?                     | Need ordering/range queries, or need predictable worst case — a rehash is an unbounded stall that wrecks p99.                                                                                                                        |
| `vector` vs `list`?                                 | Vector, almost always. Contiguity and prefetching beat pointer chasing; list's O(1) insert is nullified by an allocation and a cache miss per node.                                                                                  |
| What's wrong with `vector<bool>`?                   | It's a bit-packed specialization, not a real container. `operator[]` returns a proxy, not `bool&`.                                                                                                                                   |
| What is SFINAE?                                     | Substitution failure during template argument deduction removes an overload rather than erroring. In C++20 use concepts.                                                                                                             |
| Why CRTP?                                           | The base needs the derived type as a template parameter to reflect over its fields (Boost Describe + Mp11); virtual erases it. No vtable, inlining, and compile-time interface enforcement are side wins.                            |
| What is `if constexpr`?                             | Compile-time branch; the discarded branch isn't instantiated, so it may contain code invalid for that type.                                                                                                                          |
| Static initialization order fiasco?                 | Cross-TU dynamic init order is unspecified. Fix with construct-on-first-use, `constinit`, or explicit init from `main`.                                                                                                              |
| Cost of exceptions?                                 | Zero on the happy path; very expensive when thrown (unwinding + a global lock in the unwinder). Always costs binary size.                                                                                                            |
| Exception safety guarantees?                        | No-throw, strong (transactional), basic (no leaks, invariants hold), none.                                                                                                                                                           |
| Why `noexcept` on move?                             | `vector` reallocation falls back to _copying_ if the move can throw. It's a silent O(n) regression.                                                                                                                                  |
| What is false sharing?                              | Two threads writing different variables on the same 64-byte cache line, causing coherence ping-pong. Fix with `alignas(64)`.                                                                                                         |
| `memory_order_relaxed`?                             | Atomicity only, no ordering. Safe for independent counters; unsafe for anything guarding other data.                                                                                                                                 |
| Why is UB dangerous?                                | The compiler assumes it can't happen and optimizes accordingly — it deletes null checks and rewrites loops. Not just "garbage values."                                                                                               |
| Signed vs unsigned overflow?                        | Unsigned wraps (defined). Signed is UB.                                                                                                                                                                                              |
| `string_view` pitfall?                              | Dangling — it doesn't own. Also not guaranteed null-terminated.                                                                                                                                                                      |
| Tools for a memory bug?                             | ASan for UAF/overflow, Valgrind if you can't rebuild, UBSan for UB, TSan for races.                                                                                                                                                  |
| How would you find a p99 regression?                | Histogram, not mean. Then `perf` + flamegraph, check for allocation stalls, rehashes, lock contention, and GC-like batch work.                                                                                                       |
| Difference between the compiler and the linker?     | The compiler sees one translation unit and full type information. The linker sees object files and nothing but symbol names. Every confusing build error comes from that split.                                                      |
| `undefined reference` — what now?                   | Link stage: declared but not defined, or not given to the linker. Check `-l` flags and link order, then `nm -C --defined-only` the library to see if the symbol is really there.                                                     |
| Why is `undefined reference` output so ugly?        | It's a mangled name. `c++filt` or `nm -C` decodes it. Mangling exists because C++ has overloading and the linker has a flat string namespace.                                                                                        |
| What does `extern "C"` do?                          | Disables name mangling, producing a plain C symbol. Needed for C interop, `dlsym`, and any FFI boundary. Costs you overloading.                                                                                                      |
| Static vs shared library?                           | Static is copied into the binary at link time. Shared is resolved at load by the dynamic loader — smaller binary, shared text across processes, but real version-skew risk.                                                          |
| Why does linking a `.a` into a `.so` fail?          | The static library wasn't built with `-fPIC`. A shared library can be mapped anywhere, so it can't contain absolute addresses.                                                                                                       |
| API vs ABI?                                         | API is source-level — break it and code won't compile. ABI is binary-level (layout, vtables, calling convention) — break it and code fails at run time, silently.                                                                    |
| Name three things that break ABI but not API.       | Adding a data member, adding or reordering a virtual function, changing a default argument.                                                                                                                                          |
| Why does PIMPL exist?                               | To freeze a class's binary layout at one pointer, so members can change without breaking ABI for callers you can't recompile.                                                                                                        |
| Loader search order?                                | `RPATH`, then `LD_LIBRARY_PATH`, then `RUNPATH`, then `ld.so.cache`, then the system paths.                                                                                                                                          |
| Downside of `LD_LIBRARY_PATH`?                      | It's environment state, not a property of the binary — inherited by children, invisible in `readelf`, and it silently changes behavior depending on how the app was launched. `-Wl,-rpath,'$ORIGIN/../lib'` is the shippable answer. |
| Why can atomic code work on x86 and break on ARM64? | x86-64 is TSO — strongly ordered. AArch64 is weakly ordered and will reorder loads and stores. Insufficient memory ordering is masked on x86 and exposed on ARM.                                                                     |
| Is `char` signed?                                   | Signed on x86, **unsigned on ARM**. Use `int8_t`/`uint8_t` if it matters.                                                                                                                                                            |
| What's a sysroot?                                   | A copy of the target's headers and libraries, so the cross-compiler doesn't pick up the host's. Getting it wrong is the usual cause of "builds fine, won't start on the device."                                                     |
| Our build is slow — what first?                     | Measure with `-ftime-trace`. Then switch to `lld`/`mold`, add `ccache`, then cut includes. Distribution is last because it's the heaviest.                                                                                           |
| Why does hermeticity matter for a build cache?      | Without it a shared cache is _unsound_, not just less effective — you can serve an artifact built from inputs you can't account for.                                                                                                 |
| Full vs incremental build time?                     | Different problems. Full builds are fixed by caching and distribution; incremental builds are fixed by dependency hygiene. Developer experience is dominated by the incremental number.                                              |

---

## Questions

Ask two or three. They demonstrate you've thought about the actual job.

**On the codebase and craft:**

- How much of the subsystem I'd work in is C versus C++, and what standard are you on? How do you
  approach modernizing incrementally in a codebase this long-lived?
- What does memory management look like at the ONTAP layer — custom allocators and pools, or the
  system allocator? How do you handle fragmentation over a multi-year uptime?
- Are exceptions enabled in the data path, or is it explicit error propagation throughout?

**On performance and reliability:**

- What does the performance workflow look like day to day — is there continuous benchmarking, and
  how do you catch a p99 regression before a customer does?
- What's the debugging story when a customer hits something you can't reproduce? How much tracing
  and observability is built into the product?

**On the work itself:**

- The posting spans several teams. What actually distinguishes the day-to-day between, say, WAFL and
  Protocols?
- What's a problem the team is working on right now that's genuinely hard?
- How does the team use AI-assisted tooling in practice — the posting calls it out explicitly, and
  I'm curious where it's actually landed for systems work.

**On growth:**

- What does ramping up on ONTAP look like for someone strong in C++ but new to storage internals?
  What's the realistic timeline to being useful?
- What separates an engineer who's doing well here from one who's exceptional?

---

## From the Deep Dive

Project-specific and interview framing moved here from the C++ Deep Dive when it was rewritten as
neutral reference pages. Each group links to the page it came from.

### Versions

Deep Dive page: [Versions](../cpp_deep_dive/versions.md)

**The pitch you want to be able to make:** "Modern C++ is about making the correct thing the cheap
thing. Move semantics made returning big objects free, so you stop passing out-parameters. RAII made
cleanup automatic, so you stop leaking. Templates made abstraction free, so you stop paying for a
vtable you don't need. NetApp cares about this because ONTAP is a decades-old C/C++ codebase where
the cost of a leak or a data race isn't a crashed web request — it's a customer's data."

A NetApp-specific framing worth internalizing: **ONTAP is largely C with C++ in newer subsystems.**
Do not walk in assuming everything is C++20. Be ready to say "in a codebase that's C-first, I'd
reach for RAII wrappers around the C handles rather than rewriting the C" — that answer signals
you've worked in real legacy systems, not just greenfield.

### Memory

Deep Dive page: [Memory](../cpp_deep_dive/memory.md)

**Static/global.** Lives for the whole program. Zero-initialized before `main`, dynamically
initialized in an order that is **only defined within a translation unit** — across TUs the order is
unspecified. This is the Static Initialization Order Fiasco, and it is the exact bug you shipped a
fix for on the OTel project. It is one of the highest-value stories you have.

**The mental model to state out loud:** "Stack for scope-bound, heap for lifetime-bound, static for
program-bound. The bugs live at the boundaries — an object whose real lifetime doesn't match the
storage class you gave it."

**The mirror image — the destruction order fiasco** — is the one that bit you: destruction happens
in reverse order of construction, still unspecified across TUs, and now other threads may still be
running.

**Your story, tightened:** "We had a non-deterministic crash that only appeared at shutdown in a
multi-threaded ADAS application. I traced it to static destruction order — the OpenTelemetry
provider objects were global statics being destroyed while worker threads were still emitting their
final spans. My first fix was a Meyers singleton, which was the right instinct for the
_initialization_ problem but doesn't address destruction order at all. So I refactored to a
weak-pointer singleton so every caller holds a strong reference while it's using the provider, and
registered `atexit` cleanup in the accessor to force a deterministic flush. That eliminated the
crashes and became the team's standard pattern for global resources."

**The distinction to make:** "Leak" and "unbounded RSS growth" are different failure modes, and in a
controller that runs for two years, **fragmentation is often the one that actually kills you.**
That's why storage systems use slab allocators and object pools with fixed-size classes — if every
allocation comes from a pool of identically-sized slots, a freed slot always fits the next request
exactly, and fragmentation is bounded by construction.

Mentioning `pmr` is a strong depth signal for a storage role — it's the standard-library answer to
exactly the allocation-control problem NetApp lives with.

**Why a storage system uses `O_DIRECT`:** it has better information than the kernel about what to
cache and evict — it knows which blocks are metadata, which are hot, and what the access pattern
means. Double-caching in both the page cache and the application's buffer cache wastes memory and
adds a copy.

**Useful to name:** `fsync` vs `fdatasync` (durability of data + metadata vs data only — `fdatasync`
skips the metadata write when only the timestamp changed, saving a seek), and the general durability
question — _when_ is a write actually on stable media? A `write()` that returns has only reached the
page cache; the drive may also have it in a volatile write cache. That gap is the heart of
NVRAM-backed write caching in storage arrays: acknowledge the write once it's in battery-backed
memory, and destage to disk later.

### Storage

Why NetApp cares about C++ specifically, and what to emphasize:

- **Data integrity is non-negotiable.** A dangling pointer in a web service is a 500. In ONTAP it's
  corrupted customer data. This is why RAII, ownership clarity, and const-correctness are not style
  preferences there.
- **Long uptime.** Controllers run for years. Leaks and fragmentation that are invisible in a
  request-scoped service are fatal here.
- **Latency tails matter more than averages.** Enterprise storage sells on p99. This makes unbounded
  operations — rehashing, `vector` reallocation, allocator locks, exception unwinding — actively
  dangerous in the data path.
- **Concurrency at scale.** A filesystem is inherently concurrent: many clients, many I/Os in
  flight, shared metadata. Lock granularity is the whole ballgame.
- **Debugging without a debugger.** You often get a core dump, a log, and a customer who can't
  reproduce. Hence the premium on tracing, observability, and defensive design — which is _exactly_
  what your OTel work was.

### Ownership

Deep Dive page: [Ownership](../cpp_deep_dive/ownership.md)

**Why this is the answer to half of all systems questions.** "How do you make sure the mutex is
released if the function throws?" RAII. "How do you avoid leaking the buffer on an error path?"
RAII. "How would you wrap this C API safely?" RAII.

**The NetApp framing:** in a C-heavy codebase like ONTAP, you don't get to rewrite everything — but
you _can_ wrap the C handles (buffers, locks, contexts) in thin RAII types at the C++ boundary,
which is how you get leak-safety incrementally without a rewrite.

Note the size difference: a function-pointer deleter makes the `unique_ptr` 16 bytes, because the
pointer to `fclose` is runtime data that has to be stored alongside the object pointer. A stateless
functor deleter carries no data — the type itself encodes what to do — so EBO applies and the
`unique_ptr` stays at 8. Mentioning that is a nice depth signal.

**This is your default smart pointer.** If you're reaching for `shared_ptr`, first ask whether the
ownership is genuinely shared or whether you just haven't thought about it.

> "Is `shared_ptr` thread-safe?"

The question is underspecified, and saying so is the point. There are three separate things that
could be shared, and the answer differs for each:

That three-part answer is much stronger than "the ref count is atomic."

**3. The pattern you actually shipped — safe teardown.** A `weak_ptr`-based singleton lets the
accessor hand out ownership while the singleton itself doesn't force the object to outlive the
program. This is how you fixed the OTel shutdown crash: consumers `lock()` the telemetry provider;
if teardown has begun, the `lock()` fails and they no-op instead of touching a destroyed global.

**The interview line:** "Rule of 0 is the goal — I structure classes so ownership lives in members
that already handle it. I only descend to Rule of 5 when I'm writing the resource wrapper itself,
and then I write all five explicitly, mark the moves `noexcept`, and `= delete` anything that
shouldn't exist."

### Value Semantics

Deep Dive page: [Value Semantics](../cpp_deep_dive/value-semantics.md)

Say the taxonomy if pushed; lead with the two-question framing rather than the vocabulary, because
the vocabulary alone sounds memorized.

That's the whole implementation. Being able to write it from memory is a strong signal.

general one. `std::string` with SSO may not be empty. Say "valid but unspecified — I don't rely on
it beyond destroy-or-reassign."

### Move constructor pattern

```cpp
Buffer(Buffer&& other) noexcept
    : data_(std::exchange(other.data_, nullptr)),
      size_(std::exchange(other.size_, 0)) {}

Buffer& operator=(Buffer&& other) noexcept {
    if (this != &other) {
        delete[] data_;                              // release ours
        data_ = std::exchange(other.data_, nullptr); // steal theirs
        size_ = std::exchange(other.size_, 0);
    }
    return *this;
}
```

`std::exchange(a, b)` sets `a = b` and returns `a`'s old value — it's the steal-and-clear operation
in one expression. Note the two things every move operation must do: take the resource, _and_ clear
the source. Skip the second and both objects free the same pointer.

The `if (this != &other)` guard in the assignment operator matters because `v = std::move(v)` is
legal code that a generic algorithm can produce. Without the guard you'd delete your own buffer and
then steal the null pointer you just left behind.

### Why `noexcept` matters here — the killer follow-up

`std::vector` grows by allocating a bigger buffer and relocating elements. Suppose it's moved 500 of
1000 elements into the new buffer and element 501's move constructor throws. The old buffer is now
half-gutted and the new buffer is half-built — there is no way to get back to a valid state, because
undoing the moves would require moving them back, which could throw again.

So the vector refuses to take that risk. If your move constructor is not marked `noexcept`, it
**falls back to copying** — copies leave the source intact, so a throw halfway through just means
destroying the partial new buffer and keeping the original.

A non-`noexcept` move constructor silently makes every vector reallocation O(n) copies instead of
O(n) pointer steals. Mark move operations `noexcept`. (The mechanism is `std::move_if_noexcept`,
which the container calls internally to decide.)

### Where moves silently don't happen

```cpp
std::vector<int> f() {
    std::vector<int> v(1000);
    return v;        // NOT a move — this is NRVO/copy elision, even better
}

const std::string s = "...";
take(std::move(s)); // std::move on a const lvalue yields const&& —
                    // binds to const&, so this COPIES. Silent perf bug.
```

The second one is worth understanding rather than memorizing: a move constructor takes `T&&`, not
`const T&&`, because it needs to _modify_ the source in order to clear it. A `const` object can't be
modified, so the move constructor isn't viable, and overload resolution quietly falls back to the
copy constructor. `const` and movable are fundamentally incompatible.

### Why `noexcept` matters here — the killer follow-up

### Critical distinction interviewers probe

`std::vector<T>&&` in a template is **not** a forwarding reference — `T` there isn't being deduced
at the top level, the parameter type is a concrete rvalue reference to a vector. Only the bare
pattern `T&&` with `T` deduced qualifies. Same for `auto&&`.

The test is mechanical: is the deduced parameter _exactly_ `T&&`, with nothing wrapped around it and
no `const`? `const T&&` doesn't qualify either.

One-liner: _move says "I'm done with this." Forward says "do whatever the caller would have done."_

**The rule to state:** "Never `std::move` a local on return. It pessimizes — it turns a free elision
into a real move, and it blocks the compiler from doing the better thing."

This is _extremely_ relevant to storage code, where you're constantly passing buffers around and the
alternative is `(void* ptr, size_t len)` pairs that lose all type safety — nothing stops a caller
from passing a length that doesn't match the pointer, and nothing stops the callee from writing to a
buffer that was meant to be read-only. `span` carries both facts in the type.

### Objects

Deep Dive page: [Objects](../cpp_deep_dive/objects.md)

**How you'd say it:** "A virtual call is a load-load-call. The indirection is a few cycles; the real
cost is that it's an optimization barrier — the compiler can't inline through it. That was one
reason CRTP suited the ORM's row-mapping path, though it wasn't the deciding one — I needed the
derived type visible at compile time so I could reflect over its fields, and virtual dispatch erases
exactly that."

That second
half is the answer that separates candidates: it shows you know the vptr has a cost and that "always
make destructors virtual" is cargo cult.

Object layout matters enormously in storage code, where you're mapping structs onto on-disk formats
and wire protocols.

This matters
when you're serializing structs to disk or across a wire — and it's exactly the property your Python
schema-generator had to preserve when emitting C++ structs from C# models.

**Your bridge story lives next door to this topic, so keep the distinction clean.** Padding is what
makes a struct's layout depend on alignment — that's why the generated headers had to be
memory-aligned and verified with `static_assert`s on `sizeof` and `offsetof`. But the ordering
problem the generator actually solved was between _types_, not between members: a struct containing
another struct by value needs that type **complete** first, and the source schemas came in arbitrary
order. See [Incomplete](../cpp_deep_dive/objects.md#complete-and-incomplete-types). Don't conflate the two in an interview — an interviewer who
knows layout will notice.

**Where this bit you.** This is the actual core problem in your
[schema bridge](../projects/cpp/bridge.md#bridge). The generated models composed by value, so
every referenced type had to appear _above_ the type using it. The source schemas had no such
ordering — Swagger's `components/schemas` is an unordered map — so emitting them in source order
produced headers that failed to compile with "field has incomplete type." The fix was a
**topological sort over the type reference graph**: build an adjacency list, DFS, emit each type
only after everything it contains, and fail the build with the cycle path if the graph isn't
acyclic. Which it must be — a by-value cycle would mean a struct whose size includes its own size,
i.e. infinite, so C++ forbids it outright. (A cycle through _pointers_ is fine, since a pointer's
size doesn't depend on the pointee — which is the same rule from the top of this section, seen from
the other end.)

That's a genuine algorithms problem falling out of a genuine language rule, which is why it's a good
story. Keep it distinct from padding: padding is about member order _within_ a struct; this is about
definition order _between_ structs.

### Where this matters concretely in storage

The pattern in all of these: once memory is being read by something other than the CPU's normal load
path — a DMA engine, a disk controller — that device's alignment rules apply, and they're stricter.

- **Direct I/O (`O_DIRECT`)** requires buffers aligned to the block size (typically 512B or 4KB) —
  the kernel DMAs straight from your buffer, so the hardware's alignment rules apply rather than the
  CPU's. Getting this wrong is an `EINVAL`, not a slowdown, which at least fails loudly.
- **DMA** to a device generally requires page or sector alignment.
- **On-disk structures** must be laid out so no field straddles a sector boundary — a sector is the
  atomic unit the drive writes, so a field spanning two sectors can be half-updated by a power
  failure.
- **Cache-line alignment** (`alignas(64)`) to avoid false sharing — see [Sharing](../cpp_deep_dive/concurrency.md#9-false-sharing).

This is precisely the class of problem your C#→C++ schema generator was solving: making the layout
contract explicit and machine-generated rather than hand-maintained on both sides, so the two
languages' views of a message can't drift.

**Why you chose it for the ORM — lead with reflection, not performance.**

The base class needed the derived type **as a type**, because that's the only way to reflect over
its fields at compile time. Boost Describe's `describe_members<T, ...>` is a template — it takes the
concrete type as a parameter — and Mp11's `mp_for_each` iterates the resulting member list, giving
you each field's name and type at build time. That's what generated the column list and the SQL and
`static_assert`ed that every field type had a valid SQL mapping.

Virtual inheritance cannot do this, and not by a small margin: a virtual base only ever sees
`Base*`, so the derived type is erased — that _is_ dynamic dispatch. No type, no reflection, no
field enumeration, no compile-time schema checking. The alternative wasn't "virtual, a bit slower";
it was every entity hand-writing its own column list, which is the duplication that causes schema
drift in the first place.

```cpp
template<typename Derived>
class Entity {
    using Members = boost::describe::describe_members<Derived, boost::describe::mod_public>;
    //                                                ^^^^^^^ needs a concrete type — CRTP supplies it
};
```

**The side wins — mention them second, never first:**

- **Static polymorphism with no vtable overhead** — the mapping layer sits in a hot path; I didn't
  want an indirection per field.
- **Better inlining** — the compiler sees the concrete `serialize()` and can inline and
  constant-fold the whole mapping.
- **Compile-time enforcement of the interface** — if a record type forgets `table_name()`, it's a
  build error, not a runtime SQL failure in the field.
- **Predictable performance** — no allocation, no indirection, no surprise.

**Why the ordering matters.** Lead with "no vtable overhead" and a sharp interviewer hears a
micro-optimization and asks whether you measured it — now you're defending a benchmark instead of a
design. Lead with reflection and the answer is that virtual couldn't express the design at all.

**The honest tradeoffs to volunteer** (interviewers respect this): compile times go up, error
messages get worse pre-Concepts, you can't store heterogeneous entities in one container, and the
"magic" has a learning cost for the team. Your answer to that last one was rigorous GoogleTest
coverage — proving the abstraction was a safety net, not a liability.

### Keywords

Deep Dive page: [Keywords](../cpp_deep_dive/keywords.md)

**Why const-correctness matters at NetApp:** in a concurrent system, `const` is a documented promise
about thread safety. A `const` method can be assumed not to mutate shared state, which means it may
be safe to call concurrently — the standard library formalizes this by requiring that concurrent
`const` operations on library types are race-free. Get const wrong (or reach for `mutable` without
locking) and you've silently created a data race. That's why it's not a style preference in storage
code.

One keyword, four unrelated meanings — a historical accident from C, where the committee reused an
existing keyword rather than adding new ones. Interviewers ask this to see if you know all four.

**The clean answer:** "`const` controls mutability; `static` controls **lifetime and visibility**.
At file scope it means internal linkage, on a local it means program-lifetime with lazy thread-safe
init, and on a class member it means class-level rather than instance-level."

### Templates

Deep Dive page: [Templates](../cpp_deep_dive/templates.md)

**The mandatory closing line:** "In C++20 I wouldn't write this — I'd write a concept. Same
semantics, dramatically better error messages, and it reads like the requirement instead of like a
puzzle."

**Standard concepts you should name-drop:** `std::integral`, `std::floating_point`, `std::same_as`,
`std::convertible_to`, `std::invocable`, `std::ranges::range`.

**The connection back to your work:** "The CRTP ORM enforced its interface through `static_cast`
failures, which worked but produced ugly errors. If I were rebuilding it on a C++20 toolchain, I'd
express the entity contract as a concept — same zero-overhead static dispatch, but the failure
message tells a junior engineer exactly which method they forgot."

Worth mentioning when you tell the
OTel story; see [Fiasco](../cpp_deep_dive/memory.md#the-static-initialization-order-problem).

It's a great thing to show an interviewer: it's how you make "you may only memcpy this to disk if
it's safe to memcpy" a compiler-enforced rule instead of a comment. Same spirit as your compile-time
ORM.

### Containers

Deep Dive page: [Containers](../cpp_deep_dive/containers.md)

Use `std::vector<char>`, `std::vector<uint8_t>`, or `std::bitset`. Interviewers love this one; it's
the standard's most famous mistake.

2. **You need predictable latency.** This is the systems answer. `unordered_map` amortizes O(1) by
   occasionally **rehashing** — allocating a bigger bucket array and reinserting every element,
   which is an unbounded allocation plus a full traversal. That's the same amortization trick as
   vector growth, and it has the same downside: the average is great, one individual insert is
   terrible. In a storage controller with a p99 latency target, that stall is a tail-latency spike
   you cannot explain to a customer. `map` has no such cliff — every operation is O(log n), full
   stop.

**Worth mentioning:** kernels and storage systems use **intrusive linked lists** (the node pointers
live _inside_ the element, e.g. Linux's `list_head`) precisely to avoid the extra allocation and
indirection of `std::list` — the element and its link fields are one object in one cache line, and
an element can be on several lists at once without any extra allocation. ONTAP-style code is full of
these.

The reason this is an interview favorite is that invalidation bugs are silent. The freed memory
usually still holds the old value, so the code appears to work until the allocator reuses it — often
only under load, in production.

For systems work the smoothness matters as much as the total: an average that's fine but a p99
that's terrible is exactly the tail-latency problem storage controllers are judged on.

Mixing these up is a common source of bugs, and it's a favorite quick check in interviews.

The mental model: **`reserve` buys the parking lot, `resize` parks the cars.**

**Terms to use:** temporal locality (reuse the same data soon), spatial locality (use nearby data
soon), TLB pressure (the cache of virtual→physical address translations; huge pages help when your
working set is large), cache line (64 bytes on x86).

### Concurrency

Deep Dive page: [Concurrency](../cpp_deep_dive/concurrency.md)

Mention TSan by
name — candidates who've actually debugged concurrency do.

Say this — it shows you've measured rather
than assumed.

This is exactly how concurrent hash maps in storage systems work.

Getting these distinctions crisp is a
common interview checkpoint.

**The clean summary for the "explain the difference" question:**

> "`lock_guard` is the minimal RAII lock — acquire on construct, release on destruct, nothing else.
> `unique_lock` adds flexibility: you can defer, unlock early, move it, or time out, and it's what
> condition variables require because they need to unlock while waiting. `scoped_lock` is C++17's
> default — it does what `lock_guard` does for one mutex, but for multiple mutexes it uses a
> deadlock-avoidance algorithm rather than locking them in the order I wrote them. These days I
> reach for `scoped_lock` unless I need `unique_lock`'s flexibility."

canonical example, and it's a great thing to mention because it converts a latent deadlock — which
might only occur one run in a million, in production — into a loud, immediate assertion during
testing.

**The honest interview answer:** "I default to `seq_cst`. It's the only ordering where the code
means what it looks like it means. I'd move to acquire/release only in a measured hot path, and I'd
want the reasoning written down in a comment because the next person to read it won't reconstruct
it."

**`volatile` does not help with threading. Ever.** This is a stock interview question and the wrong
answer is disqualifying.

**The correct answer:** "`volatile` prevents the _compiler_ from optimizing away accesses. It says
nothing about atomicity, and nothing about the _hardware's_ reordering or store buffers. For
inter-thread communication you need `std::atomic`, which gives you both atomicity and a specified
memory ordering. `volatile` is for MMIO and `sig_atomic_t`, not concurrency. Java's `volatile` means
something completely different, which is where the confusion comes from."

**RCU (Read-Copy-Update)** is worth naming for a storage interview: readers are completely
uninstrumented (zero cost — no atomics, no barriers on the read path), writers copy-modify-publish,
and reclamation waits for a **grace period** until all pre-existing readers have finished. It's the
dominant pattern in the Linux kernel for read-mostly data structures, and the same idea underlies
how copy-on-write filesystems (like WAFL) let readers proceed without blocking on writers — never
mutate in place, write a new version and atomically flip a pointer to it.

**The judgment answer:** "I'd reach for lock-free only where profiling shows lock contention is the
bottleneck and the data structure is simple — an SPSC ring buffer, a counter, a free list. For
anything with multi-word invariants, a well-designed fine-grained locking scheme is usually faster
to get correct and easier to maintain, and the performance difference is often smaller than people
expect once you account for cache-line contention on the atomics."

For a storage data path you'd go further: pin threads to
cores (so their data stays in that core's cache), use per-core run queues to avoid contention on a
single shared queue, and consider work stealing for load balance.

**This is exactly the bug you hit and fixed on OTel.** Have the fix ready:

The other half of your fix: registering `atexit()` handlers in the accessor to force a controlled,
ordered flush-and-teardown rather than relying on static destruction order.

Volunteering this tradeoff shows engineering judgment, not just
knowledge.

This is exactly what you'd do in
a storage controller, where a global "IOPS" counter would otherwise be a scalability wall — every
I/O on every core hammering one cache line.

### Errors

Deep Dive page: [Errors](../cpp_deep_dive/errors.md)

### Why storage/kernel code often disables exceptions (`-fno-exceptions`)

- Unbounded, unpredictable latency in the data path — a p99 killer, since unwind time depends on
  stack depth and table size.
- The unwinder's global lock hurts under concurrency: many threads erroring at once serialize.
- Binary size matters in constrained environments.
- Error paths become invisible in the source, which hurts auditability in code that must never lose
  data. If you're reviewing a write path, "which lines can fail" should be readable.

**The answer to give:** "I use exceptions for genuinely exceptional, unrecoverable conditions and
for constructor failure — where there's no other way to report. For _expected_ failures like 'block
not found' or 'timed out', I return an explicit type: `std::optional`, `std::expected`, or a
LEAF-style error carrying context. In a storage data path I'd expect exceptions to be off entirely,
and I'd design around explicit error propagation."

**Boost.LEAF** — lightweight error augmentation framework. You used this, so be ready to defend the
choice.

**Your framing, from the Beast/REST work:** "When exposing internal state and control to other
systems over REST with Boost.Beast, the failure modes were varied — input validation, network,
timing, downstream state. A bare error code told me _that_ something failed but not _which layer_,
and in a complex test environment that distinction is the entire debugging cost. LEAF let each layer
attach its context without allocating or paying for unwinding, so by the time an error reached the
handler I could tell immediately whether it was a client problem, a transport problem, or a state
problem."

**Where it fits storage code:** protocol message dispatch (an NFS op is one of a fixed set), state
machines (a connection is Idle | Handshaking | Active | Draining), and parsed configuration values.

### Compiler

Deep Dive page: [Compiler](../cpp_deep_dive/compiler.md)

**Your toolkit answer:**

- `-fsanitize=address` — ASan: use-after-free, buffer overflow, leaks.
- `-fsanitize=undefined` — UBSan: signed overflow, misaligned access, bad shifts.
- `-fsanitize=thread` — TSan: data races.
- `-D_GLIBCXX_ASSERTIONS` — bounds-checked STL in debug.
- `-Wall -Wextra -Werror`, plus clang-tidy and static analysis in CI.
- Valgrind for when you can't rebuild.

Being able to name the sanitizers _and say which one catches which class of bug_ is a strong
practical signal. Worth adding: ASan and TSan can't be combined (they instrument the same things
differently), so a real CI matrix runs separate builds.

**The methodology, stated as a process** (this is what interviewers are actually testing):

**Key numbers worth quoting:** IPC below ~1.0 suggests a memory-bound workload. An L3 miss rate
above a few percent of loads is worth investigating. Context switches in the thousands per second
per core suggests lock contention.

**A strong closing line:** "I always look at the distribution, not the mean. In storage the mean is
nearly meaningless — customers experience the tail, and a p99 regression is what generates the
support case."

**Your systematic approach** — worth having as a rehearsed narrative, because "how do you debug a
hard problem" is a guaranteed question:

1. **Reproduce, and shrink the repro.** The smaller the trigger, the faster every subsequent step.
2. **Read the evidence before forming a theory.** Core dump, logs, `dmesg`, the actual error — not
   the summary someone gave you.
3. **Form a falsifiable hypothesis.** "I think X, and if X is true then Y should be observable."
4. **Bisect.** In time (`git bisect`), in code (disable half), or in configuration.
5. **Instrument.** If it isn't observable, make it observable — and _keep_ the instrumentation. This
   is your OTel thesis.
6. **Fix the root cause, not the symptom.** Then add a regression test.

| Only in production              | Tracing and structured logging — the OTel argument                       |
| Only at shutdown                | **Static destruction order.** This is your story.                        |
| Only under load                 | Contention, queue depth, or a resource limit (fd, memory)                |

**Debugging concurrency specifically** — the honest answer: "Concurrency bugs frequently don't
survive being observed, so I lean less on breakpoints and more on (a) TSan, (b) tracing with
timestamps and thread IDs so I can reconstruct the interleaving after the fact, and (c) reasoning
about the code's happens-before edges directly. On the OTel shutdown crash, the debugger was useless
because attaching changed the timing — I found it by reasoning about which objects could still be
alive at that point in the exit sequence, then confirming with instrumented destructors."

The three costs that dominate systems C++: **cache misses, allocations, and synchronization.**
Almost every real optimization you'll describe is removing one of those three.

---

_End of C++ Deep Dive._
