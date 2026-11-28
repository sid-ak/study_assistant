# Ownership

> Part of the [C++ Deep Dive](README.md) · Overview: [Ownership](../cpp_overview/ownership.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:intro"

This page looks underneath each ownership type: why manual cleanup fails, what a correct RAII wrapper
needs beyond a destructor, how `unique_ptr` and `shared_ptr` are laid out, what is and is not
thread-safe, and the rules the compiler follows when it generates copy and move operations.

## 1. RAII: tying cleanup to scope

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:raii"

### Why manual cleanup fails

In C, releasing a resource is a statement that has to be written at every point a function can exit.

```cpp
// C style: every early return needs its own cleanup sequence
int process(const char* path) {
    std::FILE* f = std::fopen(path, "rb");
    if (!f) return -1;

    char* buf = static_cast<char*>(std::malloc(4096));
    if (!buf) return -1;                          // leaks f

    if (std::fread(buf, 1, 4096, f) == 0) {
        std::free(buf);
        return -1;                                // correct, but easy to forget
    }
    std::free(buf);
    std::fclose(f);
    return 0;
}
```

- Growth: each new exit path multiplies the cleanup sequences that must be kept correct. The C idiom
  `goto cleanup` exists because this does not scale.
- Exceptions: in C++ any call can throw, so any line is a potential exit path, and handwritten cleanup
  at the bottom of a function is skipped entirely.

### What a correct wrapper needs

A destructor alone is not enough; the wrapper must also decide what copying and moving mean.

```cpp
class FileHandle {
public:
    explicit FileHandle(const char* path) : f_(std::fopen(path, "rb")) {
        if (!f_) throw std::runtime_error("open failed");
    }
    ~FileHandle() { if (f_) std::fclose(f_); }

    FileHandle(const FileHandle&) = delete;                  // one owner: no copies
    FileHandle& operator=(const FileHandle&) = delete;

    FileHandle(FileHandle&& other) noexcept : f_(std::exchange(other.f_, nullptr)) {}
    FileHandle& operator=(FileHandle&& other) noexcept {
        if (this != &other) {
            if (f_) std::fclose(f_);
            f_ = std::exchange(other.f_, nullptr);
        }
        return *this;
    }

    std::FILE* get() const { return f_; }
private:
    std::FILE* f_;
};
```

- Deleted copies: two objects holding the same `FILE*` would both close it. Deleting the copy
  operations makes the single-owner rule part of the type.
- Moves that empty the source: `std::exchange` leaves the moved-from handle holding `nullptr`. Its
  destructor still runs, finds nothing to close, and does nothing.
- Self-move: move assignment checks `this != &other`, so `h = std::move(h)` does not close the file it
  is about to keep.

### RAII types in the standard library

| Type | Resource | Released by the destructor |
| ---- | -------- | -------------------------- |
| `std::unique_ptr`, `std::shared_ptr` | Heap object | `delete` or a custom deleter |
| `std::vector`, `std::string` | Heap buffer | Deallocation of the buffer |
| `std::lock_guard`, `std::scoped_lock`, `std::unique_lock` | Mutex | `unlock` |
| `std::fstream` | File | `close` |
| `std::jthread` (C++20) | Thread | Requests stop, then `join` |

- `std::thread` is the notable exception: destroying a `std::thread` that is still joinable calls
  `std::terminate` instead of joining, which is why C++20 added `std::jthread`.

### Destructors must not throw

```cpp
class Connection {
public:
    void close() {                          // reports failure to callers who care
        if (open_ && !send_goodbye()) throw std::runtime_error("close failed");
        open_ = false;
    }
    ~Connection() {                         // implicitly noexcept
        try { if (open_) close(); } catch (...) { /* swallow: nowhere to report it */ }
    }
private:
    bool send_goodbye() { return true; }
    bool open_ = true;
};
```

- Why: destructors run during stack unwinding. If a second exception escaped a destructor while one
  was already propagating, there would be no way to deliver both, so the program calls
  `std::terminate`.
- Default: destructors are implicitly `noexcept`, so a throw that escapes one terminates the program
  even when no other exception is active.
- Pattern: expose an explicit `close()` that can report errors, and let the destructor call it as a
  fallback while swallowing any failure.

> Scope guards generalize RAII to one-off cleanup. `scope_exit`, proposed in the Library Fundamentals
> technical specification and available today as Folly's `SCOPE_EXIT` or Abseil's `absl::Cleanup`,
> runs a lambda when the scope ends. Code uses it to restore a terminal's mode or remove a temporary
> file without writing a dedicated class.

## 2. `std::unique_ptr`: exclusive ownership

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:unique"

### `get`, `release`, and `reset`

```cpp
struct Node { int value = 0; };

void operations() {
    auto p = std::make_unique<Node>();
    Node* borrowed = p.get();            // still owned by p: do not delete
    borrowed->value = 1;

    p.reset(new Node{2});                // deletes the old Node, takes ownership of the new one

    Node* abandoned = p.release();       // p is now empty; the caller must delete
    delete abandoned;

    auto numbers = std::make_unique<int[]>(8);   // array form calls delete[]
    numbers[0] = 42;
}
```

- `get()` borrows: the pointer stays owned by the `unique_ptr`.
- `release()` gives up ownership without deleting, returning the raw pointer; the caller becomes
  responsible for it. It exists for handing ownership to APIs that take raw pointers.
- `reset(p)` deletes the current object and adopts `p`.
- Moved-from state: unlike most standard types, a moved-from `unique_ptr` is guaranteed to be empty.

### `make_unique` and evaluation order

<!-- needs: 4 -->
```cpp
void consume(std::unique_ptr<Node> a, std::unique_ptr<Node> b);

void callers() {
    consume(std::make_unique<Node>(), std::make_unique<Node>());          // preferred
    consume(std::unique_ptr<Node>(new Node), std::unique_ptr<Node>(new Node));   // safe since C++17
}
```

- Before C++17: the compiler could evaluate `new Node`, then the second `new Node`, and only then
  construct the two `unique_ptr`s. If the second allocation threw, the first object had no owner and
  leaked.
- Since C++17: each function argument is fully evaluated before the next one begins, so that
  interleaving is no longer allowed. `make_unique` remains preferred because it avoids naming the type
  twice and never exposes a raw `new`.

### Custom deleters and their cost

```cpp
struct FileCloser {
    void operator()(std::FILE* f) const { std::fclose(f); }
};

using FilePtr = std::unique_ptr<std::FILE, FileCloser>;          // stateless functor
using FilePtrFn = std::unique_ptr<std::FILE, int (*)(std::FILE*)>; // function pointer

static_assert(sizeof(std::unique_ptr<int>) == sizeof(int*));
static_assert(sizeof(FilePtr) == sizeof(std::FILE*));             // no extra storage
static_assert(sizeof(FilePtrFn) == 2 * sizeof(std::FILE*));       // stores the function address

FilePtr open_read(const char* path) { return FilePtr(std::fopen(path, "rb")); }
```

- Stateless deleters: an empty functor type carries no data, and implementations store it using the
  empty base optimization, so the `unique_ptr` stays pointer-sized.
- Function pointers: the address of `fclose` is run-time data, so it is stored next to the object
  pointer and the `unique_ptr` doubles in size.

### Incomplete types

```cpp
// widget.h
class Widget {
public:
    Widget();
    ~Widget();                        // declared here, defined in widget.cpp
private:
    struct Impl;                      // incomplete in the header
    std::unique_ptr<Impl> impl_;
};
```

- Rule: `unique_ptr<T>` may be declared with an incomplete `T`, but `T` must be complete wherever the
  destructor is instantiated, because `delete` needs to know the type's size and destructor.
- Consequence: a class holding `unique_ptr<Impl>` must declare its destructor in the header and define
  it (even as `= default`) in the source file where `Impl` is defined. This is the basis of the PIMPL
  idiom described in [Build & Toolchain](build-toolchain.md).

> Code that wraps a C library such as OpenSSL typically declares aliases like
> `std::unique_ptr<SSL_CTX, SslCtxDeleter>`, where the deleter calls `SSL_CTX_free`. Every error path
> in the setup code then releases the library's objects without a single explicit free call.

## 3. `std::shared_ptr`: shared ownership

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:shared"

### The control block

A `shared_ptr` is two pointers: one to the object and one to a control block shared by every copy.

```cpp
static_assert(sizeof(std::shared_ptr<int>) == 2 * sizeof(int*));

void layouts() {
    auto one_allocation = std::make_shared<std::string>("fused");        // object + control block together
    std::shared_ptr<std::string> two_allocations(new std::string("split")); // allocated separately
}
```

- Contents: the strong count (owners), the weak count (observers), the deleter, and the allocator.
- Why it is separate from the object: the object can be destroyed while `weak_ptr`s still need to read
  the counts, so the counts must live somewhere that outlasts the object.

| Creation | Allocations | Trade-off |
| -------- | ----------- | --------- |
| `std::make_shared<T>(...)` | One: object and control block in one block | Faster and cache-friendly, but the object's memory is not returned until the last `weak_ptr` is gone |
| `std::shared_ptr<T>(new T)` | Two | Slower, but object memory is freed as soon as the strong count reaches zero; allows a custom deleter |

### What is thread-safe

```cpp
std::shared_ptr<std::vector<int>> global = std::make_shared<std::vector<int>>();
std::mutex global_mutex;

void reader() {
    std::shared_ptr<std::vector<int>> local;
    {
        std::lock_guard lock(global_mutex);   // reading the shared_ptr variable itself needs a lock
        local = global;                        // copying bumps the count atomically
    }
    std::lock_guard lock(global_mutex);        // the vector's contents need their own protection
    local->push_back(1);
}
```

1. The reference count is thread-safe: copies and destructions of different `shared_ptr` objects that
   point to the same object may happen concurrently.
2. The pointed-to object is not: concurrent modification of `*p` is a data race unless something else
   synchronizes it. `shared_ptr` manages lifetime, not contents.
3. A single `shared_ptr` variable is not: one thread assigning to `global` while another copies from it
   is a data race. C++20 adds `std::atomic<std::shared_ptr<T>>` for this case.

### The cost of reference counting

- Atomic updates: every copy and destruction performs an atomic increment or decrement. Under
  contention, the cache line holding the count moves between cores on every update, the same effect as
  [false sharing](concurrency.md).
- Avoiding needless copies: a function that only uses the object during the call should take `T&` or
  `T*`, not `shared_ptr<T>` by value. Pass `shared_ptr` by value only when the callee keeps a copy.
- Good fits: objects whose lifetime genuinely depends on several independent users, such as cached
  resources or objects kept alive by pending asynchronous callbacks.

### `enable_shared_from_this`

```cpp
class Session : public std::enable_shared_from_this<Session> {
public:
    void start(std::function<void(std::function<void()>)> schedule) {
        schedule([self = shared_from_this()] { self->on_ready(); });   // keeps Session alive
    }
private:
    void on_ready() {}
};
```

- Problem: inside a member function, `std::shared_ptr<Session>(this)` creates a second, independent
  control block, and the object is deleted twice.
- Mechanism: `enable_shared_from_this` holds a `weak_ptr` that the first `shared_ptr` to own the object
  fills in. `shared_from_this()` locks that `weak_ptr`, joining the existing control block. Calling it
  on an object not owned by any `shared_ptr` throws `std::bad_weak_ptr`.

> Asynchronous networking code built on Boost.Asio commonly captures `shared_from_this()` in each
> completion handler. The connection object stays alive exactly as long as some operation on it is
> still pending, and is destroyed automatically after the last handler runs.

## 4. `std::weak_ptr`: observing without owning

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:weak"

### What the weak count keeps alive

A `weak_ptr` increments the weak count, not the strong count. The weak count keeps the control block
alive after the object itself has been destroyed.

```cpp
void observe() {
    std::weak_ptr<int> watcher;
    {
        auto owner = std::make_shared<int>(7);
        watcher = owner;                     // strong count 1, weak count 1
    }                                        // object destroyed; control block survives
    bool gone = watcher.expired();           // true: the control block reports strong count 0
    std::shared_ptr<int> attempt = watcher.lock();   // empty
    (void)gone;
    (void)attempt;
}
```

- `expired()` answers "has the object been destroyed?", but the answer can be stale immediately in
  multithreaded code.
- `lock()` performs the check and the increment as one atomic operation. A separate check followed by
  an increment could observe a live object, lose the race to another thread releasing the last owner,
  and then revive a destroyed object.

### Why reference counting cannot collect cycles

```cpp
struct TreeNode {
    std::vector<std::shared_ptr<TreeNode>> children;   // owning edges point down the tree
    std::weak_ptr<TreeNode> parent;                     // back edges point up and do not own
};
```

- Mechanism: reference counting only knows each object's own count. Two objects that reference each
  other keep each other's counts at one, even when nothing else refers to either.
- Contrast: a tracing garbage collector starts from the program's roots and finds such pairs
  unreachable; reference counting has no global view.
- Rule: in an ownership graph, edges pointing down (from owner to owned) are `shared_ptr`, and edges
  pointing back up are `weak_ptr`.

### Caches and registries

```cpp
class TextureCache {
public:
    std::shared_ptr<std::string> get(const std::string& name) {
        std::lock_guard lock(mutex_);
        if (auto existing = entries_[name].lock()) return existing;   // reuse while anyone holds it
        auto fresh = std::make_shared<std::string>("pixels for " + name);
        entries_[name] = fresh;
        return fresh;
    }
private:
    std::mutex mutex_;
    std::unordered_map<std::string, std::weak_ptr<std::string>> entries_;
};
```

- Behavior: the cache never keeps an entry alive on its own. While any user holds the resource,
  lookups reuse it; once the last user releases it, it is freed and the next lookup recreates it.
- Housekeeping: expired entries remain in the map as empty `weak_ptr`s, so long-lived caches remove
  them periodically.

> Event systems use `weak_ptr` subscriber lists: the publisher locks each subscriber before notifying
> it and drops entries whose `lock()` fails. Subscribers can be destroyed at any time without
> unregistering first.

## 5. Raw pointers and references: borrowing

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:borrowing"

### Pointer or reference

```cpp
struct Logger { void write(const char*) {} };

void always_logs(Logger& logger) { logger.write("ready"); }          // must be given a logger

void maybe_logs(Logger* logger) {                                      // may be given nothing
    if (logger) logger->write("ready");
}

class Service {
public:
    explicit Service(Logger& logger) : logger_(&logger) {}   // stores a pointer so Service stays assignable
private:
    Logger* logger_;                                          // non-owning: Logger must outlive Service
};
```

- References: cannot be null and cannot be re-seated, so they fit parameters that must refer to an
  object.
- Pointers: can be null and re-pointed, so they fit optional parameters and non-owning members, where
  a reference member would make the class non-assignable.
- Documentation: the Core Guidelines Support Library adds `gsl::not_null<T*>` to mark pointers that
  must not be null and `gsl::owner<T*>` to mark the rare raw pointers that do own.

### How borrowed pointers dangle

<!-- needs: 14 -->
```cpp
std::function<int()> make_counter() {
    int count = 0;
    return [&count] { return ++count; };       // captures a reference to a local that is about to die
}

struct Registry {
    std::vector<const Logger*> loggers;
    void add(const Logger& l) { loggers.push_back(&l); }   // stores a borrow beyond the call
};
```

- Captured references: a lambda that captures by reference and outlives the scope refers to destroyed
  locals.
- Stored borrows: saving a reference parameter's address turns a temporary borrow into a long-lived
  one, which is only safe if the caller's object is guaranteed to live longer.
- Invalidated targets: pointers into containers dangle when the container reallocates. See
  [Memory](memory.md).

### Letting the compiler check lifetimes

```cpp
const std::string& longer(const std::string& a [[clang::lifetimebound]],
                          const std::string& b [[clang::lifetimebound]]) {
    return a.size() >= b.size() ? a : b;
}

void check() {
    const std::string& r = longer("temporary", "strings");   // Clang warns: r dangles
    (void)r;
}
```

- `[[clang::lifetimebound]]` tells Clang that the return value refers to a parameter, so binding the
  result to a temporary produces a dangling-reference warning at compile time.
- Sanitizers: AddressSanitizer reports use-after-free and use-after-return at run time for the cases the
  compiler cannot see.

> Chromium replaced many raw pointer class members with `raw_ptr<T>`, a wrapper that cooperates with
> its allocator to make use-after-free on those pointers non-exploitable, after finding that dangling
> non-owning pointers were a major source of security bugs.

## 6. The Rule of Zero, Three, and Five

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:rules"

### Why generated members are memberwise

The compiler-generated special member functions apply the same operation to each member in turn.

```cpp
struct Shallow {
    int* data = new int[4];
    ~Shallow() { delete[] data; }
};

void double_free() {
    Shallow a;
    Shallow b = a;          // generated copy copies the pointer, not the array
}                           // both destructors delete the same array: undefined behavior
```

- Correct when: every member manages itself, as `std::vector` and `std::unique_ptr` do.
- Wrong when: a member is a raw handle. Copying the handle copies the address, not the resource, so two
  objects believe they own it.

### Which declarations suppress which generated members

| Declaring... | Suppresses... |
| ------------ | ------------- |
| Any constructor | The implicit default constructor |
| A destructor | The implicit move constructor and move assignment (copies are still generated, but this is deprecated) |
| A copy constructor or copy assignment | Both move operations |
| A move constructor or move assignment | Both copy operations, which become deleted |

```cpp
struct Tracker {
    std::string s;
    Tracker() = default;
    Tracker(const Tracker&) { std::puts("copy"); }
    Tracker(Tracker&&) noexcept { std::puts("move"); }
};

struct WithDestructor {
    Tracker t;
    ~WithDestructor() {}                     // suppresses the implicit move operations
};

void silent_copy() {
    WithDestructor a;
    WithDestructor b = std::move(a);         // prints "copy": there is no move constructor to call
}
```

- The trap: adding a destructor, perhaps only for logging, silently turns every move of the class into
  a copy. Nothing fails to compile; the code only gets slower.
- The reasoning: a user-written destructor suggests the class manages something non-trivial, so the
  compiler declines to assume a memberwise move is safe.
- The fix: `= default` restores a suppressed operation explicitly, and doubles as documentation.

### `= default` and `= delete`

```cpp
class Handle {
public:
    Handle() = default;
    ~Handle() { /* logging */ }
    Handle(const Handle&) = delete;               // not copyable
    Handle& operator=(const Handle&) = delete;
    Handle(Handle&&) noexcept = default;          // moves restored despite the destructor
    Handle& operator=(Handle&&) noexcept = default;
private:
    std::unique_ptr<int> resource_;
};
```

- `= default` asks for the compiler's memberwise version and fails to compile if a member cannot
  support it, so it is also a check.
- `= delete` removes an operation entirely, so misuse is a compile error rather than a runtime bug.

> Static analysis enforces these rules in large codebases: clang-tidy's
> `cppcoreguidelines-special-member-functions` check reports any class that defines some special
> member functions but not all of them.

## Choosing an ownership type

??? note "Overview"

    --8<-- "guides/cpp_overview/ownership.md:choosing"

When writing a resource wrapper yourself, write all five special member functions deliberately: delete
the copies unless copying has a clear meaning, make the moves `noexcept` and leave the source empty,
and keep destructors from throwing.

## C++ References

Language

- [RAII](https://en.cppreference.com/cpp/language/raii)
- [Rule of three/five/zero](https://en.cppreference.com/cpp/language/rule_of_three)
- [Destructors](https://en.cppreference.com/cpp/language/destructor)
- [Copy constructors](https://en.cppreference.com/cpp/language/copy_constructor), [copy assignment](https://en.cppreference.com/cpp/language/copy_assignment), [move constructors](https://en.cppreference.com/cpp/language/move_constructor), [move assignment](https://en.cppreference.com/cpp/language/move_assignment)
- [Defaulted and deleted functions](https://en.cppreference.com/cpp/language/function)
- [Order of evaluation](https://en.cppreference.com/cpp/language/eval_order)
- [Empty base optimization](https://en.cppreference.com/cpp/language/ebo)
- [Incomplete types](https://en.cppreference.com/cpp/language/type)
- [Lambda captures](https://en.cppreference.com/cpp/language/lambda)
- [Attributes](https://en.cppreference.com/cpp/language/attributes)
- [Exceptions and stack unwinding](https://en.cppreference.com/cpp/language/exceptions)

Library

- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr): [`get`](https://en.cppreference.com/cpp/memory/unique_ptr/get), [`release`](https://en.cppreference.com/cpp/memory/unique_ptr/release), [`reset`](https://en.cppreference.com/cpp/memory/unique_ptr/reset), [`std::make_unique`](https://en.cppreference.com/cpp/memory/unique_ptr/make_unique)
- [`std::shared_ptr`](https://en.cppreference.com/cpp/memory/shared_ptr) and [`std::make_shared`](https://en.cppreference.com/cpp/memory/shared_ptr/make_shared)
- [`std::atomic<std::shared_ptr>`](https://en.cppreference.com/cpp/memory/shared_ptr/atomic2)
- [`std::weak_ptr`](https://en.cppreference.com/cpp/memory/weak_ptr): [`lock`](https://en.cppreference.com/cpp/memory/weak_ptr/lock), [`expired`](https://en.cppreference.com/cpp/memory/weak_ptr/expired)
- [`std::enable_shared_from_this`](https://en.cppreference.com/cpp/memory/enable_shared_from_this) and [`std::bad_weak_ptr`](https://en.cppreference.com/cpp/memory/bad_weak_ptr)
- [`std::lock_guard`](https://en.cppreference.com/cpp/thread/lock_guard), [`std::scoped_lock`](https://en.cppreference.com/cpp/thread/scoped_lock), [`std::unique_lock`](https://en.cppreference.com/cpp/thread/unique_lock)
- [`std::thread`](https://en.cppreference.com/cpp/thread/thread) and [`std::jthread`](https://en.cppreference.com/cpp/thread/jthread)
- [`std::terminate`](https://en.cppreference.com/cpp/error/terminate)
- [`std::exchange`](https://en.cppreference.com/cpp/utility/exchange)
- [`std::function`](https://en.cppreference.com/cpp/utility/functional/function)
- [`std::fopen`](https://en.cppreference.com/cpp/io/c/fopen), [`std::fclose`](https://en.cppreference.com/cpp/io/c/fclose), [`std::malloc`](https://en.cppreference.com/cpp/memory/c/malloc)
