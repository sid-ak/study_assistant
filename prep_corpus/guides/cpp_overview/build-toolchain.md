# Build & Toolchain

> Part of the [C++ Overview](README.md)

!!! warning "TODO"

    The matching Deep Dive page has not been rewritten in the new format yet. Its Go deeper links lead to
    the previous version of the Build & Toolchain chapter.

Turning a C++ project into a running program takes several separate tools, collectively called the
toolchain. The compiler handles one source file at a time and knows nothing about the others; the
linker combines the results into a single executable or library; and at startup, the operating
system's loader connects that program to the shared libraries it depends on. Many confusing build
errors make sense once you know which of these tools produced them and what that tool can see.

| Step | Tool | Input | Output | Typical errors |
| ---- | ---- | ----- | ------ | -------------- |
| Preprocess | Preprocessor (part of the compiler driver) | `.cpp` file and its headers | One expanded translation unit | Missing header, macro conflicts |
| Compile | Compiler (see [Compiler](compiler.md)) | Translation unit | Object file (`.o`) | Syntax and type errors |
| Link | Linker (`ld`, `lld`, `gold`, `mold`) | Object files and libraries | Executable or shared library | Undefined reference, multiple definition |
| Load | Dynamic loader (`ld-linux.so`, `dyld`) | Executable at startup | Running process | Shared library not found, missing symbol |

## 1. Preprocessing and translation units

Before compiling, the preprocessor handles every line beginning with `#`.

```cpp
// parser.h
#pragma once                        // paste this header at most once per translation unit

#include <string>                   // the whole <string> header is pasted here

class Logger;                       // forward declaration: no need to include logger.h

class Parser {
public:
    explicit Parser(Logger* logger);
    bool parse(const std::string& input);
private:
    Logger* logger_;                // a pointer to an incomplete type is fine
};
```

- `#include`: pastes the entire contents of the named header in place. A header included by many
  files is re-read and re-compiled by each of them.
- Translation unit: the result of preprocessing one `.cpp` file with all of its headers expanded.
  This is the unit the compiler actually works on.
- Include guards: `#pragma once` or `#ifndef` guards stop a header from being pasted twice into the
  same translation unit.
- Build cost: large headers included everywhere are usually the biggest driver of build time.
  Forward declarations, which name a type without defining it, reduce how much each file has to
  include.

> Large projects such as LLVM track how many headers each file includes. Replacing an `#include` in
> a widely used header with a forward declaration can cut minutes from a full rebuild.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#headers)

## 2. Symbols and linking

Each object file lists the symbols — named functions and variables — that it defines and the ones
it uses but does not define. The linker matches every use to exactly one definition.

```cpp
// checksum.h
int checksum(const char* data, int length);            // declaration only: "defined elsewhere"

inline int version() { return 3; }                     // inline: safe to define in a header
// int build_id() { return 7; }                        // without inline: multiple definition
                                                       // once two .cpp files include this header

extern "C" int legacy_crc32(const char* data, int n);  // C linkage: symbol is plain "legacy_crc32"
```

- Undefined reference: a function was declared and called, but no object file or library given to
  the linker defines it. Common causes are a missing source file, a missing library, or libraries
  listed in the wrong order.
- Multiple definition: two object files define the same non-`inline` symbol, often because a
  function was defined in a header without `inline`. See [Keywords](keywords.md).
- Name mangling: C++ encodes a function's namespace and parameter types into its symbol name so that
  overloads have distinct names — `checksum` above becomes `_Z8checksumEPKci` on Linux. `extern "C"`
  turns this off so C code can call the function. Tools such as `nm -C` and `c++filt` translate
  mangled names back into readable ones.

> An "undefined reference to `curl_easy_init`" error means the code compiled against the libcurl
> header but the libcurl library was never passed to the linker, which is usually fixed by adding it
> to the build's link dependencies.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#symbols)

## 3. Static and shared libraries

A library is a collection of compiled code. The main question is when that code becomes part of the
program.

```cpp
// storage.h — the public interface of libstorage
#pragma once

// Export only this function from the shared library; everything else stays internal
[[gnu::visibility("default")]]
int storage_write(int block, const char* data);
```

