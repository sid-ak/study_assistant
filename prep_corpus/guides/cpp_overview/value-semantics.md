# Value Semantics

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
In C++, assigning one variable to another or passing an object to a function copies the object by
default, the same way copying an `int` does. This is called value semantics: each variable holds its
own independent object. Copying is simple to reason about but can be expensive for objects that own
large buffers, so the language provides move semantics, which let an object hand over its internals
instead of duplicating them, and rules that let the compiler skip copies entirely.

| Operation | What happens | Cost | Typical trigger |
| --------- | ------------ | ---- | --------------- |
| Copy | The target gets its own duplicate of the source's data | Proportional to the data size | Initializing from or assigning a named object |
| Move | The target takes the source's internal resources; the source is left valid but unspecified | Usually a few pointer assignments | Initializing from a temporary, or from `std::move(x)` |
| Copy elision | The object is constructed directly in its final location | None | Returning a local or a temporary from a function |
| Borrow | A reference or view refers to the existing object | None | Passing `const T&`, `std::string_view`, `std::span` |
<!-- --8<-- [end:intro] -->

## 1. Value categories

<!-- --8<-- [start:categories] -->
Every expression in C++ has a value category, which tells the compiler whether the expression names
an object that will keep existing or a temporary result that is about to disappear.

```cpp
void store(const std::string&) {}   // chosen for lvalues
void store(std::string&&) {}        // chosen for rvalues

void categories() {
    std::string name = "disk";
    store(name);                    // name is an lvalue: it has a name and persists
    store(name + "0");              // name + "0" is an rvalue: a temporary result
    store(std::string("tmp"));      // a temporary object is also an rvalue
}
```

- Lvalue: an expression that refers to an object with a name or a stable address, such as a variable
  `x`. It can appear on the left side of an assignment.
- Rvalue: a temporary value, such as the result of `a + b` or a function returning by value. Nothing
  else can refer to it after the current expression, so its contents can safely be taken.
- Why it matters: the compiler uses the category to choose between overloads. A copy constructor
  accepts `const T&` and binds to lvalues; a move constructor accepts `T&&` (an rvalue reference) and
  is preferred for rvalues.

> A string builder class can offer `append(const std::string&)` and `append(std::string&&)`.
> Appending a variable copies it, while appending the result of a function call steals its buffer,
> and callers get the faster path without writing anything different.
<!-- --8<-- [end:categories] -->

