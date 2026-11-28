# Containers

> Part of the [C++ Deep Dive](README.md) · Overview: [Containers](../cpp_overview/containers.md)

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:intro"

This page quantifies why memory layout decides container performance, then looks inside each
container: how `vector` grows and why that is still constant time on average, how trees and hash tables
trade predictability for speed, the full iterator invalidation rules, and the internal structure of
`array`, `deque`, and `list`.

## 1. Why memory layout dominates

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:layout"

### The memory hierarchy in numbers

| Where the data is | Approximate time to read |
| ----------------- | ------------------------ |
| L1 cache | about 1 ns |
| L2 cache | about 4 ns |
| L3 cache | about 15 ns |
| Main memory | about 80–100 ns |
| NVMe SSD | about 20–100 µs |
| Rotating disk | about 5–10 ms |

- The gap: a read from main memory costs about as much time as a hundred reads from L1. Big-O notation
  counts operations as if each cost the same, which is why structures with better asymptotic complexity
  often lose on real hardware.
- Cache lines: data moves between memory and cache in fixed blocks called cache lines — 64 bytes on
  typical x86-64 processors, 128 bytes as reported by Apple Silicon. Touching one byte loads its
  neighbours for free.
- Prefetching: the CPU watches access patterns and fetches ahead when it sees a regular stride.
  Sequential access through contiguous memory is predicted; following pointers is not, because the next
  address is only known after the current load completes.

### Struct of arrays versus array of structs

```cpp
struct ParticleAoS {                 // array of structs: one record per particle
    float x, y, z;
    float vx, vy, vz;
    float mass;
    std::uint32_t flags;
};
std::vector<ParticleAoS> particles_aos;

struct ParticlesSoA {                // struct of arrays: one array per field
    std::vector<float> x, y, z;
    std::vector<float> vx, vy, vz;
    std::vector<float> mass;
    std::vector<std::uint32_t> flags;
};

float total_mass(const ParticlesSoA& p) {
    float sum = 0;
    for (float m : p.mass) sum += m;     // every byte loaded is a byte used; easy to vectorize
    return sum;
}
```

- Array of structs (AoS): scanning one field still loads every other field of each record into cache,
  so most loaded bytes go unused.
- Struct of arrays (SoA): each field is its own contiguous array, so a scan over one field loads only
  that field, and the loop is a straightforward candidate for SIMD vectorization.
- Hot and cold splitting: moving rarely used fields into a separate structure keeps the frequently
  used fields packed into fewer cache lines, a lighter-weight version of the same idea.

### Translation lookaside buffer pressure

- Virtual memory: every memory access translates a virtual address to a physical one, and the CPU caches
  recent translations in the translation lookaside buffer (TLB), which holds a limited number of entries.
- Large working sets: a program touching many gigabytes spread across 4 KB pages needs far more
  translations than the TLB holds, adding page-table walks to cache misses. Huge pages (2 MB or 1 GB)
  cover the same memory with far fewer entries. See [Memory](memory.md).

> Database engines designed for analytics, such as DuckDB and ClickHouse, store tables column by column
> rather than row by row. A query that sums one column reads a contiguous array of that column's values
> and never touches the others, which is the struct-of-arrays layout applied to a whole database.

## 2. `std::vector`: the default

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:vector"

### Internals

```cpp
void inspect() {
    std::vector<int> v;
    std::size_t last = 0;
    for (int i = 0; i < 100; ++i) {
        v.push_back(i);
        if (v.capacity() != last) {
            last = v.capacity();
            std::printf("%zu ", last);    // libc++ and libstdc++ print 1 2 4 8 16 32 64 128
        }
    }
}

static_assert(sizeof(std::vector<int>) == 3 * sizeof(int*));   // begin, end, end of capacity
```

- Layout: three pointers — the start of the buffer, one past the last element, and one past the end of
  the allocation. `size()` and `capacity()` are differences between them.
- Growth factor: libstdc++ and libc++ double the capacity; Microsoft's library grows by 1.5×.

### Why geometric growth is constant time on average

- Fixed increments: growing by a constant 10 slots would reallocate N/10 times while filling N elements,
  copying about N²/20 elements in total — quadratic.
- Geometric growth: multiplying capacity by a constant means about log(N) reallocations, and the elements
  moved form a geometric series (N/2 + N/4 + ...) bounded by N. Spread over N insertions, each costs
  constant time on average, which is what "amortized O(1)" means.
