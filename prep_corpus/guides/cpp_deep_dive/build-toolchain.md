# Part II — Build & Toolchain

> Part of the [C++ Deep Dive](README.md) · Overview: [Build & Toolchain](../cpp_overview/build-toolchain.md)

---

## Pipeline

### Why there are stages at all

C++ inherited a model from C designed when a machine couldn't hold a whole program in memory:
compile each source file **separately** into an object file, then stitch them together at the end.
That separation is why C++ has headers (each file needs to be told about things defined elsewhere),
why it has linkers, and why a whole category of errors exists that other languages don't have.

**How a C++ program becomes a binary.** Four stages, and knowing which one an error came from is
half of debugging build problems.

| Stage          | Tool                           | Input → Output                                        | What it knows                                                                                           |
| -------------- | ------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Preprocess** | `cpp`                          | `.cpp` + headers → one big translation unit           | Nothing about C++. Pure text: `#include` pastes files in, `#define` substitutes, `#if` deletes branches |
| **Compile**    | `g++ -c` / `clang++ -c`        | translation unit → assembly → object file (`.o`)      | One TU only. Knows types, templates, overloads. **Does not know other TUs exist**                       |
| **Assemble**   | `as`                           | assembly → machine code in the `.o`                   | Instruction encoding for the target architecture                                                        |
| **Link**       | `ld` (via the compiler driver) | `.o` files + libraries → executable or shared library | Only **symbols**. Has no idea what a template or a class is                                             |

**The single most useful consequence:** the compiler and the linker see completely different worlds.
The compiler sees one translation unit and full type information. The linker sees a pile of object
files and nothing but symbol names and addresses. **Every confusing build error comes from that
split.**

```
error: no matching function for call to 'foo(int)'     → compile stage. It's a type/overload problem.
undefined reference to `foo(int)'                      → link stage. The declaration existed, the definition didn't.
multiple definition of `foo(int)'                      → link stage. Two TUs both emitted it.
```

**A translation unit** is one `.cpp` after preprocessing — including every header it pulled in,
transitively. This is why a header change recompiles everything that includes it, and why a 50-line
`.cpp` that includes `<vector>` and `<string>` can preprocess to tens of thousands of lines.

**What each stage costs, which matters for build times:**

- Preprocessing is cheap but _multiplicative_ — the same header is re-read and re-parsed once per TU
  that includes it. That's the core reason C++ builds are slow.
- Compilation is where most time goes: parsing, template instantiation, and optimization.
  Template-heavy code pays here.
- Linking is serial and memory-hungry, and often the bottleneck at the end of a build. `lld` and
  `mold` exist because `ld` is slow; switching linkers is frequently the cheapest build-time win
  available.

**Useful flags to know by name:** `-E` (stop after preprocessing — the way to debug a macro), `-S`
(stop after assembly), `-c` (stop after the object file), `-g` (debug info), `-O0/-O2/-O3/-Os`,
`-flto` (defer optimization to link time so it can cross TU boundaries), `-fno-omit-frame-pointer`
(keep profiling usable).

---

## Symbols

### The linker's very small world

Because each translation unit is compiled in isolation, an object file that calls `foo` contains a
call instruction with a _hole_ where the address should be, plus a note saying "fill this with
whatever `foo` turns out to be." The linker's whole job is filling those holes. It never sees types,
templates, or classes — only names and addresses.

**A symbol is a name the linker can see.** Functions and variables with external linkage produce
symbols in the object file's symbol table. The linker's entire job is matching _undefined_ symbols
in one object file to _defined_ symbols in another.

**Name mangling.** C++ has overloading, namespaces, and templates; the linker has a flat namespace
of strings. So the compiler encodes the full signature into the symbol name:

```cpp
void write(int);              // _Z5writei
void write(double);           // _Z5writed
namespace fs { void write(int); }  // _ZN2fs5writeEi
```

Decode with `c++filt`, or `nm -C`. **This is why `undefined reference` errors are so ugly** — you're
reading a mangled name. It's also the mechanism behind link-time type safety: a signature mismatch
between the declaration you compiled against and the definition that exists becomes a _different
symbol_, so it fails at link rather than corrupting the stack at run time.

**`extern "C"`** disables mangling for a declaration, producing a plain C symbol name. Needed
whenever C++ has to interoperate with C, with `dlsym`, or with any FFI boundary — and the reason
system headers are wrapped in `#ifdef __cplusplus extern "C" {`. The cost: no overloading, since
there's only one possible symbol name.

