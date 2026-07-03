# 7. Generation Backend

- Status: Accepted
- Date: 2026-07-02

## Context

Generation is the reasoning lane: a LangGraph loop reaches retrieval through the MCP server's tools,
pauses at HITL checkpoints, and synthesizes a grounded, cited answer. Per the interface-first
architecture ([ADR 0006](0006-interface-first-architecture.md)), the reasoning model sits behind a
`Generator` interface; this ADR records which backend goes behind that interface, and why.

Two things drive the choice. First, removing the project's only vendor tie-in — the reasoning model
was its one online, paid, hosted dependency. Second, keeping the reasoning model on-machine, which
closes the last gap to a fully offline, free run: ingestion and retrieval already run locally, so a
local generation backend makes the whole pipeline private and free end-to-end, with no prompts or
chunks transiting to a vendor.

Unlike the embedder, the generation backend carries no schema lock-in: the embedding dimension is
fixed in the pgvector `vector(N)` column (see [ADR 0002](0002-local-embedding-and-reranking.md)),
but a generation model can be swapped per run with no migration. So the concrete model should not be
pinned the way the embedder is.

## Decision

The `Generator` has one adapter, deliberately vendor-neutral: it speaks the OpenAI-compatible
chat-completions protocol — a de-facto standard implemented by local runtimes (Ollama, vLLM,
llama.cpp) and many hosted providers alike, not a dependency on OpenAI or any single vendor. No
vendor-specific SDK enters the generation lane. By default the adapter points at a local runtime for
a fully offline, free run; it can also point at any hosted endpoint that speaks the same protocol.

Candidate open-weight local backends, as a dated snapshot (2026-07) — a snapshot, not a locked
choice, and to be re-verified before implementation:

- Qwen3.6 — primary candidate. The most reliable tool/function-calling among open-weight models,
  long context, runs via Ollama with MLX acceleration on Apple Silicon (Ollama 0.19+). Best fit for
  the LangGraph MCP tool-calling loop and HITL checkpoints.
- IBM Granite 4 (Apache 2.0, 3B–32B) — secondary/conservative option. Purpose-trained for function
  calling with a smaller footprint, but less capable at open-ended reasoning.
- Kimi K2.6, DeepSeek V4 Pro, GLM-5.1 — also strong on agentic benchmarks at this time. Larger, and
  worth reconsidering if hardware allows.

## Consequences

- No vendor tie-in: generation depends only on the OpenAI-compatible protocol, so the project has no
  hosted, paid, online dependency and the whole pipeline can run offline and free end-to-end.
- The concrete model is chosen in config per run and is not locked. The list above is a 2026-07
  research snapshot that must be re-checked against the current landscape before implementation, not
  treated as a fixed decision.
- Open-weight models vary in tool-calling reliability, so model selection is weighted toward
  function-calling quality, and the golden-set eval discipline used for retrieval extends naturally
  to checking generation behavior.
- Adopting the OpenAI-compatible protocol rather than a richer vendor SDK trades some
  provider-specific features for portability — the intended trade, since portability is the point.
