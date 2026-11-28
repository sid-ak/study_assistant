# Cloud

> Part of the Projects guide — [back to index](../README.md)

<a id="cloud"></a>

> **Framing note — read this first.** You have been telling this as an Azure story: Bicep, Private
> Link, Key Vault, AKS. For a storage systems interviewer that's the _less_ interesting half. **The
> interesting half is the build-systems half** — why a shared cache is only _safe_ on a hermetic
> build, what content-addressing actually buys, and the difference between full and incremental
> build time. Lead with the build problem, let the cloud infrastructure be the implementation detail
> it actually was. The deep technical background is in the C++ guide under
> [BuildSys](../../cpp_deep_dive/build-toolchain.md#buildsys) and [Buildspeed](../../cpp_deep_dive/build-toolchain.md#buildspeed).

## The situation

Local **Bazel** builds were slow, and that slowness was taxing the entire team's development cycle —
every engineer paying a compile-time cost on every iteration. **You identified build latency as a
team-wide velocity problem** and decided to solve it at the infrastructure level rather than
accepting it.

The constraint: this had to happen inside a strict, federal-style security framework. Build traffic
could not touch the public internet.

## Why the build was the right thing to attack

Worth being able to justify, because "I made the build faster" invites "was that the best use of
your time?"

- **The cost is multiplied by every engineer and every iteration.** It's the one latency in an
  engineering org that everyone pays, all day.
- **The second-order effect is worse than the arithmetic.** Slow builds change behavior — people
  batch changes into larger commits, test locally less often, and context-switch while waiting. The
  real return isn't hours saved, it's that a fast build lets people work in small verifiable
  increments.
- **It was a shared bottleneck, not a personal annoyance.** That's the specific condition under
  which reaching for distributed build infrastructure is proportionate rather than over-engineering
  — it's the last item on the standard list of build-speed interventions for a reason.

## What you built

**Remote build execution and caching on Azure Kubernetes Service (AKS).** Bazel's remote execution
protocol lets build actions run on a cluster and lets a shared cache serve results across the whole
team — so a build action any engineer has already performed is a cache hit for everyone else. That's
where most of the win comes from: the marginal build stops rebuilding what someone else already
built.

**The property that makes this work, and the thing to actually say out loud.** Bazel actions are
**hermetic** — an action's output is a pure function of its explicitly declared inputs, with no
access to undeclared files or ambient environment — so the action can be **content-addressed**: hash
the inputs, the command line, and the environment, and store the output under that hash.
**Hermeticity is what makes a shared cache sound rather than merely fast.** On a non-hermetic build
a team-wide cache isn't just less effective, it's _unsafe_: you can serve an artifact built from
inputs you cannot fully account for, and you get stale-binary bugs that nobody can reproduce. The
same reasoning explains why `ccache` is a bolted-on approximation of this and Bazel is a structural
version of it.

**It also fixes incremental correctness, which is the half people forget.** Because inputs are
declared rather than sniffed from the filesystem, Bazel knows exactly what a change invalidates —
undeclared dependencies fail loudly instead of producing quietly stale output. Full build time is
fixed by caching and distribution; **incremental build time is fixed by dependency hygiene**, and
developer experience is dominated by the incremental number.

**You learned Bicep (Infrastructure as Code) to define it.** You were primarily a C++ developer; you
picked up Azure networking and IaC because the problem required it.

**Security decisions, made deliberately rather than as compliance checkboxes:**

- **Azure Private Link** — build traffic between the cluster, the cache, and the registry travels
  the Azure backbone rather than the public internet. Traffic never leaves the trusted network
  boundary.
- **Azure Key Vault** — secrets and certificates managed centrally, with access policies, rather
  than being embedded in pipeline definitions or config files.
- **Redis** as the remote build cache.

You spent extra time working directly with the security leads to ensure the design met their
internal zero-trust criteria — going to them proactively rather than waiting for a review to reject
it.

## Results

- Significantly faster CI/CD loop via remote caching and execution.
- A hardened security posture that met compliance requirements.
- A new competency you subsequently used to mentor others on the team.

## Concepts in play

Distributed build systems (Bazel remote execution, content-addressable caching, hermeticity) ·
incremental versus full build correctness · Kubernetes · Infrastructure as Code · network isolation
and private endpoints · secrets management · zero-trust architecture · developer velocity as an
engineering metric.

<a id="cloudstar"></a>

??? note "STAR"

    **Situation.** Our Bazel builds were running locally and they were slow enough to be a real drag on
    the whole team's iteration speed — everyone was paying a compile-time tax on every change. It wasn't
    anyone's assigned problem, which is partly why it had persisted.

    **Task.** I wanted to move builds to remote execution and caching on AKS so the team stopped
    rebuilding what someone else had already built. The constraint was that we operated under a strict
    security framework where build traffic couldn't touch the public internet, so I had to architect for
    that from the start rather than retrofit it.

    **Action.** I was primarily a C++ developer, so I ramped up on Bicep and Azure networking to do this
    properly. I defined the whole infrastructure as code — AKS cluster, Redis as the remote build cache,
    and the networking. On security, I made two choices deliberately rather than treating them as
    checkboxes: Azure Private Link so build traffic between the cluster, the cache, and the registry
    stays on the Azure backbone and never traverses the public internet, and Key Vault for secrets and
    certificates instead of embedding them in pipeline definitions. I went to our security leads early
    to walk them through the design against their zero-trust criteria, rather than building it and
    hoping it passed review.

    **Result.** We got a significantly faster CI/CD loop — the big win is that remote caching makes any
    build action one engineer performs a cache hit for everyone else — while meeting our compliance
    requirements. I also came out of it with a cloud infrastructure competency I hadn't had, which I
    later used to help ramp up other people on the team.

<a id="cloudscript"></a>

??? note "Scripts"

    ### ~60s. Use for "tell me about learning something new" or "tell me about improving a process."

    > Our Bazel builds were local and slow, and it was taxing everyone's iteration speed — but because
    > it was slowing everyone down a little rather than blocking anyone specifically, it wasn't
    > anybody's problem. I decided to take it.
    >
    > The plan was remote build execution and caching on AKS. The core idea with Bazel remote caching is
    > that build actions are content-addressed, so if any engineer on the team has already built a given
    > target with given inputs, it's a cache hit for everyone else. That's where the win actually comes
    > from — the marginal build stops redoing work that's already been done.
    >
    > The constraint was that we were under a strict security framework where build traffic couldn't
    > touch the public internet. I was primarily a C++ developer, so I ramped up on Bicep and Azure
    > networking to define the whole thing as infrastructure as code — cluster, Redis cache, networking.
    >
    > On the security side I made two choices deliberately. Private Link, so traffic between the
    > cluster, the cache, and the registry stays on the Azure backbone and never leaves the trusted
    > boundary. And Key Vault for secrets and certificates instead of embedding them in pipeline
    > definitions, which is the thing that always seems fine until someone forks a repo. I walked our
    > security leads through the design early rather than building it and hoping it cleared review —
    > that meant their feedback shaped it instead of blocking it.
    >
    > We got a significantly faster CI loop while staying compliant, and I picked up a cloud infra skill
    > set I later used to help ramp up other people on the team.

<a id="cloudqa"></a>

??? note "QA"

    **Q: Where did the speedup actually come from — the cluster or the cache?**

    > Predominantly the cache. Remote execution helps with parallelism on a big clean build, but the
    > day-to-day win is that Bazel's actions are content-addressed, so any target already built with
    > identical inputs is a cache hit for everyone. Most of an engineer's rebuilds after a small change
    > are things somebody else already compiled. That's why the caching layer was the piece I cared most
    > about getting right.

    **Q: Why Bazel rather than CMake or Make?**

    **Don't defend Bazel as universally better — name the axis and evaluate.** The disclosure that it
    predated you is a strength here, not a weakness: it lets you assess the decision rather than
    advocate for your own.

    > That predated me as a team decision, and I'd defend it — but I'd also say it's not that one is
    > better, they optimize for different things. The deciding axis is whether you need a build you can
    > _trust_ or a build that's _convenient_.
    >
    > Bazel's hermeticity is what makes remote caching sound rather than merely fast. If an action's
    > output is a pure function of its declared inputs, then a cache hit is provably the same artifact.
    > On a non-hermetic build a shared cache isn't just less effective, it's unsafe — you can serve
    > something built from inputs you can't account for, and you get stale-binary bugs nobody can
    > reproduce. It also means incrementality is correct: undeclared dependencies fail loudly instead of
    > producing quietly stale output. So if the problem is "this monorepo takes too long to build across
    > a team," Bazel is answering exactly that question.
    >
    > The cost is real though. Every third-party C++ library ships CMake, not Bazel, so you're writing
    > `BUILD` files or leaning on `rules_foreign_cc` for dependencies you'd otherwise get for free. The
    > toolchain and platform configuration is verbose. And it's infrastructure somebody has to own. For
    > a smaller project, or one that lives mostly on external dependencies, CMake plus Ninja plus
    > `ccache` gets you most of the practical benefit with none of the adoption cost. I'd reach for
    > Bazel when the build is a shared bottleneck across many engineers and the repo is big enough that
    > correct incrementality actually matters — which was true where I used it. I wouldn't introduce it
    > to a codebase of ten libraries.

    **Q: What did Bazel give you for cross-compilation specifically?**

    > One build graph producing both x86-64 and ARM64 artifacts in the same invocation, with correct
    > per-target caching, via platforms and toolchain resolution rather than a separate configured build
    > tree per target. That mattered because we were shipping to the embedded ARM64 unit and also
    > building and testing on x86-64 developer machines — with CMake that's two configured build
    > directories and a toolchain file, which works but doesn't share a cache cleanly.

    **Q: If our full build takes forty minutes, what would you do?**

    > Ask which number actually hurts first — full or incremental — because they're different problems.
    > Then measure rather than guess: `-ftime-trace` per translation unit, and the critical path through
    > the build graph. Usually it's one or two headers included nearly everywhere.
    >
    > After that, in order of return on effort: switch the linker to `lld` or `mold`, which is often
    > several-fold for a one-line change; add `ccache` if the build isn't already content-addressed;
    > then cut includes — forward declarations, PIMPL at boundaries, moving template instantiations into
    > a single translation unit. Distribution and remote execution come last, because they're the
    > heaviest intervention and they mostly help full builds, not the incremental loop that dominates
    > how the day actually feels.
    >
    > The thing I'd insist on is that a fast build which is occasionally wrong is worse than a slow
    > build that's always right — once "try a clean build" becomes folklore, people stop trusting the
    > tooling.

    **Q: Why Private Link instead of just a firewall rule or a VPN?**

    > A firewall rule still means the traffic transits the public internet with a policy allowing it —
    > you're trusting the policy. Private Link gives the service a private IP inside your VNet, so the
    > traffic goes over the Azure backbone and there's no public path at all. It's an architectural
    > guarantee rather than a configuration one, which is a meaningfully different security posture and
    > much easier to defend in a compliance review. A VPN would work but adds a network hop and an
    > operational component to maintain.

    **Q: How did you learn Bicep quickly?**

    > I had a concrete target, which is most of it — I wasn't learning Bicep in the abstract, I was
    > defining one specific architecture. I started from the Azure quickstart templates for AKS, then
    > rewrote them piece by piece as I understood what each block was actually doing, rather than
    > copying and hoping. The security review was a forcing function for real understanding: you can't
    > answer "why is this network configured this way" from a template you pasted. And I read our
    > security leads' criteria first, so I knew what the design had to satisfy before I started writing
    > it.

    **Q: How do you think about developer velocity as an engineering investment?**

    > As compound interest. A build that's two minutes slower doesn't sound like anything, but multiply
    > it by every engineer, every iteration, every day, and it's substantial — and the second-order
    > effect is worse than the arithmetic. Slow builds change _behavior_: people batch changes into
    > bigger commits, they test less often locally, they context-switch while waiting. So the real
    > return isn't the hours saved, it's that a fast build lets people work in small, verifiable
    > increments. That's the argument I'd make to justify the time.