- Individual cost: the insertion that triggers reallocation is still O(n), and its allocation has
  unpredictable latency. `reserve` removes those spikes when the final size is known.
- Middle insertion: shifting elements is a single `memmove` for trivially copyable types, which runs at
  memory bandwidth, so "O(n) with a tiny constant" often beats a node-based structure's "O(1) plus a
  cache miss".

### `resize` mistakes and `shrink_to_fit`

```cpp
void mistakes() {
    std::vector<int> values;
    values.resize(100);          // 100 zeros already exist
    for (int i = 0; i < 100; ++i) {
        values.push_back(i);     // bug: appends after the zeros, giving 200 elements
    }

    std::vector<int> big(1'000'000);
    big.clear();                 // size 0, but the capacity (and memory) is kept
    big.shrink_to_fit();         // non-binding request to release unused capacity
}
```

- `resize` followed by `push_back` is the common way to double a vector's length by accident; use either
  `resize` and index assignment, or `reserve` and `push_back`.
- `clear()` destroys the elements but keeps the allocation, which is usually what a reused buffer wants.
  `shrink_to_fit()` asks the implementation to reallocate to the current size.

### `emplace_back` compared with `push_back`

```cpp
struct Endpoint {
    explicit Endpoint(int port) : port(port) {}
    int port;
};

void add() {
    std::vector<Endpoint> endpoints;
    endpoints.push_back(Endpoint(8080));   // constructs a temporary, then moves it in
    endpoints.emplace_back(9090);          // constructs directly in the vector's storage
    // endpoints.push_back(443);           // error: the constructor is explicit
    endpoints.emplace_back(443);           // compiles: emplace calls the constructor directly
}
```

- Mechanism: `emplace_back` forwards its arguments to the element's constructor at the final address.
  See [Value Semantics](value-semantics.md).
- Savings: one move for non-trivial types; nothing measurable for simple types.
- Caveat: because `emplace_back` calls constructors directly, it bypasses `explicit`, so conversions the
  type designer meant to prevent compile silently.

### `std::vector<bool>`

```cpp
void bits() {
    std::vector<bool> flags(64);
    auto proxy = flags[0];              // not a bool&: a proxy object referring to one bit
    // bool* p = &flags[0];             // error: individual bits have no address
    proxy = true;
}
```

- A space-saving specialization stores each element as one bit, so `operator[]` returns a proxy object
  rather than a reference, and `vector<bool>` does not meet the normal container requirements.
- Alternatives: `std::vector<char>` or `std::vector<std::uint8_t>` for addressable elements, or
  `std::bitset` for a fixed number of bits.

### Small-string optimization

```cpp
void short_strings() {
    std::string inline_text = "short";                         // stored inside the string object
    std::string heap_text(100, 'x');                           // needs a heap allocation
    std::printf("%zu %zu\n", sizeof(std::string), std::string().capacity());
}
```

- Strings store short contents inside the object itself instead of on the heap: up to 22 characters in a
  24-byte `std::string` with libc++, and up to 15 characters in a 32-byte `std::string` with libstdc++.
- Benchmarking trap: tests that use only short strings never allocate, while production data may.
- Moves: a short string has no heap pointer to transfer, so moving it copies the bytes, and the source is
  not guaranteed to become empty.

> Performance-focused codebases often use small-buffer vectors such as LLVM's `SmallVector` or Abseil's
> `absl::InlinedVector`, which keep the first few elements inside the object itself and only allocate
> when that inline space runs out, applying the small-string idea to vectors.

## 3. Ordered and unordered lookup

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:lookup"

### How each structure is built

| | `std::map` | `std::unordered_map` |
| - | ---------- | -------------------- |
| Structure | Red-black tree: a binary search tree kept balanced by recoloring and rotations | Array of buckets; each bucket is a linked list of nodes |
| Lookup | O(log n), guaranteed | O(1) average, O(n) worst case |
| Ordering | Sorted by key; supports `lower_bound` and range queries | None |
| Per-element memory | A node with three pointers and a color flag | A node with a next pointer (and often a cached hash) |
| Iterator invalidation | Only erased elements | Rehashing invalidates all iterators; references stay valid |

- Naming: `std::map` is the ordered tree and `std::unordered_map` is the hash table, the reverse of most
  languages, where the unqualified name is the hash table.
