# Affordit

> Part of the Projects guide — [back to index](../README.md)

<a id="affordit"></a>

> **Why this section exists.** You have been describing Affordit as "an internship," which is a
> significant undersell. It was **two years as the first technical hire at a startup**, while you
> were an undergraduate. Two things in it are directly relevant to NetApp — **operating with no
> scaffolding whatsoever**, and **an event-driven CQRS design whose failure modes are the same ones
> storage replication has.** Neither is currently in your telling.

## The situation

**Affordit, Jun 2020 – May 2022, ~2 years. Software Engineer Intern — but the _first technical
hire_.** A financial-app startup whose product helped users restructure debt and improve their
debt-to-income ratio.

**What "first technical hire" actually means, and this is the part to say plainly:** there were no
existing codebase conventions to follow, no senior engineer to ask, no code review to catch you, and
no one to hand you a scoped ticket. Architecture decisions were either yours or nobody's. When
something broke in production, the escalation path was you.

**Why that matters for this interview specifically.** NetApp said in their own prep material that
they'll explore how you perform **in ambiguous situations.** Every other story in this document has
someone else's scaffolding underneath it — an existing ADAS stack, an existing WPF application, an
existing Bazel monorepo. This is the one where the scaffolding didn't exist. It's also the earliest
evidence for the pattern that runs through everything else: you find the thing nobody assigned,
because at Affordit _nothing_ was assigned.

## What you built

**1. Full-stack product features — .NET, C#, Angular.** The debt-restructuring functionality, which
was the product's core value rather than peripheral work. Owning the feature that the company's
proposition rests on, as the only engineer, at 20.

**2. An event-driven CQRS architecture with RabbitMQ. This is the technically interesting piece.**
**CQRS — Command Query Responsibility Segregation** — separates the write model from the read model.
Commands mutate state and publish events; consumers project those events into read models optimized
for querying. You published and consumed events over RabbitMQ, with **EF Core** for persistence,
which let data-model changes propagate without tight coupling between components and enabled
features like automated email delivery to hang off existing events rather than requiring new code
paths.

**3. Angular UI/UX at depth** — forms, components, and **RxJS** operators — raising the SPA's
cross-browser compatibility by ~**60%**.

## The bridge to NetApp — take this one seriously

**CQRS with a message broker is a distributed system, and its problems are storage's problems.** If
you can articulate this, it converts a startup web-app story into a distributed-systems story. The
questions the design forces:

