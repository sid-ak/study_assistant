# Bridge

> Part of the Projects guide — [back to index](../README.md)

<a id="bridge"></a>

## The situation, in full

Two teams, two languages, one shared data model. The **Services team** worked exclusively in C# and
.NET. The **Perception/ADAS team** needed the same data models as **memory-aligned C++ structs**.
They were hand-syncing.

**Why hand-syncing is a trap:** every schema change in C# required someone to remember to update the
C++ header. When they forgot — and people always eventually forget — the two sides disagreed about
the byte layout of the data flowing between them. That produces deserialization bugs that look like
data corruption, which produces exactly the "he-said-she-said" debugging sessions the teams were
having. In a safety-critical system, that's not just wasted time.

**You noticed the pattern and decided to fix the root cause** rather than continue fixing the
symptoms.

## What you built

A **Python code-generation tool** that ingested C# / Swagger-OpenAPI definitions and emitted
memory-aligned C++ structs, wired into the build so the headers regenerated automatically.

## The interesting technical problem — type definition ordering

The naive implementation emits struct definitions in the order the source declares them. **That
doesn't work**, and understanding why is the substance of this story.

C++ requires a type to be **completely defined before it can be used as a by-value member**. A
forward declaration isn't enough — the compiler needs the full definition to know the member's size
and alignment, which it needs to lay out the enclosing struct. The source definitions had no such
guarantee. A Swagger `components/schemas` block is an unordered map, and the C# models were written
in whatever order made sense to their authors, so a type routinely referenced another type defined
later in the file:

```cpp
// Emitted in source order — does not compile.
struct SecondStruct {
    FirstStruct x;   // error: field has incomplete type 'FirstStruct'
    int y;
    int z;
};

struct FirstStruct {
    int x;
    int y;
    int z;
};
```

```cpp
// Emitted in dependency order — compiles.
struct FirstStruct {
    int x;
    int y;
    int z;
};

struct SecondStruct {
    FirstStruct x;   // complete type, size and alignment known
    int y;
    int z;
};
```

So the generator couldn't be a straight pass over the schema. It had to **dynamically reorder the
struct definitions** so that every type was emitted after everything it referenced.

## Your algorithm

You wrote a **recursive traversal of the type dependency graph** — a topological sort:

1. **Parse every schema into a type node**, recording which other types each one references by
   value.
2. **Build an adjacency list** of those dependencies. `SecondStruct → FirstStruct` means
   `FirstStruct` must be emitted first.
3. **Resolve depth-first.** Visit a type's dependencies recursively and emit them before emitting
   the type itself, marking nodes so each is emitted exactly once.
4. **Detect cycles** during traversal and fail the build with the cycle path, since a by-value cycle
   can't be expressed in C++ at all.
5. **Emit** the header in the resulting topological order.

The output order of the _fields within_ each struct is left exactly as the schema declares it —
that's the contract both sides serialize against, so reordering members would have broken it. The
ordering problem was strictly **between** types, not within them.

**Why this is a good interview story:** it's a genuine algorithms problem — graph construction, DFS,
topological sort, cycle detection — arising from a genuine language constraint: the C++
complete-type rule for by-value members. That combination is exactly what a systems interview is
trying to find, and most candidates' "automation project" stories have neither half.

## What made it actually get adopted

You sought out the lead engineers from **both** teams before building, specifically to understand
their requirements around memory alignment and serialization. Then you made a deliberate choice:
rather than forcing the C++ team onto C# tooling they found cumbersome, you built a bridge that let
each team keep working the way they already worked.

That's the part worth emphasizing in a behavioral context. **The technical solution was necessary
but not sufficient** — the reason it became the single source of truth instead of shelfware is that
it respected both teams' existing workflows, and both leads had been consulted early enough to have
shaped it.

## Results

- Became the **single source of truth** for shared data models across both teams.
- Schema changes in C# propagated to C++ headers **automatically on the next build**.
- Eliminated the entire _category_ of integration bugs the teams had been chasing.
- Saved both teams hours of manual header maintenance and removed a recurring source of cross-team
  friction.

## Concepts in play

Complete vs. incomplete types · forward declarations and when they're insufficient · memory
alignment and `alignof` · struct layout · standard layout and trivially copyable types · ABI
compatibility · topological sort and DFS · graph cycle detection · code generation · serialization
contracts · endianness · contract-based development between services.

<a id="bridgestar"></a>

