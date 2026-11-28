# Tracker

> Part of the Projects guide — [back to index](../README.md)

<a id="tracker"></a>

## The situation

Validating ADAS localization required engineers to see, live, where the vehicle believed it was and
what its sensors were reporting. Without that, debugging a localization issue meant correlating logs
after the fact.

## What you built

A full-stack real-time vehicle and environment tracking system, from scratch:

- **.NET + Entity Framework** — backend and persistence.
- **SignalR** — real-time push of pose and sensor data to connected clients (WebSocket-based, with
  fallback), rather than polling.
- **Angular** — front end, including RxJS for reactive stream handling.
- **Leaflet** — map visualization of vehicle pose and sensor data.
- Supporting infrastructure: Azure Pipelines CI/CD standardizing tests, coverage, and linting, with
  metrics surfaced in **Prometheus and Grafana**.

Engineers could watch vehicle pose and sensor data live and debug localization issues far faster
than by post-hoc log correlation.

## Why it's useful for this interview

It's your **versatility and product sense** story. It shows you can build the tool that makes a hard
problem tractable, not just the system being debugged — which is thematically the same instinct as
the OTel work. It also demonstrates you pick up unfamiliar technologies (SignalR, Leaflet, RxJS,
Prometheus/Grafana) and integrate them into something cohesive.

Use it sparingly in a systems interview — it's the least relevant to storage internals — but it's a
strong answer for "tell me about breadth," "tell me about learning quickly," or "have you built
tooling for other engineers."

<a id="trackerstar"></a>

??? note "STAR"

    **Situation.** Our engineers were validating ADAS localization by correlating logs after the fact —
    there was no way to watch what the vehicle believed about its own position while it was happening.
    That made localization bugs slow and frustrating to chase, because you were always reconstructing
    the past rather than observing the present.

    **Task.** I decided to build the tool that made the problem visible: a real-time system where an
    engineer could watch vehicle pose and sensor data on a live map while a test was running.

    **Action.** I built it end to end. .NET with Entity Framework for the backend and persistence,
    SignalR to push pose and sensor updates to the browser in real time rather than polling, and Angular
    with RxJS on the front end feeding a Leaflet map for the visualization. I also built the surrounding
    infrastructure — Azure Pipelines CI/CD standardizing our tests, coverage, and linting, with metrics
    surfaced through Prometheus and Grafana. Several of these were technologies I hadn't used before, so
    I had to pick up SignalR, Leaflet, and the Prometheus/Grafana stack quickly and integrate them into
    something coherent rather than bolted together.

    **Result.** Engineers could see vehicle pose and sensor data live and debug localization issues
    substantially faster than by post-hoc log correlation. It's the same instinct as the observability
    work I did later — the highest-leverage thing you can build is often the thing that makes the real
    problem visible.

<a id="trackerscript"></a>

??? note "Scripts"

    ### ~45s

    > Engineers validating our ADAS localization were debugging by correlating logs after a test run —
    > reconstructing what the vehicle thought was happening, rather than watching it. That's slow, and
    > it means you often can't tell whether what you're seeing is a localization bug or a logging
    > artifact.
    >
    > I decided to build the thing that made it visible: a real-time tracking system where you could
    > watch vehicle pose and sensor data on a live map during a test.
    >
    > I built it end to end — .NET and Entity Framework on the backend, SignalR to push updates to the
    > browser in real time instead of polling, Angular with RxJS on the front, and Leaflet for the map.
    > I also set up the CI/CD around it with Azure Pipelines, and surfaced metrics through Prometheus
    > and Grafana. A few of those I hadn't used before, so there was a real ramp.
    >
    > It made localization debugging dramatically faster. And in hindsight it's the same instinct as the
    > telemetry work I did later — the highest-leverage thing to build is often not a fix, it's the
    > thing that makes the actual problem visible.

<a id="trackerqa"></a>

??? note "QA"

    **Q: Why SignalR instead of polling or plain WebSockets?**

    > Polling was wrong for the use case — pose data updates fast, and polling either lags behind or
    > hammers the server. SignalR gave me the real-time push semantics I wanted with connection
    > management, automatic reconnection, and transport fallback handled, and it integrated directly
    > with the .NET backend that already existed. Raw WebSockets would have meant reimplementing
    > reconnection and backpressure myself for no benefit.

    **Q: How did you handle the data rate?**

    > The main lever was not sending everything. Pose updates at full sensor rate are far more than a
    > human can perceive on a map, so throttling on the server side and letting the client interpolate
    > gave the same visual fidelity at a fraction of the traffic. RxJS on the client made that easy to
    > reason about — you can express "sample this stream at 10Hz" declaratively rather than managing
    > timers.

    **Q: What does this have to do with storage?**

    > Directly, not much — I'd be honest about that. Thematically, it's the same instinct that drove the
    > telemetry work: when a system is hard to debug, the leverage is often in building the
    > observability rather than in the fix. And building tools other engineers depend on daily teaches
    > you something about interface design that building a service doesn't — if it's awkward, they stop
    > using it, and then it may as well not exist.
