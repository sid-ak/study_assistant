# Objects

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
Polymorphism means writing code that works with many types through one interface. C++ offers two
ways to achieve it: dynamic polymorphism, where the concrete type is determined while the program
runs, and static polymorphism, where the compiler resolves it while building the program. The choice
affects run-time speed, binary size, and how objects are laid out in memory — and that layout matters
whenever a struct is written to disk or sent over a network.

| Approach | Resolved | Run-time cost | Best suited for |
| -------- | -------- | ------------- | --------------- |
| Virtual functions (dynamic) | At run time, from the object's actual type | One indirect call per invocation; a hidden pointer per object; calls usually cannot be inlined | A set of types that is open or only known at run time, such as plugins or drivers |
| Templates or CRTP (static) | At compile time, from the declared type | None; calls can be inlined | Performance-critical code where every type is known when compiling |
<!-- --8<-- [end:intro] -->

## 1. Virtual functions

<!-- --8<-- [start:virtual] -->
Declaring a member function `virtual` tells the compiler to decide which implementation to call based
on the object's actual type, even when it is accessed through a pointer or reference to a base class.

```cpp
struct Shape {
    virtual ~Shape() = default;
    virtual double area() const = 0;   // pure virtual: derived classes must implement it
};

struct Square final : Shape {
    double side = 1.0;
    double area() const override { return side * side; }
};

double total(const Shape& s) { return s.area(); }   // calls Square::area for a Square
```

- `override`: marks a function that is meant to replace a base class version. The compiler reports
  an error if the signatures do not match, instead of silently creating an unrelated function.
- `final`: prevents further overriding or derivation, which can also let the compiler call the
  function directly.
- Abstract class: a class with at least one pure virtual function (`= 0`) cannot be instantiated on
  its own; it only defines an interface.

> A media player defines an abstract `Decoder` class with implementations for MP3, AAC, and FLAC.
> The playback loop calls `decoder->decode()` without knowing which format the file uses, and
> support for a new format is added without changing the loop.
<!-- --8<-- [end:virtual] -->

