# Containers

> Part of the [C++ Overview](README.md)

<!-- --8<-- [start:intro] -->
The standard library provides containers — types that store collections of objects — with different
internal structures. Textbook complexity (big-O) describes how an operation scales as the collection
grows, but on real hardware the dominant cost is often how the container's memory is arranged. A
processor can read memory that sits next to what it just read far faster than memory scattered
across the heap, so a container that keeps elements together frequently outperforms one with better
theoretical complexity.

| Container | Internal structure | Strengths | Weaknesses |
| --------- | ------------------ | --------- | ---------- |
| `std::vector` | One contiguous, growable array | Fastest iteration; cheap push at the end | Inserting in the middle shifts elements; growth reallocates |
| `std::array` | Fixed-size contiguous array, no heap allocation | Zero allocation; size known at compile time | Size cannot change |
| `std::deque` | A sequence of fixed-size blocks | Cheap push at both ends | Slower iteration than `vector` |
| `std::list` | Doubly linked nodes, each allocated separately | Insertion and removal never move other elements | One allocation per element; slow iteration |
| `std::map` / `std::set` | Balanced binary search tree | Keys kept in sorted order; predictable O(log n) | A pointer hop and likely cache miss at each level |
| `std::unordered_map` / `std::unordered_set` | Hash table with buckets | Average O(1) lookup | No ordering; an occasional full rehash |
<!-- --8<-- [end:intro] -->

## 1. Why memory layout dominates

<!-- --8<-- [start:layout] -->
Main memory is far slower than the processor, so CPUs keep recently used data in small, fast caches.

```cpp
long sum_vector(const std::vector<int>& v) {   // elements sit side by side: the CPU prefetches them
    long total = 0;
    for (int x : v) total += x;
    return total;
}

long sum_list(const std::list<int>& l) {       // same loop, but each node may be anywhere in memory
    long total = 0;
    for (int x : l) total += x;
    return total;
}
```

- Cache hit: reading data already in the fastest cache takes around a nanosecond.
- Cache miss: reading data that must be fetched from main memory takes roughly 100 times longer.
- Prefetching: when a program reads elements in order through contiguous memory, the CPU detects the
  pattern and loads upcoming data before it is needed. Following pointers between separately
  allocated nodes defeats this, so `sum_list` is typically several times slower than `sum_vector`
  for the same data.
- Consequence: for small and medium collections, a linear scan of a `vector` often beats a lookup in
  a `list` or `map`, despite the worse big-O.

> A game engine iterating over all entities every frame typically stores positions in a
> `std::vector` rather than a linked structure, because a contiguous scan lets the CPU cache keep up
> at 60 frames per second.
<!-- --8<-- [end:layout] -->