[Go deeper →](../cpp_deep_dive/value-semantics.md#1-value-categories)

## 2. Move semantics

<!-- --8<-- [start:moves] -->
A move transfers ownership of an object's resources — for a `std::string`, its heap buffer — to a new
object.

```cpp
void moves() {
    std::vector<int> source(1'000'000, 7);
    std::vector<int> copy = source;               // copies one million ints
    std::vector<int> moved = std::move(source);   // takes source's buffer; no elements copied
    // source is now valid but unspecified: it may be reused by assigning to it
    source = {1, 2, 3};
}
```

- Mechanism: the move constructor copies the source's pointer and size into the target, then sets
  the source's pointer to empty so the source's destructor does not free the buffer.
- `std::move`: despite its name, `std::move` moves nothing. It is a cast that marks an lvalue as an
  rvalue, which makes the compiler choose the move constructor. It generates no code on its own.
- Moved-from state: after a move, the source is valid but its value is unspecified. It can be
  destroyed or assigned a new value, but its contents should not be relied on.
- `noexcept`: containers such as `std::vector` only move elements during reallocation if the move
  constructor is marked `noexcept`. Otherwise they copy, to preserve their guarantee that a failed
  reallocation leaves the original elements intact.

> When a message queue hands a large payload from a producer to a consumer,
> `queue.push(std::move(payload))` transfers the buffer in constant time instead of copying
> megabytes of data.
<!-- --8<-- [end:moves] -->

[Go deeper →](../cpp_deep_dive/value-semantics.md#2-move-semantics)

## 3. Copy elision

<!-- --8<-- [start:elision] -->
Copy elision lets the compiler construct a returned object directly in the caller's memory, so no
copy or move happens at all.

```cpp
std::string guaranteed() {
    return std::string(4096, 'x');   // C++17: built directly in the caller, always
}

std::string named() {
    std::string result(4096, 'x');
    return result;                   // NRVO: usually elided; otherwise moved
}

std::string pessimized() {
    std::string result(4096, 'x');
    return std::move(result);        // blocks NRVO and forces a move
}
```

- Guaranteed case: since C++17, returning a temporary (`return std::string("hi");`) never creates an
  intermediate object.
- Named return value optimization (NRVO): returning a local variable by name is usually elided as
  well, but it is permitted rather than required. When it is not applied, the value is moved.
- Consequence: `return std::move(local);` is counterproductive. It prevents NRVO and forces a move
  that would otherwise have been skipped.

> A function that loads a CSV file and returns `std::vector<Row>` by value is as fast as filling a
> vector passed in by reference, because the returned vector is built directly in the caller's
> variable.
<!-- --8<-- [end:elision] -->

[Go deeper →](../cpp_deep_dive/value-semantics.md#3-copy-elision)

## 4. Perfect forwarding

<!-- --8<-- [start:forwarding] -->
Generic wrapper functions, such as `std::make_unique`, need to pass their arguments on to another
function while keeping each argument's value category intact.

```cpp
template <typename T, typename Arg>
std::unique_ptr<T> build(Arg&& arg) {                    // forwarding reference
    return std::make_unique<T>(std::forward<Arg>(arg));  // copies lvalues, moves rvalues
}

void forwarding() {
    std::string label = "volume";
    auto a = build<std::string>(label);                  // label is copied
    auto b = build<std::string>(std::string("temp"));    // the temporary is moved
}
```

- Forwarding reference: in a template, a parameter declared `T&&` accepts both lvalues and rvalues,
  and `T` records which one was passed.
- `std::forward<T>(arg)`: passes the argument on as an lvalue if it arrived as one, and as an rvalue
  if it arrived as one. Use `std::move` when you intend to give up an object; use `std::forward` only
  inside templates that relay their arguments.

> `std::vector::emplace_back` uses perfect forwarding to pass its arguments straight to the
> element's constructor, so `points.emplace_back(x, y)` builds the point in place without a
> temporary.
<!-- --8<-- [end:forwarding] -->

[Go deeper →](../cpp_deep_dive/value-semantics.md#4-perfect-forwarding)

## 5. Passing parameters

<!-- --8<-- [start:parameters] -->
How a parameter is declared tells callers whether the function copies, borrows, or takes ownership.

```cpp
struct Widget { std::vector<int> data; };

int  area(int w, int h);                             // cheap types by value
std::size_t count(const Widget& w);                  // read an expensive type
void resize(Widget& w);                              // modify the caller's object
void adopt(std::unique_ptr<Widget> w);               // take ownership

class Label {
public:
    explicit Label(std::string text) : text_(std::move(text)) {}   // keep a copy: take by value, then move
private:
    std::string text_;
};
```

| The function needs to | Declare the parameter as |
| --------------------- | ------------------------ |
| Read a cheap type (`int`, a pointer, a small struct) | `T` |
| Read an expensive type | `const T&` |
| Modify the caller's object | `T&` |
| Keep its own copy, such as storing it in a member | `T`, then `std::move` it into place |
| Take ownership of a heap object | `std::unique_ptr<T>` by value |
| Read a string or contiguous range without caring about its container | `std::string_view` or `std::span<const T>` |

> A `User` class constructor written as `User(std::string name) : name_(std::move(name))` costs one
> copy when called with a variable and zero copies when called with a temporary, with a single
> function covering both cases.
<!-- --8<-- [end:parameters] -->

[Go deeper →](../cpp_deep_dive/value-semantics.md#5-passing-parameters)

## 6. Views

<!-- --8<-- [start:views] -->
A view is a small non-owning object, usually a pointer and a length, that refers to data owned
somewhere else.

```cpp
bool has_prefix(std::string_view text, std::string_view prefix) {
    return text.substr(0, prefix.size()) == prefix;   // no allocation, no copy
}

int total(std::span<const int> values) {              // accepts vector, array, or C array
    int sum = 0;
    for (int v : values) sum += v;
    return sum;
}

std::string_view broken() {
    std::string local = "temporary";
    return local;                                     // bug: view outlives the string it refers to
}
```

- Benefit: `std::string_view` accepts a `std::string`, a string literal, or a slice of either
  without allocating or copying.
- Hazard: a view does not keep its data alive. Returning a `string_view` into a local
  `std::string`, or storing one that outlives the string it refers to, leaves it dangling.

> A command-line parser can split an input line into `std::string_view` tokens that point back into
> the original line, avoiding one allocation per token, as long as the line outlives the tokens.
<!-- --8<-- [end:views] -->

[Go deeper →](../cpp_deep_dive/value-semantics.md#6-views)

## Deciding between copy, move, and borrow

<!-- --8<-- [start:choosing] -->
Borrow when the function only needs to look at an object during the call. Copy when both sides need
their own independent object afterwards. Move when the source is finished with its data. Return
local objects by value and let the compiler elide the copy.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Value categories](https://en.cppreference.com/cpp/language/value_category)
- [References, including rvalue and forwarding references](https://en.cppreference.com/cpp/language/reference)
- [Copy constructors](https://en.cppreference.com/cpp/language/copy_constructor) and [copy assignment](https://en.cppreference.com/cpp/language/copy_assignment)
- [Move constructors](https://en.cppreference.com/cpp/language/move_constructor) and [move assignment](https://en.cppreference.com/cpp/language/move_assignment)
- [Copy elision](https://en.cppreference.com/cpp/language/copy_elision)
- [Template argument deduction](https://en.cppreference.com/cpp/language/template_argument_deduction)
- [Overload resolution](https://en.cppreference.com/cpp/language/overload_resolution)
- [`noexcept` specifier](https://en.cppreference.com/cpp/language/noexcept_spec)

Library

- [`std::move`](https://en.cppreference.com/cpp/utility/move)
- [`std::forward`](https://en.cppreference.com/cpp/utility/forward)
- [`std::move_if_noexcept`](https://en.cppreference.com/cpp/utility/move_if_noexcept)
- [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique)
- [`std::string_view`](https://en.cppreference.com/cpp/string/basic_string_view)
- [`std::span`](https://en.cppreference.com/cpp/container/span)
- [`std::vector`](https://en.cppreference.com/cpp/container/vector)
