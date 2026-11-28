# Otel

> Part of the Projects guide — [back to index](../README.md)

<a id="otel"></a>

## The situation, in full

At Toyota Material Handling's Advanced Research & Development group, you worked on a multi-threaded
C++ ADAS (Advanced Driver Assistance Systems) stack running on autonomous forklifts. The application
ran on the **DHU — Driver/Data Handling Unit** — an embedded Linux system on **aarch64 (ARM64)**
hardware, with meaningfully constrained CPU and memory.

**The problem you identified:** the team had a black-box problem. When behavior diverged or latency
spiked in a multi-threaded system, the only diagnostic artifact was unstructured logs. Logs tell you
_what happened in one thread_. They don't tell you _where time went_, and they don't let you
correlate an event in the perception thread with an event in the control thread. Debugging a latency
issue took days of sifting through anecdotal output.

You had **no prior OpenTelemetry experience and there was no existing telemetry infrastructure.**
You chose to build it.

## What you actually built

**Layer 1 — The C++ instrumentation library.**

A wrapper around the OpenTelemetry C++ SDK exposing three signal types:

- **Traces** — spans with parent/child relationships, so a single logical operation can be followed
  across threads and components.
- **Metrics** — counters and histograms with stable label sets.
- **Logs** — structured, correlated to the active trace context.

Design principles you enforced, each of which is a defensible engineering decision:

| Principle                                           | Why                                                                                                                                                                      | C++ mechanism                                                                                                  |
| --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| **RAII scopes for spans**                           | A span must end on _every_ exit path — early return, exception, error. Manual `end()` calls get missed.                                                                  | Span object starts on construction, ends in the destructor. Same idiom as `lock_guard`.                        |
| **Minimal overhead instrumentation**                | Telemetry runs alongside safety-critical work on a constrained DHU. If instrumentation perturbs timing, it's worse than useless — it changes the thing you're measuring. | Atomics rather than mutexes for counters; avoid allocation in the hot path; sampling.                          |
| **Telemetry must never crash the app**              | An observability layer that takes down the system it observes is a net negative.                                                                                         | Exporters isolated; failures counted and swallowed, never propagated; no exceptions escape the boundary.       |
| **Back-pressure handled by dropping, not blocking** | If the exporter can't keep up, blocking the caller means telemetry stalls the ADAS pipeline.                                                                             | Bounded queue; drop spans and increment a `dropped_spans` counter so the loss is _visible_ rather than silent. |
| **Consistent attribute conventions**                | Inconsistent labels make traces uncorrelatable, which defeats the point.                                                                                                 | A shared conventions header; "instrumentation as an API" — designed so it's hard to misuse.                    |
| **Cardinality control**                             | High-cardinality labels (anything unbounded — vehicle IDs, timestamps, request IDs as _labels_) explode the metric backend's memory.                                     | Enumerated label values; high-cardinality data goes on spans, not metrics.                                     |

**Layer 2 — The Collector pipeline.**

You went beyond the library and deployed the **OpenTelemetry Collector directly on the DHU**. This
is the part that distinguishes the project from "I added some logging."

- **Cross-compiled the OTel SDK and the Collector for aarch64.** Nearly all OTel documentation and
  prebuilt binaries assume x86_64 cloud environments. Getting the SDK and the Collector building and
  running on ARM64 embedded Linux was the single largest engineering lift.
- **Local aggregation before export** — the collector batched and aggregated on-device, so the
  network carried summaries rather than raw span floods. Critical on a vehicle with intermittent
  connectivity.
- **Fan-out exports** — one collector, multiple destinations, so different consumers
  (Elasticsearch/Kibana for search, and other backends) each got what they needed without
  instrumenting the application twice.
- **Data persistence across intermittent connectivity** — a vehicle drives out of coverage;
  telemetry buffers and flushes on reconnect rather than being lost.
- **Integrated into the base DHU image.** The final milestone: your collector configuration and
  binaries shipped as part of the standard system image. Every vehicle off the line ran your
  observability stack natively.

**Layer 3 — The backend.** Export to Elasticsearch and Kibana for search and dashboards, with
schemas you designed.

## The bug — the technical centerpiece

**Symptom:** non-deterministic crash, **only at shutdown.** Steady-state operation was clean. The
crash didn't reproduce reliably and didn't reproduce under a debugger (attaching changed the timing
enough to hide it).