**The two link errors, and how to actually diagnose each:**

**`undefined reference to X`** — someone declared it, nobody defined it, or the definition wasn't
given to the linker. In order of likelihood: you forgot to link the library (`-lfoo`); you linked it
in the wrong order (traditional static linking is order-sensitive, left to right — a library must
appear _after_ the object that needs it); you declared a member function and never defined it; you
defined it with a subtly different signature, so the mangled names differ; or it's a template you
defined in a `.cpp` and instantiated elsewhere. Reach for
`nm -C --defined-only libfoo.a | grep name` to check whether the symbol is actually in there, and
`nm -C --undefined-only your.o` to see what it's asking for.

**`multiple definition of X`** — two TUs both emitted a definition. Classic causes: a non-`inline`
function defined in a header; a global variable defined rather than declared `extern` in a header; a
missing include guard.

**The One Definition Rule (ODR), stated properly.** Every entity may have exactly one definition
across the whole program — _except_ that `inline` functions, templates, and class definitions may be
repeated in multiple TUs, provided every repetition is **token-for-token identical**. Violating that
second part is the dangerous case: it compiles, it links, and the linker silently keeps one
arbitrary copy. **The classic real-world ODR bug** is compiling two TUs with different `-D` flags or
different `-O` levels such that a header's inline function differs between them — you get a program
where the same function has two bodies and which one you get depends on link order. `-Wodr` with LTO
catches some of this; discipline catches the rest.

**Linkage, precisely:**

|              | Meaning                     | How                                                           |
| ------------ | --------------------------- | ------------------------------------------------------------- |
| **External** | Symbol visible to other TUs | Default for non-`const` globals and functions                 |
| **Internal** | Symbol confined to this TU  | `static` at file scope, or an anonymous namespace (preferred) |
| **None**     | No symbol at all            | Locals                                                        |

**Symbol visibility in shared libraries** is a separate axis and a real engineering concern: by
default on Linux every external symbol is exported from a `.so`, which bloats the dynamic symbol
table, slows load-time relocation, and leaks implementation details. `-fvisibility=hidden` plus
explicit `__attribute__((visibility("default")))` on your public API is the disciplined setup.
Windows made you do this from the start with `__declspec(dllexport)`.

---

## Libraries

### The one question: when does the code get bound in?

A library is reusable compiled code. The only real decision is _when_ it becomes part of your
running program — at link time, or at load time. Every difference in the table below falls out of
that one choice.

**Static libraries (`.a`)** are just an archive of `.o` files — `ar` is barely more than `tar`. At
link time the linker pulls in _only the object files that resolve a needed symbol_ and copies that
code into your binary. Nothing remains at run time.

**Shared libraries (`.so`)** are loaded at run time by the dynamic loader. Your binary records a
_dependency_ on the library plus the list of symbols it needs; resolution happens at load.

|                             | Static (`.a`)                           | Shared (`.so`)                                              |
| --------------------------- | --------------------------------------- | ----------------------------------------------------------- |
| **Binary size**             | Larger — code is copied in              | Smaller                                                     |
| **Memory across processes** | Each process has its own copy           | Text segment shared across all processes mapping it         |
| **Deployment**              | Self-contained, one file                | Must ship or find the library at run time                   |
| **Update a dependency**     | Relink and redeploy the whole binary    | Drop in a new `.so`, no relink                              |
| **Startup cost**            | None                                    | Relocation and symbol binding at load                       |
| **Call cost**               | Direct call                             | Indirect via PLT/GOT — usually negligible, occasionally not |
| **Version skew risk**       | None at run time                        | **Real.** This is where "works on my machine" lives         |
| **Cross-TU optimization**   | LTO can inline across the whole program | Optimizer stops at the library boundary                     |

**PIC — Position Independent Code.** A shared library can be mapped at any address, so its code
cannot contain absolute addresses. `-fPIC` makes the compiler emit position-independent code,
reaching globals indirectly through the **GOT** (Global Offset Table) and calling functions through
the **PLT** (Procedure Linkage Table). Consequences worth knowing: it costs a small amount of
performance and a register; **you cannot link a non-PIC `.a` into a `.so`** (a very common build
error — the fix is rebuilding the static library with `-fPIC`); and `-fPIE` is the executable
equivalent, now the default on most distributions because it enables ASLR.

