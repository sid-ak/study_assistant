# Designing an AI assistant for the release workflow

> Part of [Gaps](README.md) in [AI, RAG & Python](../README.md)


## Why it comes up

The JD's first bullet is "Build AI assistant tools and agentic workflows that raise the quality of DriveOS software releases." The recruiter named "LLM tool design for SW engineering use-cases." The likeliest open-ended question is some version of *"How would you build an AI tool to help our release process?"* Your prep site explains RAG and agents in general, but doesn't apply them to a release pipeline.

## The core idea: a release pipeline is a graph of gates

A release moves through stages, and a **gate** between stages decides whether work moves forward. Examples:

- Does the build pass on every target?
- Is this test failure a real regression, a flaky test, or an infrastructure problem?
- Which commit introduced the regression?
- Is the release candidate ready to promote?

Some gates are **deterministic**: an exit code or a pass/fail count gives the same answer every time. Others need **judgment**, such as reading a 40,000-line log and deciding what went wrong. Engineers spend their time on those judgment gates, so that's where an AI assistant helps.

This is the same picture as your capstone. Attractor-style pipelines have nodes (phases of work) connected by edges, and some edges are judged by an LLM. You already have the vocabulary for it: **deterministic gates vs. LLM-judged gates**, and **typed predicates vs. natural-language conditions**.

## A concrete design: nightly build and regression triage agent

Pick one use case and design it end to end. Triage is a strong choice because it's high-volume, eats engineer time, and is easy to measure.

**Problem.** Every nightly run produces failures. An engineer has to read logs, decide what kind of failure each one is, find the suspect commit, and file or route a bug. That's slow and repetitive, and two engineers might reach different conclusions.

**What the assistant produces.** For each failure, a structured triage report:

??? note "The triage report type"

    ```python
    from dataclasses import dataclass
    from enum import Enum

    class Category(Enum):
        REGRESSION = "regression"        # code change broke it
        FLAKY = "flaky"                  # passes on rerun with no code change
        INFRA = "infra"                  # machine, network, license, disk
        UNKNOWN = "unknown"              # not confident: escalate to a person

    @dataclass(frozen=True)
    class TriageReport:
        failure_id: str
        category: Category
        suspect_commits: list[str]       # commit SHAs, ranked
        evidence: list[str]              # ids of exact log lines and test results
        confidence: float                # from token logprobs, not self-reported
        needs_human: bool
    ```

**Data sources.**

- Build and test logs
- Test result history: how often has this test failed recently, and did it pass on rerun?
- `git log` and `git diff` between the last good and the first bad build
- The bug tracker: has this signature been seen before, and what fixed it?
- Docs and runbooks (this is where your RAG system fits)

**Tools.** Every tool does one thing, and every tool is read-only:

| Tool | Returns |
|------|---------|
| `get_failure_summary(run_id)` | Failing tests and the first error from each, already parsed |
| `get_log_window(run_id, line, before, after)` | A small slice of a log around one line |
| `get_test_history(test_id, days)` | Pass/fail history and rerun outcomes |
| `diff_commits(good_sha, bad_sha, paths?)` | Changed files and commit messages between two builds |
| `search_known_issues(signature)` | Matching past bugs and their fixes (RAG) |

**Agent loop.** This is a bounded state graph, like your LangGraph agent:

1. Parse deterministically (see [large logs and tool permissions](large-logs-and-tool-permissions.md)). Many failures get classified with no LLM at all. A license-server timeout is INFRA, and a test that already passed on rerun is FLAKY.
2. For what's left, the LLM looks at the error, the diff and the known issues, then proposes a category and suspect commits.
3. Gate the LLM's decision (see [LLM failure modes and trust](llm-failure-modes-and-trust.md)). Accept confident calls, recheck uncertain ones, and escalate the rest to a person.
4. Write the report with citations to the exact log lines and commits, the way study_assistant cites chunk ids.
5. A person approves before anything leaves the system, such as filing a bug or pinging an owner.

**Guardrails.**

- The agent only reads. Filing a bug or reverting a commit is a separate write tool, and it requires approval (see [large logs and tool permissions](large-logs-and-tool-permissions.md)).
- There's a hard step limit and a token budget, so the loop can't run away.
- Every decision is logged with its inputs, so you can audit it later. That matters in a safety-certified process.

**Evaluation.**

- **Golden set:** past failures that engineers already triaged. The labels come from history, so they're free.
- **Per-category precision and recall.** For a release gate, a missed REGRESSION is much worse than a false alarm, so recall on REGRESSION matters most.
- **Suspect-commit accuracy:** was the real culprit in the top 1, or the top 3? (That's Recall@K again, which you already know.)
- **Escalation rate:** how much work still lands on people.
- **Engineer acceptance rate:** how often the human approves the report without changes.
- **Time to triage:** before vs. after.
- **Cost:** model calls and tokens per failure.

**Rollout.**

1. **Shadow mode:** the agent runs, but only you see its output. Compare it to what engineers actually decided.
2. **Suggest mode:** engineers see the report and accept or fix it. Their fixes become new golden-set labels.
3. **Limited automation:** auto-apply only the categories with proven precision, such as obvious INFRA failures, and keep escalation for everything else.

## Talking points

- "I'd start with the most repetitive judgment in the pipeline, which is usually failure triage, not the most impressive one."
- "Deterministic first. If an exit code or a rerun can answer it, the LLM never sees it."
- "The model proposes and a person approves. Read and write tools are separate."
- "I'd build the eval set from past triage decisions before I build the agent. That's how I built study_assistant: the harness came first, and every component had to beat a measured baseline."
- "I'd roll it out in shadow mode first, so we measure it against real engineers before anyone relies on it."

## Hooks

- **Flaky tests are a known research area.** Luo et al. analyzed 201 commits that fixed flaky tests across 51 open-source projects. They classified root causes such as asynchronous waits, concurrency and test-order dependency. Your capstone uses this as the precedent for treating "same input, different result" as a defect you can detect and attribute. **[CGEE]** Luo, Q., Hariri, F., Eloussi, L., & Marinov, D. (2014). An empirical analysis of flaky tests. *FSE 2014*, 643–653. https://doi.org/10.1145/2635868.2635920
- **Why catching defects early matters:** post-delivery fixes are often 100 times more expensive than fixes made during requirements and design, though closer to 5:1 for small, noncritical systems. **[CGEE]** Boehm, B., & Basili, V. R. (2001). Software defect reduction top 10 list. *IEEE Computer, 34*(1), 135–137. https://doi.org/10.1109/2.962984
- **study_assistant:** it's the `search_known_issues` tool in this design. It was built for exactly this question: "I've seen this failure before, what fixed it?"
- **Bridge and the Sync pipeline:** you've already built automation that maps dependencies and verifies generated output. Same instinct.