**How you reasoned about it:** the useful question wasn't "where does it crash" — it was _"what is
true at shutdown that isn't true at any other time?"_ The answer is: static-storage objects are
being destroyed while threads may still be running.

**Root cause: the Static Destruction Order Fiasco.** The OpenTelemetry providers were global
statics. Static objects across different translation units are destroyed in an order the standard
leaves **unspecified**. Worker threads were still emitting their final spans against provider
objects that had already been destructed — a use-after-free during teardown.

**Attempt 1 — Meyers singleton.**

```cpp
Provider& instance() {
    static Provider p;   // C++11: thread-safe initialization
    return p;
}
```

This is the _correct instinct for the wrong half of the problem._ Construct-on-first-use solves the
**initialization** order fiasco completely. It does **nothing** for destruction order —
function-local statics are still destroyed at exit, in reverse order of completed construction,
still without regard to whether other threads are done with them.

Being able to say "my first fix was right for the adjacent problem and I understood why it didn't
work" is more impressive than having gotten it right immediately. It demonstrates you understood the
mechanism rather than pattern-matching a fix.

**Attempt 2 — the weak-pointer singleton. The actual fix.**

```cpp
std::shared_ptr<Provider> get_provider() {
    static std::mutex m;
    static std::weak_ptr<Provider> weak;

    std::scoped_lock lk(m);
    if (auto sp = weak.lock()) return sp;   // alive → share ownership

    auto sp = std::make_shared<Provider>();
    weak = sp;
    return sp;                               // caller now holds it alive
}
```

**Why this works — the key insight:** ownership is inverted. The singleton no longer _owns_ the
object; **every caller holds a strong reference for exactly as long as it is using it.** The
provider therefore cannot be destroyed while a consumer is mid-call, because the consumer owns it
during that window. Destruction becomes deterministic — it happens when the last user releases, not
at an arbitrary point in the exit sequence.

And if teardown has genuinely begun and the last reference is gone, `weak.lock()` returns null and
the caller **no-ops safely** instead of touching freed memory. The failure mode degrades from
"crash" to "one lost span."

**Plus:** you registered `atexit()` cleanup handlers in the accessor to force a deterministic flush
— so buffered telemetry was exported before exit rather than being dropped along with the process.

## Results

- Eliminated the shutdown crashes entirely.
- **~40% improvement in debugging efficiency**, measured against how long issues took to diagnose
  before.
- Multi-threaded race-condition and latency diagnosis went **from days to minutes**, because
  correlated traces across threads replaced anecdotal logs.
- The weak-pointer singleton pattern became the **team standard** for global resource management.
- The collector shipped in the **base DHU image** — from experimental tool to foundational system
  component.
- Culture shift: from reactive logging to proactive observability.

## The C++ concepts in play (cross-reference for the technical interview)

`std::weak_ptr` / `std::shared_ptr` lifetime · static initialization/destruction order · Meyers
singleton and its limits · RAII scope guards · thread-safe function-local statics · atomics vs
mutexes for counters · false sharing on hot metric counters · cross-compilation and toolchains ·
`atexit` · back-pressure and bounded queues · exception isolation at a library boundary.

<a id="otelstar"></a>

??? note "STAR"

    **Situation.** Our multi-threaded C++ ADAS stack on the forklift DHU was effectively a black box.
    When latency spiked or behavior diverged across threads, the only artifact we had was unstructured
    logs, and diagnosing a single issue could take days. There was no telemetry infrastructure, and
    nobody on the team had OpenTelemetry experience — including me.

    **Task.** I decided to own end-to-end observability for the stack: design and build a C++ telemetry
    library for logs, traces, and metrics, and get it running in production on constrained aarch64
    embedded hardware without perturbing the safety-critical workload it was measuring.

    **Action.** I designed the library around three non-negotiables: RAII span scopes so no exit path
    can leak an unclosed span, minimal-overhead instrumentation using atomics rather than locks in the
    hot path, and hard isolation of exporter failures so telemetry could never take down the
    application. I went further than the library and cross-compiled both the OTel SDK and the OTel
    Collector for aarch64 — nearly everything published assumes x86 cloud — and architected the
    collector for local aggregation with fan-out remote export so we kept data through intermittent
    vehicle connectivity.

    During rollout we hit a non-deterministic crash that appeared only at shutdown. I traced it to the
    static destruction order fiasco: our providers were global statics being destroyed while worker
    threads were still emitting final spans. My first fix was a Meyers singleton, which correctly solves
    _initialization_ order but does nothing for _destruction_ order — so I refactored to a weak-pointer
    singleton where every caller holds a strong reference while it's in use, and registered `atexit`
    handlers for a deterministic flush.

    **Result.** The shutdown crashes went to zero, and the weak-pointer pattern became our team standard
    for global resources. Debugging efficiency improved roughly 40%, and multi-threaded latency and race
    diagnosis went from days to minutes. The collector configuration and binaries were integrated into
    the base DHU image, so every vehicle that shipped ran the observability stack natively.

