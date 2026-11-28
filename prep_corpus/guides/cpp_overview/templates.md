# Templates

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
A template is a blueprint the compiler uses to generate code for each type it is used with. Writing
`std::vector<int>` and `std::vector<std::string>` produces two separate, fully specialized versions
of the vector code, each compiled as if written by hand for that type. This lets C++ offer generic
libraries with no run-time penalty, at the cost of longer compile times, larger binaries, and error
messages that were historically hard to read.

| Tool | What it does | Introduced |
| ---- | ------------ | ---------- |
| Function and class templates | Generate code parameterized by types or constant values | C++98 |
| Specialization | Provide a different implementation for one specific type | C++98 |
| Variadic templates | Accept any number of template arguments | C++11 |
| SFINAE and `std::enable_if` | Remove an overload from consideration when a type does not fit | C++98 rule, C++11 library support |
| `constexpr` | Evaluate functions at compile time when their inputs are known | C++11, expanded through C++20 |
| Concepts | Name and check the requirements a template places on its types | C++20 |
<!-- --8<-- [end:intro] -->

## 1. How templates generate code

<!-- --8<-- [start:generation] -->
A template is not compiled on its own. The compiler generates code from it only when it sees the
template used with specific arguments, a step called instantiation.

```cpp
template <typename T>
T largest(T a, T b) { return a < b ? b : a; }

template <typename T, std::size_t N>      // a type parameter and a value parameter
struct FixedBuffer { T items[N]; };

int    i = largest(3, 7);                 // instantiates largest<int>
double d = largest(2.5, 1.5);             // instantiates largest<double>
FixedBuffer<char, 64> line;               // instantiates FixedBuffer<char, 64>
```

- Monomorphization: each distinct set of arguments produces its own copy of the code. Because the
  compiler sees the exact types, it can inline calls and optimize as aggressively as for
  non-generic code.
- Comparison with other languages: Java generics compile to one shared version that works on object
  references, so primitive values must be boxed into objects. C++ has no such indirection.
- Headers: the compiler needs the full template definition wherever it is instantiated, which is why
  templates are usually defined entirely in header files.

> `std::sort` is a template, so sorting a `std::vector<int>` produces code specialized for `int`
> with the comparison inlined. That is a large part of why it usually outperforms C's `qsort`, which
> calls the comparison through a function pointer.
<!-- --8<-- [end:generation] -->

