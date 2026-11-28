# Ownership

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
C++ has no garbage collector, so something in the program has to decide when each resource —
heap memory, a file handle, a lock, a socket — is released. Modern C++ answers that question with
ownership: the type of a variable states whether it is responsible for releasing what it refers to.
When ownership is visible in the type, the compiler releases resources automatically and readers can
tell at a glance which code is allowed to keep a pointer.

| Type | Meaning | Released when | Cost compared with a raw pointer |
| ---- | ------- | ------------- | -------------------------------- |
| `T` (a value) | This variable owns its own copy | The variable goes out of scope | None |
| `std::unique_ptr<T>` | Exactly one owner | The owner is destroyed | None |
| `std::shared_ptr<T>` | Several owners share it | The last owner is destroyed | Reference-count updates on copy, plus a control block |
| `std::weak_ptr<T>` | Observes a shared object without keeping it alive | Never releases; must check the object still exists | Same control block as `shared_ptr` |
| `T&`, `T*`, `std::span<T>`, `std::string_view` | Borrowed; someone else owns it and must keep it alive | Never releases | None |
<!-- --8<-- [end:intro] -->

## 1. RAII: tying cleanup to scope

<!-- --8<-- [start:raii] -->
RAII (Resource Acquisition Is Initialization) is the idiom underneath every row of the table: an
object acquires a resource in its constructor and releases it in its destructor.

```cpp
class File {
public:
    explicit File(const char* path) : handle_(std::fopen(path, "r")) {}   // acquire
    ~File() { if (handle_) std::fclose(handle_); }                        // release
    File(const File&) = delete;              // copying would close the file twice
    File& operator=(const File&) = delete;
private:
    std::FILE* handle_;
};

void read_config() {
    File config("app.conf");
    // ... any return or exception from here on still closes the file
}
```

- Mechanism: C++ guarantees that the destructor of an automatic object runs when its scope ends,
  whether the scope ends normally, through an early `return`, or because an exception is passing
  through. Cleanup therefore cannot be skipped by an unexpected code path.
- Examples: `std::vector` frees its buffer, `std::lock_guard` unlocks a mutex, and `std::fstream`
  closes its file, all in their destructors.

> A database client wraps each connection in a class whose destructor returns the connection to the
> pool. Even if a query throws halfway through, the connection is handed back, so the pool never
> slowly runs out.
<!-- --8<-- [end:raii] -->

