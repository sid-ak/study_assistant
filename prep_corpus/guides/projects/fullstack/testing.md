# Testing

> Part of the Projects guide — [back to index](../README.md)

<a id="testing"></a>

> **Reframe this story.** You have been telling it as "a WPF app had poor test coverage and I
> improved it." That buries the lead. **The test harness existed to de-risk a protocol migration —
> Siemens' proprietary APOGEE to the open BACnet standard — and NetApp is hiring for Protocols teams
> (NFS, SMB, SAN, NVMe).** Lead with the migration; let the coverage numbers be the evidence that
> you de-risked it.

## The situation

At **Siemens** (Jun 2022 – Dec 2022, R&D), the team was **transitioning building automation systems
from APOGEE to BACnet.**

- **APOGEE** is Siemens' own proprietary building-automation protocol — their controllers, their
  ecosystem, their semantics.
- **BACnet** (Building Automation and Control Network, ASHRAE Standard 135) is the **open industry
  standard** — vendor-neutral, interoperable with third-party equipment.

**So this was a proprietary-to-open-standard protocol migration in deployed systems**, which is one
of the harder categories of change in software: the new protocol has to interoperate with equipment
that already exists, the semantics don't map one-to-one, and the installed base cannot break.

The application in question was a **.NET WPF** tool with limited automated testing — meaning the
team was about to make a high-risk semantic change with very little of a safety net. **You
identified the testing gap as the thing standing between the team and a safe migration**, and you
ramped up on **MSTest v2, WPF, and gRPC/REST patterns you hadn't used before** to close it.

## Why a protocol migration is a testing problem

This is the reasoning to have ready, because it's what makes the story relevant rather than generic:

- **Two implementations must agree on behavior.** The only way to know that a BACnet path does what
  the APOGEE path did is to pin the expected behavior down as executable assertions — a data-driven
  harness is exactly the right shape, because the _logic_ is "does the system behave correctly" and
  the _data_ is the matrix of protocol cases.
- **Semantics rarely map cleanly.** A proprietary protocol has capabilities the standard expresses
  differently, or not at all. Every one of those is a decision, and every decision is a place a
  regression can hide.
- **You cannot test against real equipment for every case.** Hence mocks and factories — they let
  you drive error paths, timeouts, and malformed responses that are nearly impossible to produce
  with real hardware in the loop.
- **Backward compatibility is non-negotiable.** Deployed buildings keep running. That's the same
  constraint a storage vendor has with a protocol version bump, where clients across many OS
  versions and vendors must keep working.

## What you built

**1. An automated data-driven test harness.** Rather than writing one test per scenario, a
data-driven harness separates the test _logic_ from the test _data_, so coverage scales by adding
cases rather than by adding code — which is precisely what a protocol behavior matrix needs. Result:
**~30% reduction in reported defects**, established through root-cause analysis sessions — i.e., the
team traced defects back and found the category the harness now caught.

**2. Integration tests with mocks and factories for gRPC and REST.** Integration boundaries are
where bugs hide, and they're the hardest to test because they require the dependency to exist. Mocks
and factories let you test the boundary behavior — including error paths and timeouts, which are
nearly impossible to trigger against a real service — deterministically. Result: **70% increase in
test coverage**, measured with coverlet.

**3. Custom JSON serializers for complex and non-generic types.** This required going into .NET
internals and serialization patterns you hadn't used. The payoff: **~95% of a product tester's
manual workflow automated** inside the existing WPF tool. That's the highest-impact item — you
removed most of a person's repetitive work and made the outcome repeatable rather than dependent on
who ran it.