| The question in a CQRS system                                | The same question in storage                                                                                                                 |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Does the broker guarantee ordering? Per-queue, or globally?  | Write ordering in a replication stream; why a log is ordered                                                                                 |
| At-least-once versus exactly-once delivery                   | Exactly-once is essentially unavailable; you get at-least-once plus idempotent consumers                                                     |
| What happens when a consumer processes the same event twice? | **Idempotency** — the property that makes retries safe. See [Idempotency](../../networking_and_storage/05-distributed-systems.md#idempotency)                          |
| The read model lags the write model                          | **Eventual consistency**, and specifically the **read-your-own-writes** problem. See [Consistency](../../networking_and_storage/05-distributed-systems.md#consistency) |
| A consumer is down; events queue up                          | Replication lag, backlog, and RPO. See [RPO](../../networking_and_storage/03-availability-replication.md#rpo)                                                               |
| Replaying the event log to rebuild a read model              | Log replay after a crash; journal recovery                                                                                                   |

**The line that makes this land:**

> "I built an eventually-consistent read path when I was twenty and didn't have the vocabulary for
> it until years later. The bug I remember was a user completing an action and not seeing it
> reflected — which I now know is read-your-own-writes, and the reason storage systems care so much
> about which consistency model they're actually offering."

**Be honest about scale.** A startup's event volume is nothing, and an interviewer will know that.
Say so first and pivot to the reasoning: the failure modes are the same shape regardless of volume,
and what you took from it was the design tension rather than the throughput.

## Concepts in play

Event-driven architecture · CQRS · message brokers and delivery semantics · idempotent consumers ·
eventual consistency and read-your-own-writes · ORM and persistence (EF Core) · full-stack ownership
· operating without scaffolding.

<a id="affstar"></a>

??? note "STAR"

    **Situation.** I was the first technical hire at a financial-app startup, as an undergraduate. There
    was no existing codebase to follow, no senior engineer to ask, and no code review. The product
    helped users restructure debt, and the core features were mine to build.

    **Task.** As the product grew, the write path and the read path were fighting each other. Adding
    functionality — automated email on a debt-restructuring event, for instance — meant threading new
    code through the request path every time, and each addition made the next one harder. I needed the
    system to absorb new features without every one of them being a modification to existing code.

    **Action.** I restructured it around **CQRS with RabbitMQ**: commands mutate state and publish
    events, and consumers subscribe to those events and project them into read models or trigger side
    effects. EF Core handled persistence. Adding automated email delivery became adding a consumer, not
    editing the write path.

    **What I got wrong, and I'd volunteer this:** I didn't initially think carefully about delivery
    semantics. RabbitMQ is at-least-once, so a consumer can see the same event twice, and I hadn't made
    the consumers idempotent. I also had users occasionally not seeing their own change reflected
    immediately — which I understood at the time as a bug and understand now as the read-your-own-writes
    problem, an inherent property of separating the read model rather than a defect.

    **Result.** New features could be added as consumers rather than as modifications, which was the
    point. And I learned the fundamentals of eventual consistency by building one and hitting its
    failure modes directly, rather than by reading about it — which is the version that actually sticks.

<a id="affscript"></a>

??? note "Scripts"

    ### ~60s. Use for "tell me about working with ambiguity," "the most autonomous thing you've done," or "your earliest significant project."

    > Before Toyota I spent two years as the first technical hire at a financial-app startup, while I
    > was still an undergrad. It's listed as an internship but in practice it wasn't — there was no
    > existing codebase to follow, no senior engineer to ask, and no code review. Architecture decisions
    > were either mine or nobody's.
    >
    > The piece I'd point to is that I restructured the app around CQRS with RabbitMQ. The problem was
    > that every new feature meant threading more logic through the write path, and each one made the
    > next harder. So I split it: commands mutate state and publish events, and consumers project those
    > events into read models or trigger side effects. Adding automated emails became adding a consumer
    > instead of editing the core path.
    >
    > What I'd flag is what I got wrong. I didn't think carefully about delivery semantics — RabbitMQ is
    > at-least-once, so consumers can see an event twice and mine weren't idempotent. And users would
    > occasionally not see their own change reflected right away. I treated that as a bug at the time.
    > It's actually read-your-own-writes, and it's inherent to separating the read model.
    >
    > That's the reason I bring it up for a storage role. I built an eventually-consistent system at
    > twenty and hit its failure modes without having the vocabulary for them, and the vocabulary —
    > ordering, idempotency, replication lag — is the same vocabulary.

<a id="affqa"></a>

??? note "QA"

    **Q: Wasn't this just an internship?**

    > Titled that way, and I won't oversell it — but it was two years and I was the only engineer for a
    > good part of it. The thing I'd point at isn't seniority, it's that there was no scaffolding. No
    > conventions, no reviewer, no one to escalate to. That's a different way of working from anything I
    > did afterward, and I think it's why I default to owning things end to end.

    **Q: Why CQRS? Isn't that over-engineering for a startup?**

    > That's a fair challenge and the honest answer is that it was probably more architecture than the
    > stage warranted. What drove it was a real symptom — every new feature was a modification to the
    > write path and coupling was compounding. CQRS solved that. But if I were making the call now I'd
    > probably start with a simpler event bus and only separate the read model when query load actually
    > demanded it. The lesson I took is that the _coupling_ problem was real and my solution was one
    > size too large for it.

    **Q: How would you make a consumer idempotent?**

    > Give every event a stable identifier and have the consumer record which identifiers it has already
    > processed, in the same transaction as the effect — so the dedup and the work commit or fail
    > together. If the effect isn't transactional, make it naturally idempotent instead: set a value
    > rather than increment it, upsert rather than insert. That's the same reasoning behind idempotent
    > request handling in a storage protocol, where a retried write must not apply twice.

    **Q: At-least-once versus exactly-once — is exactly-once possible?**

    > Not really, not end to end. You can get _effectively_-once, which is at-least-once delivery plus
    > an idempotent or deduplicating consumer. The reason is that the acknowledgement can always be lost
    > after the work was done, so the producer can't distinguish "not processed" from "processed but the
    > ack didn't arrive," and its only safe move is to retry. So the guarantee has to live in the
    > consumer.

    **Q: What would you do differently in the whole thing?**

    > Two things. Delivery semantics up front rather than discovered — idempotent consumers from the
    > beginning. And I'd have been explicit with the product side about the consistency model, because
    > "your change might take a moment to appear" is a product decision, not just an implementation
    > detail. I was making that tradeoff silently without knowing I was making it.