- Static library (`.a`, `.lib`): the linker copies the needed object code into the executable at
  build time. The result is self-contained but larger, and updating the library requires relinking.
- Shared library (`.so`, `.dylib`, `.dll`): the executable records only the library's name, and the
  code is loaded when the program starts. Several programs can share one copy, and the library can
  be updated without rebuilding them.
- Symbol visibility: building a shared library with `-fvisibility=hidden` and marking only the public
  functions as visible keeps internal symbols private and speeds up loading.
- Position-independent code (`-fPIC`): shared libraries are loaded at different addresses in
  different processes, so their code must be compiled to work at any address.

> Linux distributions ship OpenSSL as a shared library, so a single security update to `libssl.so`
> fixes every program that uses it. Command-line tools distributed as a single self-contained binary
> often link their dependencies statically instead, so they run on machines that lack those
> libraries.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#libraries)

## 4. The dynamic loader

When a program that uses shared libraries starts, the operating system first runs the dynamic
loader, which finds and maps each library before `main()` runs.

```cpp
#include <dlfcn.h>                 // POSIX

int load_plugin() {
    void* handle = dlopen("libcompress.so", RTLD_NOW);     // load a library at run time
    if (!handle) return -1;

    using CompressFn = int (*)(const char*, int);
    auto compress = reinterpret_cast<CompressFn>(dlsym(handle, "compress"));   // look up a C symbol
    int result = compress ? compress("data", 4) : -1;

    dlclose(handle);
    return result;
}
```

- Search order on Linux: a legacy `RPATH` embedded in the executable (ignored if `RUNPATH` is
  present), the `LD_LIBRARY_PATH` environment variable, a `RUNPATH` embedded in the executable, the
  system cache built by `ldconfig`, then default directories such as `/usr/lib`.
- Diagnosis: `ldd ./program` lists which library file each dependency resolves to, or reports it as
  not found.
- Run-time loading: `dlopen` loads a library while the program is running and `dlsym` finds a
  function in it by name, which is how plugin systems work. Plugin entry points are declared
  `extern "C"` so their names are not mangled.

> Audio applications and image editors load effects and filters from a plugins folder with `dlopen`
> at run time, so third parties can ship new plugins without the main application being rebuilt.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#loader)

## 5. ABI compatibility

An ABI (Application Binary Interface) is the set of low-level conventions that compiled code relies
on: how functions receive arguments, how classes are laid out in memory, and how names are mangled.

```cpp
// widget.h — PIMPL keeps the class layout fixed across library versions
#include <memory>

class Widget {
public:
    Widget();
    ~Widget();                    // defined in widget.cpp, where Impl is complete
    int value() const;
private:
    struct Impl;                  // declared here, defined only in widget.cpp
    std::unique_ptr<Impl> impl_;  // sizeof(Widget) is one pointer, whatever Impl contains
};

// widget.cpp
struct Widget::Impl { int value = 42; /* new fields can be added freely */ };
Widget::Widget() : impl_(std::make_unique<Impl>()) {}
Widget::~Widget() = default;
int Widget::value() const { return impl_->value; }
```

- Why it matters: a program and a shared library compiled separately work together only if they
  agree on the ABI. Adding a member to a class changes its size and breaks every already-compiled
  user of that class, even though the source still compiles.
- PIMPL ("pointer to implementation"): a class keeps its data in a separate private struct reached
  through a pointer, so the class's size and layout stay fixed when its internals change.

> Qt and many operating system SDKs use PIMPL in their public classes. That lets them add features
> in a minor release while existing applications, compiled against the older version, keep working
> without recompiling.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#abi)

## 6. Cross-compilation

Cross-compiling means building on one kind of machine (the host, often x86-64) for another (the
target, such as an ARM board).

```cpp
#include <climits>
#include <cstdint>

// Assumptions that differ between targets, checked when the code is built for each one
static_assert(sizeof(void*) == 8, "this code assumes a 64-bit target");
static_assert(CHAR_BIT == 8);

bool is_high_byte(char c) {
    return c < 0;                 // true for 0x80 on x86-64 (char is signed),
}                                 // always false on ARM Linux (char is unsigned)

std::int8_t explicit_signed(std::uint8_t raw) {
    return static_cast<std::int8_t>(raw);   // fixed-width types remove the ambiguity
}
```