[Go deeper →](../cpp_deep_dive/containers.md#1-why-memory-layout-dominates)

## 2. `std::vector`: the default

<!-- --8<-- [start:vector] -->
A `vector` stores its elements in one contiguous heap buffer and tracks its size and capacity.

```cpp
std::vector<int> build(std::size_t n) {
    std::vector<int> v;
    v.reserve(n);                 // one allocation up front; capacity() >= n, size() == 0
    for (std::size_t i = 0; i < n; ++i) {
        v.push_back(static_cast<int>(i));   // never reallocates
    }
    return v;
}

void resize_vs_reserve() {
    std::vector<int> a;
    a.reserve(10);                // size 0: no elements exist yet
    std::vector<int> b;
    b.resize(10);                 // size 10: ten zero-valued elements exist
}
```

- Growth: when the buffer is full, the vector allocates a larger buffer (typically 1.5 or 2 times the
  size), moves every element over, and frees the old one. This keeps the average cost of `push_back`
  constant.
- `reserve(n)`: allocates space for `n` elements up front, avoiding repeated reallocations when the
  final size is known. `resize(n)` is different: it creates `n` elements.
- `emplace_back`: constructs an element directly inside the vector from constructor arguments,
  instead of constructing it first and then moving it in.
- Guideline: use `vector` unless there is a specific, measured reason to use something else.

> A service that reads a file with a known number of records calls `records.reserve(count)` before
> parsing, so loading a million records performs one allocation instead of about twenty
> reallocations and element moves.
<!-- --8<-- [end:vector] -->

[Go deeper →](../cpp_deep_dive/containers.md#2-stdvector-the-default)

## 3. Ordered and unordered lookup

<!-- --8<-- [start:lookup] -->
Both `map` and `unordered_map` associate keys with values, but they find a key differently.

```cpp
std::string lookups() {
    std::map<int, std::string> by_time{{30, "c"}, {10, "a"}, {20, "b"}};
    std::string order;
    for (const auto& [time, name] : by_time) {
        order += name;                                 // visits keys 10, 20, 30: order == "abc"
    }
    order += by_time.lower_bound(15)->second;          // range query: first key >= 15 is 20, "b"

    std::unordered_map<std::string, int> ports{{"http", 80}, {"ssh", 22}};
    if (auto it = ports.find("ssh"); it != ports.end()) {   // average O(1); iteration order unspecified
        order += std::to_string(it->second);
    }
    return order;                                      // "abcb22"
}
```

- `std::map`: a balanced tree compares the key at each level. Lookups cost O(log n) every time, and
  iteration visits keys in sorted order.
- `std::unordered_map`: a hash function selects a bucket directly, giving O(1) average lookups. When
  the table grows past its maximum load factor, it rehashes every element at once, which causes an
  occasional long pause.
- Choice: use `unordered_map` for fast lookups when ordering does not matter. Use `map` when you need
  sorted iteration, range queries such as "all keys between A and B", or a worst-case time with no
  rehash pauses.

> An order book in a trading system uses `std::map` keyed by price, because it constantly needs the
> best bid and ask — the lowest and highest keys. A session cache keyed by session token uses
> `std::unordered_map`, because it only ever looks up exact tokens.
<!-- --8<-- [end:lookup] -->

[Go deeper →](../cpp_deep_dive/containers.md#3-ordered-and-unordered-lookup)

## 4. Iterator invalidation

<!-- --8<-- [start:invalidation] -->
An iterator is an object that points to a position in a container. Some operations change a
container's memory so that existing iterators, pointers, and references no longer point to valid
elements; this is called invalidation.

```cpp
void invalidation(std::vector<int>& v) {
    // Bug: push_back may reallocate, leaving the loop's iterators pointing at freed memory
    // for (int x : v) { v.push_back(x); }

    // Correct: erase returns a valid iterator to the next element
    for (auto it = v.begin(); it != v.end();) {
        if (*it % 2 == 0) it = v.erase(it);
        else ++it;
    }

    // Simplest: C++20 std::erase_if does the same in one call
    std::erase_if(v, [](int x) { return x % 2 == 0; });
}
```

- `vector`: any insertion that causes reallocation invalidates everything; inserting or erasing
  invalidates everything after that position.
- `list`, `map`, `set`: inserting never invalidates other elements, and erasing invalidates only the
  erased element, because nodes never move.
- `unordered_map`: a rehash invalidates iterators but not pointers or references to elements.
- Hazard: using an invalidated iterator is undefined behavior. The classic example is calling
  `push_back` on a `vector` while looping over it.

> A classic bug in simulation code is removing dead objects from a `std::vector` inside a
> range-based `for` loop. Replacing the loop with `std::erase_if` removes them in one pass with no
> invalidated iterators.
<!-- --8<-- [end:invalidation] -->

[Go deeper →](../cpp_deep_dive/containers.md#4-iterator-invalidation)

## 5. `std::array` and small fixed sizes

<!-- --8<-- [start:array] -->
`std::array<T, N>` is a fixed-size array whose storage is part of the object itself.

```cpp
std::array<int, 26> letter_counts(std::string_view word) {
    std::array<int, 26> counts{};       // {} sets every element to zero
    for (char c : word) {
        if (c >= 'a' && c <= 'z') ++counts[c - 'a'];
    }
    return counts;                      // no heap allocation anywhere
}
```

- Storage: a local `std::array` lives on the stack, so creating one does not allocate. See
  [Memory](memory.md).
- Initialization: `std::array<int, 26> counts;` leaves the integers uninitialized when declared as a
  local variable; `std::array<int, 26> counts{};` sets them all to zero.

> Counting letter frequencies for an anagram check uses `std::array<int, 26>`: the size is fixed by
> the alphabet, and the counts live on the stack with no allocation.
<!-- --8<-- [end:array] -->

[Go deeper →](../cpp_deep_dive/containers.md#5-stdarray-and-small-fixed-sizes)

## 6. `std::deque` and `std::list`

<!-- --8<-- [start:deque_list] -->
These containers give up contiguous storage in exchange for properties a `vector` cannot offer.

```cpp
void queue_work() {
    std::deque<int> jobs;
    jobs.push_back(1);
    jobs.push_front(0);                  // O(1) at the front as well as the back

    std::list<int> lru{1, 2, 3};
    auto it = std::next(lru.begin());    // points at 2
    lru.splice(lru.begin(), lru, it);    // move 2 to the front: no copying, it stays valid
}
```

- `std::deque`: stores elements in fixed-size blocks, so adding at either end never moves existing
  elements. It is the default underlying container for `std::queue`.
- `std::list`: every element is its own allocation, so elements never move and can be relinked with
  `splice` in constant time. That property, not insertion speed, is the usual reason to choose it.

> A least-recently-used (LRU) cache pairs a `std::list` of entries with an `unordered_map` from key
> to list iterator. On each access, `splice` moves the entry to the front in constant time, and the
> stored iterators stay valid because list nodes never move.
<!-- --8<-- [end:deque_list] -->

[Go deeper →](../cpp_deep_dive/containers.md#6-stddeque-and-stdlist)

## Choosing a container

<!-- --8<-- [start:choosing] -->
Start with `std::vector`, or `std::array` when the size is fixed. Use `unordered_map` for key
lookups and `map` when order or a strict worst case matters. Pick `deque` or `list` only when their
specific properties — cheap insertion at the front, or elements that never move — are required and a
profiler confirms the choice.
<!-- --8<-- [end:choosing] -->

## C++ References

Overview

- [Containers library, including the iterator invalidation table](https://en.cppreference.com/cpp/container)
- [Iterator library and iterator categories](https://en.cppreference.com/cpp/iterator)

Sequence containers

- [`std::vector`](https://en.cppreference.com/cpp/container/vector): [`reserve`](https://en.cppreference.com/cpp/container/vector/reserve), [`resize`](https://en.cppreference.com/cpp/container/vector/resize), [`push_back`](https://en.cppreference.com/cpp/container/vector/push_back), [`emplace_back`](https://en.cppreference.com/cpp/container/vector/emplace_back), [`erase`](https://en.cppreference.com/cpp/container/vector/erase), [`capacity`](https://en.cppreference.com/cpp/container/vector/capacity)
- [`std::erase_if` for vector](https://en.cppreference.com/cpp/container/vector/erase2)
- [`std::array`](https://en.cppreference.com/cpp/container/array)
- [`std::deque`](https://en.cppreference.com/cpp/container/deque)
- [`std::list`](https://en.cppreference.com/cpp/container/list) and [`splice`](https://en.cppreference.com/cpp/container/list/splice)

Associative containers

- [`std::map`](https://en.cppreference.com/cpp/container/map) and [`lower_bound`](https://en.cppreference.com/cpp/container/map/lower_bound)
- [`std::set`](https://en.cppreference.com/cpp/container/set)
- [`std::unordered_map`](https://en.cppreference.com/cpp/container/unordered_map): [`find`](https://en.cppreference.com/cpp/container/unordered_map/find), [`reserve`](https://en.cppreference.com/cpp/container/unordered_map/reserve), [`rehash`](https://en.cppreference.com/cpp/container/unordered_map/rehash), [`max_load_factor`](https://en.cppreference.com/cpp/container/unordered_map/max_load_factor)
- [`std::unordered_set`](https://en.cppreference.com/cpp/container/unordered_set)

Adaptors and helpers

- [`std::queue`](https://en.cppreference.com/cpp/container/queue)
- [`std::next`](https://en.cppreference.com/cpp/iterator/next)
- [`std::string_view`](https://en.cppreference.com/cpp/string/basic_string_view)
