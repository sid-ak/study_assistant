# Gaps

> Part of [AI, RAG & Python](../README.md)

Written 2026-11-28 for the NVIDIA DriveOS SWE intern interview on Nov 30. These pages assume the rest
of the [AI, RAG & Python](../README.md) section has been read, so they only cover what that section
doesn't: applying RAG and agents to a release pipeline, fitting huge logs into a context window,
bounding what an agent may do, the failure modes that make an LLM untrustworthy as a gate, and the
everyday Python that algorithm practice leaves out.

Each page has the same layout:

- Why it comes up: the line in the JD or the recruiter's note that makes it likely.
- The core idea: the content itself.
- Talking points: short, standalone lines to build an answer from.
- Hooks: where it connects to the study_assistant work, the CGEE capstone, or past jobs.

Citations marked [CGEE] come from the reference library of the capstone report, *Confidence-Gated
Edge Evaluation* (Final_Report.md), quoted exactly. Citations marked [outside CGEE] are well-known
sources added here; open them before quoting them.

---

## Pages

| Gap | Time | What it covers |
|-----|------|----------------|
| [Designing an AI assistant for the release workflow](release-workflow-assistant.md) | 60 min | A release pipeline as a graph of deterministic and LLM-judged gates, and a nightly build and regression triage agent designed end to end: tools, loop, guardrails, evaluation, rollout |
| [Handling large logs and tool permissions](large-logs-and-tool-permissions.md) | Folds into the assistant design | Deterministic log reduction (extract, normalize, deduplicate, paginate) before the model sees anything, then least privilege, dry runs, idempotency, approval and audit for write tools |
| [LLM failure modes and trust](llm-failure-modes-and-trust.md) | 30 min | Non-determinism at temperature 0, judge self-inconsistency, confidence-gated evaluation as the fix, hallucination controls, prompt injection, and the metrics for a trust layer |
| [Python scripting for HackerRank](python-scripting-for-hackerrank.md) | 45 min | Two timed drills from a blank file (a log parser, a retry decorator with exponential backoff) and the scripting idioms to have at hand |
| [Python fundamentals rapid-fire](python-fundamentals-rapid-fire.md) | 20 min | One- or two-sentence answers on the GIL, copies, mutable defaults, generators, exceptions, decorators, context managers, dataclass against Pydantic, and the big-O of built-ins |
