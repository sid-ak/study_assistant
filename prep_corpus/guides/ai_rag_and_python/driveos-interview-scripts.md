# DriveOS interview scripts v2: NVIDIA answer, stories, standards, questions

> Part of [AI, RAG & Python](README.md)

## The through-line (40 s)

**Use for:** "walk me through your background", "why are you a fit", or as the closer to any story when they ask how it relates.

> Most of my work at Toyota was on a safety-relevant ADAS stack, and the lesson I took from it is that standards like ISO 26262 and ISO/SAE 21434 aren't an audit at the end. They have to be built into the workflow. That means catching interface errors at build time instead of in the field, making builds reproducible from a known baseline, giving every device its own identity, and measuring timing on the real target without disturbing it. I've shipped a project for each of those. And it's what an AI assistant for DriveOS releases has to respect too: it's a tool inside a safety workflow, so what it produces has to be verifiable.

| Pillar | The idea in plain words | Your stories | Standard (say the name, not the clause) |
| --- | --- | --- | --- |
| Catch errors at build time | A mismatch should fail the build, not the vehicle | Bridge generator, CRTP ORM | ISO 26262 Part 6 (strong typing, coding guidelines); Part 8 tool confidence for the generator |
| Reproducible, isolated builds | Every release can be identified and rebuilt from a controlled baseline | Bazel remote build, Sync pipeline | ISO 26262 Part 8 configuration management; ISO/SAE 21434 configuration and tool management |
| Unique device identity | Every device proves who it is before it talks | IoT Edge provisioning | ISO/SAE 21434 design and production requirements |
| Measure without disturbing | Timing and resource evidence from the real target | OTel, localization tracker | ISO 26262 Part 6 software verification (timing, resource usage, freedom from interference) |
| Executable verification | The same check gives the same answer whoever runs it | Siemens test harness | General verification practice (Siemens wasn't automotive) |

## Bridge code generator: verify the generator's output (90 s)

**Use for:** problem solving, Python, automation, cross-team work. Pairs with Course Schedule (207/210) if they ask about topological sort.

> **[Problem]** At Toyota our services team defined data models in .NET, exposed through Swagger, and the ADAS team needed the same models as memory-aligned C++ structs. They synced them by hand, so every schema change was a chance for the two sides to disagree on byte layout. That doesn't fail loudly. It shows up as corrupt data in integration.
>
> **[Action]** After talking to the leads on both teams, I wrote a Python tool that generates the C++ structs from the Swagger models on every build. The hard part was ordering. C++ needs a type fully defined before it's used by value, and the schemas came in arbitrary order. So I built a dependency graph and did a depth-first topological sort, with cycle detection that fails the build and prints the cycle.
>
> **[Verification]** Because the generator writes production code, I didn't want anyone to have to trust it. It also emits `static_assert` checks on every struct's size and field offsets, so if the compiler disagrees with the generator, the build fails.
>
> **[Result]** It became the single source of truth and ended the recurring integration failures.
>
> **[Standards and DriveOS]** In ISO 26262 terms, a tool that generates code can introduce errors, so you either qualify the tool or verify its output downstream. I chose to verify the output. That's how I'd treat an AI tool in the DriveOS release flow: don't trust the generator, check what it produces.

## CRTP ORM: make schema drift a compile error (70 s)

**Use for:** a disagreement with a senior engineer, C++ depth, "a design decision you defended".

> **[Problem]** I was building the storage layer for ADAS localization data on TimescaleDB. A senior lead wanted hand-written SQL strings, which are quicker to start with, but they make the schema a runtime contract. A renamed column or a changed type becomes a failure in a vehicle, not a build error.
>
> **[Action]** Rather than argue style, we first agreed the real risk was runtime failures from schema drift. Then I built a prototype: a CRTP base class, so a developer describes a record type once and the column list, the SQL and the row mapping all derive from it, with `static_assert` checks that every field has a valid SQL type. I showed him a type mismatch failing the build that raw SQL would have hidden until deployment, benchmarked it to show no runtime cost, and answered his maintainability concern with a GoogleTest suite.
>
> **[Result]** He agreed, we shipped it cross-compiled for x86 and ARM64, and runtime SQL errors in localization storage dropped to near zero.
>
> **[Standards and DriveOS]** Safety standards prefer strong typing and catching interface errors statically over defensive checks at runtime. I'd want the same from release tooling: make the wrong thing fail the build.

Be ready for: "Compile time can't see the live database, so how did you catch drift against it?" You didn't have a live-schema check, so say so: "The type system guarantees that the C++ record, its SQL and its row mapping always agree with each other. We didn't check against the deployed schema, so drift there would still surface at runtime. The next step I'd add is a startup or CI check that compares each record against the database's information_schema."

**[GUESS]** Your prep plan says Boost.Describe and the older notes say "Boost Reflection". Use one name consistently; Boost.Describe is the actual library name.

## Bazel remote build: reproducible from a controlled baseline (85 s)

**Use for:** build systems, Linux, CI, developer velocity. The JD names build systems, so this one matters.

> **[Problem]** Our Bazel builds ran on developer machines, for x86 and ARM64, and everyone paid a compile tax on every change. It wasn't anyone's job, so I took it.
>
> **[Action]** I provisioned Bazel remote caching and remote execution on Azure Kubernetes Service, all defined in Bicep. The constraint was that build traffic couldn't touch the public internet, so the cluster, cache and registry sat behind Private Link, secrets lived in Key Vault, and I walked our security leads through the design before I built it.
>
> **[Insight]** What makes a shared cache safe is that Bazel is hermetic and content-addressed. Each action is keyed by a hash of its exact inputs, so a cache hit is the same result, not a guess. A fast build that's sometimes wrong is worse than a slow one.
>
> **[Result]** Anything one engineer built became a cache hit for everyone and for CI, inside our compliance rules. I didn't keep a clean before-and-after measurement, and that's the one thing I'd do differently: track cache hit rate and median CI time from day one.
>
> **[Standards and DriveOS]** Safety and cybersecurity standards both ask that every released build be uniquely identified and reproducible from a controlled baseline, with the build environment protected from tampering. Content-addressed builds on an isolated network are a practical way to get there. And it's the base an AI release assistant stands on: if the build isn't reproducible, nothing the agent reports about it can be trusted.

Careful with your note's phrase "cryptographic proof that a flashed binary can be reproduced". The standards ask for unique identification and controlled reproduction. Hashes and signing are how teams usually show it, but the standards don't say "cryptographic". Also, Bazel's content addressing doesn't by itself give bit-for-bit reproducible binaries: timestamps, build stamping and non-hermetic toolchains can still differ. Claim "reproducible inputs and correct caching", not "bit-identical binaries", unless you verified that.

## Sync pipeline: every dependency known, every side effect mapped (80 s)

**Use for:** scripting, CI/CD, a mistake you owned, ambiguity.

> **[Problem]** Teams shared library dependencies across many Azure DevOps repositories, synced by hand by different people at different times. Drift showed up as confusing build failures downstream.
>
> **[Action]** I replaced that with a multi-stage Azure Pipelines workflow that runs weekly. The sync logic drives the `az` CLI and uses bare git clones, so there's no working tree for a step to change. Two things bit me. Azure has an undocumented limit of 20 repositories per pipeline YAML, so past that I generated extra YAML dynamically. And after rollout, work items started closing on their own. Synced commits contained hashtags that Azure DevOps reads as commands to resolve work items. That was mine to own: I found the API setting and had the pipeline turn auto-resolve off during the sync and restore it after.
>
> **[Result]** Weekly runs, no manual steps, and the dependency drift ended. I documented the hashtag case for the DevOps team.
>
> **[Standards and DriveOS]** A certified release needs every dependency in its baseline known and traceable. And automation that touches shared systems needs its side effects mapped and guarded, which is the read-only versus write question I'd ask about any agent in the release pipeline.

## IoT Edge provisioning: unique identity for every device (60 s)

**Use for:** security, automation, working with other teams.

> **[Problem]** Onboarding a vehicle's IoT devices took hours of manual configuration, and the result depended on who did it. These devices live outside a controlled network, so shared keys weren't acceptable.
>
> **[Action]** I automated it with Azure IoT Edge and the Device Provisioning Service. Each device enrolls zero-touch with its own X.509 certificate, managed through Azure Key Vault, so it has a unique identity that can be revoked on its own. The devices were nested, gateways managing sub-devices, so deployments roll out parent first, then children, and nothing is left pointing at a gateway that isn't ready. I brought in our security and hardware teams early.
>
> **[Result]** Onboarding went from hours to a single script, and every vehicle left with a verified configuration.
>
> **[Standards and DriveOS]** ISO/SAE 21434 treats provisioning unique credentials in production as a cybersecurity requirement. It's the same pattern as giving every ECU its own identity so components authenticate each other. And the ordering rule carries over to releases: a half-applied rollout is worse than none.

**Resolved:** keys were managed in Azure Key Vault. So say "per-device certificates managed through Key Vault", not "hardware-backed". Hardware-backed means the key never leaves a chip on the device (a TPM or secure element). Expect the follow-up "where did the key sit on the device itself?", because a device needs its key locally to authenticate. **[GUESS]** If it was a file deployed by the provisioning script, say that, and add: "For production vehicles I'd move it into a TPM or secure element, which is what ECUs do."

## OTel: measure on the target without disturbing it (90 s)

**Use for:** most proud of, hardest bug, multi-threading, Linux.

> **[Problem]** At Toyota I worked on a multi-threaded C++ ADAS stack on ARM64 Yocto Linux. When a frame ran late or two threads disagreed, all we had were unstructured logs, and diagnosing one issue could take days. Nobody on the team, including me, had used OpenTelemetry.
>
> **[Action]** I built a C++ library over the OpenTelemetry SDK with one hard rule: measuring must not disturb what's measured. Spans are RAII-scoped so they close on every exit path, the hot path uses atomics instead of locks, and a full queue drops and counts spans rather than blocking a real-time thread. I cross-compiled the Collector for ARM64 and built it into the vehicle's Yocto image.
>
> **[Bug]** During rollout we got a crash only at shutdown that vanished under a debugger. Statics were being destroyed while worker threads still emitted spans. A Meyers singleton fixed initialization order, not destruction order. A weak-pointer singleton, where each caller holds ownership while it uses the provider, fixed it.
>
> **[Result]** Multi-threaded debugging went from days to minutes, and it became the company-wide observability standard.
>
> **[Standards and DriveOS]** ISO 26262 asks for timing and resource evidence measured on the target, and for showing that non-critical work can't starve safety tasks. My library was a debugging tool, not a certified safety mechanism, but it produces the same kind of evidence. That's the evidence an AI release assistant should be reading, and on DriveOS the same problem gets harder across CPU threads, CUDA streams and hardware engines.

Keep the "debugging tool, not a certified safety mechanism" clause. Your notes map OTel to the error-detection mechanisms table, but those are runtime safety mechanisms inside the product. Claiming your telemetry satisfies them would invite a hard follow-up.

### Alternate: localization tracker (45 s)

**Use for:** release decisions, full-stack work, a second measurement story.

> To improve our ADAS positional and orientation accuracy, I built a full-stack app that ingested real-time localization data over SignalR and drew it on a map against ground truth, in .NET, Angular and Leaflet. Engineers used it to see exactly where the estimate drifted and correct it, and stakeholders used it to make release decisions. The lesson I'd bring to DriveOS: a release decision should rest on a measurement against a known reference, not on someone's impression of a test drive.

## Siemens test harness: the same answer whoever runs it (75 s)

**Use for:** testing, quality, internship experience, measurable impact.

> **[Problem]** At Siemens I interned on an R&D team moving building-automation systems from Siemens' proprietary APOGEE protocol to the open BACnet standard. The .NET tool at the center had little automated testing, and the migration changed behavior in buildings that were already deployed.
>
> **[Task]** I saw it as a verification problem: the only way to know the BACnet path behaves like the APOGEE path is to pin the expected behavior down as executable cases.
>
> **[Action]** I built a data-driven .NET test harness that separates test logic from test data, so new coverage means adding a row, not writing code. I added gRPC and REST integration tests with mocks, so error paths and timeouts were deterministic instead of depending on live equipment. And I wrote custom C# JSON serializers for complex non-generic types, which let me automate the manual regression workflow.
>
> **[Result]** Over my last two to three months, reported defects dropped about 30 percent. Test coverage went from about 10 percent to about 80 percent, and about 95 percent of manual regression testing was automated.
>
> **[DriveOS]** The part I liked most is that the result stopped depending on who ran it. That's what you want from every gate in a release pipeline.

**Resolved:** coverage went from about 10 to about 80 percent, which is 70 points. That's stronger than the resume's "by 70%", which most readers take as 10 to 17. Say "from about 10 to about 80 percent" out loud, and consider changing the resume bullet to match. The 30 percent defect drop was measured over your last two to three months, compared through root-cause sessions.

## If they ask about the standards directly (45 s)

**"What do you know about ISO 26262 and ISO/SAE 21434?"**

> ISO 26262 is functional safety: the vehicle has to stay safe when hardware or software fails. ISO/SAE 21434 is cybersecurity: the vehicle can't be compromised by an attacker. The thing I've learned is that neither is an audit at the end. They show up in everyday engineering: configuration management so every build can be identified and reproduced, strong typing and static checks, verification on the target, and confidence that your tools don't introduce errors. That last one matters most for this role, because an AI assistant in the release pipeline is itself a tool, so its output has to be verified or the tool has to be qualified.

**"Have you worked under ISO 26262?"** You aren't sure which standard your work fell under, so don't guess in the room. ISO 26262 covers road vehicles, and forklifts are industrial trucks, which have their own safety standards. Say: "Not in a formally certified ISO 26262 program. Forklifts are industrial trucks, so they fall outside 26262's road-vehicle scope. But the ADAS work was safety-relevant, and I've studied how 26262 maps to the practices I used, which is why I framed it that way." That's honest and still shows you did the homework. Only name a specific forklift standard if you've checked it.

## Three questions for the interviewer

Pick by interviewer: an engineer gets 1 or 2, a manager gets 3.

1. **Bottleneck.** "Where does a DriveOS release lose the most time today: triaging test and build failures, assembling safety evidence, or approvals? And how would you know if an AI tool actually shortened it?"
2. **Tool confidence.** "If an AI assistant's output feeds a DriveOS release, does the team treat it as a software tool under ISO 26262 Part 8, with its own confidence level, or keep it advisory and verify everything it produces? Where's the line between what it does alone and what needs sign-off?"
3. **Success.** "What would a great outcome for this internship look like: a tool running in the real release pipeline, or a measured prototype with recommendations? And who would use it day to day?"

Question 2 is your strongest. It shows you know the standard, you've thought about agent guardrails, and it ties straight to your Bridge story.

## Citation check on your notes

I can't open the standards themselves (they're paywalled), so this is from memory of the 2018 edition of ISO 26262 and the 2021 ISO/SAE 21434. Treat it as a reason not to quote numbers, not as the final word.

