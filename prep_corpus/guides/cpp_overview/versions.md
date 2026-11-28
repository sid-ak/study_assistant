# Versions

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
C++ is designed around one trade: it gives the programmer direct control over memory and hardware
resources, and in return the programmer takes on responsibility for correctness that languages with
a garbage collector or a managed runtime handle automatically. Each revision of the standard has
tried to make correct code easier to write without giving up that control or adding hidden runtime
cost. Knowing which standard a codebase targets tells you which tools are available to it.

The language is defined by an ISO standard, revised every three years since 2011. Compilers
implement each standard gradually, so a feature can exist on paper well before a given toolchain
supports it.

| Standard | Headline additions | Problem they addressed |
| -------- | ------------------ | ---------------------- |
| C++98/03 | Classes, templates, the Standard Template Library (STL), exceptions | Reusable, type-safe abstractions on top of C |
| C++11 | Move semantics, smart pointers, `auto`, lambdas, `std::thread`, a defined threading memory model | Expensive copies, manual `delete`, and no portable threading |
| C++14 | `std::make_unique`, generic lambdas, relaxed `constexpr` | Gaps left by C++11 |
| C++17 | `std::optional`, `std::variant`, `std::string_view`, structured bindings, guaranteed copy elision | Clearer ways to express "maybe a value", "one of several types", and "borrowed text" |
| C++20 | Concepts, ranges, coroutines, modules, `std::span`, `std::jthread` | Readable template constraints and composable algorithms |
| C++23 | `std::expected`, `std::print`, `std::mdspan`, deducing `this` | Value-based error handling and simpler formatted output |
<!-- --8<-- [end:intro] -->

## 1. C++98: the foundation

<!-- --8<-- [start:cpp98] -->
The first standard combined C's low-level model with classes and templates.

```cpp
// C++98 style: manual cleanup and an output parameter to avoid copying the result
void load_names(std::vector<std::string>& out) {
    std::string* temp = new std::string("example");
    out.push_back(*temp);
    delete temp;                  // skipped entirely if push_back throws
}
```

- Resource management: memory was released with explicit `delete`. Any code path that returned
  early or threw an exception could skip that call and leak.
- Copying: returning a large object from a function copied it, so APIs often used output parameters
  instead to avoid the cost.

> Many long-lived C++ codebases still contain C++98-era modules full of hand-written `delete` calls
> and output parameters. Reading such code, the typical bug to look for is an early `return` added
> years later that skips the cleanup at the bottom of the function.
<!-- --8<-- [end:cpp98] -->

