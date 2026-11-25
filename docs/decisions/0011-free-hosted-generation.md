# 11. Free Hosted Generation Endpoint

- Status: Accepted
- Date: 2026-11-25

## Context

[ADR 0007](0007-generation-backend.md) puts generation behind a `Generator` interface with one
adapter that speaks the OpenAI-compatible chat-completions protocol. It points that adapter at a
local runtime by default and notes that any hosted endpoint speaking the same protocol also works.

The development machine cannot run the local default in a useful form:

- An Apple M1 with 8 GB of RAM and about 7 GB of free disk. Models that fit sit at the 3-billion
  parameter scale, well below the open-weight candidates ADR 0007 lists for tool calling.
- A budget of zero, so paid APIs and rented compute are out.

The MVP agent needs three things from the model: strict JSON-schema output (an answer plus the ids of
the chunks it cites), tool calling for the retrieval tool, and enough free quota to run the golden set
through the agent several times a day.

Free tiers were compared from their documentation on 2026-11-25:

| Provider | Outcome |
| --- | --- |
| Groq | Free plan with tool calling on every hosted model and strict JSON-schema output on `qwen/qwen3.8-27b`, `openai/gpt-oss-120b`, and `openai/gpt-oss-20b`. Its services agreement does not permit training on inputs or outputs. Inference data is not retained by default, and zero data retention can be turned on. |
| Google Gemini | Free tier with tool calling, but free-tier inputs and outputs are used to improve Google products and may be read by human reviewers. Reasoning cannot be turned off on Gemini 3 and 4 models, which adds tokens and latency to every call. Free limits are not published, and the OpenAI compatibility layer is in beta with no stated support for a raw `json_schema` response format. |
| GitHub Models | Retired on 2026-07-30. |
| Cerebras | A trial credit that requires a payment method, not a free tier. |
| OpenRouter free models | 50 requests per day without purchased credits. |

Groq was then probed live with `scripts/probes/probe_generation.py`:

- Free-plan limits for both `qwen/qwen3.8-27b` and `openai/gpt-oss-120b` are 30 requests per
  minute, 1,000 per day, 8,000 tokens per minute, and 200,000 tokens per day. The account limits page
  and the `x-ratelimit-*` response headers agree.
- Limits apply per model. After requests to one model, the other still reported its full allowance.
- Both models returned a valid strict-schema answer with the correct cited id and produced a correct
  `search` tool call, each in under one second.
- `qwen/qwen3.8-27b` also copied the cited id into the answer text. `openai/gpt-oss-120b` spent
  reasoning tokens on every call.
- Requests sent with Python's default `Python-urllib` User-Agent were rejected with HTTP 403 and
  "error code: 1010" by the Cloudflare layer in front of the API.

## Decision

The MVP generates through Groq's free plan, configured only through the `GENERATION_*` settings:

- Base URL: `https://api.groq.com/openai/v1`.
- Default model: `qwen/qwen3.8-27b`, which supports strict schemas, tool calling, and parallel tool
  calls and spends no hidden reasoning tokens.
- Alternative model: `openai/gpt-oss-120b`, used for comparison runs.

The adapter, its interface, and the vendor-neutral protocol from ADR 0007 do not change. A local
runtime remains a supported setting. This record replaces only ADR 0007's default endpoint.

The free-plan limits shape how the agent and its evals call the model:

- One model request per graph step. Groq does not combine strict structured output and tool calling
  in one request, so grading, rewriting, tool selection, and answering are separate calls.
- The adapter treats HTTP 429 as a signal to wait, using the `x-ratelimit-reset-*` headers, and then
  retries. It does not fail the run.
- Generation responses are cached, keyed by model, prompt, question, and retrieved context, so a rerun
  with nothing changed makes no calls.
- Relevance grading uses a retrieval score and a threshold instead of a model call. The dense
  similarity score serves until the reranker exists, and the cross-encoder score replaces it after.
- The answer step receives a small context, such as the top few chunks after reranking.
- Retrieval evals never call the model. Only generation evals spend quota.

## Consequences

- Generation costs nothing, and the per-call latency is well under a second.
- Prompts and retrieved chunks leave the machine for generation. The MVP corpus is public
  release-engineering documentation ([ADR 0009](0009-mvp-corpus.md)), and Groq's agreement rules out
  training on it. Ingestion, embedding, retrieval, and reranking stay local.
- Generation needs a network connection. A fully offline run needs a local runtime and a machine that
  can host a capable model.
- The token limits bound the eval loop. A rough estimate, to be replaced by measured counts, is
  40,000 to 80,000 tokens for one pass of a 10-question golden set, so a few full generation evals
  per model per day.
- Scoring relevance from retrieval scores is deterministic and free, but less flexible than asking
  the model. Measuring that trade-off is part of the generation evals.
- The prompt must keep citations in the cited-ids field only, because a model may repeat them in the
  answer text.
- Any HTTP client used by the adapter must send its own User-Agent, or the Cloudflare layer rejects
  the request.
- Free-plan terms and limits can change without notice. Recheck them before relying on a number, and
  switch the setting to another compatible endpoint if they stop fitting.
