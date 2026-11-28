# ORM

> Part of the Projects guide — [back to index](../README.md)

<a id="orm"></a>

## The situation, in full

You were building the data layer for a time-series telemetry database — **TimescaleDB on Postgres**
— storing telemetry from the ADAS system. A senior lead advocated the traditional approach:
hand-written SQL strings with manual row-to-struct mapping, on the grounds that it was simpler to
write initially.

**Your assessment of the risk:** hand-written SQL is a _runtime_ contract. The compiler has no idea
whether `record.temperature` corresponds to a `DOUBLE PRECISION` column named `temperature`. As the
schema grows and evolves, every mismatch — a renamed column, a changed type, a reordered result set
— becomes a runtime failure. And in this system, "runtime" means _in a vehicle, in the field_, which
is the most expensive possible place to discover a type error.

## What you built

A drop-in C++ ORM-style layer whose central idea was **compile-time safety**: query construction and
row mapping validated by the compiler rather than by production.

**The mechanism — CRTP (Curiously Recurring Template Pattern):**

```cpp
template<typename Derived>
class Entity {
public:
    void save(Connection& c) {
        // static downcast: resolved at compile time, no vtable, fully inlinable
        auto& self = static_cast<Derived&>(*this);
        c.exec(Derived::insert_sql(), self.bind_values());
    }

    static std::vector<Derived> query(Connection& c, const Predicate& p) {
        // Derived::columns() known at compile time → mapping generated per type
    }
};

class Reading : public Entity<Reading> {          // derives from Entity<itself>
public:
    static constexpr std::string_view table = "readings";
    static std::string insert_sql();
    auto bind_values() const;
    // If any of these is missing → COMPILE ERROR, not a runtime SQL failure.
};
```

Plus **Boost Reflection** for automatic field enumeration and type mapping, so a developer
describing a record didn't hand-write the column list twice and let the two drift apart.

**Why CRTP rather than virtual inheritance — lead with the real reason.**

The whole design rests on the base class being able to **reflect over the derived class's fields at
compile time**. That's what generates the column list, the SQL, and the type validation. Boost
Describe (`boost::describe`) plus Mp11 gives you that — but `describe_members<T, ...>` takes the
concrete type `T` as a **template parameter**. It's a compile-time construct. You have to _have_ the
derived type as a type to use it at all.

CRTP is what puts that type in the base class's hands:

```cpp
template<typename Derived>
class Entity {
    using Members = boost::describe::describe_members<
        Derived, boost::describe::mod_public>;   // Derived is a type here — this is the point

    static std::string column_list() {
        std::string cols;
        boost::mp11::mp_for_each<Members>([&](auto D) {
            cols += D.name;                       // field name, at compile time
            using FieldType = std::remove_reference_t<decltype(std::declval<Derived&>().*D.pointer)>;
            static_assert(SqlMappable<FieldType>);  // field type → SQL type, checked at compile time
        });
        return cols;
    }
};
```

**Virtual inheritance can't do this, and the reason is fundamental, not a matter of degree.** A
virtual base only ever knows `Base*` at compile time; the derived type is erased by design — that's
the entire purpose of dynamic dispatch. So inside the base you have no type to hand to
`describe_members`, no way to enumerate the fields, no way to know a field is a `double` and must
map to `DOUBLE PRECISION`. You'd be back to every entity hand-writing its own column list and
binding code — which is exactly the duplication that produces schema drift, the problem the project
existed to solve. The alternative isn't "virtual, slightly slower." The alternative is **no
compile-time reflection at all**, and therefore no compile-time safety.

**The other benefits are real but secondary — mention them as side wins, not as the argument:**

1. **Static polymorphism, no vtable overhead.** The row-mapping path runs per field per row; an
   indirect call per field is a real cost at telemetry volumes.
2. **Better inlining.** The compiler sees the concrete `bind_values()` and can inline it and
   constant-fold the whole mapping. A virtual call is an optimization barrier.
3. **Compile-time interface enforcement.** With `virtual`, forgetting to implement a method is
   caught at instantiation of an abstract class — better than nothing. With CRTP plus static
   assertions, you can enforce the _shape_ of the contract, including static members and return
   types, which a vtable can't express at all.
4. **Predictable performance.** No allocation, no indirection, no surprise. In a system where
   telemetry runs alongside safety-critical work, predictable matters more than fast-on-average.

**Why the ordering matters in the interview.** If you lead with "no vtable overhead," a good
interviewer hears a micro-optimization and asks whether you measured it — and now you're defending a
performance claim instead of a design. Lead with reflection and the answer becomes: virtual
inheritance couldn't express the design at all, and the performance win came along for free.