- Target triple: a string such as `aarch64-linux-gnu` names the CPU architecture, operating system,
  and C library the code will run on.
- Sysroot: a directory containing the target's headers and libraries, so the build uses those rather
  than the host's.
- Target-only bugs: differences in pointer size, alignment rules, and the signedness of `char` can
  hide bugs that appear only on the target, as `is_high_byte` shows.

> Firmware for a Raspberry Pi or an embedded controller is usually built on a developer's x86-64
> workstation with an `aarch64-linux-gnu` cross toolchain and a sysroot copied from the target
> image, because compiling on the board itself would take hours.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#cross)

## 7. Build systems

A build system decides which files need rebuilding and runs the tools in the right order.

```cmake
# CMakeLists.txt
cmake_minimum_required(VERSION 3.20)
project(app CXX)

set(CMAKE_CXX_STANDARD 20)

add_library(storage SHARED storage.cpp)          # builds libstorage.so
target_include_directories(storage PUBLIC include)

add_executable(app main.cpp parser.cpp)
target_link_libraries(app PRIVATE storage)       # CMake adds the -L and -l flags
```

- Make and Ninja: execute a dependency graph of commands. Ninja is designed to be generated by other
  tools and is very fast at deciding what to rebuild.
- CMake: describes a project at a higher level and generates Make, Ninja, or IDE project files from
  that description.
- Bazel: declares every dependency explicitly, which enables reproducible builds and caching
  build results across machines, at the cost of more upfront configuration.

The same steps, run by hand:

```sh
g++ -std=c++20 -c parser.cpp -o parser.o          # compile only
g++ -std=c++20 -c main.cpp -o main.o
g++ main.o parser.o -L./lib -lstorage -o app      # link against libstorage
nm -C app | grep parse                            # inspect defined symbols
ldd ./app                                         # check shared library resolution (Linux)
```

> Many open-source C++ projects ship a `CMakeLists.txt` so users can build them with Ninja on Linux,
> Xcode on macOS, or Visual Studio on Windows from the same description, while large monorepos at
> companies such as Google use Bazel for cached, reproducible builds.

[Go deeper →](../cpp_deep_dive/build-toolchain.md#buildsys)

## Working with the toolchain

When a build fails, first identify which step failed: compiler errors point to source lines, linker
errors name symbols, and loader errors name library files. Keep headers small to control build time,
treat the layout of public classes in shared libraries as a fixed contract, and let a build system
manage the steps rather than invoking tools by hand.

## C++ References

Preprocessor

- [Preprocessor overview](https://en.cppreference.com/cpp/preprocessor)
- [`#include`](https://en.cppreference.com/cpp/preprocessor/include)
- [`#pragma` and implementation-defined directives](https://en.cppreference.com/cpp/preprocessor/impl)
- [Conditional inclusion and include guards](https://en.cppreference.com/cpp/preprocessor/conditional)

Language

- [Phases of translation](https://en.cppreference.com/cpp/language/translation_phases)
- [Declarations](https://en.cppreference.com/cpp/language/declarations)
- [Definitions and the One Definition Rule](https://en.cppreference.com/cpp/language/definition)
- [Linkage](https://en.cppreference.com/cpp/language/storage_duration)
- [Language linkage (`extern "C"`)](https://en.cppreference.com/cpp/language/language_linkage)
- [`inline` specifier](https://en.cppreference.com/cpp/language/inline)
- [Class declarations and forward declarations](https://en.cppreference.com/cpp/language/class)
- [Attributes](https://en.cppreference.com/cpp/language/attributes)
- [PImpl](https://en.cppreference.com/cpp/language/pimpl)
- [Modules](https://en.cppreference.com/cpp/language/modules)
- [Fundamental types and data models](https://en.cppreference.com/cpp/language/types)

Library

- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr)
- [Fixed-width integer types](https://en.cppreference.com/cpp/types/integer)
- [`CHAR_BIT` and numeric limits macros](https://en.cppreference.com/cpp/types/climits)
