# Orientation

> Part of the Projects guide — [back to index](README.md)

---

## Howto

**Two weeks out.** Read the Deep Dive sections. These exist so that when an interviewer asks the
third follow-up — the one past what you rehearsed — you have real technical substance rather than a
memorized paragraph running out.

**One week out.** Rehearse the Scripts out loud, timed. Every script here is annotated with a target
length. Speaking a 90-second answer takes practice; reading it silently gives you a false sense of
readiness.

**Day before.** Read only the STAR blocks and [Drills](wrap-up.md#drills).

**Three rules for the room:**

1. **Lead with the problem, not the technology.** "Our cross-team dependencies were drifting" is a
   better opener than "I built a Bash script using the az CLI." The interviewer needs to care before
   they need the details.
2. **Name the tradeoff you rejected.** Every design choice you made had an alternative. Saying "I
   considered X and chose Y because Z" is the single highest-signal thing you can do — it proves you
   designed rather than defaulted.
3. **Land on impact, then stop.** Say the result and be quiet. The silence invites the follow-up
   you're prepared for, and it lets the interviewer steer.

**When you don't know something:** say so immediately, then reason forward. "I haven't worked with
WAFL directly. Based on what I know about copy-on-write filesystems, I'd expect X — is that roughly
right?" That answer scores better than a confident wrong one, and it's exactly the collaborative
behavior the recruiter's email described.

---

## Portfolio

| #   | Project                                   | Core technical claim                                                                           | Best for                                                 |
| --- | ----------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| 1   | **OpenTelemetry C++ library + Collector** | Multi-threaded C++, cross-compiled aarch64, static destruction order bug, RAII instrumentation | Hardest bug · Most proud · Systems depth · Concurrency   |
| 2   | **Compile-time ORM (CRTP)**               | Template metaprogramming, static polymorphism, compile-time safety, zero runtime overhead      | Disagreement · Innovation · C++ depth · Design tradeoffs |
| 3   | **Python schema bridge**                  | Complete-type rule, memory alignment, topological sort over the type graph                     | Cross-team · Algorithms · Automation · Systems thinking  |
| 4   | **External libraries sync**               | Git internals, platform limits, automation at scale, surprising downstream behavior            | Ownership · Scale · Debugging a layer below you          |
| 5   | **AKS + Bicep build infra**               | Remote build execution, caching, zero-trust networking                                         | Learning fast · Security · Velocity                      |
| 6   | **Azure IoT nested edge**                 | Device lifecycle, certificate auth, ordered manifest rollout                                   | Hardware/software · Complex architecture                 |
| 7   | **Real-time tracker**                     | Full-stack, SignalR streaming, live visualization                                              | Versatility · Product sense                              |
| 8   | **Protocol migration testing (Siemens)**  | APOGEE→BACnet migration de-risked by a data-driven harness; mocks, custom serializers          | **Protocols** · Quality · Measurable impact · Ramping up |
| 9   | **Boost.Beast REST + LEAF**               | C++ HTTP services, structured error handling                                                   | Error design · C++ in a service context                  |
| 10  | **Affordit CQRS + RabbitMQ**              | Event-driven design, delivery semantics, eventual consistency — as the _first technical hire_  | **Ambiguity** · Distributed systems · Full ownership     |

**If you only prepare three:** #1 (OTel), #2 (ORM), #3 (Bridge). Those three cover systems C++,
design judgment, and low-level correctness — which is the entire evaluation surface for this role.

**Two more that punch above their weight, and that you have been undertelling:** **#8** is a
proprietary-to-open **protocol migration** and NetApp is hiring Protocols teams. **#10** is your
only story with _no scaffolding at all_ — first technical hire, two years — and its CQRS design has
the same failure modes as replication. Prepare both.

---

## Matching

How each project maps to what NetApp actually said they're hiring for.

| NetApp requirement (from the JD)                                                    | Your evidence                                                                                                                                                                                                       |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| "Write high-quality C/C++ code that is efficient, reliable, maintainable"           | OTel library (production, embedded, safety-adjacent); ORM (compile-time safety, zero overhead)                                                                                                                      |
| "Analyze and improve existing code paths for performance, scalability, correctness" | OTel overhead tuning on a constrained DHU; ORM benchmarks proving zero runtime cost                                                                                                                                 |
| "Debug complex issues using system-level tools, logs, tracing, profiling"           | **The OTel project _is_ this requirement.** You built the tracing infrastructure, then used it. Plus the static destruction order diagnosis.                                                                        |
| "Collaborate across engineering teams — filesystem, protocol, cloud, hardware, QA"  | Bridge (Services/C# ↔ Perception/C++); IoT (security + hardware teams); Cloud (security leads)                                                                                                                      |
| **Protocols** (NFS/SMB/SAN/NVMe is a named team)                                    | **Siemens APOGEE→BACnet migration** — a proprietary-to-open-standard protocol transition in deployed systems: interop, semantic mapping, backward compatibility. See [Testing](fullstack/testing.md#testing)             |
| **Distributed systems** (a named team)                                              | **Affordit CQRS + RabbitMQ** — delivery semantics, idempotent consumers, eventual consistency and read-your-own-writes. See [Affordit](fullstack/affordit.md#affordit)                                                    |
| Performing in **ambiguous situations** (called out in their prep deck)              | **Affordit as first technical hire** — no conventions, no reviewer, no escalation path. The one story with no scaffolding underneath it                                                                             |
| Build systems, toolchains, cross-compilation                                        | Bazel remote execution + caching on AKS; cross-compiling for aarch64 and dependency isolation on the DHU. See [Cloud](devops/cloud.md#cloud) and the C++ guide's [Cross](../cpp_deep_dive/build-toolchain.md#cross) |
| "Participate in design and code reviews, contributing to best practices"            | ORM disagreement → became team standard; OTel singleton pattern → became team standard                                                                                                                              |
| "Investigate performance bottlenecks and implement optimizations"                   | Bazel remote build execution + Redis cache; OTel minimal-overhead instrumentation                                                                                                                                   |
| "Support prototyping, research, feasibility analysis"                               | The ORM POC that won the architectural argument                                                                                                                                                                     |
| "Communicate design decisions and findings clearly"                                 | The disagreement story is entirely about this                                                                                                                                                                       |
| "Use AI-assisted tools to accelerate development"                                   | Be ready with an honest, specific answer — see [Framing](#framing)                                                                                                                                                  |
| Concurrency & multithreading                                                        | OTel: multi-threaded ADAS, thread-safe instrumentation, context propagation, teardown ordering                                                                                                                      |
| Memory management                                                                   | OTel singleton lifetime; ORM allocation avoidance; Bridge struct layout and alignment                                                                                                                               |
| Systems design & architecture                                                       | OTel collector pipeline (local aggregation + remote export + back-pressure); nested edge hierarchy                                                                                                                  |

**The gap to name honestly and proactively:** you have not worked on filesystems or storage
internals. Do not hide this. The correct move is to say it once, early, and immediately pivot to the
transferable core — _"I haven't worked on a filesystem, but the problems you've described —
concurrency at scale, resource lifetime under long uptime, latency tails, debugging without a
reproducer — are exactly what I've been doing on constrained embedded systems where failure isn't
recoverable either."_

---

## Framing

Three framings to have loaded, because they'll come up regardless of which project is being
discussed.

**"Why storage? Why NetApp?"**

> "Two reasons, and one of them is honest self-interest. First, the problem class: I've spent the
> last three years on systems where correctness isn't negotiable — safety-adjacent ADAS software on
> constrained hardware, where a crash isn't a retry, it's a vehicle. Storage has that same property,
> at a much bigger scale. Data integrity, multi-year uptime, latency tails that customers actually
> feel. Second, I want to go deeper into the stack. I've been working _near_ the metal —
> cross-compiling for aarch64, worrying about cache and alignment and teardown order — and I want to
> work _at_ it. ONTAP is one of the few codebases where those things are the job rather than an
> occasional detour."

**"What's your experience with AI-assisted tooling?"** _(The JD calls this out explicitly, which
means someone will ask.)_

> "I use it heavily but selectively. It's genuinely good at the things that are tedious and
> verifiable — generating test scaffolding, translating between formats, first-pass documentation,
> exploring an unfamiliar API. My schema-bridge tool was essentially that problem in a deterministic
> form, so I have a reasonable instinct for where codegen helps. Where I'm deliberate: I don't trust
> it for concurrency or lifetime reasoning, because the failure mode is plausible-looking code with
> a subtle race, and that's exactly the class of bug that doesn't show up in testing. So I use it to
> go faster on the parts I can verify quickly, and I slow down on the parts where being wrong is
> expensive."

**"What are you looking for in your next role?"**

> "Depth over breadth. I've been rewarded for being the person who can pick up an unfamiliar stack
> fast — and I'm good at it — but I want to spend the next several years going deep on one hard
> system rather than broad across many. I'd rather know one subsystem well enough to have opinions
> about it than know ten well enough to be dangerous. That, plus a team where the code review bar is
> high, because I learn most from having my design decisions challenged. The ORM disagreement is a
> good example — I got a better outcome because someone pushed back."