- Node-based hashing: the standard requires references to elements to stay valid across rehashing, which
  forces each element into its own node. That rules out faster open-addressing designs that store
  elements directly in the bucket array.

### Predictable latency and rehashing

- Rehash cost: when the load factor (elements divided by buckets) exceeds `max_load_factor()` (1.0 by
  default), the table allocates a larger bucket array and relinks every element. Average insertion stays
  constant time, but the rehashing insertion takes time proportional to the size of the table.
- Latency-sensitive code: a single long pause can matter more than average speed. `std::map` has no such
  pause; every operation stays O(log n).
- Mitigation: calling `reserve(n)` sizes the bucket array once, so no rehash happens while inserting up to
  `n` elements.
- Adversarial keys: if an attacker can choose keys that hash to the same bucket, every lookup degrades to
  a scan of one long chain. Internet-facing services use randomized or keyed hash functions, or trees.

### Heterogeneous lookup

```cpp
void lookups() {
    std::map<std::string, int, std::less<>> ports{{"http", 80}};   // transparent comparator
    auto it = ports.find(std::string_view{"http"});                // no std::string is constructed
    (void)it;
}
```

- Problem: `map<std::string, int>::find("http")` converts the literal into a temporary `std::string`,
  which may allocate, just to compare.
- Transparent comparators: with `std::less<>`, `find` accepts any type comparable with the key. C++20
  extends this to unordered containers when both the hash and equality types declare
  `is_transparent`.

### `std::flat_map`

- C++23's `std::flat_map` keeps keys and values in sorted contiguous arrays. Lookup is binary search over
  contiguous memory, which loads far fewer cache lines than walking a tree.
- Insertion shifts elements, so it is O(n). It suits lookup tables that are built once and read often.

> Open-addressing hash tables such as Abseil's `absl::flat_hash_map` and Boost's
> `boost::unordered_flat_map` store elements directly in the bucket array and give up the standard's
> reference-stability guarantee in exchange for far fewer cache misses per lookup. Many large codebases
> standardize on them for that reason.

## 4. Iterator invalidation

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:invalidation"

### Iterator categories

| Category | Adds | Example containers |
| -------- | ---- | ------------------ |
| Input | Single-pass reading | `std::istream_iterator` |
| Forward | Multiple passes | `std::forward_list`, `std::unordered_map` |
| Bidirectional | `--` | `std::list`, `std::map`, `std::set` |
| Random access | `+ n`, `-`, `<` in constant time | `std::deque` |
| Contiguous (C++20) | Elements adjacent in memory | `std::vector`, `std::array`, `std::string`, `std::span` |

- Purpose: algorithms state the weakest category they need, so one implementation serves every container
  that meets it. N algorithms and M containers need N + M implementations instead of N × M.
- Example: `std::sort` requires random access because it jumps to arbitrary positions, so `std::list`
  provides its own member `sort()` based on merge sort, which only needs sequential access.

### The full invalidation rules

| Container | Insertion invalidates | Erasure invalidates |
| --------- | --------------------- | ------------------- |
| `vector` | Everything if it reallocates; otherwise iterators and references at or after the insertion point | Iterators and references at or after the erased element |
| `deque` | All iterators; references survive insertion at either end | Everything, unless erasing at the front or back |
| `list`, `forward_list` | Nothing | Only the erased elements |
| `map`, `set` | Nothing | Only the erased elements |
| `unordered_map`, `unordered_set` | All iterators if it rehashes; references stay valid | Only the erased elements |

- Iterators versus references: in node-based containers elements never move, so references stay valid even
  when an iterator, which also depends on the surrounding structure, does not.
- Why these bugs survive testing: freed memory usually still holds the old values, so reading through an
  invalid iterator appears to work until the allocator reuses that memory. AddressSanitizer and debug
  standard library modes (`-D_GLIBCXX_DEBUG`, libc++ hardening modes) catch them.

### Erase-remove

```cpp
void remove_negatives(std::vector<int>& v) {
    auto first_removed = std::remove_if(v.begin(), v.end(), [](int x) { return x < 0; });
    v.erase(first_removed, v.end());          // remove_if only shuffled survivors forward
}

void remove_expired(std::map<int, bool>& sessions) {
    std::erase_if(sessions, [](const auto& entry) { return !entry.second; });   // C++20, any container
}
```

