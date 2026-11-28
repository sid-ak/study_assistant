# Compiler

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
A compiler translates one C++ source file into machine code for a specific processor. Along the way
it checks that the program follows the language rules, reports what it finds as errors and warnings,
and transforms the code to run faster. This page covers what happens inside a single compiler run on
a single source file; the steps around it, such as preprocessing and linking, are covered in
[Build & Toolchain](build-toolchain.md).

| Stage | Input | Output | What can go wrong here |
| ----- | ----- | ------ | ---------------------- |
| Parsing | Preprocessed source text | A syntax tree describing the code's structure | Syntax errors such as a missing semicolon |
| Semantic analysis | Syntax tree | A checked tree with every name, type, and overload resolved | Type errors, ambiguous overloads, template failures |
| IR generation | Checked tree | Intermediate representation (IR), a simplified machine-independent form | Rarely user-visible |
| Optimization | IR | Faster, equivalent IR | Undefined behavior in the source producing surprising results |
| Code generation | Optimized IR | Assembly or object code for the target CPU | Target-specific problems, such as an unsupported instruction |
<!-- --8<-- [end:intro] -->

## 1. The front end: understanding the code

<!-- --8<-- [start:frontend] -->
The front end reads the source and builds a complete model of what it means.

```cpp
void write_log(int value);
void write_log(double value);
void write_log(const char* text);

void front_end() {
    write_log(42);          // overload resolution picks write_log(int)
    write_log(3.14);        // picks write_log(double)
    write_log("ready");     // picks write_log(const char*)
    // write_log(42L);      // error: ambiguous; long converts equally well to int and double
}
```

- Parsing: the compiler turns the text into a syntax tree, a structure in which a function contains
  statements and a statement contains expressions.
- Name lookup and overload resolution: for each name, the compiler finds its declaration; for each
  function call, it chooses the best-matching overload from the candidates, as the calls above show.
- Template instantiation: templates are expanded into concrete code for each set of arguments they
  are used with (see [Templates](templates.md)). This step is a major source of compile time.
- Diagnostics: every language rule violation is reported here, before any machine code exists.

> When a call is ambiguous after someone adds a new overload of a widely used function, the front
> end's error lists every candidate it considered. Reading those candidates shows which implicit
> conversion made the new overload an equally good match.
<!-- --8<-- [end:frontend] -->

