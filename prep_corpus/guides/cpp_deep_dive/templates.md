# Templates

> Part of the [C++ Deep Dive](README.md) · Overview: [Templates](../cpp_overview/templates.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:intro"

This page covers how the compiler actually processes templates: two-phase name lookup, controlling
where instantiations happen, why function templates should be overloaded rather than specialized, how
packs expand, the "immediate context" rule behind SFINAE, how constraints are ordered, what can and
cannot run at compile time, and how type traits are built. Static polymorphism with CRTP is covered in
[Objects](objects.md).

## 1. How templates generate code

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:generation"

### Monomorphization compared with other approaches

- C: one function per type, or a macro with no type checking.
- Java and C#: one shared implementation working through a common interface. Java boxes primitive values
  into objects; C# generates specialized code for value types at run time. Either way, calls on generic
  values usually go through an indirection.
- C++: a separate, fully typed copy of the code for each set of template arguments, generated at compile
  time. The trade is compile time and binary size in exchange for no run-time cost.

### Two-phase name lookup

```cpp
template <typename Container>
typename Container::value_type first(const Container& c) {   // typename: value_type is a type
    return *c.begin();
}

template <typename T>
struct Wrapper {
    template <typename U> U get() const { return U{}; }
};

template <typename T>
int read(const Wrapper<T>& w) {
    return w.template get<int>();     // template: get is a member template, not a less-than comparison
}
```

- Phase one, at the template's definition: the compiler checks everything that does not depend on the
  template parameters, such as calls to non-template functions and syntax errors.
- Phase two, at instantiation: names that depend on the parameters (dependent names) are looked up once
  the actual types are known.
- The ambiguity: at definition time, `Container::value_type` could be a type or a static data member,
  and `w.get<int>()` could be a comparison. `typename` and `template` tell the parser which one is
  meant. C++20 made `typename` optional in several places where only a type is possible, such as return
  types and `using` aliases.

### Controlling where instantiation happens

```cpp
// matrix.h
template <typename T>
struct Matrix {
    T determinant() const { return T{}; }
};
extern template struct Matrix<double>;    // every includer: do not instantiate Matrix<double> here

// matrix.cpp
template struct Matrix<double>;           // instantiate it exactly once, in this file
```

- Default behavior: every translation unit that uses `Matrix<double>` instantiates it separately, and the
  linker discards the duplicates. Heavily used templates are compiled many times over.
- Explicit instantiation declaration (`extern template`): tells includers the instantiation exists
  elsewhere, so they skip generating it.
- Explicit instantiation definition: forces the instantiation in one file. Together these can reduce
  build time for large, commonly used templates. See [Build & Toolchain](build-toolchain.md).

> The C++ standard library implementation in GCC (libstdc++) explicitly instantiates common
> specializations such as `std::basic_string<char>` inside the shared library and declares them
> `extern template` in its headers, so programs do not recompile the string implementation in every
> source file.

## 2. Specialization

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:specialization"

### Full and partial specialization

```cpp
template <typename T>
struct Describe { static constexpr const char* value = "value"; };

template <>
struct Describe<bool> { static constexpr const char* value = "boolean"; };      // full: exactly bool

template <typename T>
struct Describe<T*> { static constexpr const char* value = "pointer"; };        // partial: any pointer

template <typename T, typename Alloc>
struct Describe<std::vector<T, Alloc>> { static constexpr const char* value = "vector"; };   // any vector
```

- Full specialization fixes every template argument.
- Partial specialization fixes a pattern, such as "any pointer" or "any vector". Only class and variable
  templates can be partially specialized.
- Selection: the compiler picks the most specialized matching version.

### Overload function templates instead of specializing them

```cpp
template <typename T> void handle(T)          { std::puts("generic"); }
template <>           void handle<int*>(int*) { std::puts("specialization for int*"); }
template <typename T> void handle(T*)         { std::puts("overload for pointers"); }

void call() {
    int* p = nullptr;
    handle(p);        // prints "overload for pointers"
}
```

- Mechanism: overload resolution first chooses among the primary templates (`handle(T)` and
  `handle(T*)`), and `handle(T*)` is more specialized. Only then are specializations of the chosen
  primary considered. The `int*` specialization belongs to `handle(T)`, which lost, so it is never used.
- Guideline: for function templates, write overloads. Reserve explicit specialization for class
  templates.

### Specializing standard library templates

```cpp
struct Point { int x; int y; };

template <>
struct std::hash<Point> {
    std::size_t operator()(const Point& p) const noexcept {
        return std::hash<int>{}(p.x) ^ (std::hash<int>{}(p.y) << 1);
    }
};

inline bool operator==(const Point& a, const Point& b) { return a.x == b.x && a.y == b.y; }
std::unordered_map<Point, int> grid;
```

- Allowed: specializing standard class templates such as `std::hash` for your own types.
- Not allowed: adding new declarations to namespace `std`, or specializing standard function templates.
  Those make the program's behavior undefined.

> Formatting libraries rely on specialization as their extension point: `std::format` and the `{fmt}`
> library format a user type once someone specializes `formatter<T>` for it, without the library knowing
> about the type in advance.

## 3. Variadic templates

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:variadic"

### Pack expansion

```cpp
void print_all() {}                                   // base case: nothing left

template <typename First, typename... Rest>
void print_all(const First& first, const Rest&... rest) {
    std::printf("%s ", std::to_string(first).c_str());
    print_all(rest...);                               // expand the remaining arguments
}

template <typename... Ts>
auto to_strings(const Ts&... values) {
    return std::vector<std::string>{std::to_string(values)...};   // pattern repeated per element
}
```

- Pattern expansion: `f(args)...` repeats the whole pattern `f(args)` once per pack element, separated by
  commas. The pattern can be any expression or type containing the pack.
- Recursion: before C++17, processing each element typically meant a recursive template peeling off one
  argument at a time, which creates one instantiation per step.

### Fold expressions

```cpp
template <typename... Ts>
auto sum(const Ts&... values) { return (values + ... + 0); }          // binary right fold with init

template <typename... Ts>
bool all_true(const Ts&... flags) { return (... && flags); }          // unary left fold

template <typename... Ts>
void print_line(const Ts&... values) {
    ((std::cout << values << ' '), ...);                               // comma fold: one statement per element
    std::cout << '\n';
}
```

- A fold expression (C++17) places a binary operator between every element, so `sum(1, 2, 3)` becomes
  `1 + (2 + (3 + 0))` with no recursion and no extra instantiations.
- Empty packs: a unary fold over an empty pack is only valid for `&&` (true), `||` (false), and the comma
  operator; other operators need an initial value.

> `std::tuple`, `std::variant`, and `std::make_shared` are all built on variadic templates. So are
> type-safe replacements for `printf`, such as `std::format`, which check every argument against the
> format string at compile time.

## 4. Constraining templates: SFINAE

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:sfinae"

### The immediate context

```cpp
template <typename T>
auto size_of(const T& c) -> decltype(c.size()) {   // failure here (signature): candidate removed
    return c.size();
}

std::size_t size_of(...) { return 0; }             // fallback for everything else

template <typename T>
std::size_t broken(const T& c) {
    return c.size();                               // failure here (body): a hard compile error
}

std::size_t a = size_of(std::vector<int>{1, 2});   // 2
std::size_t b = size_of(42);                       // 0: the template was removed, fallback chosen
```

- Rule: substitution failure removes a candidate only when the invalid type or expression appears in the
  immediate context of the substitution — the function's signature and template parameters. Errors
  inside the body happen after the compiler has committed to the candidate, and are real errors.
- Consequence: SFINAE-based constraints must be written in the return type, parameter types, or template
  parameter list.

### The detection idiom

```cpp
template <typename T, typename = void>
struct has_serialize : std::false_type {};

template <typename T>
struct has_serialize<T, std::void_t<decltype(std::declval<const T&>().serialize())>> : std::true_type {};

struct Row { std::string serialize() const { return "row"; } };

static_assert(has_serialize<Row>::value);
static_assert(!has_serialize<int>::value);
```

- `std::declval<T>()` produces an expression of type `T` for use in unevaluated contexts such as
  `decltype`, without needing a constructor.
- `std::void_t<...>` becomes `void` when every type inside it is valid. If `serialize()` does not exist,
  substitution fails, the partial specialization is removed, and the primary template's `false_type`
  applies.

> Libraries written before C++20, such as older versions of range-v3 and much of Boost, contain large
> amounts of `enable_if` and detection-idiom code. Most of it translates directly into concepts when a
> codebase moves to C++20.

## 5. Concepts

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:concepts"

### `requires` expressions

```cpp
template <typename T>
concept Serializable = requires(const T& value) {
    { value.serialize() } -> std::convertible_to<std::string>;   // expression plus a return requirement
    typename T::id_type;                                         // a nested type must exist
    requires sizeof(T) <= 64;                                    // a nested boolean requirement
};

struct Order {
    using id_type = int;
    int id = 0;
    std::string serialize() const { return std::to_string(id); }
};

static_assert(Serializable<Order>);
```

- Simple requirements check that an expression is valid; compound requirements (`{ expr } -> concept`)
  also constrain its result type; type requirements check that a type exists; nested requirements check a
  boolean condition.
- Diagnostics: the check happens where the template is used, so errors name the unsatisfied requirement
  instead of reporting a failure deep inside the template body.

### Constraint ordering

```cpp
template <typename T> requires std::integral<T>
const char* classify(T) { return "integral"; }

template <typename T> requires std::integral<T> && std::signed_integral<T>
const char* classify(T) { return "signed integral"; }

const char* u = classify(1u);   // "integral"
const char* s = classify(1);    // "signed integral": the more constrained overload wins
```

- Subsumption: when two constrained overloads both match, the one whose constraints logically include the
  other's is preferred. The compiler compares the constraints by breaking them into their named
  concepts, so the comparison works only when the constraints are written in terms of the same concepts.
- Replaces `enable_if` tricks that previously needed mutually exclusive conditions on every overload.

### Four ways to write a constraint

```cpp
template <typename T> requires std::integral<T> T twice_a(T x) { return 2 * x; }   // requires clause
template <std::integral T> T twice_b(T x) { return 2 * x; }                        // constrained parameter
template <typename T> T twice_c(T x) requires std::integral<T> { return 2 * x; }   // trailing requires
auto twice_d(std::integral auto x) { return 2 * x; }                               // abbreviated template
```

- All four are equivalent for a single constraint. The abbreviated form is concise for simple functions;
  a `requires` clause reads better when several parameters are related.

> The C++20 ranges library is specified almost entirely with concepts such as `std::ranges::range`,
> `std::ranges::random_access_range`, and `std::sortable`. Passing a `std::list` to `std::ranges::sort`
> produces an error that names the unsatisfied random-access requirement.

## 6. `constexpr`: running code at compile time

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:constexpr"

### `constexpr`, `consteval`, and `constinit`

```cpp
constexpr int square(int x) { return x * x; }       // may run at compile time or at run time
consteval int cube(int x) { return x * x * x; }     // must run at compile time
constinit int counter = square(4);                  // initialized at compile time, modifiable later

int at_runtime(int v) {
    int a = square(v);          // fine: square runs at run time
    // int b = cube(v);         // error: v is not a constant, and cube must be evaluated by the compiler
    return a + cube(3);         // fine: cube(3) is computed during compilation
}
```

| Keyword | Applies to | Guarantee |
| ------- | ---------- | --------- |
| `constexpr` function | Functions | Can be evaluated at compile time when its arguments are constants |
| `constexpr` variable | Variables | Initialized at compile time and `const` |
| `consteval` (C++20) | Functions | Every call must be evaluated at compile time |
| `constinit` (C++20) | Static and thread-local variables | Initialized at compile time, but not `const` |

### Compile-time evaluation catches undefined behavior

```cpp
constexpr int element(int index) {
    int values[2] = {1, 2};
    return values[index];
}

constexpr int ok = element(1);
// constexpr int bad = element(2);   // error: read past the end is not allowed in a constant expression
```

- The compiler evaluates constant expressions with an interpreter that checks every operation. Undefined
  behavior such as out-of-bounds access or signed overflow makes the expression non-constant, so it is
  reported as a compile error instead of silently producing a value.
- Consequence: running a function's tests in `static_assert` checks gives undefined-behavior detection
  for free, for the inputs tested.

### `if constexpr`

```cpp
template <typename T>
std::string describe(const T& value) {
    if constexpr (std::is_integral_v<T>) {
        return std::to_string(value);          // only instantiated when T is integral
    } else if constexpr (std::is_same_v<T, std::string>) {
        return value;
    } else {
        return value.serialize();              // only instantiated for other types
    }
}

std::string a = describe(42);
std::string b = describe(std::string("text"));
```

- Discarded branches: inside a template, the branch not taken is not instantiated, so it may contain code
  that would not compile for the current `T`. An ordinary `if` requires every branch to compile.
- Outside templates, discarded branches are still fully checked.
- Replaces tag dispatch and SFINAE overload sets for many compile-time choices.

### What can run at compile time

- C++11: a single `return` statement. C++14: loops, local variables, and multiple statements.
- C++20: `try` blocks, virtual functions, `std::vector` and `std::string` whose memory is released before
  evaluation ends, and `std::is_constant_evaluated()` to choose different code at compile time.
- C++23: `if consteval`, and `static constexpr` variables declared inside `constexpr` functions.
- Still not allowed: I/O, calls to non-`constexpr` functions, and memory allocated at compile time that
  survives into run time.

> Unit libraries such as mp-units compute dimensional analysis — checking that metres divided by seconds
> yields a velocity — entirely at compile time, so unit mismatches are build errors and the resulting
> machine code is ordinary arithmetic on numbers.

## 7. Type traits

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:traits"

### How traits are implemented

```cpp
template <typename T> struct my_is_pointer : std::false_type {};
template <typename T> struct my_is_pointer<T*> : std::true_type {};   // partial specialization

template <typename T> struct my_remove_const { using type = T; };
template <typename T> struct my_remove_const<const T> { using type = T; };

template <typename T> inline constexpr bool my_is_pointer_v = my_is_pointer<T>::value;
template <typename T> using my_remove_const_t = typename my_remove_const<T>::type;

static_assert(my_is_pointer_v<int*> && !my_is_pointer_v<int>);
static_assert(std::is_same_v<my_remove_const_t<const int>, int>);
```

- Queries inherit from `std::true_type` or `std::false_type` and expose `::value`; the `_v` variable
  templates (C++17) are shorthands.
- Transformations expose `::type`; the `_t` alias templates (C++14) are shorthands.
- Compiler intrinsics: some traits cannot be written in the language, because the answer is not visible
  to ordinary code — for example `std::is_trivially_copyable`, `std::is_standard_layout`, and
  `std::is_enum`. Standard libraries implement them with built-in compiler hooks.

### Guarding byte-level operations

```cpp
template <typename T>
bool write_record(std::FILE* file, const T& record) {
    static_assert(std::is_trivially_copyable_v<T>, "records must be trivially copyable");
    static_assert(std::is_standard_layout_v<T>, "records must have standard layout");
    return std::fwrite(&record, sizeof(T), 1, file) == 1;
}
```

- What the checks guarantee: the type has no virtual functions, no user-defined copy semantics, and a
  predictable member layout, so its bytes are a faithful copy of its value within this process.
- What they cannot guarantee: traits cannot detect pointer members, whose addresses are meaningless in
  another process, nor can they fix byte order and padding differences between machines. Data that leaves
  the process still needs explicit encoding. See [Objects](objects.md).

> Boost.Serialization's binary archives check the `is_bitwise_serializable` trait and write arrays of
> such types with a single bulk copy, falling back to one element at a time for everything else, with the
> choice made entirely at compile time.

## Writing templates well

??? note "Overview"

    --8<-- "guides/cpp_overview/templates.md:choosing"

For function templates, overload rather than specialize. Keep constraints in the signature where
failures are reported clearly, move validated logic into `constexpr` functions checked by `static_assert`,
and use `extern template` for heavily used instantiations that slow down builds.

## C++ References

Language

- [Templates](https://en.cppreference.com/cpp/language/templates), [function templates](https://en.cppreference.com/cpp/language/function_template), [class templates](https://en.cppreference.com/cpp/language/class_template)
- [Dependent names, `typename`, and `template` disambiguators](https://en.cppreference.com/cpp/language/dependent_name)
- [Explicit instantiation](https://en.cppreference.com/cpp/language/class_template)
- [Explicit specialization](https://en.cppreference.com/cpp/language/template_specialization) and [partial specialization](https://en.cppreference.com/cpp/language/partial_specialization)
- [Overload resolution of function templates](https://en.cppreference.com/cpp/language/function_template)
- [Extending namespace `std`](https://en.cppreference.com/cpp/language/extending_std)
- [Parameter packs](https://en.cppreference.com/cpp/language/pack), [fold expressions](https://en.cppreference.com/cpp/language/fold), [`sizeof...`](https://en.cppreference.com/cpp/language/sizeof...)
- [SFINAE](https://en.cppreference.com/cpp/language/sfinae) and [`decltype`](https://en.cppreference.com/cpp/language/decltype)
- [Constraints and concepts](https://en.cppreference.com/cpp/language/constraints) and [`requires` expressions](https://en.cppreference.com/cpp/language/requires)
- [Abbreviated function templates](https://en.cppreference.com/cpp/language/function_template)
- [`constexpr`](https://en.cppreference.com/cpp/language/constexpr), [`consteval`](https://en.cppreference.com/cpp/language/consteval), [`constinit`](https://en.cppreference.com/cpp/language/constinit)
- [Constant expressions](https://en.cppreference.com/cpp/language/constant_expression)
- [`if` statement, including `if constexpr` and `if consteval`](https://en.cppreference.com/cpp/language/if)
- [`static_assert`](https://en.cppreference.com/cpp/language/static_assert)

Library

- [Concepts library](https://en.cppreference.com/cpp/concepts): [`std::integral`](https://en.cppreference.com/cpp/concepts/integral), [`std::signed_integral`](https://en.cppreference.com/cpp/concepts/signed_integral), [`std::convertible_to`](https://en.cppreference.com/cpp/concepts/convertible_to)
- [`std::ranges::range`](https://en.cppreference.com/cpp/ranges/range) and [`std::sortable`](https://en.cppreference.com/cpp/iterator/sortable)
- [`<type_traits>`](https://en.cppreference.com/cpp/header/type_traits): [`std::true_type`](https://en.cppreference.com/cpp/types/integral_constant), [`std::is_same`](https://en.cppreference.com/cpp/types/is_same), [`std::is_integral`](https://en.cppreference.com/cpp/types/is_integral), [`std::is_pointer`](https://en.cppreference.com/cpp/types/is_pointer)
- [`std::is_trivially_copyable`](https://en.cppreference.com/cpp/types/is_trivially_copyable) and [`std::is_standard_layout`](https://en.cppreference.com/cpp/types/is_standard_layout)
- [`std::remove_const`](https://en.cppreference.com/cpp/types/remove_cv)
- [`std::enable_if`](https://en.cppreference.com/cpp/types/enable_if) and [`std::void_t`](https://en.cppreference.com/cpp/types/void_t)
- [`std::declval`](https://en.cppreference.com/cpp/utility/declval)
- [`std::is_constant_evaluated`](https://en.cppreference.com/cpp/types/is_constant_evaluated)
- [`std::hash`](https://en.cppreference.com/cpp/utility/hash)
- [`std::formatter`](https://en.cppreference.com/cpp/utility/format/formatter)
- [`std::tuple`](https://en.cppreference.com/cpp/utility/tuple)