[Go deeper →](../cpp_deep_dive/versions.md#1-c98-and-c03-the-foundation)

## 2. C++11: modern C++ begins

<!-- --8<-- [start:cpp11] -->
C++11 changed how everyday code is written, which is why "modern C++" usually means C++11 or later.

```cpp
std::vector<std::string> load_names() {
    auto temp = std::make_shared<std::string>("example");   // released automatically
    std::vector<std::string> names{*temp};
    return names;                                            // moved, not copied
}

void sort_by_length(std::vector<std::string>& v) {
    std::sort(v.begin(), v.end(),
              [](const std::string& a, const std::string& b) { return a.size() < b.size(); });
}
```

- Move semantics: an object can hand its internal resources to another object instead of
  duplicating them, which makes returning large values cheap. See
  [Value Semantics](value-semantics.md).
- Smart pointers: `std::unique_ptr` and `std::shared_ptr` release memory automatically when their
  owners go away. See [Ownership](ownership.md).
- Lambdas and `auto`: small functions can be written inline where they are used, and the compiler
  deduces variable types from their initializers.
- Threading: before C++11 the standard did not acknowledge that threads existed. C++11 defined
  what programs may assume when several threads touch memory, and added `std::thread`. See
  [Concurrency](concurrency.md).

> A codebase moving to C++11 commonly starts by replacing owning raw pointers with `std::unique_ptr`
> and output parameters with return values. Leaks from forgotten `delete` calls become impossible in
> the converted code, with no added run-time cost.
<!-- --8<-- [end:cpp11] -->

[Go deeper →](../cpp_deep_dive/versions.md#2-c11-modern-c-begins)

## 3. C++14 and C++17: filling gaps

<!-- --8<-- [start:cpp14_17] -->
These releases refined C++11 and added vocabulary types — small standard types that express a common
intent directly.

```cpp
std::optional<int> find_port(std::string_view name) {
    if (name == "http") return 80;
    return std::nullopt;                      // "no value", instead of a sentinel like -1
}

void print_all(const std::map<std::string, int>& ports) {
    for (const auto& [name, port] : ports) {  // structured bindings
        std::printf("%s=%d\n", name.c_str(), port);
    }
}
```

- `std::optional<T>` holds either a `T` or nothing, replacing sentinel values such as `-1`.
- `std::string_view` refers to text owned by someone else without copying it.
- Structured bindings unpack a pair, tuple, or struct into named variables.
- Guaranteed copy elision means that returning a temporary never creates an intermediate copy.

> A configuration loader that returns `std::optional<std::string>` for a missing key lets every
> caller see, from the function signature alone, that the key may be absent, instead of discovering
> at run time that an empty string meant "not set".
<!-- --8<-- [end:cpp14_17] -->

[Go deeper →](../cpp_deep_dive/versions.md#3-c14-and-c17-filling-the-gaps)

## 4. C++20 and C++23: expressing intent

<!-- --8<-- [start:cpp20_23] -->
The most recent standards focus on making generic code readable and error handling explicit.

```cpp
template <std::integral T>                    // C++20 concept: only integer types accepted
T halve(T value) { return value / 2; }

std::expected<int, std::string> parse_positive(int raw) {   // C++23
    if (raw <= 0) return std::unexpected("value must be positive");
    return raw;
}

auto evens(const std::vector<int>& v) {       // C++20 ranges: a lazy, composable view
    return v | std::views::filter([](int x) { return x % 2 == 0; });
}
```

- Concepts name the requirements a template places on its types, which turns long template error
  messages into short ones. See [Templates](templates.md).
- Ranges let algorithms be composed with `|` and evaluated lazily, without writing index loops.
- `std::expected<T, E>` (C++23) holds either a result or an error, so a function can report failure
  without exceptions. See [Errors](errors.md).
- Toolchain lag: embedded compilers and long-lived enterprise codebases often trail the newest
  standard by several years.

> A game engine's math library can declare `template <std::floating_point T> struct Vec3`. A
> developer who accidentally writes `Vec3<int>` gets a one-line error naming the unmet requirement,
> instead of pages of errors from inside the square-root code.
<!-- --8<-- [end:cpp20_23] -->

[Go deeper →](../cpp_deep_dive/versions.md#4-c20-and-c23-expressing-intent)

## Choosing a standard

<!-- --8<-- [start:choosing] -->
Use the newest standard that every compiler in your build supports. Many established systems
codebases are primarily C with C++ in newer components; in that situation the practical approach is
to wrap existing C interfaces in small C++ types that manage their lifetime, rather than rewriting
the C code.
<!-- --8<-- [end:choosing] -->

## C++ References

Standards and support

- [C++11](https://en.cppreference.com/cpp/11), [C++14](https://en.cppreference.com/cpp/14), [C++17](https://en.cppreference.com/cpp/17), [C++20](https://en.cppreference.com/cpp/20), [C++23](https://en.cppreference.com/cpp/23)
- [Compiler support by feature](https://en.cppreference.com/cpp/compiler_support)

Language

- [Classes](https://en.cppreference.com/cpp/language/classes)
- [Templates](https://en.cppreference.com/cpp/language/templates)
- [Exceptions](https://en.cppreference.com/cpp/language/exceptions)
- [`auto` type deduction](https://en.cppreference.com/cpp/language/auto)
- [Lambda expressions](https://en.cppreference.com/cpp/language/lambda)
- [Move constructors](https://en.cppreference.com/cpp/language/move_constructor)
- [`constexpr`](https://en.cppreference.com/cpp/language/constexpr)
- [Structured bindings](https://en.cppreference.com/cpp/language/structured_binding)
- [Copy elision](https://en.cppreference.com/cpp/language/copy_elision)
- [Constraints and concepts](https://en.cppreference.com/cpp/language/constraints)
- [Coroutines](https://en.cppreference.com/cpp/language/coroutines)
- [Modules](https://en.cppreference.com/cpp/language/modules)
- [Default comparisons and `<=>`](https://en.cppreference.com/cpp/language/default_comparisons)
- [Explicit object parameters (deducing `this`)](https://en.cppreference.com/cpp/language/member_functions)

Library

- [Standard library headers](https://en.cppreference.com/cpp/header)
- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr), [`std::shared_ptr`](https://en.cppreference.com/cpp/memory/shared_ptr), [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique)
- [`std::thread`](https://en.cppreference.com/cpp/thread/thread) and [`std::jthread`](https://en.cppreference.com/cpp/thread/jthread)
- [`std::optional`](https://en.cppreference.com/cpp/utility/optional), [`std::variant`](https://en.cppreference.com/cpp/utility/variant), [`std::string_view`](https://en.cppreference.com/cpp/string/basic_string_view)
- [Ranges library](https://en.cppreference.com/cpp/ranges) and [`std::views::filter`](https://en.cppreference.com/cpp/ranges/filter_view)
- [`std::span`](https://en.cppreference.com/cpp/container/span) and [`std::mdspan`](https://en.cppreference.com/cpp/container/mdspan)
- [`std::expected`](https://en.cppreference.com/cpp/utility/expected)
- [`std::print`](https://en.cppreference.com/cpp/io/print)
- [`std::sort`](https://en.cppreference.com/cpp/algorithm/sort)