**Testing as the argument.** The lead's objection was maintainability — template-heavy code is
"magic" and hard for a junior engineer to debug. You didn't dismiss that; you answered it with a
rigorous **GoogleTest** suite: unit tests for the type mapping itself, integration-style tests for
query behavior against a real database. The tests were the argument. They demonstrated that the
abstraction was a _safety net_, not a liability, and that a change couldn't silently corrupt
analytics.

**Performance discipline:** avoided unnecessary allocations in the mapping path, kept type
conversions explicit rather than implicit (so a lossy conversion is a compile error rather than a
silent truncation).

## How you handled the disagreement — the part that matters most

The technical content is good. The _process_ is what the behavioral interviewer is grading, and
yours is genuinely strong:

1. **Sought the reasoning behind the other position first.** The lead's concern wasn't stupid —
   template metaprogramming _is_ harder to debug, and onboarding cost is real.
2. **Reframed from preference to risk.** You proposed agreeing on the primary risk before arguing
   about solutions. You both landed on: runtime crashes from schema drift, in a vehicle, in the
   field. Once that was the shared metric, the debate stopped being about taste.
3. **Built a POC instead of arguing theory.** You demonstrated a column-type mismatch caught at
   _build_ time that a raw SQL string would not have caught until deployment. Data beats opinion.
4. **Answered the actual objection.** He was worried about maintainability, so you addressed
   maintainability directly with test coverage — rather than re-arguing the point you'd already won.
5. **Stayed receptive.** You incorporated his feedback about complexity rather than treating
   agreement as the only acceptable outcome.

Your general framework, worth stating explicitly if asked about conflict: _understand the why behind
the other position; agree on success metrics before debating solutions; use a POC to move from
opinions to benchmarks; and distinguish high-risk irreversible decisions (architecture) from
easily-changeable ones (implementation detail) — because they deserve different amounts of
argument._

## Results

- The lead agreed after seeing the POC and the test coverage.
- Runtime SQL errors reduced to **nearly zero**.
- Onboarding simplified — new engineers described a record type and got a working, validated mapping
  instead of hand-writing fragile SQL.
- Clean boundary between data storage and the real-time system.

## The C++ concepts in play

CRTP and static polymorphism · templates and instantiation · `static_cast` downcasting ·
compile-time vs runtime error surfaces · virtual dispatch cost and inlining barriers · type traits
and `static_assert` · Boost Reflection · `std::optional` for nullable columns · allocation avoidance
· explicit vs implicit conversions · C++20 Concepts as the modern successor.

<a id="ormstar"></a>

??? note "STAR"

    **Situation.** I was building the data layer for our ADAS telemetry — TimescaleDB on Postgres — and
    a senior lead wanted to use hand-written SQL strings with manual row mapping because it was simpler
    to get started. I disagreed. Hand-written SQL makes the schema contract a runtime contract, and as
    the schema grew, every column rename or type change would become a crash in a vehicle in the field
    rather than a build failure on my machine.

    **Task.** I set out to build a database interface that was human-error-proof by construction — one
    where schema drift was a compiler error — and, just as importantly, to get the lead genuinely on
    board rather than escalating past him.

    **Action.** I started by asking what our primary risk actually was, so we'd be arguing about the
    same thing. We agreed it was runtime crashes from schema drift in the field. Then instead of arguing
    the theory of template metaprogramming, I built a prototype using CRTP and Boost Reflection —
    developers inherit from `Entity<Record>`, and static polymorphism handles the type mapping
    automatically. I showed him a column-type mismatch getting caught at build time that a raw SQL
    string wouldn't have surfaced until deployment, and benchmarked it to demonstrate that static
    dispatch added zero runtime overhead versus his approach. His real objection was maintainability —
    that template-heavy code is "magic" for junior engineers — so I answered that directly with a
    thorough GoogleTest suite covering both the mapping logic and query behavior, proving the
    abstraction was a safety net rather than a liability.

    **Result.** He agreed, and we shipped it. Runtime SQL errors dropped to nearly zero and onboarding
    got simpler, because a new engineer describes a record type and gets a validated mapping instead of
    hand-writing fragile SQL. The more durable outcome was how the conversation went: we moved the
    debate from "whose style is better" to "which solution reduces project risk," and that reframing
    became how I approach architectural disagreements generally.

<a id="ormscript"></a>