- Why two steps: `std::remove_if` only has iterators, not the container, so it cannot shrink anything. It
  moves the elements to keep toward the front and returns where the leftovers begin; `erase` removes them.
- C++20's `std::erase_if` performs the right idiom for each container type.

> Game engines that remove destroyed entities during an update loop usually defer the removal: they mark
> entities as dead while iterating, then compact the array once at the end of the frame, so no iterator is
> ever invalidated mid-loop.

## 5. `std::array` and small fixed sizes

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:array"

### What C arrays lose

```cpp
void takes_pointer(int* data);                       // the length is gone

void decay() {
    int raw[16] = {};
    takes_pointer(raw);                              // raw decays to int*: sizeof(raw) is unknown inside

    std::array<int, 16> arr{};
    auto copy = arr;                                 // a std::array can be copied and returned
    std::span<int> view = arr;                       // and passed with their length intact
    (void)copy;
    (void)view;
}
```

- Array-to-pointer decay: a C array converts to a pointer to its first element when passed to a function,
  losing its length. The callee must be told the size, and nothing checks that it was told correctly.
- `std::array<T, N>` wraps a C array in a struct with no overhead: same layout, same size, but copyable,
  returnable, and aware of its size.

### `std::array` compared with `std::vector`

| | `std::array<T, N>` | `std::vector<T>` |
| - | ------------------ | ---------------- |
| Size | Fixed at compile time, part of the type | Chosen and changed at run time |
| Storage | Inside the object: on the stack, inside another object, or static | Always a separate heap buffer |
| Allocations | None | At least one, more as it grows |
| `sizeof` | `N * sizeof(T)` | Three pointers, regardless of contents |
| Move | Moves every element: nothing to transfer | Constant time: transfers the buffer |
| Invalidation | Never | On reallocation |

- Moving is not cheap: with no pointer to transfer, moving an `array` costs as much as moving each
  element.
- Members: an `array` member makes the enclosing object `N * sizeof(T)` larger, which is ideal for small
  fixed buffers and costly for large ones stored in bulk.
- Compile-time use: `std::array` works fully in `constexpr` code, and a trivially copyable element type
  makes the whole array trivially copyable.

### Details worth knowing

- Bounds: `operator[]` is unchecked; `at()` throws `std::out_of_range`. Because the size is known at
  compile time, compilers can often diagnose constant out-of-range indexes.
- Initialization: `std::array<int, 3> a;` leaves elements uninitialized in local variables, while
  `std::array<int, 3> a{};` sets them to zero.
- Zero size: `std::array<T, 0>` is valid, which helps templates where the size is computed.

> A hashing API can represent a SHA-256 digest as `std::array<std::uint8_t, 32>`. The size is part of the
> type, so passing a 20-byte SHA-1 digest where a SHA-256 digest is expected fails to compile, and
> producing a digest never allocates.

## 6. `std::deque` and `std::list`

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:deque_list"

### How `deque` is built

```cpp
void deque_references() {
    std::deque<int> d{1, 2, 3};
    int& middle = d[1];
    d.push_front(0);
    d.push_back(4);
    middle = 20;                // still valid: existing blocks never move
}
```

- Structure: a sequence of fixed-size blocks plus an index of pointers to them. Adding at either end fills
  or adds a block and updates the index; existing blocks never move.
- Element access: constant time but with two indirections (find the block, then the element).
- Guarantees: references to elements survive insertion at either end, though iterators do not, because the
  index they depend on may be reallocated.
- Costs: chunk boundaries interrupt prefetching, and even a small deque allocates a whole block (libstdc++
  uses blocks of about 512 bytes).
- Uses: the default storage for `std::queue` and `std::stack`, and any sequence that needs stable element
  addresses while growing.

### How `list` is built

```cpp
void relink() {
    std::list<int> active{1, 2, 3};
    std::list<int> idle{7, 8};
    auto it = idle.begin();
    active.splice(active.end(), idle, it);   // moves node 7 in constant time: no copy, no allocation
    // it still refers to 7, now inside active
}
```

- Structure: each element lives in its own heap node with pointers to the previous and next nodes, adding
  two pointers of overhead per element.
- Cost of traversal: each step loads a node from an unrelated address, so the CPU cannot prefetch and a
  traversal can miss cache on every element.
- Where it wins: `splice` moves nodes between lists in constant time without touching the elements, and
  iterators stay valid through every insertion and through erasure of other elements.
