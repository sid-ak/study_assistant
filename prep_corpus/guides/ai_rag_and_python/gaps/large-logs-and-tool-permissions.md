# Handling large logs and tool permissions

> Part of [Gaps](README.md) in [AI, RAG & Python](../README.md)


## Why it comes up

As soon as you say "the agent reads build logs," a good interviewer asks: "Our logs are huge. How do you fit that in a context window?" Then: "What stops the agent from doing something destructive?" The prep plan calls out both: log truncation and pagination, and read-only vs. destructive tools with dry runs.

## Part A: getting large logs into a small context

**The problem.** A full build log can be millions of tokens. You can't send it all, and even if you could:

- It's slow and expensive.
- Models use information in the middle of a long context less reliably than information near the start or end. **[outside CGEE]** Liu, N. F., et al. (2024). Lost in the middle: How language models use long contexts. *Transactions of the ACL, 12*. arXiv:2307.03172.

**The rule: reduce deterministically, then let the model reason over what's left.**

1. **Extract with regex.** Pull out lines that match error signatures, such as `error:`, `FAILED`, `Segmentation fault` or `undefined reference`, along with file:line locations.
2. **Normalize, then deduplicate.** Replace timestamps, hex addresses, temp paths and PIDs with placeholders, so 500 copies of the same error collapse into one signature with a count.
3. **Keep the first error.** In a compiler or build log, the first error usually causes the rest. Keep it in full and summarize the cascade.
4. **Head and tail.** If you must cut, keep the start (configuration, versions) and the end (the final failure), and drop the middle.
5. **Paginate with a cursor.** Tools return a page and a `next_cursor`, and the model asks for more only if it needs it. That's the same idea as "small results" in your tool-design notes.
6. **Map-reduce summarization.** For a log that's still too long, summarize chunks separately (map), then summarize the summaries (reduce). It costs more calls, so it's a last resort.

??? note "Reducing a log to its first error and top signatures"

    ```python
    import re
    from collections import Counter

    ERROR = re.compile(r"(?P<file>[\w./-]+):(?P<line>\d+):\d*:?\s*error:\s*(?P<msg>.+)")
    NOISE = [
        (re.compile(r"0x[0-9a-fA-F]+"), "<ADDR>"),
        (re.compile(r"\d{4}-\d{2}-\d{2}[T ][\d:.]+"), "<TS>"),
        (re.compile(r"/tmp/\S+"), "<TMP>"),
    ]

    def signature(msg: str) -> str:
        for pattern, placeholder in NOISE:
            msg = pattern.sub(placeholder, msg)
        return msg

    def summarize_errors(lines, limit=20):
        """Return the first error in full plus the top signatures with counts."""
        first, counts = None, Counter()
        for line in lines:                     # works on a generator: never loads the whole file
            m = ERROR.search(line)
            if m:
                first = first or m.groupdict()
                counts[signature(m["msg"])] += 1
        return {"first_error": first, "top": counts.most_common(limit)}
    ```

**Talking points**

- "I never send a raw log to the model. A parser turns it into a short, structured summary first, and the model reasons over that."
- "Deduplication by normalized signature is the biggest win, because most of a failing log is the same error repeated."
- "Tools return pages with a cursor, so the context stays small and the model pulls more only when it needs to."

## Part B: what the agent is allowed to do

**Separate read tools from write tools.** Read tools (get a log, get a diff, search bugs) are safe to call freely. Write tools (file a bug, rerun a job, revert a commit, block a release) change the world.

| Control | What it means |
|---------|---------------|
| **Least privilege** | The agent's credentials can only do what its tools need. A triage agent gets read-only tokens. |
| **Dry run** | Every write tool has `dry_run=True` by default. It returns what it *would* do, and a person sees that before anything happens. |
| **Human approval** | A write runs only after a person approves the dry-run output. That's your LangGraph checkpoint: pause, persist state in Postgres, resume on approval. |
| **Idempotency** | Calling a write twice has the same effect as calling it once, for example by passing an idempotency key or checking "does this bug already exist?" first. Retries and resumed runs then can't create duplicates. |
| **Allow lists and bounds** | Arguments are validated by the schema (enums, ranges). The agent can't pass a branch name it wasn't given. |
| **Audit log** | Every tool call is recorded with its arguments, result and the approving person. |

??? note "A write tool with a dry run and an idempotency key"

    ```python
    def file_bug(title: str, body: str, component: str, *,
                 dry_run: bool = True, idempotency_key: str) -> dict:
        existing = tracker.find_by_key(idempotency_key)
        if existing:
            return {"status": "exists", "bug": existing.id}
        if dry_run:
            return {"status": "dry_run", "would_create": {"title": title, "component": component}}
        bug = tracker.create(title, body, component, key=idempotency_key)
        audit.log("file_bug", bug.id, approved_by=current_approver())
        return {"status": "created", "bug": bug.id}
    ```

**Talking points**

- "The model proposes, a person approves, and the tool executes. The model never holds a write credential."
- "Writes are dry run by default and idempotent, so a retry or a resumed run can't double-file a bug."
- "That's the same pattern as my study_assistant checkpoint, applied to actions instead of answers."

## Hooks

- **CGEE:** your capstone cites the principle that a deterministic rejection always overrides an LLM approval. That's exactly the rule for write tools in a release pipeline. **[CGEE]** Wahi, V. (2026). *LLM-as-a-judge is not an oracle: Why self-improving agents need deterministic guardrails* (arXiv:2609.02246). https://arxiv.org/abs/2609.02246
- **Sync pipeline story:** "every side effect mapped" is the same idea as separating read tools from write tools.
- **study_assistant:** MCP is the only path to retrieval, the schema bounds the arguments, and approval survives across processes in Postgres.