<a id="otelscript"></a>

??? note "Scripts"

    ### Version A — Full (~2:00). Use for "most proud" / "hardest problem" / "tell me about a project."

    > I'll take the OpenTelemetry work at Toyota, because it's the one where I owned the whole thing end
    > to end.
    >
    > **[Problem]** We had a multi-threaded C++ ADAS stack running on autonomous forklifts, and it was a
    > black box. When latency spiked or two threads diverged, all we had were unstructured logs. Logs
    > tell you what happened in one thread — they don't tell you where time went, and they don't let you
    > correlate across threads. Diagnosing a single issue could take days.
    >
    > **[Ownership]** Nobody had asked for telemetry and nobody on the team had OpenTelemetry
    > experience, including me. I decided this was the highest-leverage thing I could fix, so I took it
    > on.
    >
    > **[What I built]** I built a C++ library over the OTel SDK for logs, traces, and metrics, and I
    > designed it around three rules. Spans are RAII-scoped, so a span ends on every exit path including
    > exceptions — you can't forget to close one. Instrumentation is minimal-overhead, atomics instead
    > of locks in the hot path, because this runs alongside safety-critical work on constrained hardware
    > and if the telemetry perturbs the timing it's actively harmful. And telemetry can never crash the
    > app — exporters are isolated, failures get counted and swallowed, and back-pressure drops spans
    > rather than blocking the caller.
    >
    > **[Depth]** Then I went past the library. I cross-compiled both the SDK and the OTel Collector for
    > aarch64 and ran the collector on the vehicle itself, which was the biggest lift because
    > essentially all OTel tooling assumes x86 cloud. That let me aggregate locally and fan out exports,
    > so we kept data through intermittent connectivity instead of losing it.
    >
    > **[The bug]** The interesting part was a bug. During rollout we got a non-deterministic crash —
    > only at shutdown, never in steady state, and it wouldn't reproduce under a debugger because
    > attaching changed the timing. So I reasoned about it structurally instead: what's true at shutdown
    > that isn't true anywhere else? Static objects are being destroyed while threads are still running.
    > Our providers were global statics, and destruction order across translation units is unspecified —
    > worker threads were emitting their final spans against objects that had already been destructed.
    >
    > **[The fix, and the honest part]** My first fix was a Meyers singleton. That was the right
    > instinct for the _initialization_ order problem and does nothing for destruction order — I was
    > solving the adjacent problem. The real fix was inverting ownership: a weak-pointer singleton, so
    > every caller holds a strong reference for as long as it's using the provider. Now it physically
    > can't be destroyed mid-call, and if teardown has already happened the `lock()` just fails and we
    > drop one span instead of crashing. Plus `atexit` handlers to force a deterministic flush.
    >
    > **[Result]** Crashes went to zero, and that pattern became the team's standard for global
    > resources. Debugging efficiency went up about 40%, and multi-threaded latency issues went from
    > days to minutes. The part I'm proudest of is that the collector ended up in the base DHU image —
    > it went from an experimental tool to a component every vehicle ships with.

    ### Version B — Compressed (~45s). Use when time is short or as a follow-up.

    > At Toyota I built the observability layer for a multi-threaded C++ ADAS stack on embedded aarch64
    > hardware — a telemetry library over the OpenTelemetry SDK plus a collector I cross-compiled to run
    > on the vehicle itself. The design constraints were that instrumentation couldn't perturb
    > safety-critical timing and couldn't ever crash the app, so spans are RAII-scoped, counters are
    > atomic, and exporter failures are isolated and dropped rather than propagated. The hardest part
    > was a shutdown-only crash that turned out to be static destruction order — providers were global
    > statics being destroyed while threads were still emitting spans. I fixed it with a weak-pointer
    > singleton so callers hold ownership while in use. Crashes went to zero, debugging efficiency
    > improved about 40%, and the collector shipped in the base vehicle image.

    ### Version C — Bug-focused (~60s). Use for "tell me about the hardest bug you've debugged."

    > Non-deterministic crash in a multi-threaded C++ application, only during shutdown. Steady state
    > was completely clean.
    >
    > The debugger was actively unhelpful — attaching changed the timing enough that it stopped
    > reproducing. So I stopped trying to catch it and reasoned about it instead: what is true at
    > shutdown that isn't true at any other point? Static-storage objects are being destroyed, and
    > threads may still be running.
    >
    > That pointed straight at the static destruction order fiasco. Our OpenTelemetry providers were
    > global statics. Destruction order across translation units is unspecified by the standard, so
    > worker threads were emitting their final spans against providers that had already been destructed
    > — use-after-free during teardown.
    >
    > My first fix was a Meyers singleton, and I want to be straight that it didn't work, because it's
    > instructive. Construct-on-first-use solves the _initialization_ order problem completely. It does
    > nothing for destruction order — the object still dies at exit, in an order I don't control.
    >
    > What actually worked was inverting ownership. I moved to a weak-pointer singleton: the accessor
    > holds a `weak_ptr`, and every caller gets a `shared_ptr` back, so a consumer owns the provider for
    > exactly as long as it's using it. It can't be destroyed mid-call. And if teardown has genuinely
    > finished, the `lock()` returns null and we drop one span instead of dereferencing freed memory —
    > the failure mode degrades from crash to data loss. I also registered `atexit` handlers so buffered
    > telemetry flushed deterministically instead of being lost with the process.
    >
    > Zero crashes after that, and it became the team's standard pattern for anything global.

