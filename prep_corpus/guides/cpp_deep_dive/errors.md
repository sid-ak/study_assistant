# Errors

> Part of the [C++ Deep Dive](README.md) · Overview: [Errors](../cpp_overview/errors.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:intro"

This page covers how exceptions are implemented and what they really cost, how to give code a specific
exception safety guarantee, how error codes and categories scale across libraries, the details of
`optional`, `expected`, and `variant`, and how structured error libraries attach context without
exceptions or allocation.

## 1. Exceptions

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:exceptions"

### How table-based unwinding works

- No checks on the normal path: instead of testing a flag after every call, the compiler records side
  tables that map ranges of machine code to the cleanup actions needed there. A function that returns
  normally never consults them.
- Throwing: `throw` allocates the exception object, then the unwinder walks the stack frame by frame,
  looking up each return address in those tables, running the destructors of each frame's automatic
  objects, and checking each `catch` clause for a match.
- Costs that remain: the tables increase binary size, the compiler must keep enough information to
  unwind, and a throw takes time proportional to stack depth and table size. Some implementations also
  serialized concurrent throws behind a process-wide lock; recent GCC and glibc versions largely removed
  that bottleneck.
- No handler: if the search finds no matching `catch`, `std::terminate` is called. Whether the stack is
  unwound first is implementation-defined.

### Catching, rethrowing, and transporting exceptions

```cpp
void load_config() {
    try {
        throw std::runtime_error("missing file");
    } catch (const std::exception& e) {       // catch by const reference: no copy, no slicing
        std::fprintf(stderr, "%s\n", e.what());
        throw;                                // rethrows the original object with its full type
    }
}

std::exception_ptr run_task() {
    try {
        load_config();
        return nullptr;
    } catch (...) {
        return std::current_exception();      // capture the exception to rethrow elsewhere
    }
}

void report(std::exception_ptr failure) {
    if (failure) {
        try { std::rethrow_exception(failure); }
        catch (const std::exception& e) { std::fprintf(stderr, "task failed: %s\n", e.what()); }
    }
}
```

- Catch by reference: catching by value copies the exception and slices derived types down to the
  caught type. See [Objects](objects.md).
- `throw;` versus `throw e;`: a bare `throw;` rethrows the original exception object; `throw e;` throws a
  new copy of the static type.
- `std::exception_ptr`: holds an exception so it can be moved to another thread and rethrown there. This
  is how `std::future::get()` rethrows an exception from the task that produced it.
- `std::throw_with_nested` and `std::rethrow_if_nested` wrap one exception inside another, keeping the
  low-level cause while adding higher-level context.

### Code built without exceptions

- `-fno-exceptions`: the compiler rejects `throw`, `try`, and `catch`, and emits no unwind tables for that
  code. Standard library operations that would throw typically abort the program instead.
- Reasons codebases choose it: throw latency that depends on stack depth, which hurts tail latency in
  data paths; binary size in constrained environments; and failure paths that are invisible in the source,
  which makes code harder to audit.
- Consequence: such codebases need an explicit error channel for every fallible operation, which is where
  the remaining sections of this page apply.

> Google's C++ style guide historically disallowed exceptions, largely because its existing code was not
> exception-safe, and teams following it report errors through status types such as `absl::Status` and
> `absl::StatusOr<T>` instead.

## 2. Exception safety guarantees

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:safety"

### The four levels

| Guarantee | If an exception escapes |
| --------- | ----------------------- |
| No-throw | Cannot happen: the operation always succeeds |
| Strong | The program state is exactly as it was before the call |
| Basic | Invariants still hold and nothing leaks, but values may have changed |
| None | Anything may happen, including leaks and broken invariants |

- Basic is the minimum for code that ships: the object must stay destructible and internally consistent.
- Strong matters for operations callers may retry, because a failed attempt leaves nothing to undo.
- No-throw is required for the operations the other two are built from: destructors, `swap`, and moves.

### How the strong guarantee is built

```cpp
class Widget {
public:
    Widget& operator=(Widget other) noexcept {   // the copy happens when the argument is built
        swap(other);                             // cannot fail: the commit point
        return *this;                            // the old state is destroyed with other
    }
    void swap(Widget& other) noexcept {
        names_.swap(other.names_);
        sizes_.swap(other.sizes_);
    }
private:
    std::vector<std::string> names_;
    std::vector<int> sizes_;
};
```

- Pattern: do every operation that can fail on a copy, then commit with operations that cannot fail. If
  anything throws before the commit, the original object was never touched.
- Copy-and-swap: taking the parameter by value moves the copy (and its possible failure) to the call site,
  so the assignment body only swaps.
- Cost: the full copy is made even when only a small change is needed. Performance-sensitive code often
  settles for the basic guarantee and documents it.

### What breaks the basic guarantee

```cpp
class Pair {
public:
    void set(std::string first, std::string second) {
        first_ = std::move(first);
        second_ = std::move(second);   // if this could throw, first_ is updated but second_ is not
    }
private:
    std::string first_;
    std::string second_;
};
```

- Partial updates: when an operation modifies several members and a later step can throw, an invariant
  that ties the members together (such as "both refer to the same record") may be left broken.
- Raw resources: any owning raw pointer between an acquisition and a throwing call leaks. RAII members
  prevent this. See [Ownership](ownership.md).

> Database transactions give the strong guarantee at the storage level: changes are written to a log and
> applied only when the commit record is durably written, so a failure at any earlier point leaves the
> database exactly as it was before the transaction started.

## 3. Error codes

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:codes"

### Defining an error category

```cpp
enum class StorageError { ok = 0, not_found = 1, timeout = 2 };

class StorageCategory : public std::error_category {
public:
    const char* name() const noexcept override { return "storage"; }
    std::string message(int code) const override {
        switch (static_cast<StorageError>(code)) {
            case StorageError::ok:        return "success";
            case StorageError::not_found: return "block not found";
            case StorageError::timeout:   return "operation timed out";
        }
        return "unknown storage error";
    }
};

const std::error_category& storage_category() {
    static StorageCategory instance;
    return instance;
}

std::error_code make_error_code(StorageError e) {
    return {static_cast<int>(e), storage_category()};
}

template <>
struct std::is_error_code_enum<StorageError> : std::true_type {};

std::error_code read_block() { return StorageError::timeout; }   // converts implicitly
```

- Category: an `std::error_code` is an integer paired with a pointer to a category object. Codes from
  different libraries can reuse the same numbers, because codes compare equal only when both number and
  category match.
- Messages: each category turns its codes into readable text through `message()`.
- `std::error_condition` and `std::errc`: portable conditions such as
  `std::errc::no_such_file_or_directory` let callers test for a meaning without depending on each
  platform's specific numbers.

### Codes at C boundaries

```cpp
#include <cerrno>
#include <fcntl.h>

std::error_code open_read(const char* path, int& fd) {
    fd = ::open(path, O_RDONLY);
    if (fd < 0) return {errno, std::system_category()};   // capture errno immediately
    return {};
}
```

- C interfaces report failure through return values and `errno`, and exceptions must never propagate
  across a C boundary, so any C-compatible API uses codes.
- `errno` is thread-local but overwritten by the next failing call, so it must be captured right away.
- Branch cost: every call site needs its own check and propagation, which is why C codebases use
  `goto cleanup` patterns that RAII replaces in C++.

### Adopting `[[nodiscard]]`

```cpp
[[nodiscard("check whether the flush succeeded")]]
std::error_code flush();

enum class [[nodiscard]] Status { ok, failed };   // every function returning Status is checked
```

- A message string (C++20) explains why the result matters.
- Marking a type `[[nodiscard]]` applies the check to every function that returns it by value, which
  makes incremental adoption practical: annotate one error type, fix the resulting warnings, and repeat.

> The Linux kernel returns negative `errno` values from most internal functions and marks many with
> `__must_check`, the kernel's equivalent of `[[nodiscard]]`, so ignoring a possible failure produces a
> compiler warning during the kernel build.

## 4. `std::optional`

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:optional"

### Layout and access

```cpp
static_assert(sizeof(std::optional<int>) == 8);       // 4-byte int + flag, padded
static_assert(sizeof(std::optional<double>) == 16);   // 8-byte double + flag, padded

int read(const std::optional<int>& maybe) {
    int a = maybe.value_or(0);        // no throw, no undefined behavior
    int b = maybe ? *maybe : 0;       // operator* is unchecked: undefined behavior if empty
    try {
        int c = maybe.value();        // checked: throws std::bad_optional_access if empty
        return a + b + c;
    } catch (const std::bad_optional_access&) {
        return a + b;
    }
}
```

- Storage: the value lives inside the `optional` with a flag recording whether it is present. There is no
  heap allocation, and the value is constructed in place only when engaged.
- Two accessors: `value()` checks and throws; `operator*` and `operator->` do not check. The library
  leaves the choice of whether a check is worth its branch to the caller.

### Monadic operations (C++23)

```cpp
std::optional<std::string> lookup_user(int id) {
    if (id == 1) return "ada";
    return std::nullopt;
}

std::optional<std::size_t> name_length(int id) {
    return lookup_user(id)
        .transform([](const std::string& name) { return name.size(); })   // apply if present
        .or_else([] { return std::optional<std::size_t>{0}; });            // supply if absent
}
```

- `transform(f)` applies `f` to the contained value and wraps the result; an empty optional stays empty.
- `and_then(f)` calls a function that itself returns an optional, flattening the result.
- `or_else(f)` produces a replacement when empty.
- Effect: a chain of steps that may each produce nothing reads as a pipeline instead of nested `if`
  statements.

### When `optional` is the wrong type

- Needing a reason: `optional` collapses every failure into "nothing". When the caller must tell "not
  found" from "permission denied", use `expected` or an error code.
- Optional references: `std::optional<T&>` is not available in C++23; `T*` or
  `std::optional<std::reference_wrapper<T>>` are the usual substitutes.

> Configuration systems commonly model settings as `std::optional<T>`, distinguishing "the user did not set
> this" from "the user set it to the default value", a distinction that sentinel values such as `0` or an
> empty string cannot represent.

## 5. `std::expected` and `std::variant`

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:expected"

### Chaining fallible steps with `expected`

```cpp
struct Config { int port; };

std::expected<std::string, std::string> read_file(const std::string& path) {
    if (path.empty()) return std::unexpected("no path given");
    return "port=8080";
}

std::expected<Config, std::string> parse(const std::string& text) {
    if (text.rfind("port=", 0) != 0) return std::unexpected("missing port");
    return Config{std::stoi(text.substr(5))};
}

std::expected<int, std::string> load_port(const std::string& path) {
    return read_file(path)
        .and_then(parse)                                  // stops at the first error
        .transform([](const Config& c) { return c.port; });
}
```

- Propagation: `and_then` runs the next step only on success and passes an error through untouched, so a
  pipeline needs no branch per step.
- `transform_error` converts error types between layers, such as wrapping a parser error in a
  configuration error.
- Before C++23: `tl::expected`, Boost.Outcome, and `absl::StatusOr<T>` offer the same model.

### How `variant` works

```cpp
using Value = std::variant<std::int64_t, double, std::string>;

static_assert(sizeof(Value) == 32);   // largest alternative (24-byte string here) plus an index, padded

template <typename... Fs>
struct overloaded : Fs... { using Fs::operator()...; };

std::string describe(const Value& v) {
    return std::visit(overloaded{
        [](std::int64_t i)       { return "integer " + std::to_string(i); },
        [](double d)             { return "real " + std::to_string(d); },
        [](const std::string& s) { return "text " + s; },
    }, v);
}
```

- Layout: storage large enough for the largest alternative plus a small index recording which one is
  active. Unlike a C `union`, it destroys and copies the active alternative correctly.
- `std::visit`: calls the handler matching the active alternative. A missing handler is a compile error,
  so adding a new alternative breaks the build at every place that needs updating.
- Implementation: `visit` typically dispatches through a table indexed by the active alternative — one
  indirect call, comparable to a virtual call.
- `valueless_by_exception()`: if constructing a new alternative throws partway through an assignment, the
  variant can be left holding nothing. This is rare and usually only matters for types whose moves throw.

### `variant` compared with virtual functions

| | `std::variant` | Virtual functions |
| - | -------------- | ----------------- |
| Set of types | Closed: fixed when the variant is declared | Open: new derived classes can be added later |
| Storage | By value, inline, no allocation | Usually behind a pointer, often heap-allocated |
| Adding an operation | Write a new visitor | Add a virtual function to every class |
| Adding a type | Update every visitor | Add one derived class |
| Missing case | Compile error | Falls back to the base implementation |

- Rule of thumb: use `variant` for a fixed set of states or message types, such as parsed tokens or the
  states of a connection; use virtual functions when other code must be able to add types.

### Structured error context without exceptions

```cpp
struct FileName { std::string value; };
struct Offset { std::uint64_t value; };

enum class ReadError { truncated, checksum };

std::expected<std::uint32_t, std::pair<ReadError, std::string>> read_header(const FileName& file, Offset at) {
    if (at.value > 1024) {
        return std::unexpected(std::pair{ReadError::truncated,
                                         file.value + " at offset " + std::to_string(at.value)});
    }
    return 42;
}
```

- The limitation of plain codes: a code says what failed, not where, on which input, or after how many
  retries. Carrying that context in a returned object means every layer copies or allocates it, costs
  that avoiding exceptions was meant to avoid.
- Boost.LEAF's approach: error objects are placed in thread-local storage by the layer that has the
  context, while the returned value stays small. A handler at the top declares which context types it
  wants, such as a file name and a retry count, and receives only those; context nobody asked for is
  discarded. It needs no allocation and works with or without exceptions enabled.

```cpp
// Boost.LEAF handler shape (requires Boost):
// auto r = leaf::try_handle_some(
//     []() -> leaf::result<Data> { return parse(input); },
//     [](leaf::match<ReadError, ReadError::truncated>, const FileName& f) { /* log f.value */ },
//     [](const NetworkError& e, const RetryCount& n) { /* ... */ });
```

- The first handler runs only when the error is `truncated` and some lower layer attached a `FileName`.
  The intermediate layers never needed to know that the top-level handler wanted a file name.

> Rust's `Result<T, E>` with the `?` operator is the language-level version of `std::expected` with
> `and_then`: each fallible call either yields its value or returns the error to the caller immediately,
> which is the propagation style C++23 makes possible with library types.

## Choosing a strategy

??? note "Overview"

    --8<-- "guides/cpp_overview/errors.md:choosing"

Give every fallible operation a documented exception safety level, keep failure-reporting types
`[[nodiscard]]`, and attach context at the layer that has it so the top-level handler can report which
input and which step failed.

## C++ References

Language

- [Exceptions](https://en.cppreference.com/cpp/language/exceptions), [`throw`](https://en.cppreference.com/cpp/language/throw), [`try` and `catch`](https://en.cppreference.com/cpp/language/try_catch)
- [`noexcept` specifier](https://en.cppreference.com/cpp/language/noexcept_spec)
- [`[[nodiscard]]`](https://en.cppreference.com/cpp/language/attributes/nodiscard)
- [Scoped enumerations](https://en.cppreference.com/cpp/language/enum)
- [Unions](https://en.cppreference.com/cpp/language/union)

Exceptions library

- [`std::exception`](https://en.cppreference.com/cpp/error/exception) and [`std::runtime_error`](https://en.cppreference.com/cpp/error/runtime_error)
- [`std::exception_ptr`](https://en.cppreference.com/cpp/error/exception_ptr), [`std::current_exception`](https://en.cppreference.com/cpp/error/current_exception), [`std::rethrow_exception`](https://en.cppreference.com/cpp/error/rethrow_exception)
- [`std::throw_with_nested`](https://en.cppreference.com/cpp/error/throw_with_nested) and [`std::rethrow_if_nested`](https://en.cppreference.com/cpp/error/rethrow_if_nested)
- [`std::terminate`](https://en.cppreference.com/cpp/error/terminate)

Error codes

- [`std::error_code`](https://en.cppreference.com/cpp/error/error_code), [`std::error_category`](https://en.cppreference.com/cpp/error/error_category), [`std::error_condition`](https://en.cppreference.com/cpp/error/error_condition)
- [`std::is_error_code_enum`](https://en.cppreference.com/cpp/error/error_code/is_error_code_enum)
- [`std::errc`](https://en.cppreference.com/cpp/error/errc) and [`std::system_category`](https://en.cppreference.com/cpp/error/system_category)
- [`errno`](https://en.cppreference.com/cpp/error/errno)

Value-based errors

- [`std::optional`](https://en.cppreference.com/cpp/utility/optional): [`value`](https://en.cppreference.com/cpp/utility/optional/value), [`value_or`](https://en.cppreference.com/cpp/utility/optional/value_or), [`transform`](https://en.cppreference.com/cpp/utility/optional/transform), [`and_then`](https://en.cppreference.com/cpp/utility/optional/and_then), [`or_else`](https://en.cppreference.com/cpp/utility/optional/or_else), [`std::bad_optional_access`](https://en.cppreference.com/cpp/utility/optional/bad_optional_access)
- [`std::expected`](https://en.cppreference.com/cpp/utility/expected): [`and_then`](https://en.cppreference.com/cpp/utility/expected/and_then), [`transform`](https://en.cppreference.com/cpp/utility/expected/transform), [`transform_error`](https://en.cppreference.com/cpp/utility/expected/transform_error), [`std::unexpected`](https://en.cppreference.com/cpp/utility/expected/unexpected)
- [`std::variant`](https://en.cppreference.com/cpp/utility/variant), [`std::visit`](https://en.cppreference.com/cpp/utility/variant/visit), [`valueless_by_exception`](https://en.cppreference.com/cpp/utility/variant/valueless_by_exception)
- [`std::reference_wrapper`](https://en.cppreference.com/cpp/utility/functional/reference_wrapper)
- [`std::future`](https://en.cppreference.com/cpp/thread/future)
