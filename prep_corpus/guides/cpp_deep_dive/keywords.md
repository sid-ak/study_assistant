# Keywords

> Part of the [C++ Deep Dive](README.md) · Overview: [Keywords](../cpp_overview/keywords.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:intro"

This page explains the mechanism behind each keyword: how `const` changes the type of `this`, the
difference between bitwise and logical constness, what the linker does with `static` and `inline`
definitions, which conversions `explicit` blocks, and what the compiler and library do differently
when a function is `noexcept`.

## 1. `const`

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:const"

### Reading declarations

```cpp
const int* a = nullptr;         // pointer to const int: *a is read-only, a can be re-pointed
int const* b = nullptr;         // identical to a
int* const c = nullptr;         // const pointer to int: *c is writable, c cannot be re-pointed
const int* const d = nullptr;   // neither can change

using IntPtr = int*;
const IntPtr e = nullptr;       // const applies to the pointer: this is int* const, not const int*
```

- Rule: `const` applies to what is immediately to its left, or to what is immediately to its right when
  nothing is to its left. Reading the declaration right to left gives its meaning.
- Aliases: `const` on a type alias applies to the aliased type as a whole, which is a common surprise
  with pointer aliases.

### How `const` member functions work

```cpp
class Buffer {
public:
    char& operator[](std::size_t i) { return data_[i]; }              // called on non-const Buffers
    const char& operator[](std::size_t i) const { return data_[i]; }  // called on const Buffers
    std::size_t size() const { return size_; }                        // this is const Buffer*
private:
    char data_[64] = {};
    std::size_t size_ = 64;
};

void read(const Buffer& b) {
    char first = b[0];              // chooses the const overload
    (void)first;
}
```

- Mechanism: a member function receives a hidden `this` pointer. Marking the function `const` makes
  `this` a pointer to `const`, so every member accessed through it is read-only.
- Overloading: because the type of `this` differs, a `const` and a non-`const` version of the same
  function are separate overloads. Containers use this to return a writable reference from a non-`const`
  object and a read-only one from a `const` object.

### Bitwise and logical constness

```cpp
class Report {
public:
    std::string summary() const {
        std::scoped_lock lock(mutex_);              // locking changes the mutex's bits
        if (!cached_) cached_ = build();            // filling the cache changes cached_'s bits
        return *cached_;
    }
private:
    std::string build() const { return "summary"; }
    mutable std::mutex mutex_;
    mutable std::optional<std::string> cached_;
};
```

- Bitwise constness: what the compiler enforces — no member's bits change.
- Logical constness: what callers care about — the object's observable value does not change.
- `mutable`: marks members that may change inside `const` functions because changing them does not
  change the observable value. Caches and mutexes are the legitimate cases.

### `const` and thread safety

- Library contract: the standard library guarantees that concurrent calls to `const` member functions
  of its types are safe, as long as no thread calls a non-`const` function on the same object at the
  same time.
- Consequence for your own types: callers will assume the same. A `const` member function that
  modifies `mutable` state without synchronization, as a lazily filled cache would, creates a data race
  that the signature hides. That is why `Report` above locks before touching `cached_`.

### `const` versus `constexpr`

```cpp
int read_setting() { return 8; }

const int runtime_value = read_setting();   // const, but only known at run time
constexpr int compile_value = 8;            // known at compile time, and implicitly const

std::array<int, compile_value> ok{};        // array size must be a constant expression
// std::array<int, runtime_value> bad{};    // error: not a constant expression
```

- `const` promises the value will not change after initialization.
- `constexpr` additionally requires the value to be computed at compile time. See
  [Templates](templates.md).

> The C++ Core Guidelines rule Con.2 recommends making member functions `const` by default. Static
> analyzers such as clang-tidy's `readability-make-member-function-const` find member functions that
> could be marked `const` but are not, which also exposes code that mutates state unexpectedly.

## 2. `static`

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:static"

### What connects the meanings

Every use of `static` describes something that exists once rather than once per call, once per object,
or once per file that could see it.

| Where `static` appears | What exists once | Effect |
| ---------------------- | ---------------- | ------ |
| A namespace-scope variable or function | One entity private to this translation unit | Internal linkage |
| A local variable | One variable for all calls | Static storage, initialized on first use |
| A data member | One variable for the whole class | Shared by all objects |
| A member function | One function with no object | No `this` pointer |

### Internal linkage and the linker

```cpp
// a.cpp
static int helper() { return 1; }        // internal linkage: invisible outside a.cpp
namespace { int other() { return 2; } }  // unnamed namespace: same effect, also works for types

// b.cpp could define its own helper() and other() without any conflict
```

- Without internal linkage: two source files that both define a function `helper` each export a symbol
  named `helper`, and the linker reports a duplicate symbol.
- Unnamed namespaces are the preferred modern form, because they also give classes and type aliases
  internal linkage, which `static` cannot.

### How function-local statics are initialized

```cpp
class Registry {
public:
    static Registry& instance() {
        static Registry registry;     // constructed on the first call, even with concurrent callers
        return registry;
    }
private:
    Registry() = default;
};
```

- Guard: the compiler emits a hidden flag and, on most platforms, a call into the runtime that locks
  during the first initialization. The first thread runs the constructor while others wait; afterwards
  each call only tests the flag.
- Exceptions: if the constructor throws, the variable is not considered initialized, and the next call
  tries again.
- Lifetime and destruction order are covered in [Memory](memory.md).

### Static data members

```cpp
class Connection {
public:
    static int open_count;                  // declaration only (before C++17 style)
    static inline int total_bytes = 0;      // C++17: declaration and definition in the class
    static constexpr int max_retries = 3;   // constexpr static members are implicitly inline
};

int Connection::open_count = 0;             // the one out-of-class definition, in exactly one .cpp file
```

- Why an out-of-class definition was needed: the in-class line only declares the variable. If the
  definition were in the header, every source file including it would define the variable, and the
  linker would see duplicates.
- C++17: `inline` static members may be defined in the class, relying on the same "identical
  definitions may repeat" rule as `inline` functions.

### Static member functions

```cpp
class Timer {
public:
    static void on_tick(void* context) {                     // usable as a C function pointer
        static_cast<Timer*>(context)->ticks_++;
    }
private:
    int ticks_ = 0;
};

using CCallback = void (*)(void*);
CCallback callback = &Timer::on_tick;                        // no object needed to take its address
```

- No `this`: a static member function cannot access non-static members directly, but it can access
  private members of an object it is given.
- C interoperability: its address is an ordinary function pointer, so it fits C APIs that take a
  `void (*)(void*)` callback plus a context pointer.

> Command-line tools often mark every helper function in a source file `static` or place them in an
> unnamed namespace. Besides avoiding name clashes, this lets the compiler see every caller, so it can
> inline the helper completely or remove it when unused, and warn when a helper is never called.

## 3. `inline`

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:inline"

### How the linker handles `inline` definitions

```cpp
// a.cpp
inline int version() { return 1; }
int from_a() { return version(); }
```

```cpp
// b.cpp
inline int version() { return 2; }      // different body: an ODR violation, and no diagnostic
int from_b() { return version(); }
```

- Mechanism: each translation unit that uses an `inline` function emits its own copy, marked so the
  linker keeps one copy and discards the rest instead of reporting a duplicate.
- The rule behind it: every definition must be identical (the One Definition Rule). The linker does not
  check this. In the example above, both `from_a()` and `from_b()` can end up calling whichever copy the
  linker kept; a test build returned 1 from both.
- Contrast: two ordinary (non-`inline`) definitions of the same function in different source files
  produce a "duplicate symbol" link error.

### What actually enables inlining

- Visibility: the compiler can only inline a call when the callee's definition is visible in the same
  translation unit, which is what defining `inline` functions in headers provides. Link-time
  optimization (LTO) extends this across translation units.
- The compiler's decision: whether to inline depends on the callee's size, how often it is called, and
  the optimization level, not on the keyword.
- Why inlining pays off: after inlining, the callee's code is specialized for the actual arguments, so
  constants propagate into it and branches that cannot be taken at that call site are removed. Skipping
  the call instruction itself is the smaller benefit.

### Forcing and preventing inlining

```cpp
[[gnu::always_inline]] inline int fast_path(int x) { return x + 1; }   // GCC and Clang
[[gnu::noinline]] void slow_path();                                      // keep out of hot callers
```

- Attributes: `[[gnu::always_inline]]` and `[[gnu::noinline]]` in GCC and Clang; MSVC uses `__forceinline`
  and `__declspec(noinline)`.
- Caution: forcing inlining everywhere enlarges code, which can push hot code out of the CPU's
  instruction cache. These attributes belong where a profile shows a benefit.

> Error-handling and logging paths are commonly marked `noinline` (and often `[[unlikely]]` at the
> branch) so that the rarely executed code stays out of the hot function, keeping the common path small
> enough to fit in fewer cache lines.

## 4. `explicit`

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:explicit"

### Which conversions `explicit` blocks

```cpp
class Buffer {
public:
    explicit Buffer(std::size_t size) : size_(size) {}
    std::size_t size() const { return size_; }
private:
    std::size_t size_;
};

void conversions() {
    Buffer direct(100);                 // direct initialization: allowed
    Buffer braced{100};                 // direct-list initialization: allowed
    auto cast = static_cast<Buffer>(100);   // explicit conversion: allowed
    // Buffer copy_init = 100;          // copy initialization: blocked
    // Buffer list_copy = {100};        // copy-list initialization: blocked
    (void)direct; (void)braced; (void)cast;
}
```

- Implicit conversions: C++ applies at most one user-defined conversion automatically to make an
  expression work. A non-`explicit` single-argument constructor is such a conversion.
- What `explicit` blocks: copy initialization (`T x = value;`), copy-list initialization, and implicit
  conversions in function arguments and return statements.
- What still works: direct initialization, braces without `=`, and casts, because the conversion is
  visible at those sites.

### `explicit operator bool`

```cpp
class Handle {
public:
    explicit operator bool() const { return fd_ >= 0; }
private:
    int fd_ = -1;
};

void test(const Handle& h) {
    if (h) {}                   // allowed: contextual conversion to bool
    bool ok = !h;               // allowed: operands of ! are contextually converted
    // int n = h;               // error: no implicit conversion to bool, and so none to int
    (void)ok;
}
```

- Contextual conversion: conditions of `if`, `while`, and `for`, operands of `!`, `&&`, `||`, and
  `?:`, and `static_assert` may use an `explicit operator bool`.
- Why it matters: a non-`explicit` `operator bool` lets an object convert to `bool` and then to `int`
  in arithmetic, so mistakes such as `handle + 1` compile.

### `explicit(condition)`

```cpp
template <typename T>
class Wrapper {
public:
    template <typename U>
    explicit(!std::is_convertible_v<U, T>) Wrapper(U&& value) : value_(std::forward<U>(value)) {}
private:
    T value_;
};

Wrapper<std::string> implicit_ok = "text";              // const char* converts to std::string implicitly
// Wrapper<std::string> blocked = std::string_view{};   // string_view does not: constructor is explicit
```

- C++20 lets a constructor be `explicit` only under a condition, so a wrapper can be implicitly
  constructible exactly when its contents are. `std::pair`, `std::tuple`, and `std::optional` use this.

> `std::chrono::duration` has an explicit constructor from a raw number, so passing `500` to a function
> that takes `std::chrono::milliseconds` does not compile. Callers must write `500ms` or
> `std::chrono::milliseconds(500)`, which prevents the classic mistake of passing seconds where
> milliseconds were expected.

## 5. `noexcept`

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:noexcept"

### What happens when the promise is broken

- Behavior: if an exception tries to leave a `noexcept` function, `std::terminate` is called. Whether the
  stack is unwound first is implementation-defined, so destructors of local objects may not run.
- Why so harsh: callers and the standard library make decisions that are only correct if the function
  truly cannot throw. A broken promise cannot be recovered from safely.

### What `noexcept` lets the compiler and library do

```cpp
struct Packet {
    std::vector<char> bytes;
};

static_assert(std::is_nothrow_move_constructible_v<Packet>);   // implicitly noexcept move

struct Risky {
    Risky() = default;
    Risky(Risky&&) {}                                            // user-written, not noexcept
};

static_assert(!std::is_nothrow_move_constructible_v<Risky>);    // vector<Risky> will copy on growth
```

- Library decisions: containers query traits such as `std::is_nothrow_move_constructible` and copy
  instead of moving during reallocation when moves might throw. See
  [Value Semantics](value-semantics.md).
- Code generation: a caller of a `noexcept` function does not need unwinding information for that call,
  which can reduce binary size and removes paths the optimizer would otherwise have to preserve.

### The `noexcept` operator and conditional `noexcept`

```cpp
template <typename T>
void swap_values(T& a, T& b) noexcept(std::is_nothrow_move_constructible_v<T> &&
                                      std::is_nothrow_move_assignable_v<T>) {
    T tmp = std::move(a);
    a = std::move(b);
    b = std::move(tmp);
}

bool can_swap_strings = noexcept(swap_values(std::declval<std::string&>(), std::declval<std::string&>()));
```

- `noexcept(expression)` as an operator evaluates, at compile time, whether the expression is declared
  not to throw. It does not evaluate the expression.
- Conditional specifications: `noexcept(condition)` lets a template promise non-throwing behavior
  exactly when the operations it uses are non-throwing.
- Implicit `noexcept`: destructors, and defaulted special member functions whose member operations are
  all non-throwing, are `noexcept` without being marked.

### Where not to use it

- Functions that allocate: `new` and container growth can throw `std::bad_alloc`, so a `noexcept`
  function that allocates turns an out-of-memory condition into immediate termination.
- Functions that report failure by throwing: marking them `noexcept` converts every recoverable error
  into a crash.
- Part of the type: since C++17, `noexcept` is part of a function's type, so a pointer to a `noexcept`
  function converts to an ordinary function pointer, but not the other way around.

> Codebases built with `-fno-exceptions`, common in games and embedded firmware, still benefit from
> marking move operations `noexcept`: the standard library's containers check the trait, not whether
> exceptions are enabled, when deciding whether to move or copy during reallocation.

## Using these keywords well

??? note "Overview"

    --8<-- "guides/cpp_overview/keywords.md:choosing"

Keep `const` member functions free of unsynchronized mutation, prefer unnamed namespaces for
file-private helpers, and make sure every `inline` definition of a name is identical, because the
linker will not tell you when they differ.

## C++ References

Language

- [`const` and `volatile`](https://en.cppreference.com/cpp/language/cv)
- [Member functions and `this`](https://en.cppreference.com/cpp/language/member_functions)
- [`mutable` and class members](https://en.cppreference.com/cpp/language/data_members)
- [`constexpr`](https://en.cppreference.com/cpp/language/constexpr)
- [Storage duration and linkage](https://en.cppreference.com/cpp/language/storage_duration)
- [Namespaces, including unnamed namespaces](https://en.cppreference.com/cpp/language/namespace)
- [Static members](https://en.cppreference.com/cpp/language/static)
- [`inline` specifier](https://en.cppreference.com/cpp/language/inline)
- [Definitions and the One Definition Rule](https://en.cppreference.com/cpp/language/definition)
- [Attributes, including `[[likely]]` and `[[unlikely]]`](https://en.cppreference.com/cpp/language/attributes)
- [`explicit` specifier](https://en.cppreference.com/cpp/language/explicit)
- [Converting constructors](https://en.cppreference.com/cpp/language/converting_constructor)
- [Implicit conversions and contextual conversion](https://en.cppreference.com/cpp/language/implicit_conversion)
- [Copy initialization](https://en.cppreference.com/cpp/language/copy_initialization) and [direct initialization](https://en.cppreference.com/cpp/language/direct_initialization)
- [User-defined conversion functions](https://en.cppreference.com/cpp/language/cast_operator)
- [`noexcept` specifier](https://en.cppreference.com/cpp/language/noexcept_spec) and [`noexcept` operator](https://en.cppreference.com/cpp/language/noexcept)
- [Type alias](https://en.cppreference.com/cpp/language/type_alias)

Library

- [`std::is_nothrow_move_constructible`](https://en.cppreference.com/cpp/types/is_move_constructible) and [`std::is_nothrow_move_assignable`](https://en.cppreference.com/cpp/types/is_move_assignable)
- [`std::is_convertible`](https://en.cppreference.com/cpp/types/is_convertible)
- [`std::declval`](https://en.cppreference.com/cpp/utility/declval)
- [`std::terminate`](https://en.cppreference.com/cpp/error/terminate) and [`std::bad_alloc`](https://en.cppreference.com/cpp/memory/new/bad_alloc)
- [`std::scoped_lock`](https://en.cppreference.com/cpp/thread/scoped_lock) and [`std::mutex`](https://en.cppreference.com/cpp/thread/mutex)
- [`std::optional`](https://en.cppreference.com/cpp/utility/optional)
- [`std::chrono::duration`](https://en.cppreference.com/cpp/chrono/duration)
- [Thread-safety guarantees for standard library types](https://en.cppreference.com/cpp/container)