[Go deeper →](../cpp_deep_dive/ownership.md#1-raii-tying-cleanup-to-scope)

## 2. `std::unique_ptr`: exclusive ownership

<!-- --8<-- [start:unique] -->
A `unique_ptr` is the only owner of the object it points to, and deletes that object in its
destructor.

```cpp
struct Session { int id = 0; };

std::unique_ptr<Session> open_session() {
    return std::make_unique<Session>();      // caller becomes the sole owner
}

void transfer() {
    auto a = open_session();
    auto b = std::move(a);                   // ownership moves to b; a is now empty
    // auto c = b;                           // error: unique_ptr cannot be copied
}

using FilePtr = std::unique_ptr<std::FILE, int (*)(std::FILE*)>;
FilePtr open_log() { return FilePtr(std::fopen("log.txt", "a"), &std::fclose); }
```

- Transfer: it cannot be copied, because two copies would both try to delete the object. It can be
  moved, which transfers ownership and leaves the source empty.
- Cost: a `unique_ptr` with the default deleter is the same size as a raw pointer, and with
  optimization enabled its operations compile to the same instructions as the equivalent manual
  code.
- Custom deleters: the deleter can be any callable, so a `unique_ptr` can manage resources from C
  APIs, such as calling `fclose` on a `FILE*` as `open_log` does above.

> A document editor's undo stack holds `std::unique_ptr<Command>` objects. Each command has exactly
> one owner, the stack, and popping a command off the stack frees it automatically.
<!-- --8<-- [end:unique] -->

[Go deeper →](../cpp_deep_dive/ownership.md#2-stdunique_ptr-exclusive-ownership)

## 3. `std::shared_ptr`: shared ownership

<!-- --8<-- [start:shared] -->
A `shared_ptr` is used when several parts of a program need to keep the same object alive and no
single one of them clearly outlives the rest.

```cpp
struct Texture { int width = 0; };

void share() {
    auto tex = std::make_shared<Texture>();  // owner count: 1
    {
        std::shared_ptr<Texture> copy = tex; // owner count: 2
    }                                        // copy destroyed; owner count: 1
    long owners = tex.use_count();           // 1
    (void)owners;
}                                            // count reaches 0; Texture is deleted
```

- Mechanism: all copies point to a shared control block that holds a count of owners. Copying a
  `shared_ptr` increments the count and destroying one decrements it; the object is deleted when the
  count reaches zero.
- Cost: the count is updated with atomic CPU operations so it stays correct across threads, which is
  noticeably slower than copying a raw pointer. `std::make_shared` places the object and control
  block in a single allocation.
- Thread safety: the reference count is thread-safe; the object it points to is not. Two threads
  modifying the object still need their own synchronization.

> A texture cache in a game can hand out `std::shared_ptr<Texture>` to every sprite that draws the
> same image. The texture is freed only when the last sprite using it is destroyed, without the
> cache having to track who still needs it.
<!-- --8<-- [end:shared] -->

[Go deeper →](../cpp_deep_dive/ownership.md#3-stdshared_ptr-shared-ownership)

## 4. `std::weak_ptr`: observing without owning

<!-- --8<-- [start:weak] -->
A `weak_ptr` refers to an object managed by `shared_ptr` without adding to its owner count.

```cpp
struct Node {
    std::shared_ptr<Node> next;   // owns the next node
    std::weak_ptr<Node> prev;     // observes the previous node, so the two never own each other
};

void visit_previous(const Node& n) {
    if (std::shared_ptr<Node> p = n.prev.lock()) {   // empty if the node was already destroyed
        // safe to use *p here; p keeps it alive until the end of this block
    }
}
```

- Access: calling `lock()` returns a `shared_ptr` that is empty if the object has already been
  destroyed, so the check and the access happen in one step.
- Breaking cycles: if two objects hold `shared_ptr`s to each other, neither count ever reaches zero
  and both leak. Making one direction a `weak_ptr` breaks the cycle.

> A UI widget tree stores child widgets as `shared_ptr` and each child's link to its parent as
> `weak_ptr`. Closing a window releases the whole tree, because no child keeps its parent alive.
<!-- --8<-- [end:weak] -->

[Go deeper →](../cpp_deep_dive/ownership.md#4-stdweak_ptr-observing-without-owning)

## 5. Raw pointers and references: borrowing

<!-- --8<-- [start:borrowing] -->
A raw pointer or reference in modern C++ should mean "I use this, but I do not own it and I will not
delete it."

```cpp
struct Account { int balance = 0; };

void deposit(Account& account, int amount) {   // borrows for the duration of the call
    account.balance += amount;
}

Account* dangling() {
    Account local;
    return &local;                             // bug: local is destroyed when the function returns
}
```

- Correct use: function parameters that only read or modify an object during the call.
- Hazard: the borrower must not outlive the owner. A pointer that outlives its object is a dangling
  pointer, and using it is undefined behavior.

> A sorting function such as `void sort_rows(std::vector<Row>& rows)` borrows the caller's vector
> for the duration of the call. It rearranges the rows but never stores the reference, so ownership
> stays entirely with the caller.
<!-- --8<-- [end:borrowing] -->

[Go deeper →](../cpp_deep_dive/ownership.md#5-raw-pointers-and-references-borrowing)

## 6. The Rule of Zero, Three, and Five

<!-- --8<-- [start:rules] -->
A class that manages a resource directly needs to control what happens when it is copied, moved, and
destroyed. These operations are called the special member functions.

```cpp
// Rule of Zero: members manage themselves, so no special member functions are written
struct Document {
    std::string title;
    std::vector<std::string> lines;
    std::unique_ptr<int[]> cache;
};

// Rule of Five: this class owns a raw buffer, so it defines all five
class Buffer {
public:
    explicit Buffer(std::size_t n) : size_(n), data_(new char[n]) {}
    ~Buffer() { delete[] data_; }
    Buffer(const Buffer& other) : size_(other.size_), data_(new char[other.size_]) {
        std::copy(other.data_, other.data_ + size_, data_);
    }
    Buffer& operator=(const Buffer& other) {
        Buffer copy(other);
        swap(copy);
        return *this;
    }
    Buffer(Buffer&& other) noexcept
        : size_(std::exchange(other.size_, 0)), data_(std::exchange(other.data_, nullptr)) {}
    Buffer& operator=(Buffer&& other) noexcept {
        swap(other);
        return *this;
    }
    void swap(Buffer& other) noexcept {
        std::swap(size_, other.size_);
        std::swap(data_, other.data_);
    }
private:
    std::size_t size_;
    char* data_;
};
```

- Rule of Zero: if a class holds its resources through members that already manage themselves
  (`std::vector`, `std::unique_ptr`), it needs none of the special member functions. This is the
  preferred design.
- Rule of Three: a class that defines a destructor, copy constructor, or copy assignment operator
  almost certainly needs all three, because each one exists to manage the same resource.
- Rule of Five: since C++11, the same reasoning extends to the move constructor and move assignment
  operator.

> Most application classes — a `User` record with a name, email, and list of roles — follow the Rule
> of Zero because every member already manages itself. The Rule of Five is reserved for the few
> low-level classes that wrap a raw resource, such as a memory-mapped file.
<!-- --8<-- [end:rules] -->

[Go deeper →](../cpp_deep_dive/ownership.md#6-the-rule-of-zero-three-and-five)

## Choosing an ownership type

<!-- --8<-- [start:choosing] -->
Hold objects by value when possible. When heap allocation is required, use `std::unique_ptr`. Reach
for `std::shared_ptr` only when ownership is genuinely shared and no single owner can be identified.
Use references and raw pointers to borrow, and never to express that some code must remember to
call `delete`.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [RAII](https://en.cppreference.com/cpp/language/raii)
- [Rule of three/five/zero](https://en.cppreference.com/cpp/language/rule_of_three)
- [Constructors](https://en.cppreference.com/cpp/language/constructor) and [destructors](https://en.cppreference.com/cpp/language/destructor)
- [Copy constructors](https://en.cppreference.com/cpp/language/copy_constructor) and [copy assignment](https://en.cppreference.com/cpp/language/copy_assignment)
- [Move constructors](https://en.cppreference.com/cpp/language/move_constructor) and [move assignment](https://en.cppreference.com/cpp/language/move_assignment)
- [Deleted functions](https://en.cppreference.com/cpp/language/function)
- [References](https://en.cppreference.com/cpp/language/reference) and [pointers](https://en.cppreference.com/cpp/language/pointer)
- [Object lifetime and dangling references](https://en.cppreference.com/cpp/language/lifetime)

Library

- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr) and [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique)
- [`std::shared_ptr`](https://en.cppreference.com/cpp/memory/shared_ptr), [`std::make_shared`](https://en.cppreference.com/cpp/memory/shared_ptr/make_shared), and [`use_count`](https://en.cppreference.com/cpp/memory/shared_ptr/use_count)
- [`std::weak_ptr`](https://en.cppreference.com/cpp/memory/weak_ptr) and [`lock`](https://en.cppreference.com/cpp/memory/weak_ptr/lock)
- [`std::span`](https://en.cppreference.com/cpp/container/span) and [`std::string_view`](https://en.cppreference.com/cpp/string/basic_string_view)
- [`std::lock_guard`](https://en.cppreference.com/cpp/thread/lock_guard)
- [`std::fopen`](https://en.cppreference.com/cpp/io/c/fopen) and [`std::fclose`](https://en.cppreference.com/cpp/io/c/fclose)
- [`std::move`](https://en.cppreference.com/cpp/utility/move), [`std::exchange`](https://en.cppreference.com/cpp/utility/exchange), and [`std::swap`](https://en.cppreference.com/cpp/utility/swap)