| Your note | My read | Confidence |
| --- | --- | --- |
| ISO 26262-8 Clause 7, configuration management: work products uniquely identified and reproduced in a controlled manner | Right clause. Your wording is close to the objective but not verbatim, so don't put it in quotes. | High |
| ISO 26262-8 Clause 11, confidence in the use of software tools | Right clause, and the best link in your notes. | High |
| ISO 26262-6 Table 6, 1d "Use of strong typing" | I recall strong typing as Table 1 (modelling and coding guidelines), method 1c, with 1d as defensive implementation techniques. | Medium |
| ISO 26262-6 Table 6, 1f "No implicit type conversions" | Table 6 is right, but I recall it as 1g (1f is restricted use of pointers). | Medium |
| ISO 26262-6 Table 4, "temporal monitoring" and range checks | The 2018 edition reorganized Part 6's tables, and "temporal monitoring" reads like a hardware-side mechanism. I wouldn't cite this one. | Low |
| ISO 26262-6 Clause 9, resource usage evaluation and freedom from interference | Resource usage evaluation as an integration verification method sounds right. Freedom from interference is a real concept, but it's defined in Part 1 and covered in Part 6 Annex D. | Medium |
| ISO/SAE 21434 Clause 5.4.6, configuration management | Clause 5.4 is organizational cybersecurity management, but I'm not sure 5.4.6 is the configuration management item. | Low |
| ISO/SAE 21434 Clause 10 (product development) and Clause 12 (production) | The clause topics are right. I can't confirm the exact quoted phrases. | Medium |

The safe way to say any of these: "ISO 26262 Part 8's configuration management and tool confidence requirements" or "21434's production requirements for unique credentials". Naming the part and the idea shows you've read it. A wrong table number in front of a safety engineer costs more than it earns.

## Open guesses to resolve

Updated Nov 27 with your answers:

- Bazel: resolved. The script now uses the "didn't measure" line.
- ORM: resolved. No live-schema check, and the CRTP ORM script has the follow-up answer.
- IoT: resolved to Key Vault. One follow-up is left: where the key sat on the device.
- Toyota standard: resolved. The standards script has an answer that doesn't depend on knowing it.
- NVIDIA facts: researched and fixed in the opening script. The big correction is Linux or QNX, not both.
- Siemens: resolved. Coverage went from about 10 to about 80 percent, and the defect drop covered your last two to three months.