**Note the serialization angle, because it's more relevant than it looks:** custom serializers for
complex and non-generic types is fundamentally a **wire-format** problem — mapping structured data
onto a transport representation and back without losing fidelity. That's the same class of problem
as the [schema bridge](../cpp/bridge.md#bridge) and as protocol encoding generally.

## Why it matters for NetApp

- **Protocol migration experience, which they are explicitly hiring for.** NFS, SMB, SAN, and NVMe
  are named teams in the posting. You have worked on a proprietary-to-standard protocol transition
  in deployed systems and can talk about interoperability, semantic mapping, and backward
  compatibility from having done it rather than from having read about it.
- **Measured impact.** 30% fewer defects, 70% more coverage, 95% of a manual workflow automated —
  with the measurement methods named (root-cause sessions, coverlet). Interviewers weight numbers
  with attribution far more than numbers alone.
- **Quality as a first-class concern.** The JD explicitly calls out collaboration with QA and
  participation in code reviews. This is your evidence that testing isn't an afterthought for you.
- **Ramping up fast.** MSTest v2, WPF, gRPC, .NET serialization internals — all new. This is your
  direct evidence for "ramps quickly on ONTAP, WAFL, protocols, or storage technologies," which is a
  literal line in the level-3 requirements.

<a id="testingstar"></a>

??? note "STAR"

    **Situation.** I joined an R&D team at Siemens that owned a .NET WPF application with very limited
    automated testing. The consequence was that defects which automation should have caught were making
    it all the way to being reported, and a product tester was spending a large share of their time on a
    repetitive manual verification workflow.

    **Task.** I decided to close that gap, even though it meant ramping up on MSTest v2, WPF, and
    gRPC/REST patterns I hadn't worked with before.

    **Action.** I built three things. First, an automated data-driven test harness that separated test
    logic from test data, so adding coverage meant adding cases rather than writing new test code —
    that's what makes a suite keep growing after the person who built it moves on. Second, integration
    tests using mocks and factories for our gRPC and REST APIs, which let me test the boundary behavior
    deterministically, including error paths and timeouts that are nearly impossible to trigger against
    a live service. Third, and the one that took the most digging, I implemented custom JSON serializers
    to handle complex and non-generic types, which meant getting into .NET serialization internals I
    hadn't touched before.

    **Result.** Reported defects dropped about 30%, which we attributed through root-cause analysis
    sessions rather than just observing a trend. Test coverage went up 70% as measured by coverlet. And
    the serializer work let me automate roughly 95% of the product tester's manual workflow directly
    inside the existing WPF tool — which was the piece I was happiest about, because it turned a process
    that depended on who ran it into one that produced the same answer every time.

<a id="testingscript"></a>

??? note "Scripts"

    ### ~55s. Use for "tell me about ramping up quickly" or "how do you think about quality."

    > I joined an R&D team at Siemens that owned a .NET WPF application with almost no automated
    > testing. The visible symptom was that defects automation should have caught were reaching the
    > reported stage, and a product tester was burning a big chunk of their week on a repetitive manual
    > workflow.
    >
    > I took it on, which meant ramping up on MSTest v2, WPF, and gRPC and REST patterns I hadn't used.
    >
    > I built three things. A data-driven test harness, so test logic and test data are separate and
    > adding coverage means adding a row rather than writing a new test — that's what determines whether
    > a suite keeps growing after you leave. Integration tests with mocks and factories for the gRPC and
    > REST boundaries, which is where the bugs actually were and which let me test error paths and
    > timeouts deterministically instead of hoping to catch them live. And custom JSON serializers for
    > complex and non-generic types, which meant getting into .NET serialization internals.
    >
    > Reported defects went down about 30%, attributed through root-cause sessions rather than just
    > observed. Coverage went up 70% by coverlet. And the serializer work let me automate about 95% of
    > that tester's manual workflow inside the tool they already used — which is the part I care most
    > about, because it turned a process that varied by who ran it into one that gave the same answer
    > every time.

<a id="testingqa"></a>

??? note "QA"

    **Q: How do you decide what to test?**

    > Risk-weighted rather than coverage-driven. I want heavy coverage where a failure is expensive and
    > the logic is non-obvious — boundaries, error paths, state transitions, anything concurrent. I want
    > much less on code that's simple and where a failure is visible immediately. Coverage percentage is
    > a useful smoke detector for untested regions but it's a terrible target on its own, because you
    > can hit a high number while testing nothing that matters. The question I actually ask is "if this
    > broke, how would we find out, and how bad would it be by then."

    **Q: How would you test a storage system differently?**

    > The failure modes are different in kind, so the testing has to be too. On top of normal unit and
    > integration testing I'd want: fault injection — kill a node, pull a disk, partition the network,
    > and verify the invariants still hold; power-loss and crash-consistency testing, because the
    > question that matters is what's on stable media at the moment of the crash; property-based testing
    > over sequences of operations, since a filesystem's correctness is about the _sequence_, not any
    > single call; long-running soak tests to catch leaks and fragmentation that don't appear in a
    > five-minute run; and performance regression testing on distributions rather than averages, because
    > a p99 regression is what generates the support case. And I'd want the sanitizers — ASan, TSan,
    > UBSan — running in CI, not just available.

    **Q: 30% defect reduction — how do you know it was your work?**

    > Because we attributed it rather than inferred it. The team did root-cause analysis sessions on
    > reported defects, and the finding was that a specific category — the ones the data-driven harness
    > now covered — largely stopped arriving. I'd be careful not to overclaim: it's an attribution from
    > a review process, not a controlled experiment, and other things changed in that window too. But
    > the category-level attribution is a lot stronger than pointing at a trend line.
