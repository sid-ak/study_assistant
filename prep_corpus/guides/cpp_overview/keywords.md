# Keywords

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
A handful of C++ keywords appear in almost every file, and several of them do something different
from what their names suggest. Each one is a promise to the compiler or to other programmers: about
what may be modified, how long something lives, which files can see a definition, which conversions
are allowed, or whether a function can throw. This page explains what each keyword actually controls.

| Keyword | What it controls | Common misunderstanding |
| ------- | ---------------- | ----------------------- |
| `const` | Whether an object can be modified through a particular name, pointer, or reference | That the underlying object can never change |
| `static` | Lifetime, linkage, or class membership, depending on where it appears | That it has one meaning |
| `inline` | Whether a definition may appear in several source files | That it forces the compiler to inline calls |
| `explicit` | Whether a constructor or conversion can be used implicitly | That it is only a style preference |
| `noexcept` | Whether a function promises not to throw | That throwing anyway is merely a warning |
<!-- --8<-- [end:intro] -->

## 1. `const`

<!-- --8<-- [start:const] -->
`const` marks something as read-only through that particular access path.

```cpp
const int limit = 10;              // cannot be reassigned

void pointers(int* data) {
    const int* read_only = data;   // *read_only cannot be changed; the pointer can move
    int* const fixed = data;       // *fixed can be changed; the pointer cannot move
    *fixed = 1;
    read_only = nullptr;
}

class Cache {
public:
    int lookup(int key) const {    // promises not to modify the Cache...
        ++hits_;                   // ...except members declared mutable
        return key;
    }
private:
    mutable int hits_ = 0;
};
```

- On variables: `const int limit = 10;` cannot be assigned after initialization.
- On pointers: the position matters. `const T* p` means the pointed-to value cannot be changed
  through `p`; `T* const p` means `p` itself cannot be re-pointed.
- On member functions: `int lookup(int) const;` promises not to modify the object, and it is the
  only kind of member function that can be called on a `const` object.
- Limits: `const` restricts one path, not the object. Another non-`const` reference to the same
  object can still modify it, and members marked `mutable` (such as a cache or a mutex) can change
  inside `const` functions.

> A function signature such as `double average(const std::vector<double>& samples)` tells callers
> that passing their data is safe: the function reads the samples but cannot modify them, and the
> compiler enforces that promise.
<!-- --8<-- [end:const] -->

