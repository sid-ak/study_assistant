# Errors

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
Every non-trivial function can fail, and a language has to give the caller some way to find out. C++
supports several strategies — exceptions, error codes, and types that hold either a result or an
error — and real codebases often combine them. They differ in what failure costs at run time, whether
a caller can accidentally ignore it, and how much information about the failure reaches the code
that handles it.

| Strategy | How failure is reported | Can the caller ignore it? | Cost | Best suited for |
| -------- | ----------------------- | ------------------------- | ---- | --------------- |
| Exceptions | `throw` unwinds the stack to the nearest matching `catch` | No; an uncaught exception ends the program | Almost free when nothing is thrown; slow and unpredictable when thrown | Rare failures, and constructors |
| Error codes | A return value such as `int`, an `enum`, or `std::error_code` | Yes, unless marked `[[nodiscard]]` | Cheap and predictable | C interfaces and performance-critical paths |
| `std::optional<T>` | Holds a value or nothing | No; the value must be unwrapped | Cheap | "Not found" results where the reason is obvious |
| `std::expected<T, E>` (C++23) | Holds a value or an error describing the failure | No; the value must be unwrapped | Cheap | Expected failures that need a reason |
<!-- --8<-- [end:intro] -->

## 1. Exceptions

<!-- --8<-- [start:exceptions] -->
An exception is an object thrown to signal failure. The runtime searches back through the call stack
for a `catch` block that accepts its type.

```cpp
class Volume {
public:
    explicit Volume(int size_gb) {
        if (size_gb <= 0) {
            throw std::invalid_argument("volume size must be positive");   // constructors can't return errors
        }
        blocks_.resize(static_cast<std::size_t>(size_gb));
    }
private:
    std::vector<char> blocks_;
};

int create(int size_gb) {
    try {
        Volume v(size_gb);
        return 0;
    } catch (const std::invalid_argument& e) {   // most specific type first
        std::fprintf(stderr, "bad input: %s\n", e.what());
        return 1;
    } catch (const std::exception& e) {          // any other standard exception
        std::fprintf(stderr, "failed: %s\n", e.what());
        return 2;
    }
}
```

- Unwinding: as the search leaves each function, destructors of that function's local objects run.
  This is why RAII types (see [Ownership](ownership.md)) keep cleanup correct even when
  exceptions are thrown.
- Cost model: mainstream compilers use table-based ("zero-cost") exceptions. Code that does not throw
  pays essentially nothing at run time, but throwing requires looking up tables and walking the
  stack, which is slow and its duration hard to bound.
- Constructors: a constructor has no return value, so throwing is the standard way for one to report
  failure.
- Disabled exceptions: some embedded, kernel, and low-latency codebases compile with
  `-fno-exceptions` to remove that unpredictability and the extra binary size, and must use another
  strategy.

> A JSON parsing library can throw a `parse_error` exception from deep inside nested parsing
> functions. The application catches it once at the top level and reports the file and line to the
> user, without every intermediate function checking a return value.
<!-- --8<-- [end:exceptions] -->