<a id="otelqa"></a>

??? note "QA"

    **Q: Why not just use logging? What does tracing actually give you?**

    > Logs are per-event and per-thread. A trace is a causal tree — one logical operation, with
    > parent/child spans across threads and components, and a duration on each. That's the difference
    > between "here are 4,000 lines that happened around the time it was slow" and "this operation took
    > 340ms and 310ms of it was inside this one call." In a single-threaded request/response service
    > logs get you most of the way. In a multi-threaded pipeline where work hands off between
    > components, correlation is the entire value.

    **Q: What was the actual overhead of your instrumentation?**

    > I designed for it rather than measuring it after the fact, which mattered because we were on a
    > constrained DHU alongside safety-critical work. The specific choices: atomics rather than mutexes
    > for counters so there's no possibility of a thread parking in the hot path, no allocation in span
    > creation on the common path, sampling so we weren't paying full cost on every operation, and local
    > aggregation in the collector so the application wasn't doing serialization work. The forcing
    > constraint was that telemetry must never change the timing of the thing it's measuring — if it
    > does, you're not observing the system anymore, you're observing a different system.

    **Q: What happens if the exporter goes down or the network is out?**

    > Two mechanisms. Back-pressure is handled by a bounded queue that **drops** rather than blocks —
    > blocking would mean telemetry could stall the ADAS pipeline, which is unacceptable. When we drop,
    > we increment a `dropped_spans` counter, so the loss is visible rather than silent; you can see in
    > the data that you're missing data. And the on-device collector buffers and persists across
    > intermittent connectivity, so a vehicle driving out of coverage flushes on reconnect instead of
    > losing the window.

    **Q: Why run a collector on the device instead of exporting directly?**

    > Three reasons. Aggregation — the collector batches and pre-aggregates locally, so the network
    > carries summaries rather than a raw span flood, which matters a lot on a vehicle. Decoupling — the
    > application talks to one local endpoint, and I can change or add backends in collector config
    > without touching or redeploying application code. And fan-out — multiple consumers wanted
    > different views, and I'd rather configure that in one place than instrument the app twice.

    **Q: What made cross-compiling for aarch64 hard?**

    > Mostly ecosystem assumptions. The OTel C++ SDK and the Collector are built and tested against
    > x86_64 cloud environments — prebuilt binaries, container images, and a lot of the dependency chain
    > assume it. So it was building the SDK and its transitive dependencies for ARM64, getting the
    > toolchain and sysroot right, and then tuning for a memory and CPU budget that a cloud collector
    > never has to think about. The value was that once it worked, it was reproducible and it shipped in
    > the base image.

    **Q: Explain the static destruction order fiasco precisely.**

    > Objects with static storage duration that require dynamic initialization are initialized in an
    > order that's only defined _within_ a translation unit — declaration order. **Across** translation
    > units the order is unspecified; in practice the linker decides. Destruction happens in reverse
    > order of construction, so it inherits the same indeterminacy. The initialization half is the
    > classic fiasco: object A's constructor uses object B, and B hasn't been constructed yet. The
    > destruction half is what bit us, and it's worse in a multi-threaded process, because it's not just
    > ordering between two objects — it's ordering between a destructor and threads that are still
    > running.

    **Q: Why didn't the Meyers singleton fix it?**

    > Because a Meyers singleton solves _when the object is constructed_, not _when it's destroyed_.
    > Construct-on-first-use guarantees the object exists before anyone uses it, which fully solves the
    > initialization fiasco. But a function-local static is still destroyed at program exit, in reverse
    > order of completed construction, and that order still has nothing to do with whether other threads
    > are finished with it. I'd fixed a real problem — just not the one I had.

    **Q: Are there downsides to the weak-pointer singleton?**

    > Yes, and they're worth naming. You pay an atomic refcount increment and a mutex acquisition on
    > every `get`, so you don't want it in a per-operation hot path — I cached the `shared_ptr` at the
    > component level rather than calling `get_provider()` inside a loop. And the lifetime becomes
    > genuinely dynamic: the object can be destroyed and reconstructed if all references drop and
    > someone calls `get` again, which is fine for a logger but wrong if construction is expensive or
    > has side effects. The alternative I considered was a deliberately leaked singleton — `new` it and
    > never delete it, let the OS reclaim at exit. That trades one reported leak for the complete
    > elimination of shutdown-order bugs, and plenty of production systems make exactly that trade for
    > loggers and allocators. I went with the weak pointer because I also wanted the deterministic
    > flush.

    **Q: How did you know the fix worked, given the bug was non-deterministic?**

    > Fair challenge, and "it stopped happening" is a weak proof for a race. Two things. First, the
    > reasoning is structural rather than probabilistic — under the weak-pointer design the object
    > _cannot_ be destroyed while a caller holds a reference, so the specific use-after-free is
    > eliminated by construction, not by timing. Second, I could exercise the teardown path in a loop
    > under load, which is where it had been reproducing most often, and I instrumented the destructors
    > so I could see the ordering directly rather than inferring it. If I were doing it today I'd also
    > run the shutdown path under TSan.

    **Q: What is cardinality control and why did you care?**

    > Metric backends index by label set, and every unique combination of label values is a separate
    > time series stored in memory. If you put something unbounded in a label — a request ID, a
    > timestamp, a vehicle serial — you get a cardinality explosion that will take down the backend. So
    > the rule I enforced was: labels are enumerated and bounded; anything high-cardinality goes on a
    > _span_ attribute instead, because traces are sampled and stored differently. Getting that
    > convention right up front is much cheaper than retrofitting it after someone's dashboard has half
    > a million series.

    **Q: What would you do differently?**

    > I'd design the shutdown path deliberately from day one rather than discovering it. Most of the
    > instrumentation was designed for steady state, and teardown got attention only after it crashed —
    > that's a category of thinking I now apply upfront. I'd also push harder on making instrumentation
    > _impossible_ to misuse rather than merely documented; we had conventions, but they were enforced
    > by review rather than by the type system, and I'd rather a wrong label set be a compile error.
    > That's the same instinct as the ORM work.

    **Q: How does this relate to storage?**

    > Directly, I think. Debugging a customer issue you can't reproduce is the core problem in both. The
    > tools are the same — structured tracing, correlated timing, latency distributions instead of
    > averages. And the constraints rhyme: instrumentation in a storage data path has the same
    > requirement mine had, which is that it can't be allowed to affect the thing it's measuring or take
    > down the system it's observing. I'd also expect the resource-lifetime and teardown reasoning to
    > transfer almost unchanged, because a controller that runs for years has a much harsher version of
    > the same problem.