[Go deeper →](../cpp_deep_dive/objects.md#1-virtual-functions)

## 2. How virtual dispatch works

<!-- --8<-- [start:dispatch] -->
Compilers implement virtual functions with a table of function pointers.

```cpp
struct Plain   { int value; };
struct Virtual { int value; virtual void f() {} };

// On a typical 64-bit platform:
static_assert(sizeof(Plain) == 4);
static_assert(sizeof(Virtual) == 16);   // 8-byte vptr + 4-byte int + 4 bytes padding
```

- vtable: for each class with virtual functions, the compiler generates one table containing the
  address of that class's implementation of each virtual function.
- vptr: each object of such a class contains a hidden pointer to its class's vtable, typically
  8 bytes on a 64-bit platform, as the size difference above shows.
- A virtual call: load the vptr from the object, load the function address from the table, then call
  through that address. The extra indirection is small, but because the target is unknown at compile
  time, the compiler usually cannot inline the call or optimize across it.

> A particle system updating millions of particles per frame avoids a virtual `update()` call per
> particle, because the indirect call and lost inlining add up. It stores particles of each kind in
> their own array and loops over each array directly.
<!-- --8<-- [end:dispatch] -->

[Go deeper →](../cpp_deep_dive/objects.md#2-how-virtual-dispatch-works)

## 3. Virtual destructors

<!-- --8<-- [start:destructors] -->
If a class is meant to be deleted through a pointer to its base, the base class destructor must be
`virtual`.

```cpp
struct Base { ~Base() {} };                     // not virtual
struct Derived : Base { std::vector<int> data; };

struct SafeBase { virtual ~SafeBase() = default; };
struct SafeDerived : SafeBase { std::vector<int> data; };

void destroy() {
    Base* bad = new Derived;
    delete bad;                                 // undefined behavior: ~Derived never runs

    SafeBase* good = new SafeDerived;
    delete good;                                // runs ~SafeDerived, then ~SafeBase
}
```

- Reason: `delete base_ptr` calls the destructor found through the pointer's static type. Without
  `virtual`, only the base destructor runs, the derived part is never cleaned up, and the behavior is
  undefined.
- Rule: a class with any virtual function should have a virtual destructor, or a protected
  non-virtual one if deleting through the base is never intended.

> A plugin system that loads plugins as `std::unique_ptr<Plugin>` must give `Plugin` a virtual
> destructor; otherwise unloading a plugin would skip the plugin's own cleanup, such as closing the
> files it opened.
<!-- --8<-- [end:destructors] -->

[Go deeper →](../cpp_deep_dive/objects.md#3-virtual-destructors)

## 4. Object slicing

<!-- --8<-- [start:slicing] -->
Copying a derived object into a variable of the base type by value copies only the base part.

```cpp
struct Animal {
    virtual ~Animal() = default;
    virtual std::string sound() const { return "..."; }
};
struct Dog : Animal {
    std::string sound() const override { return "woof"; }
};

std::string by_value(Animal a)            { return a.sound(); }   // "..." : sliced
std::string by_reference(const Animal& a) { return a.sound(); }   // "woof" for a Dog
```

- Effect: the derived members are discarded, and virtual calls on the copy use the base class
  behavior.
- Prevention: pass polymorphic objects by reference or pointer, never by value.

> Catching exceptions by value, as in `catch (std::exception e)`, slices a `std::runtime_error` down
> to its base class and loses its specific message. Catching by reference, `catch (const
> std::exception& e)`, keeps the full object.
<!-- --8<-- [end:slicing] -->

[Go deeper →](../cpp_deep_dive/objects.md#4-object-slicing)

## 5. Memory layout and padding

<!-- --8<-- [start:layout] -->
A struct's members are laid out in declaration order, but the compiler may insert unused bytes
between them.

```cpp
struct Loose { char a; int b; char c; };   // a, 3 padding, b, c, 3 padding
struct Tight { int b; char a; char c; };   // b, a, c, 2 padding

static_assert(alignof(int) == 4);          // typical on mainstream platforms
static_assert(sizeof(Loose) == 12);
static_assert(sizeof(Tight) == 8);

struct DiskHeader {                        // a format that leaves the process
    std::uint32_t magic;
    std::uint32_t version;
    std::uint64_t length;
};
static_assert(sizeof(DiskHeader) == 16);   // fails the build if the layout ever changes
```

- Alignment: many CPUs read a value fastest, or can only read it at all, when it starts at an address
  that is a multiple of a fixed number for its type — for example, a 4-byte `int` usually at a
  multiple of 4. That number is the type's alignment, and `alignof(T)` reports it.
- Padding: to satisfy alignment, the compiler inserts padding bytes, so member order changes a
  struct's size, as `Loose` and `Tight` show.
- On-disk and network formats: padding, alignment, and byte order can differ between compilers and
  CPUs, so a struct written directly to a file may not be read back correctly elsewhere. Formats that
  must be stable use fixed-width types such as `std::uint32_t`, layout checks with `static_assert`,
  and explicit byte-order conversion.

> File formats such as ZIP and PNG begin with fixed-layout headers. Code that reads them with a
> struct uses fixed-width fields and a `static_assert` on `sizeof`, so a different compiler or
> platform cannot silently change where each field sits.
<!-- --8<-- [end:layout] -->

[Go deeper →](../cpp_deep_dive/objects.md#5-memory-layout-and-padding)

## 6. Static polymorphism with CRTP

<!-- --8<-- [start:crtp] -->
The Curiously Recurring Template Pattern (CRTP) gets polymorphic behavior without virtual functions:
a base class template takes the derived class as its template parameter.

```cpp
template <typename Derived>
struct Serializer {
    std::string serialize() const {
        return static_cast<const Derived&>(*this).fields();   // resolved at compile time
    }
};

struct User : Serializer<User> {
    std::string name = "ada";
    std::string fields() const { return "name=" + name; }
};

std::string save(const User& u) { return u.serialize(); }     // no vtable, can be inlined
```

- Mechanism: because the base knows the derived type at compile time, it can call derived functions
  directly through `static_cast`. No vtable or vptr exists.
- Trade-off: each derived type produces separate compiled code, and the set of types must be known at
  compile time. [Templates](templates.md) covers the underlying mechanism.

> Math and numeric libraries such as Eigen use CRTP so that operations on matrices and vectors share
> one implementation while every call is resolved at compile time and inlined into tight loops.
<!-- --8<-- [end:crtp] -->

[Go deeper →](../cpp_deep_dive/objects.md#6-static-polymorphism-with-crtp)

## Choosing between them

<!-- --8<-- [start:choosing] -->
Use virtual functions when the set of types is open-ended or selected at run time, and the call is
not in a performance-critical loop. Use templates or CRTP when the types are known at compile time
and the calls are frequent enough that inlining matters. In either case, check `sizeof` for any
struct whose layout leaves the process.
<!-- --8<-- [end:choosing] -->

## C++ References

Language

- [Derived classes and inheritance](https://en.cppreference.com/cpp/language/derived_class)
- [Virtual functions](https://en.cppreference.com/cpp/language/virtual)
- [`override`](https://en.cppreference.com/cpp/language/override) and [`final`](https://en.cppreference.com/cpp/language/final)
- [Abstract classes and pure virtual functions](https://en.cppreference.com/cpp/language/abstract_class)
- [Destructors](https://en.cppreference.com/cpp/language/destructor)
- [Object representation and alignment](https://en.cppreference.com/cpp/language/object)
- [`sizeof`](https://en.cppreference.com/cpp/language/sizeof) and [`alignof`](https://en.cppreference.com/cpp/language/alignof)
- [`static_assert`](https://en.cppreference.com/cpp/language/static_assert)
- [`static_cast`](https://en.cppreference.com/cpp/language/static_cast) and [`dynamic_cast`](https://en.cppreference.com/cpp/language/dynamic_cast)
- [Curiously Recurring Template Pattern](https://en.cppreference.com/cpp/language/crtp)
- [Incomplete types](https://en.cppreference.com/cpp/language/type)

Library

- [Fixed-width integer types](https://en.cppreference.com/cpp/types/integer)
- [`std::endian`](https://en.cppreference.com/cpp/types/endian) and [`std::byteswap`](https://en.cppreference.com/cpp/numeric/byteswap)
- [`std::is_standard_layout`](https://en.cppreference.com/cpp/types/is_standard_layout)