??? note "Scripts"

    ### Version A — Disagreement framing (~90s). Use for "tell me about a time you disagreed with someone."

    > I had an architectural disagreement with a senior lead about our time-series database layer. He
    > wanted raw SQL strings and manual row mapping because it was simpler to start with. I wanted a
    > compile-time ORM using CRTP and template metaprogramming.
    >
    > **[Steelman his position first]** His concern was completely legitimate, and I want to be fair to
    > it: template-heavy code is "magic." It's harder to debug, the error messages are bad, and it
    > raises the bar for a junior engineer touching the codebase. That's a real cost.
    >
    > **[The reframe — this is the key move]** So rather than argue about which approach was better in
    > the abstract, I asked if we could first agree on what our primary risk was. That changed the
    > conversation. We landed on: runtime crashes caused by schema drift, in a vehicle, in the field.
    > Once that was the shared metric, we weren't debating taste anymore.
    >
    > **[Evidence over theory]** Then I built a small proof of concept instead of arguing. I showed him
    > a column-type mismatch that my version caught at build time and that a raw SQL string wouldn't
    > have caught until deployment. And I benchmarked it to show that the static polymorphism added zero
    > runtime overhead — CRTP resolves at compile time, so there's no vtable and the mapping actually
    > inlines.
    >
    > **[Answer the real objection]** His actual objection was maintainability, so I addressed
    > maintainability rather than re-arguing the point I'd already made. I wrote a thorough GoogleTest
    > suite — unit tests for the type mapping, integration tests for query behavior — specifically to
    > prove the abstraction was a safety net rather than something fragile.
    >
    > **[Result]** He agreed and we shipped it. Runtime SQL errors went to nearly zero and onboarding
    > got easier. But the thing I actually took away is the reframe: the conversation only moved once we
    > stopped asking "whose approach is better" and started asking "which one reduces project risk."

    ### Version B — Technical framing (~75s). Use for "tell me about a design decision" or a C++ question about templates.

    > I built a compile-time ORM layer for our time-series telemetry database in C++. The problem I was
    > solving is that hand-written SQL makes your schema contract a runtime contract — the compiler has
    > no idea whether the field you're binding matches the column you're binding it to. Every rename or
    > type change becomes a crash in the field.
    >
    > The core of it is CRTP. A record type inherits from `Entity<Record>` — from a template
    > instantiated with itself — so the base class has the derived type available as a compile-time
    > template parameter, not just a pointer to a base.
    >
    > That's the actual reason I chose it over virtual inheritance, and it's not a performance argument.
    > I was using Boost Describe with Mp11 to reflect over the record's fields and generate the column
    > list, the SQL, and the type validation from them. Describe's `describe_members` takes the concrete
    > type as a template parameter — it's a compile-time facility. With virtual inheritance the base
    > class only ever sees a base pointer; the derived type is erased by design. So there's no type to
    > reflect over, no way to enumerate the fields or learn that one of them is a `double` that has to
    > map to `DOUBLE PRECISION`, and the whole compile-time-safety idea collapses. Virtual wasn't a
    > slower way to do it — it couldn't do it.
    >
    > The other benefits came along for free. No vtable, so no indirection per field in a mapping path
    > that runs per row per column. Better inlining, because the compiler sees the concrete method and
    > can constant-fold the whole mapping. And compile-time enforcement of the interface shape,
    > including static members and return types, which a vtable can't express at all.
    >
    > The honest tradeoffs: compile times went up, the error messages before C++20 concepts were rough,
    > and you can't put heterogeneous entities in one container because each instantiation is an
    > unrelated type. Those were acceptable here because entity types are known at compile time by
    > definition.
    >
    > If I were building it on a modern toolchain I'd express the entity contract as a C++20 concept
    > instead of relying on `static_cast` failures — same zero-overhead dispatch, but the error message
    > tells you which method you forgot instead of producing four hundred lines of instantiation
    > backtrace.

<a id="ormqa"></a>