[Go deeper →](../cpp_deep_dive/errors.md#1-exceptions)

## 2. Exception safety guarantees

<!-- --8<-- [start:safety] -->
When a function throws, callers need to know what state the program was left in. The standard
library describes this with three levels.

```cpp
class Inventory {
public:
    // Strong guarantee: build the new state on the side, then commit with a non-throwing swap
    void replace_all(const std::vector<std::string>& incoming) {
        std::vector<std::string> next(incoming);   // may throw; items_ is untouched if it does
        items_.swap(next);                         // noexcept: cannot fail
    }
private:
    std::vector<std::string> items_;
};
```

- Basic guarantee: no resources leak and all objects remain usable, though their values may have
  changed.
- Strong guarantee: if the operation fails, the program state is exactly as it was before the call.
  The copy-then-swap shape above is the usual way to provide it.
- No-throw guarantee: the operation never fails. Destructors, swaps, and move operations should aim
  for this, and are marked `noexcept` (see [Keywords](keywords.md)).

> `std::vector::push_back` provides the strong guarantee: if copying the new element throws while
> the vector is reallocating, the vector is left exactly as it was, so a failed insert never
> corrupts existing data.
<!-- --8<-- [end:safety] -->

[Go deeper →](../cpp_deep_dive/errors.md#2-exception-safety-guarantees)

## 3. Error codes

<!-- --8<-- [start:codes] -->
A function returns a value that indicates success or the kind of failure, as C APIs do.

```cpp
enum class Status { Ok, NotFound, Timeout };

[[nodiscard]] Status flush_block(int block_id) {
    return block_id >= 0 ? Status::Ok : Status::NotFound;
}

std::error_code open_device() {
    return std::make_error_code(std::errc::permission_denied);
}

void caller() {
    // flush_block(7);                  // warning: ignoring a [[nodiscard]] return value
    if (flush_block(7) != Status::Ok) { /* handle */ }

    if (std::error_code ec = open_device()) {
        std::fprintf(stderr, "%s\n", ec.message().c_str());
    }
}
```

- Predictability: checking a return value costs the same whether the call succeeded or failed.
- Weaknesses: callers can silently ignore the value, and each layer that passes the code upward loses
  context about what was being attempted.
- Mitigation: `[[nodiscard]]` makes the compiler warn when a return value is discarded.
  `std::error_code` pairs a numeric code with a category, so codes from different libraries do not
  collide.

> POSIX functions such as `open` and `read` return `-1` and set `errno` on failure. C++ wrappers
> around them commonly convert that into a `std::error_code`, which callers can compare against
> values like `std::errc::no_such_file_or_directory`.
<!-- --8<-- [end:codes] -->

[Go deeper →](../cpp_deep_dive/errors.md#3-error-codes)

## 4. `std::optional`

<!-- --8<-- [start:optional] -->
`std::optional<T>` holds either a `T` or nothing.

```cpp
std::optional<std::size_t> find_index(const std::vector<int>& v, int target) {
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (v[i] == target) return i;
    }
    return std::nullopt;                          // instead of returning -1
}

std::size_t index_or_zero(const std::vector<int>& v) {
    if (auto idx = find_index(v, 42)) {
        return *idx;                              // only reached when a value exists
    }
    return find_index(v, 7).value_or(0);          // supply a fallback
}
```

- Problem it replaces: sentinel values such as returning `-1` or `nullptr` to mean "not found", which
  a caller can mistake for a real result.
- Access: `if (result)` checks for a value, `*result` or `result.value()` reads it, and
  `value_or(fallback)` supplies a default.
- Limitation: it cannot explain why there is no value. When the reason matters, use `expected`.

> A user directory lookup such as `std::optional<User> find_user(std::string_view email)` returns no
> value when no account matches. The caller must check before reading the result, so "not found"
> cannot be mistaken for a real user.
<!-- --8<-- [end:optional] -->

[Go deeper →](../cpp_deep_dive/errors.md#4-stdoptional)

## 5. `std::expected` and `std::variant`

<!-- --8<-- [start:expected] -->
`std::expected<T, E>` (C++23) holds either a successful `T` or an error `E`.

```cpp
enum class ParseError { Empty, NotADigit };

std::expected<int, ParseError> parse_digit(std::string_view text) {
    if (text.empty()) return std::unexpected(ParseError::Empty);
    if (text[0] < '0' || text[0] > '9') return std::unexpected(ParseError::NotADigit);
    return text[0] - '0';
}

int use() {
    auto result = parse_digit("7");
    if (!result) {
        return result.error() == ParseError::Empty ? -1 : -2;
    }
    return *result;
}

using Reply = std::variant<int, std::string>;     // one of several alternatives

std::string describe(const Reply& r) {
    if (std::holds_alternative<int>(r)) return "code " + std::to_string(std::get<int>(r));
    return "message " + std::get<std::string>(r);
}
```

- Behavior: success and failure travel through ordinary return values, so the cost is predictable,
  and the error can carry as much context as its type holds.
- Before C++23: libraries such as `tl::expected`, Boost.Outcome, and Boost.LEAF provide the same
  approach.
- `std::variant<A, B, ...>`: a type-safe union that holds exactly one of several alternatives and
  records which one. It is the general tool that `expected` specializes for the success-or-error
  case; `std::visit` handles every alternative in one call.

> A configuration file parser returning `std::expected<Config, ParseError>` can report "missing
> field 'port' on line 12" to the caller without exceptions, which suits programs such as embedded
> firmware that are built with exceptions disabled.
<!-- --8<-- [end:expected] -->

[Go deeper →](../cpp_deep_dive/errors.md#5-stdexpected-and-stdvariant)

## Choosing a strategy

<!-- --8<-- [start:choosing] -->
Use value-based types such as `std::optional` or `std::expected` for failures that callers are
expected to handle as part of normal operation, such as a missing file or a timeout. Use exceptions
for failures that should be rare, especially in constructors, when the codebase allows them. Avoid
exceptions in code with strict latency requirements, and follow the existing convention when working
in a codebase that has already chosen one.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Exceptions and exception safety](https://en.cppreference.com/cpp/language/exceptions)
- [`throw` expressions](https://en.cppreference.com/cpp/language/throw)
- [`try` blocks and handlers](https://en.cppreference.com/cpp/language/try_catch)
- [`noexcept` specifier](https://en.cppreference.com/cpp/language/noexcept_spec)
- [`[[nodiscard]]`](https://en.cppreference.com/cpp/language/attributes/nodiscard)
- [Scoped enumerations](https://en.cppreference.com/cpp/language/enum)

Exceptions library

- [Error handling overview](https://en.cppreference.com/cpp/error)
- [`std::exception`](https://en.cppreference.com/cpp/error/exception) and [`what`](https://en.cppreference.com/cpp/error/exception/what)
- [`std::invalid_argument`](https://en.cppreference.com/cpp/error/invalid_argument) and [`std::runtime_error`](https://en.cppreference.com/cpp/error/runtime_error)

Error codes

- [`std::error_code`](https://en.cppreference.com/cpp/error/error_code)
- [`std::errc`](https://en.cppreference.com/cpp/error/errc)
- [`std::make_error_code`](https://en.cppreference.com/cpp/error/errc/make_error_code)
- [`std::system_error`](https://en.cppreference.com/cpp/error/system_error)

Value-based errors

- [`std::optional`](https://en.cppreference.com/cpp/utility/optional), [`std::nullopt`](https://en.cppreference.com/cpp/utility/optional/nullopt), and [`value_or`](https://en.cppreference.com/cpp/utility/optional/value_or)
- [`std::expected`](https://en.cppreference.com/cpp/utility/expected) and [`std::unexpected`](https://en.cppreference.com/cpp/utility/expected/unexpected)
- [`std::variant`](https://en.cppreference.com/cpp/utility/variant), [`std::holds_alternative`](https://en.cppreference.com/cpp/utility/variant/holds_alternative), [`std::get`](https://en.cppreference.com/cpp/utility/variant/get), and [`std::visit`](https://en.cppreference.com/cpp/utility/variant/visit)