??? note "STAR"

    **Situation.** Our Services team worked exclusively in C# and .NET while the Perception/ADAS team
    needed the same data models as memory-aligned C++ structs, and the two sides were syncing by hand.
    Every schema change meant someone had to remember to update a C++ header, and when that got missed
    the two sides silently disagreed about byte layout — which surfaces as data corruption, not as an
    error. It was generating recurring cross-team debugging sessions where neither team could tell whose
    model was wrong.

    **Task.** I decided the real problem wasn't the individual bugs, it was that we had two sources of
    truth. I wanted a single authoritative definition that propagated automatically, and I wanted it to
    respect how both teams already worked rather than forcing one onto the other's tooling.

    **Action.** Before writing anything, I went to the lead engineers on both teams to understand their
    actual constraints around memory alignment and serialization. Then I built a Python code generator
    that ingested the C# and Swagger definitions and emitted C++ headers, hooked into the build so it
    ran automatically. The genuinely hard part was the ordering of the generated type definitions.
    Structs referenced other structs by value, and C++ requires a type to be completely defined before
    it's used as a member — a forward declaration isn't enough, because the compiler needs the size and
    alignment to lay out the parent. The source schemas were in arbitrary order, so emitting them as
    declared produced headers that didn't compile. So I wrote a recursive traversal of the type
    dependency graph — a topological sort. I built an adjacency list of which types referenced which,
    resolved dependencies depth-first so every type was emitted after everything it contained, and
    failed the build with the cycle path if the graph wasn't acyclic, since a by-value cycle can't exist
    in C++ anyway.

    **Result.** The bridge became the single source of truth for shared models. Schema changes in C#
    propagate to C++ headers on the next build, which eliminated the entire category of integration bugs
    we'd been chasing rather than fixing them one at a time. The reason it actually got adopted, though,
    was that I involved both leads early enough that the output fit how each team already worked — I've
    seen better tools than this one fail because nobody wanted to use them.

<a id="bridgescript"></a>

??? note "Scripts"

    ### Version A — Cross-team framing (~75s)

    > Our Services team worked in C# and our Perception team needed the same data models as
    > memory-aligned C++ structs, and they were syncing by hand. Every schema change meant somebody had
    > to remember to update a header on the other side — and when that got missed, the two sides
    > disagreed about byte layout, which doesn't produce an error, it produces silently wrong data. So
    > the teams kept having these debugging sessions where nobody could tell whose model was stale.
    >
    > I decided the real problem wasn't any individual bug, it was that we had two sources of truth. So
    > I built a Python code generator that ingested the C# and Swagger definitions and emitted the C++
    > headers automatically as part of the build.
    >
    > The part I didn't expect to be hard was the ordering of the generated definitions. The models
    > referenced each other — one struct would have another struct as a member — and C++ requires a type
    > to be completely defined before you can use it by value, because the compiler needs its size and
    > alignment to lay out the parent. A forward declaration doesn't cut it. And the source schemas came
    > in arbitrary order, so a struct would routinely reference a type defined below it. Emitting in
    > source order gave you headers that didn't compile. So I wrote a recursive traversal of the type
    > dependency graph — a topological sort. Build an adjacency list of which types reference which,
    > resolve depth-first so every type gets emitted after everything it contains, and error out with
    > the cycle path if there's a cycle, since a by-value cycle is impossible in C++ anyway.
    >
    > The bridge became the single source of truth. Schema changes propagate automatically, which killed
    > the whole category of integration bug rather than fixing them one at a time. Honestly, though, the
    > reason it got adopted wasn't the algorithm — it's that I went to the lead engineers on both teams
    > first and built something that fit how each of them already worked, instead of forcing the C++
    > team onto C# tooling they'd have resented.

    ### Version B — Technical framing (~50s). Use if the question was about algorithms or systems.

    > I built a code generator that produced memory-aligned C++ structs from C# model definitions, so
    > two teams could share one source of truth for their data contract.
    >
    > The core problem was emission order. The models were composite — structs held other structs by
    > value — and C++ requires a complete type for a by-value member, since the compiler needs its size
    > and alignment to lay out the enclosing struct. A forward declaration isn't sufficient. The source
    > schemas came in arbitrary order, so emitting them as declared produced headers referencing
    > incomplete types, which just doesn't compile.
    >
    > I solved it as a graph problem. Types form a dependency graph — a struct containing another struct
    > depends on it — so I built an adjacency list, resolved depth-first, and emitted each type only
    > after everything it referenced. A topological sort, with cycle detection that fails the build and
    > prints the cycle path, since a by-value cycle can't be expressed in C++ at all. Field order within
    > each struct I deliberately left as the schema declared it — that's the contract both sides
    > serialize against, so reordering members would have broken the thing I was trying to protect.

<a id="bridgeqa"></a>

