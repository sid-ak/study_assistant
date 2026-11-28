# Value Semantics

> Part of the [C++ Deep Dive](README.md) · Overview: [Value Semantics](../cpp_overview/value-semantics.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:intro"

This page covers the machinery behind copies and moves: the full value category taxonomy, how
`std::move` and `std::forward` are implemented, reference collapsing, the rules that decide when a copy
is elided, and the costs hidden in parameter types and views.

## 1. Value categories

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:categories"

### Why the language needs value categories

Moving from an object is only safe if no other code will look at that object afterwards. The compiler
therefore needs to answer one question about every expression: can anything else still observe this
object once this expression is done with it?

- If nothing can, the compiler may let a move constructor take the object's resources.
- If something can, it must copy.
- Cost: value categories are a purely compile-time classification; they generate no code.

### Identity and movability

```cpp
int x = 5;                  // x is an lvalue; 5 is a prvalue
int* p = &x;                // an lvalue has an address
// int* q = &5;             // error: a prvalue has no address to take

std::string make() { return "made"; }

void taxonomy() {
    std::string s = "text";
    std::string a = s;              // s: lvalue (identity, not movable) -> copy
    std::string b = std::move(s);   // std::move(s): xvalue (identity, movable) -> move
    std::string c = make();         // make(): prvalue (no identity) -> constructed in place
}
```

The categories come from two independent questions, which is why there are three leaf categories:

| Category | Has identity | May be moved from | Examples |
| -------- | ------------ | ----------------- | -------- |
| lvalue | Yes | No | A variable, `*ptr`, `v[0]` |
| xvalue ("expiring value") | Yes | Yes | `std::move(x)`, a member of an xvalue |
| prvalue ("pure rvalue") | No | Yes | `42`, `a + b`, a call returning by value |

- glvalue ("generalized lvalue") is the umbrella for lvalues and xvalues: expressions with identity.
- rvalue is the umbrella for xvalues and prvalues: expressions that may be moved from.
- Addressability: an object whose address can be taken might have that address stored somewhere, so
  something else could observe it later. Having an address is the observable form of having identity.
- History: "lvalue" and "rvalue" once meant "left and right of `=`". That mnemonic no longer holds (a
  `const` lvalue cannot be assigned to), but it explains the names.

### A named rvalue reference is an lvalue

```cpp
void g(const std::string&) { std::puts("copy overload"); }
void g(std::string&&) { std::puts("move overload"); }

void f(std::string&& s) {
    g(s);               // "copy overload": the expression s has a name, so it is an lvalue
    g(std::move(s));    // "move overload": opting back in explicitly
}
```

- Type versus category: the declared type of `s` is `std::string&&`, but the expression `s` is an
  lvalue. Type and value category are separate properties of an expression.
- Reason: `s` has a name, so it could be used again on the next line. If the compiler moved from it
  implicitly, that later use would read an emptied object. Code must say `std::move` to show it is
  finished with `s`.

> Static analysis flags the common mistake of taking a parameter as `T&&` and then
> passing it on by name, which silently copies. Clang-tidy's
> `cppcoreguidelines-rvalue-reference-param-not-moved` check reports rvalue reference parameters that
> are never moved from.

## 2. Move semantics

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:moves"

### How `std::move` is implemented

`std::move` is a cast and nothing else.

```cpp
template <typename T>
constexpr std::remove_reference_t<T>&& my_move(T&& t) noexcept {
    return static_cast<std::remove_reference_t<T>&&>(t);
}
```

- Sequence: `std::move(v)` changes the expression's category from lvalue to xvalue, so overload
  resolution prefers `vector(vector&&)` over `vector(const vector&)`, and the move constructor then
  transfers the buffer. Only the last step does any work at run time.
- `remove_reference_t`: strips any reference from `T` before adding `&&`, so the result is always an
  rvalue reference even when `T` was deduced as an lvalue reference.

### Why moving is cheaper

- Work avoided: copying a `std::vector<int>` of a million elements allocates a new buffer and copies
  about 4 MB. Moving copies three pointers (begin, end, capacity) and clears the source's.
- Allocation avoided: the saved heap allocation is often the larger win. An allocation may search free
  lists, contend on allocator locks, or make a system call, so removing it removes an operation with
  unpredictable latency. See [Memory](memory.md).

### Writing move operations

```cpp
class Buffer {
public:
    explicit Buffer(std::size_t n) : data_(new char[n]), size_(n) {}
    ~Buffer() { delete[] data_; }

    Buffer(Buffer&& other) noexcept
        : data_(std::exchange(other.data_, nullptr)), size_(std::exchange(other.size_, 0)) {}

    Buffer& operator=(Buffer&& other) noexcept {
        if (this != &other) {
            delete[] data_;                               // release what this object owns
            data_ = std::exchange(other.data_, nullptr);  // take the source's resource
            size_ = std::exchange(other.size_, 0);        // and leave the source empty
        }
        return *this;
    }
private:
    char* data_;
    std::size_t size_;
};
```

- Two obligations: take the resource and clear the source. Skipping the second leaves two objects that
  free the same buffer.
- `std::exchange(a, b)` assigns `b` to `a` and returns the old value of `a`, which expresses
  "take and clear" in one step.
- Self-move: `v = std::move(v)` is legal and can arise inside generic algorithms. Without the
  `this != &other` check, the object would delete its own buffer before taking it.

### What "valid but unspecified" means

- Guarantee: a moved-from standard library object can be destroyed or assigned a new value. Its
  contents are otherwise unspecified.
- Why only that much: the moved-from object's destructor will still run, so it must be left in some
  valid state, but the standard lets each type choose the cheapest one.
- Exceptions: some types do promise more. A moved-from `std::unique_ptr` is guaranteed empty. A
  moved-from `std::string` usually is, but a short string stored inline (small-string optimization) may
  simply be copied, so code must not rely on emptiness.

### Why containers need `noexcept` moves

```cpp
struct Loud {
    Loud() = default;
    Loud(const Loud&) { std::puts("copy"); }
    Loud(Loud&&) { std::puts("move"); }          // not noexcept
};

void grow() {
    std::vector<Loud> v(2);
    v.reserve(16);                               // relocation prints "copy" twice, not "move"
}
```

- Strong guarantee: `push_back` promises that if it throws, the vector is unchanged. If reallocation
  moved half the elements and the next move threw, the old buffer would already be partly emptied and
  could not be restored.
- Fallback: so the vector relocates with copies unless the move constructor is `noexcept`. It decides
  with `std::move_if_noexcept`. A missing `noexcept` quietly turns every reallocation into element-wise
  copies.

### Where moves silently do not happen

```cpp
void take(std::string s);

void surprises() {
    const std::string config = "large configuration text";
    take(std::move(config));     // copies: a move constructor needs a non-const source to clear

    std::string name = "value";
    auto lambda = [name] { return name; };   // the captured copy is const inside the lambda
    (void)lambda;
}
```

- `const` objects: `std::move` on a `const` object yields `const T&&`, which cannot bind to the move
  constructor's `T&&`, so overload resolution picks the copy constructor without any warning.
- Returning locals: `return local;` is already elided or moved, so `std::move` there only prevents
  elision. See section 3.
- Captured values: a lambda's by-value captures are `const` unless the lambda is declared `mutable`, so
  moving them out copies.

> Profiling a service that passed `const std::vector<Record>` objects through `std::move` into queues
> would show deep copies where the author expected moves. Removing the `const`, or passing ownership
> through a `std::unique_ptr`, restores constant-time handoff.

## 3. Copy elision

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:elision"

### Where the returned object is built

When a function returns a class by value, the caller reserves storage for the result and passes the
function a hidden pointer to it. If the function constructs its return value directly in that storage,
there is nothing left to copy or move.

```cpp
struct Pinned {
    Pinned() = default;
    Pinned(const Pinned&) = delete;    // neither copyable
    Pinned(Pinned&&) = delete;         // nor movable
};

Pinned make_pinned() {
    return Pinned{};                   // compiles: C++17 guarantees no copy or move is needed
}

void use() {
    Pinned p = make_pinned();          // constructed exactly once, in p
    (void)p;
}
```

- Guaranteed elision: since C++17, a prvalue used to initialize an object of the same type is not a
  temporary at all; it initializes the target directly. This is a language rule, so it works even for
  types with no copy or move constructor.
- Named return value optimization (NRVO): returning a named local is still an optimization the compiler
  may apply rather than a rule, and it requires the copy or move constructor to be accessible.

### When NRVO cannot apply

```cpp
std::vector<int> choose(bool flag) {
    std::vector<int> a(100), b(200);
    if (flag) return a;                // two different candidates: neither can be built in the
    return b;                          // caller's slot in advance, so the result is moved
}

std::vector<int> pessimized() {
    std::vector<int> v(100);
    return std::move(v);               // std::move(v) is not a name, so NRVO is not allowed
}
```

- Multiple candidates: the compiler must build the returned object in the caller's slot from the start,
  which is impossible when either of two locals might be returned.
- `return std::move(local)`: elision requires the returned expression to name a local object, and a
  function call does not. The result is a forced move where there could have been none; compilers warn
  with `-Wpessimizing-move`.
- Implicit move: when NRVO does not apply, `return local;` still treats `local` as an rvalue, so it is
  moved rather than copied.

### Deep and shallow copies

- Memberwise: the generated copy constructor copies each member with that member's own copy
  constructor. For a `std::vector` member that is a deep copy; for a raw pointer member it copies only
  the address.
- Consequence: two objects sharing one heap block both free it. This is why owning raw pointers need the
  Rule of Three or Five, covered in [Ownership](ownership.md).

> A helper such as `std::lock_guard<std::mutex> acquire(std::mutex& m)` can return a lock guard by
> value, even though `lock_guard` can be neither copied nor moved, because returning
> `std::lock_guard<std::mutex>(m)` initializes the caller's variable directly. The same rule lets a
> function return a `std::atomic<int>` by value.

## 4. Perfect forwarding

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:forwarding"

### The problem forwarding solves

```cpp
void inner(const std::string&) {}
void inner(std::string&&) {}

template <typename T>
void by_value(T arg) { inner(arg); }            // always copies into arg, then passes an lvalue

template <typename T>
void by_const_ref(const T& arg) { inner(arg); } // no copy, but inner can never move
```

- By value: copies even when the caller passed a temporary.
- By `const&`: avoids that copy but loses the information that the argument was a temporary, so the
  inner call must copy.
- Overloads: handling both cases with separate `const T&` and `T&&` overloads needs 2^N functions for N
  parameters. Forwarding references reduce that to one.

### Reference collapsing

A forwarding reference (`T&&` with `T` deduced) records whether it received an lvalue or an rvalue in
the deduced type `T`.

```cpp
template <typename T>
void show(T&& arg) {
    if (std::is_lvalue_reference_v<T>) std::puts("given an lvalue: T = U&, parameter = U&");
    else                               std::puts("given an rvalue: T = U,  parameter = U&&");
    (void)arg;
}

void calls() {
    int x = 0;
    show(x);    // T deduced as int&: int& && collapses to int&
    show(5);    // T deduced as int:  parameter is int&&
}
```

| Formed type | Collapses to |
| ----------- | ------------ |
| `T& &` | `T&` |
| `T& &&` | `T&` |
| `T&& &` | `T&` |
| `T&& &&` | `T&&` |

- Rule: any lvalue reference in the combination wins.
- `std::forward<T>(arg)`: returns `arg` as an lvalue when `T` is an lvalue reference type and as an
  rvalue otherwise. It is a conditional `std::move` driven by the recorded `T`.

### What is and is not a forwarding reference

```cpp
template <typename T> void a(T&& x);                  // forwarding reference
template <typename T> void b(const T&& x);            // rvalue reference to const: not forwarding
template <typename T> void c(std::vector<T>&& x);     // rvalue reference to a vector: not forwarding

template <typename T>
struct Box {
    void put(T&& x);                                  // not forwarding: T was fixed when Box<T> was chosen
};

void d() {
    auto&& any = std::string("works like T&&");       // auto&& is a forwarding reference
    (void)any;
}
```

- The test: the parameter must be exactly `T&&` (or `auto&&`) where `T` is deduced for this call, with
  no `const` and nothing wrapped around it.
- `move` versus `forward`: `std::move` unconditionally casts to an rvalue and is used on objects the code
  owns and is finished with; `std::forward` is used only on forwarding references inside templates.

### Variadic forwarding

```cpp
template <typename T, typename... Args>
std::unique_ptr<T> make_owned(Args&&... args) {
    return std::unique_ptr<T>(new T(std::forward<Args>(args)...));
}

auto greeting = make_owned<std::string>(5, 'x');   // forwards two arguments to string(size_t, char)
```

- Each argument is forwarded with its own recorded category, so one function template serves any number
  of arguments with no extra copies.
- Forwarding once: after `std::forward<Args>(args)` passes an argument on, it may have been moved from,
  so forwarding the same argument twice is a bug.

> `std::thread`'s constructor and `std::bind` deliberately do not forward references into the new
> thread; they copy or move arguments into internal storage, because the new thread may outlive the
> caller's objects. Passing a reference requires wrapping it with `std::ref`.

## 5. Passing parameters

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:parameters"

### Why a reference is not free

- Indirection: a reference parameter is passed as an address, so every read goes through memory.
- Aliasing: because some other pointer could refer to the same object, the compiler often must reload
  the value after any write through another pointer, instead of keeping it in a register.

```cpp
void add_twice(int& total, const int& amount) {
    total += amount;
    total += amount;   // amount might alias total, so it must be re-read from memory
}

void add_twice_value(int& total, int amount) {
    total += amount;
    total += amount;   // amount is a local copy: the compiler can compute total += 2 * amount
}
```

- Guideline: pass by value when the type is cheap to copy — roughly two or three machine words and
  trivially copyable, such as `int`, pointers, `std::string_view`, and `std::span`.

### The cost of "take by value, then move"

```cpp
struct Tracker {
    Tracker() = default;
    Tracker(const Tracker&) { std::puts("copy"); }
    Tracker(Tracker&&) noexcept { std::puts("move"); }
};

struct Holder {
    Tracker t;
    explicit Holder(Tracker v) : t(std::move(v)) {}
};

void counts() {
    Tracker named;
    Holder h1(named);                // copy (into v), then move (into t)
    Holder h2(Tracker{});            // move only: the temporary initializes v directly
    Holder h3(std::move(named));     // move (into v), then move (into t)
}
```

| Caller passes | By value, then move | Separate `const&` and `&&` overloads |
| ------------- | ------------------- | ------------------------------------ |
| A named lvalue | 1 copy + 1 move | 1 copy |
| A temporary | 1 move | 1 move |
| `std::move(x)` | 2 moves | 1 move |

- Trade-off: one function instead of two, at the cost of at most one extra move. Worth it when moves are
  cheap; for types whose move is as expensive as a copy, such as a large `std::array`, write the
  overloads.

### Lifetime extension stops at the binding

```cpp
std::string make_text() { return "temporary"; }

const std::string& dangling_return() {
    return make_text();                     // the temporary dies at the end of the return statement
}

void extended() {
    const std::string& kept = make_text();  // extended: lives as long as kept
    (void)kept;
}
```

- Rule: binding a temporary directly to a `const&` or `&&` local variable extends the temporary's
  lifetime to that variable's scope.
- Limit: extension is purely local. It does not follow the reference through a return, into a class
  member initialized in a constructor, or through a function parameter.

> Code guidelines such as the C++ Core Guidelines (F.15 through F.18) encode this decision table, and
> clang-tidy's `performance-unnecessary-value-param` check flags expensive types taken by value but
> never moved or modified.

## 6. Views

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:views"

### Why views avoid allocations

```cpp
void log_ref(const std::string& msg);   // log_ref("ready") builds a temporary std::string first
void log_view(std::string_view msg);    // log_view("ready") stores a pointer and a length

static_assert(sizeof(std::string_view) == 2 * sizeof(void*));
static_assert(sizeof(std::span<int>) == 2 * sizeof(void*));      // dynamic extent: pointer + length
static_assert(sizeof(std::span<int, 4>) == sizeof(void*));       // fixed extent: just a pointer

std::string_view first_word(std::string_view text) {
    return text.substr(0, text.find(' '));   // adjusts pointer and length; std::string::substr would allocate
}
```

- `const std::string&` from a literal: the compiler constructs a temporary `std::string`, which may
  allocate, just to have something to bind to.
- `substr`: on a `string_view` it is constant time with no allocation.
- Fixed-extent spans: `std::span<T, N>` stores only the pointer, because the length is part of the type.

### Views are not null-terminated

```cpp
void open_file(std::string_view path) {
    // std::fopen(path.data(), "r");         // bug: data() may not be followed by '\0'
    std::string terminated(path);            // build a terminated copy for C APIs
    if (std::FILE* f = std::fopen(terminated.c_str(), "r")) std::fclose(f);
}
```

- A `string_view` marks its end with a length, not a terminator. A view of part of a larger string has
  more characters after its end, so passing `data()` to a C function reads past the view.

### Views as parameters, not members

```cpp
std::string load_name() { return "loaded"; }

struct Config {
    std::string_view name;                   // risky: nothing ties the text's lifetime to Config
};

Config broken() {
    Config c;
    c.name = load_name();                    // the std::string temporary dies at the semicolon
    return c;                                // c.name dangles
}
```

- Parameters: a view parameter is safe because the caller's data outlives the call.
- Members and return values: storing a view commits to a lifetime relationship the type cannot express
  or check. Store a `std::string` or `std::vector` in long-lived objects, or document and test the
  lifetime explicitly.
- `std::span<const std::byte>`: replaces `(void* data, size_t len)` pairs with one type that carries
  both pieces and marks read-only access with `const`.

> High-performance parsers such as simdjson hand out `string_view`s that point into buffers owned by
> the parser instead of copying each string. Their documentation requires the parser and its input to
> outlive every view obtained from them, which is exactly the lifetime contract views push onto the
> caller.

## Deciding between copy, move, and borrow

??? note "Overview"

    --8<-- "guides/cpp_overview/value-semantics.md:choosing"

Mark move operations `noexcept`, avoid `std::move` on `const` objects and on returned locals, and keep
views out of data members unless the lifetime of the viewed data is guaranteed by design.

## C++ References

Language

- [Value categories](https://en.cppreference.com/cpp/language/value_category)
- [References, including forwarding references and reference collapsing](https://en.cppreference.com/cpp/language/reference)
- [Move constructors](https://en.cppreference.com/cpp/language/move_constructor) and [move assignment](https://en.cppreference.com/cpp/language/move_assignment)
- [Copy constructors](https://en.cppreference.com/cpp/language/copy_constructor)
- [Copy elision](https://en.cppreference.com/cpp/language/copy_elision)
- [`return` statement and automatic move](https://en.cppreference.com/cpp/language/return)
- [Template argument deduction](https://en.cppreference.com/cpp/language/template_argument_deduction)
- [Parameter packs](https://en.cppreference.com/cpp/language/pack)
- [Reference initialization and lifetime extension](https://en.cppreference.com/cpp/language/reference_initialization)
- [Lambda captures](https://en.cppreference.com/cpp/language/lambda)
- [Overload resolution](https://en.cppreference.com/cpp/language/overload_resolution)

Library

- [`std::move`](https://en.cppreference.com/cpp/utility/move), [`std::forward`](https://en.cppreference.com/cpp/utility/forward), [`std::move_if_noexcept`](https://en.cppreference.com/cpp/utility/move_if_noexcept)
- [`std::exchange`](https://en.cppreference.com/cpp/utility/exchange)
- [`std::remove_reference`](https://en.cppreference.com/cpp/types/remove_reference) and [`std::is_lvalue_reference`](https://en.cppreference.com/cpp/types/is_lvalue_reference)
- [`std::ref`](https://en.cppreference.com/cpp/utility/functional/ref)
- [`std::lock_guard`](https://en.cppreference.com/cpp/thread/lock_guard)
- [`std::vector::reserve`](https://en.cppreference.com/cpp/container/vector/reserve)
- [`std::string_view`](https://en.cppreference.com/cpp/string/basic_string_view) and [`substr`](https://en.cppreference.com/cpp/string/basic_string_view/substr)
- [`std::span`](https://en.cppreference.com/cpp/container/span)
- [`std::byte`](https://en.cppreference.com/cpp/types/byte)