- Constant-time insertion needs an iterator to the position first; finding that position is a linear
  traversal.

### Intrusive lists

```cpp
struct ListLink {
    ListLink* prev = this;
    ListLink* next = this;
};

struct Request {
    int id = 0;
    ListLink pending;          // the links live inside the element itself
    ListLink by_client;        // the same element can be on two lists at once
};
```

- Idea: instead of wrapping elements in separately allocated nodes, an intrusive list places the link
  fields inside the element, so linking costs no allocation and the element and its links share a cache
  line.
- Multiple lists: an element can sit on several lists at once by holding several link members.
- Where it appears: operating system kernels (Linux's `struct list_head`), allocators, and schedulers.
  Boost.Intrusive provides a C++ implementation.

> The Linux kernel's `struct task_struct`, which describes a process, embeds several `struct list_head`
> members, so the same task is linked into the global task list, its parent's list of children, and
> other lists at once without allocating any list nodes.

## Choosing a container

??? note "Overview"

    --8<-- "guides/cpp_overview/containers.md:choosing"

Measure with realistic data sizes before replacing `vector`, reserve capacity when counts are known, use
transparent comparators to avoid temporary keys, and consider open-addressing hash maps or
`std::flat_map` when lookup speed matters more than reference stability.

## C++ References

Overview

- [Containers library, including iterator invalidation](https://en.cppreference.com/cpp/container)
- [Iterator library and iterator categories](https://en.cppreference.com/cpp/iterator)
- [`std::hardware_destructive_interference_size`](https://en.cppreference.com/cpp/thread/hardware_destructive_interference_size)

Sequence containers

- [`std::vector`](https://en.cppreference.com/cpp/container/vector): [`capacity`](https://en.cppreference.com/cpp/container/vector/capacity), [`reserve`](https://en.cppreference.com/cpp/container/vector/reserve), [`resize`](https://en.cppreference.com/cpp/container/vector/resize), [`shrink_to_fit`](https://en.cppreference.com/cpp/container/vector/shrink_to_fit), [`clear`](https://en.cppreference.com/cpp/container/vector/clear), [`emplace_back`](https://en.cppreference.com/cpp/container/vector/emplace_back)
- [`std::vector<bool>`](https://en.cppreference.com/cpp/container/vector_bool) and [`std::bitset`](https://en.cppreference.com/cpp/utility/bitset)
- [`std::array`](https://en.cppreference.com/cpp/container/array) and [`at`](https://en.cppreference.com/cpp/container/array/at)
- [`std::deque`](https://en.cppreference.com/cpp/container/deque)
- [`std::list`](https://en.cppreference.com/cpp/container/list), [`splice`](https://en.cppreference.com/cpp/container/list/splice), [`sort`](https://en.cppreference.com/cpp/container/list/sort), and [`std::forward_list`](https://en.cppreference.com/cpp/container/forward_list)
- [`std::basic_string`](https://en.cppreference.com/cpp/string/basic_string)

Associative containers

- [`std::map`](https://en.cppreference.com/cpp/container/map): [`find`](https://en.cppreference.com/cpp/container/map/find), [`lower_bound`](https://en.cppreference.com/cpp/container/map/lower_bound)
- [`std::unordered_map`](https://en.cppreference.com/cpp/container/unordered_map): [`reserve`](https://en.cppreference.com/cpp/container/unordered_map/reserve), [`rehash`](https://en.cppreference.com/cpp/container/unordered_map/rehash), [`max_load_factor`](https://en.cppreference.com/cpp/container/unordered_map/max_load_factor)
- [`std::flat_map`](https://en.cppreference.com/cpp/container/flat_map)
- [`std::less<>` (transparent comparator)](https://en.cppreference.com/cpp/utility/functional/less_void)

Adaptors, views, and algorithms

- [`std::queue`](https://en.cppreference.com/cpp/container/queue) and [`std::stack`](https://en.cppreference.com/cpp/container/stack)
- [`std::span`](https://en.cppreference.com/cpp/container/span)
- [`std::remove_if`](https://en.cppreference.com/cpp/algorithm/remove), [`std::erase_if` for maps](https://en.cppreference.com/cpp/container/map/erase_if), [`std::sort`](https://en.cppreference.com/cpp/algorithm/sort)
- [Array-to-pointer conversion](https://en.cppreference.com/cpp/language/implicit_conversion)