??? note "QA"

    **Q: Why did the ordering of the generated definitions matter so much?**

    > Because the models were composite — structs contained other structs by value — and C++ requires a
    > _complete_ type for a by-value member. The compiler has to know the member's size and alignment to
    > lay out the enclosing struct, so a forward declaration doesn't help; it only works for pointers
    > and references. The source schemas had no ordering guarantee — Swagger's `components/schemas` is
    > an unordered map and the C# models were written in whatever order suited their authors — so a
    > struct would routinely reference a type defined further down. Emitting in source order gave you a
    > header that failed to compile with "field has incomplete type." So the generator had to reorder
    > the type definitions by dependency, which is a topological sort over the reference graph.

    **Q: Couldn't you just forward-declare everything at the top of the header?**

    > Only if the members were pointers or references, and they weren't — these were flat,
    > memory-aligned value types, which is exactly what the perception team wanted so they could treat
    > them as plain memory. A forward declaration tells the compiler a name exists; it doesn't tell it
    > the size or alignment, and you need both to place a member at an offset. So for by-value
    > composition, definition order is a hard requirement, not a style preference.

    **Q: Why not just alphabetize or hand-maintain the order?**

    > Hand-maintaining it puts you right back where you started — a manual step someone has to remember
    > whenever a model gains a new nested type. Alphabetizing is arbitrary; it happens to work until a
    > struct named `Alpha` contains a `Zeta`. The dependency graph is the only ordering that's correct
    > by construction, and it's cheap — one DFS over a few hundred types at build time.

    **Q: Why not `#pragma pack` to make layout trivially identical on both sides?**

    > That's the obvious first answer and it's a bad trade here. Packing produces unaligned members, and
    > unaligned access is slow on x86 and an outright fault on some ARM configurations — and we were
    > running on ARM. It's also non-standard and inconsistent across compilers. Since the generator
    > controlled both the layout and the `static_assert`s that verified it, I could guarantee agreement
    > without giving up alignment. I'd only reach for packing when forced to match a fixed external
    > format I don't control, like a wire protocol header.

    **Q: Why not use Protobuf, FlatBuffers, or Cap'n Proto?**

    > Fair question and I'd have preferred it in a greenfield system. Two things ruled it out. The C#
    > side already had its models defined and exposed through Swagger — that was the existing source of
    > truth and rewriting it in `.proto` would have been a much larger, more disruptive change to a team
    > that had no problem to solve. And the C++ side wanted plain memory-aligned structs it could work
    > with directly, not a generated API with accessors; that was a real constraint from how the
    > perception code consumed the data. So the pragmatic solution was a bridge between what already
    > existed. If I were designing the system from scratch, an IDL-first approach with Protobuf would be
    > the better architecture.

    **Q: How did you handle deeply nested structs?**

    > That's exactly why it needed to be a graph traversal rather than a single pass. Nesting is
    > transitive — `C` contains `B`, `B` contains `A` — so you can't fix it by scanning the list twice;
    > you need the full ordering. I built the dependency graph, resolved depth-first with a visited set
    > so each type was emitted exactly once, and the emission happened on the way back up the recursion:
    > children before parents, all the way down. Same shape as a classic DFS-based topological sort.

    **Q: What if there's a cycle in the type graph?**

    > A cycle of _by-value_ struct members is impossible in C++ anyway — a struct can't contain itself
    > by value, directly or transitively, because it'd have infinite size. So there's no valid ordering
    > to find; a cycle means the input is wrong. The generator tracks the recursion stack during
    > traversal and errors out with the full cycle path, because at that point either the C# model is
    > genuinely malformed or it's expressing a reference/pointer relationship that needs to become a
    > pointer or an ID on the C++ side. Failing loudly at generation time was the right call — a build
    > error beats an infinite recursion in the generator or something weird at runtime.

    **Q: How did you validate the generated code was right?**

    > A few layers. Generated `static_assert`s in the output itself — asserting `sizeof` and `offsetof`
    > for each field against the values the generator computed, so if the compiler disagrees with my
    > model of alignment, the build fails immediately rather than producing a subtly wrong struct.
    > Round-trip tests serializing from C# and deserializing in C++ with known values. And
    > `static_assert(std::is_standard_layout_v<T> && std::is_trivially_copyable_v<T>)` on the generated
    > types, since those are the properties that make it legal to `memcpy` them at all. That last one is
    > my favorite because it turns a comment into a compiler-enforced rule.

    **Q: What about endianness?**

    > It didn't bite us because both sides ran little-endian on the same physical platform, but it's the
    > obvious next failure mode and I'd want to name it rather than pretend it isn't there. The right
    > fix is to not depend on struct layout for the wire format at all — serialize field by field with
    > explicit widths and explicit byte order. Struct layout is a legitimate optimization when you
    > control both ends and the architecture; it's a latent bug the moment either of those changes.

    **Q: Was this over-engineering? Couldn't a checklist have worked?**

    > A checklist is what we had, informally, and it's what was failing. The failure mode of a manual
    > process isn't that people are careless — it's that it only takes one miss under deadline pressure,
    > and the cost of that miss is a silent data corruption bug that takes two teams a day to isolate.
    > The generator was maybe a week of work against a recurring cost we were paying every sprint. What
    > I'd push back on is the framing that automation's value is time saved — the real value was making
    > an entire class of bug structurally impossible.
