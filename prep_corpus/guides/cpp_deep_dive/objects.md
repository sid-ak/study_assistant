# Objects

> Part of the [C++ Deep Dive](README.md) · Overview: [Objects](../cpp_overview/objects.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:intro"

This page follows objects down to their bytes: the rules that govern virtual calls during construction
and with default arguments, how vtables are indexed, why virtual calls block optimization, what order
objects are torn down in, how the compiler lays out members, and the alignment and byte-order rules
that decide whether a struct can safely leave the process.

## 1. Virtual functions

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:virtual"

### Static and dynamic dispatch

```cpp
struct Shape {
    virtual ~Shape() = default;
    virtual void draw() const = 0;
    void describe() const { std::puts("a shape"); }     // non-virtual: chosen by static type
};

struct Circle : Shape {
    void draw() const override { std::puts("circle"); }
    void describe() const { std::puts("a circle"); }    // hides, does not override
};

void render_all(const std::vector<const Shape*>& shapes) {
    for (const Shape* s : shapes) {
        s->draw();        // dynamic dispatch: the object's actual type decides
        s->describe();    // static dispatch: always Shape::describe
    }
}
```

- Static dispatch: the compiler picks the function from the declared type of the expression, and the
  call target is fixed in the machine code.
- Dynamic dispatch: the target depends on the object's run-time type, which the compiler cannot know
  when `render_all` is compiled; new derived classes may be written later.
- Only through indirection: dispatch is dynamic only through a pointer or reference. Calling through an
  object of type `Shape` by value always uses `Shape`'s functions.
- Once virtual, always virtual: a function declared `virtual` in a base is virtual in every derived
  class, whether or not the derived declaration repeats the keyword.

### Virtual calls during construction and destruction

```cpp
struct Base {
    Base() { who(); }                                  // prints "Base::who", not "Derived::who"
    virtual ~Base() = default;
    virtual void who() { std::puts("Base::who"); }
};

struct Derived : Base {
    std::string name = "derived";
    void who() override { std::puts(name.c_str()); }  // would read name before it is constructed
};
```

- Construction order: base subobjects are constructed before derived members. While `Base()` runs,
  `Derived::name` does not exist yet, so dispatching to `Derived::who` would read uninitialized
  memory.
- Rule: during a constructor or destructor, the object's dynamic type is the class currently being
  constructed or destroyed. Implementations achieve this by setting the vptr to each class's vtable in
  turn as construction proceeds.
- Pure virtual calls: calling a pure virtual function this way is undefined behavior; typical
  implementations abort with "pure virtual function called".

### Default arguments bind statically

```cpp
struct Printer {
    virtual ~Printer() = default;
    virtual void print(const char* prefix = "base") { std::printf("Printer %s\n", prefix); }
};

struct Fancy : Printer {
    void print(const char* prefix = "fancy") override { std::printf("Fancy %s\n", prefix); }
};

void call(Printer& p) {
    p.print();    // with a Fancy object: prints "Fancy base"
}
```

- Mechanism: default arguments are inserted at the call site, where only the static type is known,
  while the function body is chosen at run time. The result mixes the derived body with the base
  default.
- Guideline: do not give virtual functions default arguments; use a non-virtual wrapper that supplies
  the default and calls a virtual function without one.

> Plugin architectures such as audio effect hosts load classes from shared libraries at run time and
> call them only through abstract base classes. The host was compiled long before the plugin existed,
> so dynamic dispatch is the only way it can call the plugin's code.

## 2. How virtual dispatch works

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:dispatch"

### Vtable slots

```cpp
struct Animal {
    virtual ~Animal() = default;     // slot(s) for the destructor
    virtual void speak() const {}    // next slot
    virtual int legs() const { return 4; }
};

struct Bird : Animal {
    void speak() const override {}   // Bird's vtable: same slot, different address
    int legs() const override { return 2; }
};
```

- One table per class: all objects of a class share one vtable containing the addresses of that
  class's final overriders, plus run-time type information (RTTI) used by `dynamic_cast` and
  `typeid`.
- Fixed slots: each virtual function occupies the same index in the vtable of the base and of every
  derived class. A call through `Animal&` can therefore be compiled as "call the address in slot N"
  without knowing the dynamic type.
- vptr placement: on the Itanium C++ ABI used by GCC and Clang, the vptr is at offset 0 of a
  polymorphic object with a single primary base.

### What a virtual call costs

```cpp
struct Plain   { float x, y; };
struct Virtual { virtual ~Virtual() = default; float x, y; };

static_assert(sizeof(Plain) == 8);
static_assert(sizeof(Virtual) == 16);     // the vptr doubles the size of a small object
```

- Space: one pointer per object. For small objects this can double the size and halve how many fit in
  a cache line.
- Time: two dependent memory loads (the vptr, then the slot) and an indirect branch, which the CPU's
  branch predictor must learn per call site.
- Optimization barrier: the larger cost is that the compiler cannot see the callee. It cannot inline
  it, and it must assume the call may modify any memory reachable from pointers, so it reloads values
  it would otherwise keep in registers and cannot vectorize loops around the call.

### Devirtualization

```cpp
struct Sensor {
    virtual ~Sensor() = default;
    virtual int read() const = 0;
};

struct Thermometer final : Sensor {        // final: no class can override read() further
    int read() const override { return 21; }
};

int sample(const Thermometer& t) {
    return t.read();                       // compiler may call Thermometer::read directly, or inline it
}
```

- When it happens: the compiler replaces a virtual call with a direct call when it can prove the
  dynamic type — the object is a local of known type, the class or function is `final`, or whole-program
  analysis (link-time optimization) shows only one implementation exists.
- `final` is therefore a performance tool as well as a design statement.

> Game engines built around entity-component systems store components of each type in their own
> contiguous arrays and process each array with a direct loop, instead of calling a virtual `update()`
> on a list of mixed objects. The data layout, not only the removed indirection, is where most of the
> speedup comes from.

## 3. Virtual destructors

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:destructors"

### Protected non-virtual destructors

```cpp
class Callback {                           // an interface never owned through a base pointer
public:
    virtual void fire() = 0;
protected:
    ~Callback() = default;                 // non-virtual: no need to pay for polymorphic deletion
};

class Timer : public Callback {
public:
    void fire() override {}
};

void use(Callback& cb) {
    cb.fire();
    // delete &cb;                         // error: ~Callback is protected
}
```

- Alternative to `virtual`: if objects are never deleted through a base pointer, making the base
  destructor `protected` turns `delete base_ptr` into a compile error. The class stays usable as an
  interface without implying ownership through the base.
- Guideline: a base class destructor should be either public and virtual, or protected and non-virtual.

### Destruction order

```cpp
struct Part {
    const char* name;
    ~Part() { std::printf("~%s ", name); }
};

struct Engine : Part {
    Part first{"first"};
    Part second{"second"};
    Engine() : Part{"base"} {}
    ~Engine() { std::printf("~Engine "); }
};
// destroying an Engine prints: ~Engine ~second ~first ~base
```

1. The destructor body runs.
2. Non-static data members are destroyed in reverse order of declaration.
3. Base class subobjects are destroyed in reverse order of construction.

- Reason: this is exactly construction reversed, which guarantees that anything an object might use
  during its destruction is still alive.

> Standard library classes intended as bases for polymorphic use, such as `std::exception` and
> `std::streambuf`, have virtual destructors, while value types such as `std::vector` and `std::string`
> do not. Deriving from a `std::vector` and deleting through `std::vector*` is therefore undefined
> behavior.

## 4. Object slicing

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:slicing"

### Why slicing is unavoidable in value storage

```cpp
struct Base {
    virtual ~Base() = default;
    virtual const char* name() const { return "base"; }
};

struct Derived : Base {
    std::string extra = "lost when sliced";
    const char* name() const override { return "derived"; }
};

void containers() {
    std::vector<Base> by_value;
    by_value.push_back(Derived{});                   // sliced: only the Base part is stored

    std::vector<std::unique_ptr<Base>> by_pointer;
    by_pointer.push_back(std::make_unique<Derived>());   // keeps the full Derived object
}
```

- Layout: a `Derived` object is a `Base` subobject followed by `Derived`'s members. A `Base` variable
  has exactly `sizeof(Base)` bytes, so there is nowhere to put the rest.
- Result: the copy is a valid `Base` with `Base`'s vptr. Nothing crashes; behavior silently changes.
- Containers: `std::vector<Base>` stores equal-sized elements side by side, so it must slice. Holding
  different derived types requires indirection, such as `std::unique_ptr<Base>`.

### Making slicing a compile error

```cpp
class Shape {
public:
    virtual ~Shape() = default;
    Shape(const Shape&) = delete;              // copying a Shape by value no longer compiles
    Shape& operator=(const Shape&) = delete;
    virtual double area() const = 0;
protected:
    Shape() = default;
};
```

- Polymorphic base classes rarely have a meaningful copy. Deleting the copy operations, or making the
  class abstract, turns accidental slicing into a compile error.
- When copies are needed, a virtual `clone()` returning `std::unique_ptr<Base>` copies the full dynamic
  type.

> Exception handlers are the most common place slicing appears in real code. Rethrowing with
> `throw e;` inside `catch (const std::exception& e)` throws a sliced copy of type `std::exception`,
> while a bare `throw;` rethrows the original object with its full type.

## 5. Memory layout and padding

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:layout"

### What an object contains

```cpp
struct Header {
    std::uint8_t  kind;      // offset 0
                             // 3 bytes of padding
    std::uint32_t length;    // offset 4
    std::uint64_t id;        // offset 8
};

static_assert(offsetof(Header, length) == 4);
static_assert(offsetof(Header, id) == 8);
static_assert(sizeof(Header) == 16);
```

- Contents, in order: the vptr if the class is polymorphic, base class subobjects, then non-static data
  members in declaration order, with padding to satisfy alignment.
- Declaration order: members with the same access control are laid out in declaration order, and the
  compiler may not reorder them to save space. Ordering members well is the programmer's job.
- Tail padding: `sizeof` is always a multiple of the strictest member alignment, so consecutive array
  elements stay aligned.
- Largest alignment first: ordering members from largest to smallest alignment usually minimizes
  padding.

### Empty classes take space, except as bases

```cpp
struct Empty {};

struct AsMember { Empty e; int x; };
struct AsBase : Empty { int x; };
struct WithAttribute { [[no_unique_address]] Empty e; int x; };

static_assert(sizeof(Empty) == 1);           // every object needs a distinct address
static_assert(sizeof(AsMember) == 8);        // 1 byte + 3 padding + 4
static_assert(sizeof(AsBase) == 4);          // empty base optimization
static_assert(sizeof(WithAttribute) == 4);   // C++20: the same saving for members
```

- Distinct addresses: two different objects of the same type must have different addresses, so an empty
  object still occupies at least one byte.
- Empty base optimization (EBO): a base class subobject may occupy zero bytes. Standard library
  implementations store stateless allocators and deleters this way, which is why `std::unique_ptr` with
  its default deleter is pointer-sized.
- `[[no_unique_address]]` (C++20): lets a data member receive the same treatment. MSVC ignores this
  attribute and provides `[[msvc::no_unique_address]]` instead.

### Trivially copyable and standard-layout types

```cpp
struct Record {
    std::uint32_t id;
    std::uint16_t flags;
    std::uint16_t reserved;
};

static_assert(std::is_trivially_copyable_v<Record>);   // bytes fully describe the value
static_assert(std::is_standard_layout_v<Record>);      // predictable member order

void copy_bytes(Record& dst, const Record& src) {
    std::memcpy(&dst, &src, sizeof(Record));          // well-defined for trivially copyable types
}
```

- Trivially copyable: no user-provided copy or move operations, no virtual functions or virtual bases,
  and a trivial destructor. Copying its bytes with `memcpy` produces a valid copy.
- Standard layout: all non-static members share the same access control, there are no virtual functions,
  and member layout follows rules compatible with C. A pointer to such an object can be converted to a
  pointer to its first member.
- Both together correspond to what older standards called "POD" (plain old data), the property required
  for structs that are shared with C code or mapped onto binary formats.

### Complete and incomplete types

```cpp
struct Later;                    // forward declaration: Later is incomplete here

struct Holder {
    // Later value;              // error: size and alignment of Later are unknown
    Later* pointer;              // fine: a pointer's size does not depend on its target
    Later& reference;            // fine for the same reason
};

struct Later { int x; };         // Later becomes complete here
```

- Rule: a by-value member needs a complete type, because the compiler must know its size and alignment
  to place it. Pointers and references do not.
- Operations that need completeness: `sizeof` and `alignof`, inheriting from the type, creating objects
  of it, accessing members, and `delete` through a pointer to it. Deleting an incomplete type is
  undefined behavior, and `std::unique_ptr`'s deleter rejects it at compile time.
- Definition order: when structs contain each other by value, each must be defined before the structs
  that contain it. A by-value cycle is impossible, because the struct would have to contain its own size.
- Build time: headers that only need pointers can forward-declare types instead of including their
  definitions. See [Build & Toolchain](build-toolchain.md).

> The Linux kernel ships a tool, `pahole`, that prints every hole and padding byte inside a struct
> from its debug information. Kernel developers use it to reorder members of structures such as
> `struct sk_buff`, which exist in huge numbers, so more of them fit in each cache line.

## 6. Static polymorphism with CRTP

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:crtp"

### Why the pattern is not circular

```cpp
template <typename Derived>
class Entity {
public:
    std::string save() const {
        return "INSERT INTO " + self().table() + " VALUES (" + self().values() + ")";
    }
private:
    const Derived& self() const { return static_cast<const Derived&>(*this); }
};

class Reading : public Entity<Reading> {
public:
    std::string table() const { return "readings"; }
    std::string values() const { return "42"; }
};
```

- Instantiation timing: `Entity<Reading>` is instantiated when `Reading` names it as a base, while
  `Reading` is still incomplete. That is allowed because `Entity` only uses `Derived` inside member
  function bodies, and those are instantiated later, when called, by which point `Reading` is complete.
- The cast: `static_cast<const Derived&>(*this)` is safe because the template argument guarantees the
  object really is a `Derived`. It is a compile-time pointer adjustment, not a lookup.

### Virtual functions compared with CRTP

| | Virtual functions | CRTP |
| - | ----------------- | ---- |
| Dispatch | At run time, through the vtable | At compile time, through `static_cast` |
| Run-time cost | Indirect call, no inlining, a vptr per object | None |
| Mixed types in one container | Yes, through `Base*` | No: each `Entity<T>` is an unrelated type |
| Derived type visible to the base | No: erased behind `Base*` | Yes: available as a template parameter |
| Missing implementation detected | At compile time only for pure virtual functions | At compile time when the base calls it |

- The decisive row: because CRTP gives the base the derived type as a type, the base can use it in other
  templates — for example, compile-time reflection libraries such as Boost.Describe that enumerate a
  type's members. Virtual dispatch erases exactly that information.
- Costs: longer compile times, harder error messages before concepts, and no heterogeneous containers.

### Common uses

```cpp
template <typename T>
struct Comparable {                                    // mixin: derive != and > from == and <
    friend bool operator!=(const T& a, const T& b) { return !(a == b); }
    friend bool operator>(const T& a, const T& b) { return b < a; }
};

struct Version : Comparable<Version> {
    int major = 0;
    friend bool operator==(const Version& a, const Version& b) { return a.major == b.major; }
    friend bool operator<(const Version& a, const Version& b) { return a.major < b.major; }
};

template <typename T>
struct Counted {                                       // a separate counter for each derived type
    inline static int instances = 0;
    Counted() { ++instances; }
};

struct Connection : Counted<Connection> {};
```

- Mixins: adding operators or helper functions to many unrelated types from one template.
- Per-type state: each instantiation has its own static members.
- In the standard library: `std::enable_shared_from_this<T>` and `std::ranges::view_interface<D>` are
  both CRTP bases.

> C++23's deducing `this` removes the need for CRTP in many mixins: a base class member function declared
> `template <typename Self> void f(this Self&& self)` receives the derived type directly, with no template
> parameter on the base class.

## 7. Alignment beyond the struct

Alignment also constrains memory handed to the CPU's vector instructions, to devices, and to other
threads, where the requirements are stricter than a type's natural alignment.

```cpp
struct alignas(64) PerCoreCounter {             // starts on its own 64-byte cache line
    std::atomic<std::uint64_t> value{0};
};

static_assert(alignof(PerCoreCounter) == 64);
static_assert(sizeof(PerCoreCounter) == 64);

void* page_aligned_buffer(std::size_t size) {
    return ::operator new(size, std::align_val_t{4096});   // must be freed with the aligned delete
}

void release(void* p) {
    ::operator delete(p, std::align_val_t{4096});
}
```

- Default guarantee: `new` and `malloc` return memory suitable for any fundamental type, the alignment of
  `std::max_align_t` — 16 bytes on x86-64 Linux, 8 bytes on Apple Silicon.
- Stricter alignment: `alignas` on a type or variable, `operator new` with `std::align_val_t` (used
  automatically by `new T` for over-aligned types since C++17), and `std::aligned_alloc`.
- Misaligned access: reading a type through a pointer that is not properly aligned is undefined
  behavior. Some older ARM and SPARC processors fault, x86 usually tolerates it, and optimizers may
  generate vector instructions that assume alignment and crash. `-fsanitize=alignment` detects it.
- Device and I/O alignment: direct I/O and hardware that reads memory directly require buffers aligned to
  a block or page size. See [Memory](memory.md).
- Cache lines: aligning independently updated data to 64 bytes keeps threads from invalidating each
  other's cache lines. See [Concurrency](concurrency.md).

> Network packet processing frameworks such as DPDK allocate packet buffers from memory pools aligned to
> cache lines and pages, so the network card can write directly into them and each packet's metadata
> starts at the beginning of a cache line.

## 8. Byte order

The order in which a multi-byte integer's bytes are stored is called its byte order, or endianness.

```cpp
std::uint32_t to_big_endian(std::uint32_t value) {
    if (std::endian::native == std::endian::little) {
        return std::byteswap(value);                       // C++23
    }
    return value;
}

std::array<std::uint8_t, 4> encode_length(std::uint32_t length) {   // portable: independent of host order
    return {static_cast<std::uint8_t>(length >> 24), static_cast<std::uint8_t>(length >> 16),
            static_cast<std::uint8_t>(length >> 8), static_cast<std::uint8_t>(length)};
}
```

- Little-endian: the least significant byte is at the lowest address. x86 and ARM (as configured by
  every mainstream operating system) are little-endian.
- Big-endian: the most significant byte comes first. It is the conventional "network byte order" used by
  IP, TCP, and protocols such as NFS's XDR encoding.
- When it matters: never within one machine, always when bytes cross to something else — a file format,
  a network protocol, or a device.
- Tools: `std::endian` (C++20) detects the host order at compile time, `std::byteswap` (C++23) reverses
  bytes, and POSIX `htonl`/`ntohl` convert to and from network order.

### Serializing structs safely

- Three hidden assumptions: writing a struct's bytes directly with `memcpy` or `write` bakes in the
  host's byte order, the compiler's padding, and the platform's integer widths.
- Explicit encoding: serialize field by field using fixed-width types (`std::uint32_t`, not `int`) and an
  explicit byte order, or use a schema-driven format such as Protocol Buffers or FlatBuffers that
  generates this code.

> File formats document their byte order explicitly: PNG stores multi-byte integers big-endian, while
> formats designed around x86, such as BMP and WAV, use little-endian. Readers that convert each field
> explicitly work unchanged on any host.

## Choosing between them

??? note "Overview"

    --8<-- "guides/cpp_overview/objects.md:choosing"

Mark classes and overrides `final` where extension is not intended, so the compiler can devirtualize
calls. For data that crosses a process boundary, pin the layout with fixed-width types and
`static_assert` checks, and encode byte order explicitly.

## C++ References

Language

- [Derived classes](https://en.cppreference.com/cpp/language/derived_class) and [virtual functions](https://en.cppreference.com/cpp/language/virtual)
- [`override`](https://en.cppreference.com/cpp/language/override), [`final`](https://en.cppreference.com/cpp/language/final), [abstract classes](https://en.cppreference.com/cpp/language/abstract_class)
- [Default arguments](https://en.cppreference.com/cpp/language/default_arguments)
- [Constructors and member initializer lists](https://en.cppreference.com/cpp/language/constructor)
- [Destructors](https://en.cppreference.com/cpp/language/destructor)
- [Object representation and alignment](https://en.cppreference.com/cpp/language/object)
- [`sizeof`](https://en.cppreference.com/cpp/language/sizeof), [`alignof`](https://en.cppreference.com/cpp/language/alignof), [`alignas`](https://en.cppreference.com/cpp/language/alignas)
- [Empty base optimization](https://en.cppreference.com/cpp/language/ebo) and [`[[no_unique_address]]`](https://en.cppreference.com/cpp/language/attributes/no_unique_address)
- [Classes, including standard-layout and trivially copyable classes](https://en.cppreference.com/cpp/language/classes)
- [Incomplete types](https://en.cppreference.com/cpp/language/type)
- [`static_cast`](https://en.cppreference.com/cpp/language/static_cast), [`dynamic_cast`](https://en.cppreference.com/cpp/language/dynamic_cast), [`typeid`](https://en.cppreference.com/cpp/language/typeid)
- [Curiously Recurring Template Pattern](https://en.cppreference.com/cpp/language/crtp)
- [Explicit object parameters](https://en.cppreference.com/cpp/language/member_functions)
- [`throw` expressions and rethrowing](https://en.cppreference.com/cpp/language/throw)

Library

- [`offsetof`](https://en.cppreference.com/cpp/types/offsetof) and [`std::max_align_t`](https://en.cppreference.com/cpp/types/max_align_t)
- [`std::is_trivially_copyable`](https://en.cppreference.com/cpp/types/is_trivially_copyable) and [`std::is_standard_layout`](https://en.cppreference.com/cpp/types/is_standard_layout)
- [`std::memcpy`](https://en.cppreference.com/cpp/string/byte/memcpy)
- [`operator new` with `std::align_val_t`](https://en.cppreference.com/cpp/memory/new/operator_new) and [`std::aligned_alloc`](https://en.cppreference.com/cpp/memory/c/aligned_alloc)
- [Fixed-width integer types](https://en.cppreference.com/cpp/types/integer)
- [`std::endian`](https://en.cppreference.com/cpp/types/endian) and [`std::byteswap`](https://en.cppreference.com/cpp/numeric/byteswap)
- [`std::enable_shared_from_this`](https://en.cppreference.com/cpp/memory/enable_shared_from_this) and [`std::ranges::view_interface`](https://en.cppreference.com/cpp/ranges/view_interface)
- [`std::exception`](https://en.cppreference.com/cpp/error/exception)
- [`std::unique_ptr`](https://en.cppreference.com/cpp/memory/unique_ptr) and [`std::atomic`](https://en.cppreference.com/cpp/atomic/atomic)
