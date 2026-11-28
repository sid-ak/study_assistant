# Versions

> Part of the [C++ Deep Dive](README.md) · Overview: [Versions](../cpp_overview/versions.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/versions.md:intro"

This page goes beyond the headline features of each standard: the ideas that made each release
possible, what was removed along the way, and how the standard itself is produced and adopted by
compilers and codebases.

## 1. C++98 and C++03: the foundation

??? note "Overview"

    --8<-- "guides/cpp_overview/versions.md:cpp98"

### Ownership before smart pointers

The only smart pointer in C++98 was `std::auto_ptr`, and its design shows why move semantics were
needed.

```cpp
// C++98 (auto_ptr was removed in C++17, so this no longer compiles with a current standard):
//
// std::auto_ptr<Session> a(new Session);
// std::auto_ptr<Session> b = a;          // "copy" silently transfers ownership; a is now null
// std::vector<std::auto_ptr<Session>> v; // compiles on some libraries, then breaks when elements are "copied"

std::unique_ptr<int> modern() {
    auto a = std::make_unique<int>(1);
    auto b = std::move(a);                // the transfer is explicit and visible
    return b;
}
```

- The problem: without a way to express "transfer", `auto_ptr` overloaded copying to mean moving.
  Code that looked like a copy left the source empty.
- The consequence: containers and algorithms assume copies are equivalent to the original, so storing
  `auto_ptr` in a container was unsafe.
- The resolution: C++11's rvalue references made transfer a distinct operation, `std::unique_ptr` was
  built on it, and `auto_ptr` was deprecated and later removed.

### What the STL established

The STL separated containers from algorithms through iterators, so an algorithm is written once and
works on any container that provides the iterator operations it needs.

```cpp
template <typename It>
It find_negative(It first, It last) {
    for (; first != last; ++first) {
        if (*first < 0) return first;
    }
    return last;
}

void use_stl() {
    int raw[] = {3, -1, 4};
    std::vector<int> vec(raw, raw + 3);
    int* in_array = find_negative(raw, raw + 3);                                   // a C array
    std::vector<int>::iterator in_vec = find_negative(vec.begin(), vec.end());    // a vector
    (void)in_array;
    (void)in_vec;
}
```

- Iterators: an iterator generalizes a pointer. Algorithms use only iterator operations (`*`, `++`,
  `!=`), so a raw pointer into a C array is itself a valid iterator.
- Zero overhead: because algorithms are templates instantiated per iterator type, the generic loop
  compiles to the same code as a hand-written one. See [Templates](templates.md).
- Legacy: C++20 ranges build directly on this design, packaging a begin and end iterator into a single
  object.

## 2. C++11: modern C++ begins

??? note "Overview"

    --8<-- "guides/cpp_overview/versions.md:cpp11"

### The threading memory model

Before C++11 the standard described a single-threaded abstract machine. Threads existed only through
platform libraries such as POSIX threads, and the language made no promises about what happened when
two threads touched memory.

```cpp
std::atomic<int> completed{0};

void run_parallel() {
    std::vector<std::thread> workers;
    for (int i = 0; i < 4; ++i) {
        workers.emplace_back([] { completed.fetch_add(1); });
    }
    for (auto& t : workers) t.join();
}
```

- Memory locations: C++11 defined a memory location as a scalar object or a maximal run of adjacent
  bit-fields, and stated that threads may access different memory locations concurrently without
  interfering. Unsynchronized access to the same location, with at least one writer, is a data race
  and undefined behavior.
- Why it mattered: compiler optimizations that were valid for single-threaded code, such as writing
  back to a variable a loop never modified, could corrupt another thread's data. The memory model
  told compiler writers which of those optimizations were no longer allowed.
- Library: `std::thread`, `std::mutex`, `std::condition_variable`, `std::atomic`, and `std::future`
  gave portable building blocks, and function-local `static` initialization became thread-safe. See
  [Concurrency](concurrency.md).

### `constexpr` and `noexcept`

```cpp
constexpr int square(int x) { return x * x; }   // C++11 rule: a single return statement
constexpr int area = square(12);                // evaluated by the compiler

void release() noexcept;                        // promises not to throw
```

- `constexpr`: functions that the compiler can evaluate when their arguments are constants. C++11
  restricted them to a single `return` statement; C++14 allowed loops and local variables, and later
  standards removed most remaining restrictions.
- `noexcept`: replaced the older dynamic exception specifications. It lets libraries choose faster
  code paths, such as moving rather than copying during reallocation. See [Keywords](keywords.md).

### Library changes with lasting effects

- `std::string`: C++11's complexity and iterator-invalidation requirements effectively ruled out
  copy-on-write strings, so implementations switched to the small-string optimization. GCC's
  standard library kept both layouts side by side (the "dual ABI", selected by
  `_GLIBCXX_USE_CXX11_ABI`), which is why linking libraries built with different settings can fail
  with undefined references mentioning `std::__cxx11::basic_string`.
- New containers: `std::unordered_map`, `std::unordered_set`, `std::array`, and `std::forward_list`.
- Other additions: `<chrono>`, `<random>`, `<regex>`, and `std::function`.

## 3. C++14 and C++17: filling the gaps

??? note "Overview"

    --8<-- "guides/cpp_overview/versions.md:cpp14_17"

### C++14 additions

C++14 was a small release that removed friction left by C++11.

```cpp
auto make_widget_name(int id) {                 // return type deduced as std::string
    return "widget-" + std::to_string(id);
}

auto describe = [](const auto& value) {         // generic lambda: a template call operator
    return sizeof(value);
};

constexpr int mask = 0b1111'0000;               // binary literal with a digit separator

constexpr int factorial(int n) {                // loops and locals now allowed in constexpr
    int result = 1;
    for (int i = 2; i <= n; ++i) result *= i;
    return result;
}
```

- Return type deduction: ordinary functions can return `auto`, not just lambdas.
- Generic lambdas: `auto` parameters make the lambda's call operator a template.
- Literals: binary literals (`0b1010`) and the `'` digit separator.
- Library: `std::make_unique`, `std::exchange`, and `std::shared_timed_mutex`.

### C++17 language changes

```cpp
void lookup(const std::map<std::string, int>& ports) {
    if (auto it = ports.find("ssh"); it != ports.end()) {    // it is scoped to the if statement
        std::printf("ssh on %d\n", it->second);
    }
    std::pair p{1, 2.5};                                     // CTAD: deduces std::pair<int, double>
    (void)p;
}

struct Config {
    static inline int instances = 0;                         // inline variable: defined in the header
};

namespace storage::io { void flush(); }                      // nested namespace definition
```

- Statement initializers: `if` and `switch` can declare a variable scoped to that statement.
- Class template argument deduction (CTAD): the compiler deduces a class template's arguments from its
  constructor arguments.
- `inline` variables: a header can define a global or static member once for the whole program. See
  [Keywords](keywords.md).
- Also added: fold expressions, `[[nodiscard]]` and `[[maybe_unused]]`, and `std::byte`.

### C++17 library changes

- `<filesystem>`: portable paths, directory iteration, and file operations, replacing platform-specific
  APIs.
- `std::shared_mutex`, `std::any`, and parallel overloads of standard algorithms (for example,
  `std::sort(std::execution::par, ...)`).

### What C++17 removed

- `std::auto_ptr`: deprecated in C++11 and removed in favor of `std::unique_ptr`.
- Dynamic exception specifications such as `void f() throw(std::bad_alloc)`: removed; the empty
  `throw()` form followed in C++20. `noexcept` replaces both.
- The `register` keyword and trigraphs: removed.

## 4. C++20 and C++23: expressing intent

??? note "Overview"

    --8<-- "guides/cpp_overview/versions.md:cpp20_23"

### More of C++20

```cpp
struct Version {
    int major = 0;
    int minor = 0;
    auto operator<=>(const Version&) const = default;   // all six comparisons generated
    bool operator==(const Version&) const = default;
};

std::vector<int> even_squares(const std::vector<int>& v) {
    return v | std::views::filter([](int x) { return x % 2 == 0; })
             | std::views::transform([](int x) { return x * x; })
             | std::ranges::to<std::vector>();          // C++23: materialize the view
}

struct Endpoint { std::string host; int port; };
Endpoint local{.host = "localhost", .port = 8080};       // designated initializers
```

- Three-way comparison: a defaulted `operator<=>` compares members in declaration order and generates
  `<`, `<=`, `>`, and `>=`; a defaulted `operator==` generates `!=`.
- Coroutines: functions that suspend with `co_await` or `co_yield` and resume later. The language
  provides the mechanism; libraries provide the generator and task types built on it.
- Modules: `export module` and `import` replace textual inclusion for code that adopts them. Support
  needs the compiler, standard library, and build system to cooperate. See
  [Build & Toolchain](build-toolchain.md).
- Smaller additions: `std::format`, `std::source_location`, `constinit`, and `<bit>` utilities such as
  `std::bit_cast` and `std::popcount`.

### More of C++23

```cpp
struct Counter {
    int value = 0;
    auto&& get(this auto&& self) {                       // deducing this: one function for
        return std::forward<decltype(self)>(self).value; // const, non-const, lvalue, and rvalue
    }
};

void cpp23() {
    std::print("{} items\n", 3);                        // formatted output without iostream
    std::flat_map<std::string, int> sorted_ports;       // sorted keys in contiguous storage
    sorted_ports["http"] = 80;
    enum class Level { Low, High };
    auto raw = std::to_underlying(Level::High);          // 1
    (void)raw;
}
```

- Deducing `this`: an explicit object parameter replaces the four overloads (`const`, non-`const`,
  `&`, `&&`) a member function previously needed to preserve the object's category.
- `std::print` and `std::println`: formatted output with `std::format` syntax, checked at compile
  time.
- Containers: `std::flat_map` and `std::flat_set` keep sorted elements in contiguous storage for
  faster lookup and iteration; `std::mdspan` is a multidimensional view.
- Utilities: `std::to_underlying`, `std::unreachable`, `std::byteswap`, and `std::ranges::to`.

### After C++23

The next standard, C++26, has its feature set finalized. Its headline additions include static
reflection (programs that inspect their own types at compile time), contracts (preconditions and
postconditions on functions), and `std::execution` for structured asynchronous work. As with every
standard, compiler support will arrive feature by feature over several years.

## 5. How a standard is made and adopted

The standard is written by the ISO committee WG21, which works on a three-year release train: features
that are ready ship, and features that are not wait for the next release instead of delaying it.

```cpp
#if __has_include(<expected>)
#include <expected>
#endif

#if defined(__cpp_lib_expected) && __cpp_lib_expected >= 202211L
using Result = std::expected<int, std::string>;        // use the standard type when available
#else
struct Result { int value; std::string error; };       // fallback for older libraries
#endif

constexpr long language_version = __cplusplus;          // 202302L when compiled with -std=c++23
```

- Selecting a standard: compilers take a flag such as `-std=c++20` (GCC and Clang) or `/std:c++20`
  (MSVC). `__cplusplus` reports the selected version: `201103L`, `201402L`, `201703L`, `202002L`, or
  `202302L`.
- Feature-test macros: each feature has a macro, such as `__cpp_concepts` for the language feature or
  `__cpp_lib_expected` for the library feature, defined once the implementation supports it. Checking
  the macro is more reliable than checking the version number, because support arrives feature by
  feature.
- Support lag: the compiler front end, the standard library, and build tools each implement a
  standard on their own schedule. Modules, for example, needed changes in all three.

### Upgrading a codebase

- Compile first, then modernize: switching the `-std` flag rarely requires code changes, because
  removals are few and preceded by deprecation. The exceptions are the removed features listed above
  and newly reserved keywords such as `concept` and `requires`.
- ABI boundaries: a new standard does not by itself change the binary interface, but standard library
  changes can, as with GCC's `std::string` transition. Libraries shared as binaries should be built
  with compatible settings. See [Build & Toolchain](build-toolchain.md).
- Tooling: `clang-tidy` has `modernize-*` checks that rewrite older idioms, such as replacing `NULL`
  with `nullptr` or index loops with range-based `for`.

> A team targeting both a current desktop compiler and an older embedded toolchain can adopt C++20
> features on the desktop build by guarding them with feature-test macros, while the embedded build
> keeps compiling with its C++17 fallback until its toolchain catches up.

## Choosing a standard

??? note "Overview"

    --8<-- "guides/cpp_overview/versions.md:choosing"

Check individual features with feature-test macros rather than assuming a compiler supports every
part of the standard its `-std` flag names, and keep libraries that are shared as binaries on
compatible standard library settings.

## C++ References

Standards and support

- [C++11](https://en.cppreference.com/cpp/11), [C++14](https://en.cppreference.com/cpp/14), [C++17](https://en.cppreference.com/cpp/17), [C++20](https://en.cppreference.com/cpp/20), [C++23](https://en.cppreference.com/cpp/23), [C++26](https://en.cppreference.com/cpp/26)
- [Compiler support by feature](https://en.cppreference.com/cpp/compiler_support)
- [Feature testing](https://en.cppreference.com/cpp/feature_test)
- [Standard library headers](https://en.cppreference.com/cpp/header)

Language

- [References, including rvalue references](https://en.cppreference.com/cpp/language/reference)
- [`constexpr`](https://en.cppreference.com/cpp/language/constexpr), [`constinit`](https://en.cppreference.com/cpp/language/constinit), and [`noexcept`](https://en.cppreference.com/cpp/language/noexcept_spec)
- [Memory model](https://en.cppreference.com/cpp/language/memory_model)
- [Function return type deduction](https://en.cppreference.com/cpp/language/function)
- [Integer literals](https://en.cppreference.com/cpp/language/integer_literal)
- [`if` statement with initializer](https://en.cppreference.com/cpp/language/if)
- [Class template argument deduction](https://en.cppreference.com/cpp/language/class_template_argument_deduction)
- [`inline` specifier](https://en.cppreference.com/cpp/language/inline)
- [Namespaces](https://en.cppreference.com/cpp/language/namespace)
- [Fold expressions](https://en.cppreference.com/cpp/language/fold)
- [Default comparisons and `<=>`](https://en.cppreference.com/cpp/language/default_comparisons)
- [Coroutines](https://en.cppreference.com/cpp/language/coroutines) and [modules](https://en.cppreference.com/cpp/language/modules)
- [Aggregate initialization, including designated initializers](https://en.cppreference.com/cpp/language/aggregate_initialization)
- [Explicit object parameters (deducing `this`)](https://en.cppreference.com/cpp/language/member_functions)
- [`__has_include` and conditional inclusion](https://en.cppreference.com/cpp/preprocessor/include)
- [Predefined macros, including `__cplusplus`](https://en.cppreference.com/cpp/preprocessor/replace)

Library

- [Iterator library](https://en.cppreference.com/cpp/iterator) and [algorithms](https://en.cppreference.com/cpp/algorithm)
- [`std::auto_ptr`](https://en.cppreference.com/cpp/memory/auto_ptr), [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr), [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique)
- [`std::thread`](https://en.cppreference.com/cpp/thread/thread) and [`std::atomic`](https://en.cppreference.com/cpp/atomic/atomic)
- [`std::exchange`](https://en.cppreference.com/cpp/utility/exchange), [`std::shared_timed_mutex`](https://en.cppreference.com/cpp/thread/shared_timed_mutex), [`std::shared_mutex`](https://en.cppreference.com/cpp/thread/shared_mutex)
- [`std::any`](https://en.cppreference.com/cpp/utility/any) and [`std::byte`](https://en.cppreference.com/cpp/types/byte)
- [Filesystem library](https://en.cppreference.com/cpp/filesystem)
- [Execution policies](https://en.cppreference.com/cpp/algorithm/execution_policy_tag_t)
- [`std::views::filter`](https://en.cppreference.com/cpp/ranges/filter_view), [`std::views::transform`](https://en.cppreference.com/cpp/ranges/transform_view), [`std::ranges::to`](https://en.cppreference.com/cpp/ranges/to)
- [`std::flat_map`](https://en.cppreference.com/cpp/container/flat_map) and [`std::mdspan`](https://en.cppreference.com/cpp/container/mdspan)
- [`std::format`](https://en.cppreference.com/cpp/utility/format/format) and [`std::print`](https://en.cppreference.com/cpp/io/print)
- [`std::source_location`](https://en.cppreference.com/cpp/utility/source_location), [`std::bit_cast`](https://en.cppreference.com/cpp/numeric/bit_cast), [`std::popcount`](https://en.cppreference.com/cpp/numeric/popcount)
- [`std::to_underlying`](https://en.cppreference.com/cpp/utility/to_underlying), [`std::unreachable`](https://en.cppreference.com/cpp/utility/unreachable), [`std::byteswap`](https://en.cppreference.com/cpp/numeric/byteswap)