[Go deeper →](../cpp_deep_dive/keywords.md#1-const)

## 2. `static`

<!-- --8<-- [start:static] -->
`static` has several unrelated meanings that depend on context.

```cpp
int call_count() {
    static int calls = 0;          // static storage: kept between calls
    return ++calls;
}

static int helper() { return 1; }  // internal linkage: invisible to other source files

class Connection {
public:
    static int open_count;         // one variable shared by every Connection
    static Connection create();    // no this pointer; called as Connection::create()
};
int Connection::open_count = 0;
```

- Local variable in a function: the variable has static storage — it is created the first time
  execution reaches it and kept between calls. Since C++11 that first initialization is thread-safe.
- Variable or function at namespace scope: the name has internal linkage, meaning it is only visible
  inside its own source file. An unnamed namespace achieves the same thing.
- Class member: the member belongs to the class as a whole rather than to each object. A static
  member function has no `this` pointer.

> A metrics library keeps a function-local `static` registry so the registry is created only when
> the first metric is recorded, and marks its internal helper functions `static` so their names
> cannot clash with functions in other libraries.
<!-- --8<-- [end:static] -->

[Go deeper →](../cpp_deep_dive/keywords.md#2-static)

## 3. `inline`

<!-- --8<-- [start:inline] -->
`inline` originally suggested that the compiler replace calls with the function body. Modern
compilers make that decision on their own, so the keyword's practical meaning is now about linkage.

```cpp
// config.h, included by many .cpp files
inline int default_port() { return 8080; }   // identical definition allowed in every file
inline constexpr int max_clients = 64;       // C++17 inline variable

struct Limits {
    int size() const { return 4; }           // defined in the class body: implicitly inline
    static inline int instances = 0;         // C++17: no separate .cpp definition needed
};
```

- One Definition Rule (ODR): normally a function or variable may be defined in only one source file,
  or the linker reports a duplicate. [Build & Toolchain](build-toolchain.md) explains the linker's
  role.
- What `inline` permits: an `inline` function or variable may be defined in every source file that
  includes its header, as long as every definition is identical. This is what makes header-only code
  possible.
- Implicitly inline: functions defined inside a class body, and function templates, already behave
  this way. Since C++17, `inline` variables let a header define a global constant or static member.

> Header-only libraries such as `nlohmann/json` and much of Boost define all of their functions in
> headers. Every function is `inline` (explicitly or implicitly), so hundreds of source files can
> include them without the linker reporting duplicates.
<!-- --8<-- [end:inline] -->

[Go deeper →](../cpp_deep_dive/keywords.md#3-inline)

## 4. `explicit`

<!-- --8<-- [start:explicit] -->
`explicit` prevents a constructor or conversion operator from being used for implicit conversions.

```cpp
class Buffer {
public:
    explicit Buffer(std::size_t size) : size_(size) {}
private:
    std::size_t size_;
};

void send(const Buffer&) {}

void callers() {
    // send(42);                   // error: no implicit conversion from int to Buffer
    send(Buffer(42));              // the conversion is written out
}
```

- The problem: a constructor that takes one argument also acts as an automatic conversion. Without
  `explicit`, the call `send(42)` would compile silently and create a 42-byte buffer.
- The fix: declaring the constructor `explicit` makes that call a compile error, so the conversion
  must be written out as `send(Buffer(42))`.
- Guideline: mark single-argument constructors `explicit` unless the implicit conversion is clearly
  intended, as it is for `std::string` from a string literal.

> `std::vector` has an `explicit` constructor taking a size, so `std::vector<int> v = 10;` does not
> compile. Without it, a function taking a vector could be called with a number by mistake and
> silently receive ten zeros.
<!-- --8<-- [end:explicit] -->

[Go deeper →](../cpp_deep_dive/keywords.md#4-explicit)

## 5. `noexcept`

<!-- --8<-- [start:noexcept] -->
`noexcept` declares that a function will not throw an exception.

```cpp
struct Packet {
    std::vector<char> bytes;
    Packet() = default;
    Packet(Packet&& other) noexcept = default;   // vector<Packet> will move, not copy
    Packet(const Packet&) = default;
};

static_assert(std::is_nothrow_move_constructible_v<Packet>);

void risky() noexcept {
    throw std::runtime_error("oops");            // compiles, but calls std::terminate at run time
}
```

- Enforcement: if an exception does try to leave a `noexcept` function, the program calls
  `std::terminate` and stops. The promise is checked at run time, not by the compiler.
- Benefit: code can test whether an operation is `noexcept` and choose a faster strategy. For
  example, `std::vector` moves elements during reallocation only when the move constructor is
  `noexcept`; otherwise it copies them. See [Value Semantics](value-semantics.md).
- Guideline: mark destructors (already `noexcept` by default), move operations, and swap functions
  `noexcept` when they cannot fail.

> When a vector of one million strings grows past its capacity, it can move each string to the new
> buffer by transferring a pointer, because `std::string`'s move constructor is `noexcept`. Without
> that guarantee it would copy every character of every string.
<!-- --8<-- [end:noexcept] -->

[Go deeper →](../cpp_deep_dive/keywords.md#5-noexcept)

## Using these keywords well

<!-- --8<-- [start:choosing] -->
Apply `const` wherever a value should not change, since it documents intent and lets the compiler
catch mistakes. Mark single-argument constructors `explicit` and non-failing move operations
`noexcept` by default. Use `inline` for definitions that live in headers, and remember that the
meaning of `static` depends on where it is written.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [`const` and `volatile` qualifiers](https://en.cppreference.com/cpp/language/cv)
- [Member functions, including `const` member functions](https://en.cppreference.com/cpp/language/member_functions)
- [Storage duration and linkage (`static`)](https://en.cppreference.com/cpp/language/storage_duration)
- [Static members](https://en.cppreference.com/cpp/language/static)
- [Namespaces, including unnamed namespaces](https://en.cppreference.com/cpp/language/namespace)
- [`inline` specifier](https://en.cppreference.com/cpp/language/inline)
- [Definitions and the One Definition Rule](https://en.cppreference.com/cpp/language/definition)
- [`explicit` specifier](https://en.cppreference.com/cpp/language/explicit)
- [Converting constructors](https://en.cppreference.com/cpp/language/converting_constructor)
- [`noexcept` specifier](https://en.cppreference.com/cpp/language/noexcept_spec) and [`noexcept` operator](https://en.cppreference.com/cpp/language/noexcept)
- [`constexpr`](https://en.cppreference.com/cpp/language/constexpr)

Library

- [`std::terminate`](https://en.cppreference.com/cpp/error/terminate)
- [`std::is_nothrow_move_constructible`](https://en.cppreference.com/cpp/types/is_move_constructible)
- [`std::runtime_error`](https://en.cppreference.com/cpp/error/runtime_error)