[Go deeper →](../cpp_deep_dive/compiler.md#1-the-front-end-understanding-the-code)

## 2. The middle end: optimization

<!-- --8<-- [start:middle] -->
Most compilers convert the checked program into an intermediate representation — LLVM IR in Clang,
GIMPLE in GCC — and optimize that form so the work is shared across source languages and target CPUs.

```cpp
int seconds_per_day() {
    return 60 * 60 * 24;          // constant folding: compiled as "return 86400"
}

static int square(int x) { return x * x; }
int area() { return square(12); } // inlining, then folding: also a constant

bool will_overflow(int x) {
    return x + 1 < x;             // signed overflow is undefined, so at -O2 this becomes "return false"
}
```

- Common passes: inlining (replacing a call with the function body), constant folding (computing
  `60 * 60 * 24` at compile time), dead code elimination, and loop transformations such as
  vectorization, which uses SIMD instructions to process several values in one CPU operation.
- The as-if rule: the optimizer may change the code in any way that does not change the program's
  observable behavior.
- Undefined behavior: the optimizer assumes undefined behavior never happens. Because signed integer
  overflow is undefined, `will_overflow` above is compiled to always return `false`. The same
  reasoning can delete bounds checks or loops, so a bug can appear far from its cause.

> A bounds check like `if (offset + length < offset)`, intended to detect overflow with signed
> integers, can be removed entirely by the optimizer. Security reviews look for this pattern and
> replace it with checks written in unsigned arithmetic or explicit range comparisons.
<!-- --8<-- [end:middle] -->

[Go deeper →](../cpp_deep_dive/compiler.md#2-the-middle-end-optimization)

## 3. The back end: generating machine code

<!-- --8<-- [start:backend] -->
The back end maps the optimized IR onto a specific instruction set, such as x86-64 or AArch64.

```cpp
int add(int a, int b) {
    return a + b;
}
// x86-64, -O2:   lea eax, [rdi + rsi]    ; a arrives in rdi, b in rsi, result in eax
//                ret
// AArch64, -O2:  add w0, w1, w0          ; a in w0, b in w1, result in w0
//                ret
```

- Tasks: choosing instructions, assigning values to CPU registers, and laying out each function's
  stack frame. The same function produces different instructions and uses different registers on
  each architecture.
- Output: an object file containing machine code plus a list of symbols it defines and symbols it
  still needs from other files. The linker resolves those later.

> The same program built for a laptop (x86-64) and a phone (AArch64) runs the same source through
> different back ends. Performance-sensitive libraries sometimes contain hand-tuned code paths for
> each instruction set because the generated instructions differ.
<!-- --8<-- [end:backend] -->

[Go deeper →](../cpp_deep_dive/compiler.md#3-the-back-end-generating-machine-code)

## 4. The major compilers

<!-- --8<-- [start:compilers] -->
| Compiler | Maintained by | Typical platforms | Notes |
| -------- | ------------- | ----------------- | ----- |
| GCC (`g++`) | GNU project | Linux, embedded cross-compilers | The default on most Linux distributions |
| Clang (`clang++`) | LLVM project | macOS, Linux, Android, Windows | Known for readable diagnostics; the basis of many tools |
| MSVC (`cl`) | Microsoft | Windows | Uses different flag syntax (`/O2` instead of `-O2`) |

GCC and Clang accept largely the same flags. Building a project with more than one compiler is a
cheap way to catch non-portable code.

```cpp
#if defined(__clang__)
constexpr const char* compiler_name = "Clang";
#elif defined(__GNUC__)
constexpr const char* compiler_name = "GCC";
#elif defined(_MSC_VER)
constexpr const char* compiler_name = "MSVC";
#endif

constexpr long standard_version = __cplusplus;   // 202002L when built with -std=c++20
```

> Open-source libraries commonly run continuous integration with GCC, Clang, and MSVC. Code that
> relies on one toolchain's lenient behavior, such as a missing `#include` that one standard library
> happens to pull in through another header, fails on another and is caught before release.
<!-- --8<-- [end:compilers] -->

[Go deeper →](../cpp_deep_dive/compiler.md#4-the-major-compilers)

## 5. Flags that change behavior

<!-- --8<-- [start:flags] -->
Compiler flags select the language version, how hard the optimizer works, and which extra checks are
built into the program.

```cpp
int read_past_end() {
    int values[4] = {1, 2, 3, 4};
    int index = 4;
    return values[index];   // out of bounds: -fsanitize=address reports the exact line at run time
}
```

- Language standard: `-std=c++20` selects which version of the language the compiler accepts.
- Optimization levels: `-O0` does no optimization and keeps code easy to step through in a debugger;
  `-O2` is the usual release setting; `-O3` adds more aggressive transformations; `-Os` optimizes for
  size.
- Debug information: `-g` records how machine code maps back to source lines and variables. It can be
  combined with any optimization level.
- Warnings: `-Wall -Wextra` enable the most useful warnings, and `-Werror` turns them into errors so
  they cannot be ignored.
- Sanitizers: `-fsanitize=address` detects out-of-bounds access and use-after-free,
  `-fsanitize=undefined` detects many kinds of undefined behavior, and `-fsanitize=thread` detects
  data races. Each adds run-time checks and is meant for testing builds.

```sh
# Development build: warnings, debug info, sanitizers
clang++ -std=c++20 -Wall -Wextra -g -O1 -fsanitize=address,undefined main.cpp -o main

# Release build: optimized, with debug info kept for profiling
clang++ -std=c++20 -O2 -g main.cpp -o main
```

> Many teams build their test suite a second time with `-fsanitize=address,undefined` in continuous
> integration. A buffer overflow that passes silently in the normal build fails the sanitizer run
> with the exact file and line.
<!-- --8<-- [end:flags] -->

[Go deeper →](../cpp_deep_dive/compiler.md#5-flags-that-change-behavior)

## 6. Reading and debugging compiler output

<!-- --8<-- [start:diagnostics] -->
Most time spent with a compiler goes into reading what it reports, so it pays to know where to look.

```cpp
template <typename T>
T halve(T value) { return value / 2; }

struct Size { int bytes; };

// halve(Size{8});
// error: invalid operands to binary expression ('Size' and 'int')
//   note: in instantiation of function template specialization 'halve<Size>' requested here
//
// The first line says what failed inside the template; the note points to the call in your code.
```

- Read the first error first: one mistake often causes a cascade of later errors that disappear once
  it is fixed.
- Template errors: look for the line in your own code (marked "requested here" in Clang or "required
  from here" in GCC), then find the requirement that failed. Constraining templates with concepts
  makes this message short.
- Check syntax quickly: `-fsyntax-only` runs only the front end, which is useful for fast feedback.
- Look at generated code: `-S` stops after producing assembly. [Compiler Explorer](https://godbolt.org)
  shows the assembly for any snippet across many compilers and flag combinations side by side.
- Suspect undefined behavior when results change between `-O0` and `-O2`: rebuild with
  `-fsanitize=address,undefined` before suspecting a compiler bug.

> Stepping through an error message such as "no matching function for call to `std::sort`" usually
> leads to a note explaining that the iterator type does not support random access — for example,
> trying to sort a `std::list`, which provides its own `sort` member function instead.
<!-- --8<-- [end:diagnostics] -->

[Go deeper →](../cpp_deep_dive/compiler.md#6-reading-and-debugging-compiler-output)

## Working with the compiler

<!-- --8<-- [start:choosing] -->
Treat warnings as defects and build with `-Wall -Wextra` at minimum. Run tests under sanitizers
regularly, since they catch memory and threading bugs that ordinary testing misses. When generated
code or performance is surprising, inspect the assembly directly rather than guessing what the
optimizer did.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Phases of translation](https://en.cppreference.com/cpp/language/translation_phases)
- [Name lookup](https://en.cppreference.com/cpp/language/lookup)
- [Overload resolution](https://en.cppreference.com/cpp/language/overload_resolution)
- [Implicit conversions](https://en.cppreference.com/cpp/language/implicit_conversion)
- [Templates and instantiation](https://en.cppreference.com/cpp/language/templates)
- [The as-if rule](https://en.cppreference.com/cpp/language/as_if)
- [Undefined behavior](https://en.cppreference.com/cpp/language/ub)
- [Arithmetic operators and signed overflow](https://en.cppreference.com/cpp/language/operator_arithmetic)
- [Constant expressions](https://en.cppreference.com/cpp/language/constant_expression)
- [Array subscripts and bounds](https://en.cppreference.com/cpp/language/operator_member_access)

Preprocessor and toolchain

- [Conditional inclusion (`#if`, `#elif`)](https://en.cppreference.com/cpp/preprocessor/conditional)
- [Predefined macros, including `__cplusplus`](https://en.cppreference.com/cpp/preprocessor/replace)
- [Compiler support by feature](https://en.cppreference.com/cpp/compiler_support)
- [Feature testing](https://en.cppreference.com/cpp/feature_test)