**Lazy binding.** By default a function symbol in a shared library isn't resolved until the first
call — the PLT entry initially jumps to the resolver. This is why a missing symbol in a `.so` can
crash you _minutes into a run_ rather than at startup. `LD_BIND_NOW=1` (or linking with `-z now`)
forces eager binding, which is what you want in anything safety-adjacent: **fail at startup, not
mid-operation.** Worth knowing for the DHU context specifically.

**`dlopen` / `dlsym`** load a library explicitly at run time — the mechanism behind plugin
architectures. The wrinkle: `dlsym` takes a string, so you need `extern "C"` symbols, and the
standard pattern is a C-linkage factory function returning a pointer to an abstract base class. Also
`dlclose` is a well-known source of pain — unloading a library whose objects are still alive, or
whose static destructors run at the wrong moment, connects straight back to [Fiasco](memory.md#the-static-initialization-order-problem).

**Which to prefer, and the honest answer:** static linking for anything you deploy as a unit,
especially embedded — it eliminates an entire failure class. Shared for genuinely shared system
libraries, for plugin boundaries, and when you need to patch a dependency without redeploying. Note
that `libstdc++` and `glibc` are shared by default, which is exactly the version-skew hazard that
bites on embedded targets.

---

## Loader

**What happens between `execve` and `main`.** For a dynamically linked binary the kernel loads the
ELF image, sees the `PT_INTERP` segment naming the dynamic loader (`/lib/ld-linux-aarch64.so.1`),
and hands control to _the loader_, not your code. The loader then resolves every `DT_NEEDED`
dependency transitively, maps each library, applies relocations, runs initializers, and only then
calls `main`.

**The search order the loader uses — memorize this, it's the whole debugging story:**

1. **`DT_RPATH`** — a path list baked into the binary at link time (legacy, but takes precedence)
2. **`LD_LIBRARY_PATH`** — the environment variable
3. **`DT_RUNPATH`** — the modern baked-in path (`-Wl,--enable-new-dtags`); **searched after
   `LD_LIBRARY_PATH`, which is the key difference from `RPATH`**
4. **`/etc/ld.so.cache`** — the `ldconfig` cache of system library locations
5. **`/lib`, `/usr/lib`** and the architecture-specific variants

**`ldd <binary>`** shows what will be loaded and from where. `LD_DEBUG=libs,files ./app` shows the
loader's actual search, in order, including every path it tried and failed — this is the tool for
"it can't find a library that's obviously right there." `readelf -d <binary>` shows `DT_NEEDED`,
`RPATH`, and `RUNPATH` entries. On a stripped embedded system where `ldd` may not exist,
`LD_TRACE_LOADED_OBJECTS=1 ./app` does the same job.

### `LD_LIBRARY_PATH` as dependency isolation — the DHU story

**This is your story, and it's a good one.** The situation: getting an application running on the
**DHU — an embedded ARM compute unit** — where the constraints are the ones that make this problem
interesting.

**Why the obvious approach doesn't work on embedded.** Normally you'd install dependencies into
`/usr/lib` and let the loader find them. On an embedded target you frequently can't:

- The **root filesystem is read-only** (or an immutable, signed, OTA-updated image), so you cannot
  install anything into system paths.
- The system libraries are whatever the **board support package** shipped, pinned to that vendor
  image. You don't get to upgrade `glibc` because your application wants a newer one.
- Multiple applications share the device, and two of them may need **different versions of the same
  library**. Installing either one globally breaks the other.
- Changing the base image is a heavyweight process — a release, a validation cycle, potentially a
  safety review. Shipping a library alongside your application is not.

**What `LD_LIBRARY_PATH` buys you.** You ship the application's dependencies in a private directory
next to the binary and point the loader at it before launch:

```sh
#!/bin/sh
# wrapper script deployed alongside the app
APP_DIR=$(dirname "$(readlink -f "$0")")
export LD_LIBRARY_PATH="$APP_DIR/lib:$LD_LIBRARY_PATH"
exec "$APP_DIR/bin/app" "$@"
```

Because `LD_LIBRARY_PATH` is consulted **before** the system paths and the `ld.so.cache`, the
bundled copies win. The application becomes a **self-contained deployment unit** — its own private
view of its dependencies — without touching the base image, and without requiring root. Each
application on the device gets its own directory and its own versions, so they stop fighting. That's
the isolation: **per-application dependency scoping enforced at load time rather than at install
time.**

**The framing that makes this sound like engineering rather than a hack:** you converted a _global,
mutable, shared_ resource — the system library set — into a _per-application, immutable, versioned_
one. That's the same instinct as a container image, a Python virtualenv, or `node_modules`,
implemented with the one mechanism available on a locked-down embedded target.

**Now the honest part, and say it before they ask, because it's what a senior engineer will probe.**
`LD_LIBRARY_PATH` is a blunt instrument:

- **It's inherited by every child process.** Anything your app spawns — a shell, a helper binary, a
  system tool — gets your library path too, and may pick up your bundled library instead of the
  system one it expected. This is the failure mode people actually hit.
- **It's environment state, not a property of the binary.** Launch the app any other way — a
  different init script, a debugger, someone running it manually over SSH, a systemd unit that
  doesn't inherit the environment — and it silently uses different libraries. The bug reproduces
  only under one launch path.
- **It can shadow system libraries you didn't intend to override.** A bundled `libssl` intended for
  your app now also serves anything else that loads through your environment.
- **It's a debugging trap** precisely because it's invisible in the binary — `readelf` won't show
  it.

**What you'd do instead, and this is the answer that lands:** bake the path into the binary at link
time with `$ORIGIN`:

```
g++ ... -Wl,-rpath,'$ORIGIN/../lib' -Wl,--enable-new-dtags
```

`$ORIGIN` is expanded by the loader to the directory containing the binary, so the executable
becomes **self-locating**: relocatable, no wrapper script, no environment variable, no inheritance
by children, and the dependency layout is visible in `readelf -d`. `--enable-new-dtags` emits
`RUNPATH` rather than `RPATH`, which preserves the ability to override with `LD_LIBRARY_PATH` for
debugging while making the default correct. **The one-line version: `LD_LIBRARY_PATH` was the right
tool to get it working and prove the isolation model; `RPATH` with `$ORIGIN` is the right tool to
ship it, because it moves the guarantee from the environment into the artifact.**

**Two further options worth naming if the conversation goes deeper:** static linking, which removes
the problem entirely and is often the correct embedded answer where licensing allows; and full
containerization, which is how the same problem is solved on a server but is heavier than many
embedded targets will tolerate.

**Why an interviewer at NetApp cares.** Appliances have exactly this shape — a controlled base
image, long-lived deployments, multiple components with independent release cadences, and a strong
aversion to modifying the platform to accommodate one application. The "make the artifact
self-describing rather than depending on ambient environment state" instinct is directly
transferable, and it's the same reasoning as preferring eager symbol binding in safety-adjacent
code: **push failures to a predictable moment, and make the deployed thing carry its own
guarantees.**

---

## ABI

**API vs ABI.** The **API** is the source-level contract — names, signatures, semantics. Break it
and code fails to _compile_. The **ABI** is the binary-level contract — struct layout and size,
member offsets, vtable layout and slot order, calling convention, name mangling, exception handling
tables. **Break the ABI and code fails at run time, silently and horribly**, because the caller was
compiled against one memory layout and the callee implements another.

**What breaks ABI in a class you ship in a shared library** — and note that almost none of these
break the API:

- Adding, removing, or reordering **data members** — changes offsets and `sizeof`
- Adding a **virtual function**, or reordering existing ones — changes the vtable
- Adding a base class, or changing inheritance
- Changing a member's type, even `int` → `long`
- Changing default arguments (they're baked in at the _call site_)
- Changing an `inline` function's body — callers may have inlined the old one
- Compiling with different `-D` flags that affect a header's layout, or a different `struct` packing
- Changing the standard library version or the compiler's ABI (the `std::string` change in GCC 5 is
  the famous one, and `_GLIBCXX_USE_CXX11_ABI` exists because of it)

**Why this matters practically:** it's the entire reason shipping C++ shared libraries is hard, and
why C ABIs are the lingua franca of stable interfaces. It's also why **PIMPL** exists:

```cpp
// header — stable forever: one pointer, no layout exposed
class Engine {
public:
    Engine(); ~Engine();
    void start();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;   // everything real lives here
};
```

All the data members live in `Impl`, defined only in the `.cpp`. Now you can add, remove, and
reorder members freely without changing the header's layout, because callers only ever see one
pointer. **Costs:** an extra indirection, a heap allocation, and no inlining across the boundary.
**Worth it when** you ship a library to consumers you can't recompile; usually not worth it inside a
single codebase you rebuild atomically.

**Symbol versioning** (`.symver`, version scripts) lets a single `.so` export multiple incompatible
versions of a symbol so old binaries keep working — how `glibc` maintains decades of backward
compatibility. Good to know exists; rarely something you'd build yourself.

**The judgement to express:** inside one repository that's built and deployed as a unit, ABI
stability is a non-issue and PIMPL is usually needless overhead. Across a boundary where the two
sides ship independently, ABI is the _dominant_ design constraint and you either freeze the layout,
use PIMPL, or expose a C interface.

---

## Headers

**Headers are the build-time cost center**, because preprocessing is multiplicative — every TU that
includes a header re-parses it in full.

**The techniques, in rough order of value:**

**Forward declare instead of including.** If a header only needs `class Widget;` — because it holds
a pointer or reference, or takes one as a parameter — declare it rather than including its header.
You need the full definition only when the compiler must know the _size or layout_: by-value
members, inheritance, calling a member, or `sizeof`.

**Include what you use.** Every header should compile standalone and include exactly what it needs,
no more. The `include-what-you-use` tool automates the audit. The failure mode without it: your
header happens to work because some other header transitively pulled in `<string>`, and it breaks
the day that unrelated header is cleaned up.

**Include guards** (`#ifndef FOO_H` / `#define FOO_H` / `#endif`) or `#pragma once`. Guards are
portable and standard; `#pragma once` is universally supported in practice and lets the compiler
skip re-reading the file entirely. Either is fine; consistency matters more.

**Keep templates out of headers where you can.** Templates must be visible at instantiation, so they
live in headers, which is why template-heavy code is slow to compile. **Explicit instantiation** in
a `.cpp` (`template class Widget<int>;`) lets you move the cost to one TU when the set of
instantiations is known and small — directly relevant to your CRTP ORM, where the entity types are a
closed set.

**Precompiled headers** parse a stable set of headers once and reuse the result. Big wins on
codebases with a large, rarely-changing prefix (`<vector>`, `<string>`, platform headers). Fragile
and toolchain-specific.

**Unity builds** concatenate many `.cpp` files into one TU, eliminating repeated header parsing and
often cutting full-build time dramatically. **The costs are real:** internal-linkage names in
different files can now collide, incremental builds get worse (touching one file rebuilds the whole
blob), and it can hide missing includes.

**C++20 modules** are the actual fix — a module is parsed once into a binary artifact, and `import`
is not textual inclusion. Toolchain and build-system support is still uneven enough that "I'm
watching it, I haven't shipped it" is the correct answer.

**The one-liner to have ready:** _"the fastest way to speed up a C++ build is usually to stop
including things — forward declarations, PIMPL at the boundaries, and moving template instantiations
into a single TU beat any amount of hardware."_

---

## Cross

**Cross-compilation is building on one machine for a different one.** The machine you build on is
the **host**; the machine you run on is the **target**. (A third, the **build** machine, matters
only when building a compiler itself.) You did this for real: the telemetry library and collector,
and the ORM, cross-compiled from x86-64 developer machines for the ARM64 DHU.

### The architectures, and what actually differs

| Name(s)                                       | What it is       | Pointer | Notes                                                                                                                                                 |
| --------------------------------------------- | ---------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| **x86** / **i386** / **i686**                 | 32-bit Intel     | 4 bytes | Legacy. Mostly gone outside embedded and firmware                                                                                                     |
| **x86-64** / **amd64** / **x64**              | 64-bit Intel/AMD | 8 bytes | Your dev machines and virtually all servers. Three names, one thing                                                                                   |
| **ARM** / **armv7** / **armhf** / **aarch32** | 32-bit ARM       | 4 bytes | Still common on smaller embedded. `armhf` = hard-float ABI                                                                                            |
| **ARM64** / **AArch64** / **armv8-a**         | 64-bit ARM       | 8 bytes | **Same architecture, different naming conventions.** ARM says AArch64, Apple and Microsoft say ARM64, Linux toolchains say `aarch64`. Your DHU target |
| **RISC-V**                                    | Open ISA         | 4 or 8  | Worth knowing the name exists                                                                                                                         |

**The differences that actually cause bugs**, which is what an interviewer is probing for:

**1. Memory model strength — the big one.** x86-64 is **TSO** (Total Store Order): a strong model
that will not reorder stores with other stores, or loads with other loads. **AArch64 is weakly
ordered** and will do both. The consequence is brutal: _lock-free and atomic code with insufficient
ordering can be correct on x86 by accident and broken on ARM64._ A `memory_order_relaxed` where you
needed `acquire`/`release` costs nothing and works fine on your laptop, then produces a once-a-week
impossible bug on the vehicle. Conversely, ARM64 makes you pay for `seq_cst` in ways x86 doesn't, so
over-ordering shows up as measurable slowdown on the target and not on the host. **This is the
single best point you can make about cross-architecture work** — see [Model](concurrency.md#5-memory-ordering-in-atomics) and
[Atomics](concurrency.md#4-atomics) — and it's a very strong answer to "what surprised you."

**2. `char` signedness.** Plain `char` is **signed on x86** and **unsigned on ARM** by default. Code
doing `char c = getc(); if (c == -1)` works on one and silently fails on the other. Use
`signed char`/`unsigned char` explicitly, or `int8_t`/`uint8_t`.

**3. Alignment strictness.** x86 tolerates unaligned access with a performance penalty. ARM is
stricter — historically a bus fault, and on AArch64 still fatal for some instruction classes and for
anything atomic. **So the classic bug is `reinterpret_cast`ing a byte buffer to a struct pointer**,
which works fine on x86 and faults on ARM. Directly relevant to reading on-disk and on-wire formats
— see [Alignment](objects.md#7-alignment-beyond-the-struct) and [Layout](objects.md#5-memory-layout-and-padding). `memcpy` into a properly aligned object is the
portable answer.

**4. Type sizes and `long`.** `long` is 8 bytes on 64-bit Linux and 4 bytes on 32-bit and on 64-bit
Windows. `int` is 4 nearly everywhere. **Never serialize `long`, `size_t`, or `int` directly** — use
`<cstdint>` fixed-width types for anything crossing a boundary.

**5. Floating point.** ARM32 has soft-float and hard-float ABIs (hence `armhf`) and mixing them
fails at link. SIMD differs entirely — SSE/AVX on x86, NEON on ARM — so hand-vectorized code doesn't
port.

**6. Endianness.** Both x86 and ARM are little-endian in practice, so this bites less than people
expect — but ARM is _bi-endian_ and some embedded configurations run big-endian, and network byte
order is big-endian regardless. See [Endian](objects.md#8-byte-order).

### The mechanics

**Target triples** name the target: `<arch>-<vendor>-<os>-<abi>`, e.g. `aarch64-linux-gnu`,
`arm-none-eabi` (bare metal, no OS), `x86_64-pc-linux-gnu`. The cross toolchain is the
triple-prefixed binaries — `aarch64-linux-gnu-g++`, `aarch64-linux-gnu-ld`, `aarch64-linux-gnu-nm`.
**Using the host `nm` or `objdump` on a target binary is a classic time-waster**; use the prefixed
one.

**The sysroot is the concept that matters most.** A cross-compiler needs the _target's_ headers and
libraries, not the host's — if it picks up `/usr/include` from your x86 machine you get subtly wrong
type sizes and missing symbols. `--sysroot=/path/to/target/rootfs` points the whole toolchain at a
copy of the target's filesystem. **Getting the sysroot right is most of the work in setting up
cross-compilation**, and mismatch between the sysroot's `glibc` and the target device's `glibc` is
the single most common cause of "builds fine, won't start on the device."

**In CMake**, a toolchain file:

```cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_SYSROOT /opt/sysroots/aarch64)
set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)   # find host tools on the host
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)    # find target libs in the sysroot
```

passed as `cmake -DCMAKE_TOOLCHAIN_FILE=aarch64.cmake`. Those last two lines are the ones people get
wrong: you want _build tools_ from the host and _link libraries_ from the sysroot, and conflating
them produces baffling errors.

**In Bazel**, the same idea expressed as configuration rather than a file: platforms and constraint
values (`--platforms=//platforms:aarch64_linux`), registered toolchains, and toolchain resolution
selecting the right compiler per target. More machinery up front, but it means one build graph can
produce x86-64 and ARM64 artifacts in the same invocation, with correct per-target caching — which
is exactly what you wanted for the ORM, built for both.

**Verifying you got what you think you got** — the habits worth naming out loud:

```sh
file app                      # ELF 64-bit LSB, ARM aarch64  ← confirms the architecture
readelf -h app                # Machine: AArch64
readelf -d app               # DT_NEEDED, RPATH/RUNPATH
aarch64-linux-gnu-nm -C app  # symbols, with the target's nm
objdump -p app | grep NEEDED  # what it will try to load
```

**Testing is the real problem.** You cannot run the target binary on the host, so: **QEMU user-mode
emulation** (`qemu-aarch64` — slow, but it runs your unit tests in CI and catches most correctness
bugs), **hardware in the loop** for anything timing- or performance-sensitive, and cross-compiled
unit tests run on-device as a deployment gate. The nuance to state: **QEMU will not reliably
reproduce weak-memory-model bugs**, because it doesn't faithfully model AArch64's reordering.
Concurrency bugs must be caught on real hardware, or by reasoning, or with TSan — not by emulation.
That's a genuinely sophisticated point.

**Have this narrative ready**, because "tell me about cross-compiling" is a near-certain question
given your resume: what the target was and why (the DHU, ARM64 embedded Linux, tight CPU and memory
budget), how the toolchain and sysroot were set up, what actually went wrong (dependency isolation —
see [Loader](#loader) — and the glibc/BSP version constraint), how you verified the artifact was
really for the target, how you tested without the hardware in front of you, and what surprised you
(the memory model, and how much of "it works on my machine" is really "my machine has a stronger
memory model and looser alignment rules than my target").

---

## BuildSys

**Two layers people conflate.** A _build system_ executes a dependency graph of compile and link
actions (Make, Ninja, Bazel). A _build system generator_ produces input for one (CMake, Meson,
`gn`). CMake is a generator — it emits Makefiles or Ninja files. Bazel is both.

### Make and Ninja

**Make** is the substrate: rules, targets, prerequisites, timestamp-based rebuild decisions. Worth
understanding because everything else compiles down to something like it, and because
**timestamp-based** dependency tracking is the root of most "clean build fixes it" experiences —
clock skew, a header that changed within the same second, or a dependency you never declared.
**Ninja** is a faster, deliberately dumb Make replacement designed to be _generated_ rather than
hand-written; it's what CMake should target on any modern project.

### CMake

The de facto standard. Not because it's well-designed — the language is genuinely awkward, and there
are three generations of idiom in circulation — but because **the entire C++ ecosystem ships CMake
support**, and that network effect dominates every other consideration.

**What good modern CMake looks like:** targets rather than global state, `target_link_libraries`
with `PUBLIC`/`PRIVATE`/`INTERFACE` to express dependency propagation, `target_include_directories`
rather than `include_directories`, and no manual flag mangling. The `PUBLIC`/`PRIVATE` distinction
is the concept to get right — it's how CMake models _transitive_ dependency requirements, and it's
what separates a maintainable build from a pile of global flags.

**Where CMake genuinely hurts:** builds are **not hermetic** — they consult the host environment
through `find_package`, so the same source can build differently on two machines. Dependency
management is a long-running weak point (hence Conan, vcpkg, and `FetchContent` all coexisting). And
incremental correctness relies on the generator's dependency scanning, which is good but not
guaranteed.

### Bazel

**The model:** every action declares its inputs and outputs explicitly, and the build is
**hermetic** — an action's result is a pure function of its declared inputs, with no access to
undeclared files or ambient environment. That single property is what unlocks everything else:

- **Content-addressed caching.** Hash the action's inputs, command line, and environment; the output
  is stored under that hash. Anyone with the same inputs gets the same output.
- **Safe cache sharing across a team**, which is the point. **A shared cache on a non-hermetic build
  is not merely less effective — it is unsound**, because you can serve an artifact that was built
  from inputs you can't fully account for. Hermeticity is what makes the cache trustworthy.
- **Remote execution.** If actions are hermetic they can run anywhere, so the build fans out across
  a cluster.
- **Correct incrementality.** Because inputs are declared rather than sniffed, Bazel knows exactly
  what a change invalidates. Undeclared dependencies fail loudly instead of causing stale builds.
- **Multi-language, one graph** — C++, Java, Go, protobuf, containers in one dependency graph, which
  is why it suits monorepos.

**Where Bazel genuinely hurts:** a steep adoption cost and its own DSL (Starlark); third-party C++
libraries mostly ship CMake, so every dependency needs a `BUILD` file or a wrapper, and
`rules_foreign_cc` is a workable but unpleasant escape hatch; toolchain and platform configuration
is powerful and verbose; and it's real infrastructure — someone owns the build, which is fine at
Google's scale and heavy for a team of eight.

### The answer to "why Bazel over CMake" — and the reason it's the wrong question

**Don't defend Bazel as universally better.** The strong answer names the axis:

> "It's not that one is better — they optimize for different things, and the deciding factor is
> whether you need a _trustworthy_ build or a _convenient_ one. Bazel's hermeticity is what makes
> remote caching and remote execution sound: if an action's output is a pure function of its
> declared inputs, a cache hit is provably the same artifact. On a non-hermetic build a shared cache
> isn't just less effective, it's unsafe — you can serve something built from inputs you can't
> account for. So if the problem is 'this monorepo takes too long to build across a team,' Bazel is
> answering exactly that question.
>
> The cost is real, though. Every third-party C++ library ships CMake, not Bazel, so you're writing
> `BUILD` files or using `rules_foreign_cc` for dependencies you'd otherwise get for free. And it's
> infrastructure someone has to own. For a smaller project, or one that lives on external
> dependencies, CMake plus Ninja plus ccache gets you most of the practical benefit with none of the
> adoption cost. I'd reach for Bazel when the build is a shared bottleneck across many engineers and
> the repo is large enough that correct incrementality actually matters — which was true where I
> used it. I wouldn't introduce it to a codebase of ten libraries."

**The honest disclosure to include:** Bazel predated you as a team decision at Toyota — say so, and
then defend it on the merits anyway. That reads as better judgement than pretending you chose it,
and it lets you evaluate rather than advocate.

**And for NetApp specifically:** ONTAP is a decades-old codebase and almost certainly uses neither.
Being able to reason about the _tradeoff_ — hermeticity, incremental correctness, and cache
soundness — is the transferable part, and it applies to whatever they actually use. If you get the
chance, asking what their build looks like and how long a full build takes is an excellent question:
it's a real engineering concern at that codebase size, and it signals you think about developer
velocity as an engineering property.

---

## Buildspeed

**Where C++ build time actually goes**, roughly in order: preprocessing the same headers once per
TU; template instantiation; optimization; and then a serial, memory-hungry link.

**The interventions, ordered by return on effort** — this ordering is the answer to "our build is
slow, what would you do":

1. **Measure first.** `-ftime-trace` (Clang) produces a per-TU flame chart of where the frontend
   spent its time; `-ftime-report` is the GCC equivalent. Ninja's `.ninja_log` shows the critical
   path. **Don't guess** — most build-time intuitions are wrong, and it's usually one or two
   headers.
2. **Switch linkers.** `lld` or `mold` instead of `ld`. Often a several-fold link improvement for a
   one-line change. The cheapest win available.
3. **`ccache`.** Hashes the preprocessed source plus the compiler and flags, and reuses the object
   file. Enormous for rebuilds after branch switches and for CI. Note the _shape_ of the idea: it's
   a content-addressed cache bolted on to make up for the build system not being hermetic — which is
   exactly the gap Bazel closes structurally.
4. **Cut includes.** Forward declarations, PIMPL at boundaries, `include-what-you-use`. Attacks the
   multiplicative cost at its root, and improves incremental builds too because fewer TUs depend on
   each header.
5. **Reduce template instantiation.** Explicit instantiation in one TU, type-erase where the generic
   code isn't earning its keep, avoid deep recursive metaprogramming (C++20 concepts and
   `if constexpr` are cheaper than SFINAE and tag dispatch).
6. **Parallelize properly.** `-j$(nproc)` is table stakes; the ceiling is the critical path through
   the dependency graph and the serial link at the end.
7. **Precompiled headers or a unity build.** Real gains, real costs — see [Headers](#headers).
8. **Distribute it.** `distcc`/`icecc` for compilation, or Bazel remote execution. **This is your
   story** — it's the last item on the list because it's the heaviest, and reaching for it is only
   correct once the build is a _team-wide_ bottleneck rather than an individual annoyance.

**The distinction interviewers actually care about: full build time versus incremental build time.**
They're different problems with different fixes. Full builds are fixed by caching, distribution, and
parallelism. **Incremental builds are fixed by dependency hygiene** — if touching one header
rebuilds four hundred files, no amount of hardware helps, and a unity build makes it strictly worse.
Developer experience is dominated by the incremental number, so that's usually the one to attack
first.

**The correctness point that elevates the whole answer:** a fast build that's occasionally wrong is
worse than a slow build that's always right, because "try a clean build" becomes institutional
folklore and people stop trusting the tooling. Every caching and distribution mechanism above is
only safe to the extent that inputs are correctly declared — which is why hermeticity is a
_correctness_ property first and a performance property second.