??? note "QA"

    **Q: Why not just use an existing ORM?**

    > A couple of reasons specific to the context. Most C++ ORMs are either heavyweight with runtime
    > reflection and their own build steps, or they don't handle TimescaleDB's hypertable and
    > time-series semantics well. And I only needed a narrow slice — type-safe insert and query for a
    > known set of record types — so pulling in a large dependency into an embedded-adjacent build for
    > that slice was a bad trade. If the need had been broader I'd have evaluated sqlpp11 or ODB
    > seriously, and I'd want to say that rather than pretend building was obviously correct.

    **Q: What exactly does CRTP give you that `virtual` doesn't?**

    > The base class gets the derived type _as a type_, at compile time. That's the whole thing, and for
    > this design it wasn't a nice-to-have — it was the enabling requirement. I was using Boost Describe
    > with Mp11 to reflect over the entity's fields and generate the column list, the SQL, and the type
    > validation from them. `describe_members<T, ...>` is a template; it needs the concrete type as a
    > template parameter. With `virtual` the base only ever sees `Base*` — the derived type is erased,
    > which is the entire point of dynamic dispatch — so there's nothing to hand to the reflection
    > machinery. No field enumeration, no way to know a member is a `double` that maps to
    > `DOUBLE PRECISION`, and therefore no compile-time schema checking at all. Every entity would be
    > back to hand-writing its column list, which is the duplication that causes drift in the first
    > place.
    >
    > The performance side is real but secondary: `static_cast` to the derived type resolves the call at
    > compile time and inlines, where a vtable is an indirection and an optimization barrier — which
    > matters in a per-field mapping loop. And it enforces contract shapes a vtable can't express at all
    > — static member functions, `constexpr` members, specific return types — because the enforcement is
    > just "does this code compile."

    **Q: What are the downsides of CRTP? Be honest.**

    > Four. Compile times and binary size grow, because each instantiation is separately generated code.
    > Error messages before C++20 are genuinely bad — a missing method produces a wall of instantiation
    > backtrace rather than a clear diagnostic. You lose heterogeneous containers: `Entity<A>` and
    > `Entity<B>` are unrelated types, so there's no common base to store in a `vector`. And there's a
    > real team cost — the pattern isn't obvious, which was exactly my lead's objection. I mitigated the
    > last one with test coverage and documentation, but I wouldn't claim I eliminated it.

    **Q: When would you use `virtual` instead?**

    > Whenever the set of types isn't known at compile time, or when I need to store heterogeneous
    > objects together. A plugin architecture, a device driver registry populated at boot, a protocol
    > handler dispatch where handlers register themselves — those all require runtime dispatch and CRTP
    > simply can't do them. I'd also use `virtual` when the call isn't hot and the readability of a
    > plain interface is worth more than the indirection, which is most code.

    **Q: How did Boost Describe / Mp11 fit in?**

    > They're the reason the design is CRTP in the first place. Boost Describe annotates a struct so its
    > members are queryable as a compile-time type list; Mp11 lets you iterate that list with
    > `mp_for_each`, and at each step you have the field's name and its type. That's what generates the
    > column list, builds the SQL, and `static_assert`s that every field type has a valid SQL mapping —
    > all at build time. A developer describes the record once; the column list, the bind code, and the
    > row mapping all derive from it, so there's no second copy to drift out of sync. That duplication
    > _is_ the schema drift problem in miniature, so removing it was the point. If I were doing it today
    > on C++26 I'd want static reflection in the language rather than a library, since that's the
    > direction the standard is going — and notably, language reflection would remove much of the reason
    > to reach for CRTP here at all.

    **Q: How did you test template-heavy code?**

    > Three layers. Compile-time tests using `static_assert` and negative compilation tests — asserting
    > that certain wrong usages _fail to compile_, which is the only way to test a compile-time
    > guarantee. Unit tests for the mapping logic itself, verifying that a struct round-trips through
    > the type conversion correctly, including edge cases like nulls and boundary values. And
    > integration tests against a real Postgres instance for actual query behavior, because a mapping
    > that's internally consistent but wrong about the database's type system is still wrong. That third
    > layer was what actually convinced the lead.

    **Q: What's the performance difference, concretely?**

    > The static dispatch itself is zero-cost — it compiles to the same code you'd write by hand. The
    > measurable win is in the mapping path: the compiler can inline the per-field bind and
    > constant-fold the offsets, where a virtual version would be an indirect call per field per row. At
    > telemetry volumes that's meaningful. But I want to be precise: for this workload the database
    > round-trip dominated end-to-end time, so the performance argument was never the primary one. The
    > primary argument was _correctness_ — moving errors from runtime to compile time — and the
    > performance data existed to remove the objection that safety was costing us something.

    **Q: How would you build this today?**

    > C++20 concepts for the entity contract, which is the single biggest improvement — same
    > zero-overhead static dispatch, but a failure says "T does not satisfy Serializable" instead of
    > producing an instantiation backtrace. `std::expected` rather than exceptions for query failures,
    > so error handling is explicit in the signature. And if the toolchain supported it, static
    > reflection instead of Boost Reflection.

    **Q: What if a junior engineer has to maintain this after you leave?**

    > That was the objection, and I think the honest answer is that it's a real cost you buy down rather
    > than eliminate. What I did: comprehensive tests so behavior is documented executably, a narrow
    > public API so the surface a junior actually touches is small — you inherit from `Entity<T>`, you
    > declare your fields, that's it — and documentation of the _why_, not just the _how_. The deeper
    > argument is that the complexity is bounded and in one place, whereas fragile SQL strings
    > distribute a smaller complexity across every call site, where it's much harder to review. I'd
    > rather have one hard file than fifty risky ones.