[Go deeper →](../cpp_deep_dive/templates.md#1-how-templates-generate-code)

## 2. Specialization

<!-- --8<-- [start:specialization] -->
A specialization replaces the general template with a custom implementation for particular
arguments.

```cpp
template <typename T>
struct TypeName { static constexpr const char* value = "unknown"; };

template <>                                // full specialization for exactly int
struct TypeName<int> { static constexpr const char* value = "int"; };

template <typename T>                      // partial specialization for any pointer type
struct TypeName<T*> { static constexpr const char* value = "pointer"; };
```

- Full specialization: one exact type gets its own implementation, as `std::hash<std::string>` does.
- Partial specialization: a class template can be specialized for a family of types, such as all
  pointer types `T*`.

> To use a custom `Point` type as a key in `std::unordered_map`, you specialize `std::hash<Point>`.
> The standard container picks up your specialization automatically without any change to the
> container itself.
<!-- --8<-- [end:specialization] -->

[Go deeper →](../cpp_deep_dive/templates.md#2-specialization)

## 3. Variadic templates

<!-- --8<-- [start:variadic] -->
A variadic template accepts any number of arguments, collected into a parameter pack.

```cpp
template <typename... Args>
std::size_t count_args(const Args&...) { return sizeof...(Args); }

template <typename... Args>
auto sum(const Args&... values) { return (values + ...); }   // C++17 fold expression

std::size_t three = count_args(1, "two", 3.0);   // 3
int six = sum(1, 2, 3);                          // 6
```

- Parameter pack: `Args...` stands for zero or more types, and `values...` for the matching
  arguments.
- Use: this is how `std::make_unique`, `std::tuple`, and `std::format` accept arbitrary argument
  lists while keeping every type known at compile time.

> A logging function like `log("user", id, "logged in from", address)` can accept any mix of
> argument types and count, while still checking each argument's type at compile time, as
> `std::format` does.
<!-- --8<-- [end:variadic] -->

[Go deeper →](../cpp_deep_dive/templates.md#3-variadic-templates)

## 4. Constraining templates: SFINAE

<!-- --8<-- [start:sfinae] -->
Templates accept any type by default, and a type that lacks a required operation fails deep inside
the template's body with a long error.

```cpp
template <typename T, typename = std::enable_if_t<std::is_integral_v<T>>>
T twice(T value) { return value * 2; }

int ok = twice(21);        // compiles
// twice(1.5);             // error: no matching function; the overload was removed
```

- The rule: SFINAE ("substitution failure is not an error") means that if substituting a type into a
  function template's signature produces invalid code, that overload is silently discarded instead of
  causing an error.
- Use: `std::enable_if` builds on this rule to enable an overload only for certain types, as shown
  above for integral types.
- Drawback: the resulting code is hard to read, and the error messages when no overload matches
  remain difficult to interpret.

> Before C++20, libraries used `std::enable_if` to offer one overload of a serializer for arithmetic
> types that writes raw bytes, and another for containers that writes element by element.
<!-- --8<-- [end:sfinae] -->

[Go deeper →](../cpp_deep_dive/templates.md#4-constraining-templates-sfinae)

## 5. Concepts

<!-- --8<-- [start:concepts] -->
A concept is a named, reusable requirement on template arguments, checked at the point where the
template is used.

```cpp
template <std::integral T>
T gcd(T a, T b) { return b == 0 ? a : gcd(b, a % b); }
// gcd(1.5, 2.5) fails with "constraints not satisfied" instead of an error about operator%

template <typename T>
concept Resettable = requires(T t) { t.reset(); };   // a custom concept

void clear(Resettable auto& item) { item.reset(); }
```

- Readability: the requirement is written in the declaration, such as
  `template <std::integral T>`, rather than hidden in a default template argument.
- Diagnostics: when a type does not satisfy a concept, the compiler reports which requirement failed
  instead of an error from deep inside the template body.
- Standard concepts: `<concepts>` provides common ones such as `std::integral`,
  `std::copyable`, and `std::invocable`, and `requires` expressions define new ones.

> A numeric statistics function declared as `template <std::floating_point T> T mean(std::span<const
> T>)` documents in its signature that it only works with `float` and `double`, and rejects `int`
> with a clear message instead of silently truncating results.
<!-- --8<-- [end:concepts] -->

[Go deeper →](../cpp_deep_dive/templates.md#5-concepts)

## 6. `constexpr`: running code at compile time

<!-- --8<-- [start:constexpr] -->
`constexpr` marks functions and variables that can be evaluated by the compiler while it builds the
program.

```cpp
constexpr std::uint64_t kib(std::uint64_t n) { return n * 1024; }

constexpr auto block_size = kib(4);        // computed by the compiler: 4096
std::array<char, kib(1)> header{};         // usable where a constant is required

constinit int log_level = 2;               // initialized at compile time, but still modifiable

std::uint64_t at_runtime(std::uint64_t n) { return kib(n); }   // same function, run time
```

- Effect: a `constexpr` function called with values known at compile time can produce its result as
  a constant, so the work costs nothing at run time.
- Flexibility: the same function can still run at run time when called with values that are only
  known then. A `constexpr` variable, by contrast, must be computed at compile time.
- `constinit` (C++20): requires a static variable to be initialized at compile time without making
  it `const`, which rules out the static initialization order problem described in
  [Memory](memory.md).

> A lookup table such as a CRC-32 checksum table can be generated by a `constexpr` function, so the
> 256 entries are computed during the build and stored in the binary instead of being recalculated
> every time the program starts.
<!-- --8<-- [end:constexpr] -->

[Go deeper →](../cpp_deep_dive/templates.md#6-constexpr-running-code-at-compile-time)

## 7. Type traits

<!-- --8<-- [start:traits] -->
Type traits are templates in `<type_traits>` that answer questions about types, or transform them, at
compile time.

```cpp
static_assert(std::is_integral_v<int>);
static_assert(!std::is_integral_v<double>);
static_assert(std::is_same_v<std::remove_reference_t<int&>, int>);
static_assert(std::is_same_v<std::decay_t<const int[4]>, const int*>);

template <typename T>
void copy_items(T* dst, const T* src, std::size_t n) {
    if (std::is_trivially_copyable_v<T>) {
        std::memcpy(dst, src, n * sizeof(T));   // raw bytes: fastest path
    } else {
        std::copy(src, src + n, dst);           // calls each element's copy assignment
    }
}
```

- Queries: `std::is_integral_v<T>` or `std::is_trivially_copyable_v<T>` evaluate to `true` or `false`.
- Transformations: `std::remove_reference_t<T>` or `std::decay_t<T>` produce a related type.
- Use: traits let generic code choose a faster implementation, such as copying raw bytes with
  `memcpy` for trivially copyable types.

> Standard algorithms such as `std::copy` check `std::is_trivially_copyable` internally. Copying a
> vector of plain structs becomes a single `memmove`, while a vector of strings still copies each
> element properly.
<!-- --8<-- [end:traits] -->

[Go deeper →](../cpp_deep_dive/templates.md#7-type-traits)

## Writing templates well

<!-- --8<-- [start:choosing] -->
Reach for a template when the same algorithm applies to many types and performance matters. Constrain
every template parameter with a concept so misuse produces a clear error, prefer concepts over SFINAE
in new code, and keep in mind that each instantiation adds compile time and binary size.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Templates](https://en.cppreference.com/cpp/language/templates)
- [Function templates](https://en.cppreference.com/cpp/language/function_template) and [class templates](https://en.cppreference.com/cpp/language/class_template)
- [Template parameters and arguments](https://en.cppreference.com/cpp/language/template_parameters)
- [Explicit (full) specialization](https://en.cppreference.com/cpp/language/template_specialization) and [partial specialization](https://en.cppreference.com/cpp/language/partial_specialization)
- [Parameter packs](https://en.cppreference.com/cpp/language/pack), [`sizeof...`](https://en.cppreference.com/cpp/language/sizeof...), and [fold expressions](https://en.cppreference.com/cpp/language/fold)
- [SFINAE](https://en.cppreference.com/cpp/language/sfinae)
- [Constraints and concepts](https://en.cppreference.com/cpp/language/constraints) and [`requires` expressions](https://en.cppreference.com/cpp/language/requires)
- [`constexpr`](https://en.cppreference.com/cpp/language/constexpr) and [`constinit`](https://en.cppreference.com/cpp/language/constinit)
- [Dependent names and two-phase lookup](https://en.cppreference.com/cpp/language/dependent_name)
- [Curiously Recurring Template Pattern](https://en.cppreference.com/cpp/language/crtp)

Library

- [Concepts library](https://en.cppreference.com/cpp/concepts), including [`std::integral`](https://en.cppreference.com/cpp/concepts/integral), [`std::copyable`](https://en.cppreference.com/cpp/concepts/copyable), and [`std::invocable`](https://en.cppreference.com/cpp/concepts/invocable)
- [`<type_traits>`](https://en.cppreference.com/cpp/header/type_traits)
- [`std::enable_if`](https://en.cppreference.com/cpp/types/enable_if)
- [`std::is_integral`](https://en.cppreference.com/cpp/types/is_integral), [`std::is_same`](https://en.cppreference.com/cpp/types/is_same), [`std::is_trivially_copyable`](https://en.cppreference.com/cpp/types/is_trivially_copyable)
- [`std::remove_reference`](https://en.cppreference.com/cpp/types/remove_reference) and [`std::decay`](https://en.cppreference.com/cpp/types/decay)
- [`std::hash`](https://en.cppreference.com/cpp/utility/hash)
- [`std::memcpy`](https://en.cppreference.com/cpp/string/byte/memcpy) and [`std::copy`](https://en.cppreference.com/cpp/algorithm/copy)
