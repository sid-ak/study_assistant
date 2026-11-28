# 07. Generation

> Part of the [Concepts](README.md) section of [AI, RAG & Python](../README.md)

Generation is the step where a language model reads the question and the retrieved passages and
writes the answer. Retrieval decides what evidence is available. Generation decides how it is
used: whether the answer stays within the evidence, whether it says which passage each claim came
from, and whether the output can be read by a program. This page covers how a language model
produces text, context windows and tokens, grounding and citations, structured output, and the rate
limits that shape how a system calls a hosted model.

| Concern | What can go wrong | Common control |
| ------- | ----------------- | -------------- |
| Context window | The prompt does not fit, or the evidence is cut off | Send a few short passages, not whole documents |
| Grounding | The answer states things the passages do not support | Instructions to answer only from the context, plus a way to decline |
| Citations | Claims cannot be traced to a source | Ask for the ids of the passages used, in a separate field |
| Output format | Free text that a program cannot parse | Structured output against a JSON schema |
| Rate limits | Requests are refused when the budget runs out | Wait and retry, cache replies, and make fewer requests |

## How a language model produces text

Why it matters: one property of this loop decides whether a RAG system is reproducible. The model
picks a token at a time, and whether it picks the most likely one or samples is a setting. Every
measurement in this project depends on that setting being fixed.

A language model predicts the next token from all the tokens before it. A token is a piece of text
from the model's fixed vocabulary, as described in [Embeddings](03-embeddings.md). The model
outputs a probability for every token in the vocabulary, one token is chosen, appended to the input,
and the process repeats until the model emits an end token or reaches a length limit.

In study_assistant every request sets the temperature to 0, which is the setting that matters for
this project. Greedy decoding makes the same prompt give the same answer, so a rerun of the
evaluation measures a change in the pipeline rather than noise, and a cached reply agrees with a
live one.

??? example "request_body"

    ```python
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": message.role, "content": message.content} for message in messages],
        # 0 asks for the most likely reply every time, so reruns and cached replies agree.
        "temperature": 0,
    }
    ```

Source: [`services/api/src/api/generate/openai_compatible.py:145-165`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/generate/openai_compatible.py#L145-L165)
- Greedy decoding: always taking the most likely token, as above, gives the same output for the
  same input. Sampling instead picks a token at random in proportion to its probability.
- Temperature: a setting that sharpens or flattens the probabilities before sampling. Temperature 0
  behaves like greedy decoding, which suits answers that should be repeatable. Higher temperatures
  give more varied text.
- Chat models: a chat model is trained on conversations made of messages, each with a role. The
  system message sets the rules, user messages carry the requests, and assistant messages are the
  model's own replies. The messages are joined into one token sequence before prediction.

## Context windows and tokens

Why it matters: the window is the budget a retrieval pipeline spends, and the part that silently
breaks things is truncation. A prompt cut at the wrong place removes the question rather than the
filler.

The context window is the largest number of tokens a model reads in one request, counting the
prompt and the reply together.

- Budget: a RAG prompt holds the instructions, the question, and the retrieved passages. With
  passages of about 150 tokens, five of them use about 750 tokens, a small fraction of a window of
  tens of thousands of tokens.
- Why still keep it small: hosted services price and rate-limit by tokens, and a long context
  dilutes the relevant passage among irrelevant ones. Models are known to use information in the
  middle of a long context less reliably than information near its start or end.
- Truncation: a prompt that exceeds the window is either rejected or cut, depending on the service.
  A cut that removes the question or the instructions produces an answer to the wrong request.

## Grounding and citations

Why it matters: grounding is the whole point of retrieval. Without it the model is free to answer
from training data, and the retrieved passages become decoration. This is where a RAG system either
earns its citations or does not.

An answer is grounded when every claim in it is supported by the supplied passages. Grounding is
requested through the instructions and checked afterward.

```text
system: Answer using only the context below. Each passage starts with its id in square brackets.
        Put the ids of the passages your answer relies on in cited_ids, never in the answer text.
        If the context does not answer the question, say so instead of answering.
user:   Context:
        [p1] Bazel: bazel test --config=asan runs every test under AddressSanitizer.
        [p2] CMake: set CMAKE_BUILD_TYPE=Release for optimized builds.

        Question: How do I run the tests under AddressSanitizer with Bazel?
```

- A way to decline: without an explicit option to say the context is insufficient, a model tends to
  answer anyway from its training data. Making "not answerable" a valid output reduces invented
  answers.
- Citations by id: labeling each passage with an id lets the model name its sources compactly, and
  lets a program map each id back to a document and section for display.
- Ids out of the answer text: a model may copy ids into the prose. Asking for them in a separate
  field keeps the answer readable and the citations machine-checkable.
- Checking: a citation is valid only if it names a passage that was in the context. A program can
  check that mechanically. Whether the cited passage actually supports the claim needs a human or a
  second model to judge.

study_assistant does all four. Its answer step asks for a boolean saying whether the context
answers the question at all, the answer text, and the ids it relied on as a separate field, with
the instruction that ids never appear in the prose. The declining path is wired through: an answer
marked unanswerable ends the run as insufficient context rather than being shown as an answer.

## Structured output

Why it matters: it turns "please cite your sources" from a request into a constraint. A schema
makes the answer parseable, and a well-chosen schema makes an invented citation impossible rather
than merely discouraged.

Structured output constrains the model's reply to a JSON document that matches a given JSON schema.
The service applies the schema during decoding: at each step, tokens that would break the schema
are excluded, so the reply always parses and has the required fields.

study_assistant builds that schema per request, and the `enum` is the whole point: the allowed
citation ids are the ids of the chunks just retrieved, so with strict mode on, citing a chunk the
model was not shown is not representable.

??? example "answer_schema"

    ```python
    context_ids = [hit.id for hit in context]
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "answerable": {"type": "boolean"},
            "answer": {"type": "string"},
            "cited_chunk_ids": {"type": "array", "items": {"type": "string", "enum": context_ids}},
        },
        "required": ["answerable", "answer", "cited_chunk_ids"],
        "additionalProperties": False,
    }
    ```

Source: [`services/api/src/api/graph/prompts.py:42-59`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/graph/prompts.py#L42-L59)

- Strict mode: in strict mode the reply must match the schema exactly, with no extra keys. Without
  it, the service only promises valid JSON, and the program must still check the fields.
- Constraining values: an `enum` limits a field to listed values. Listing the ids of the passages
  actually sent means the model cannot cite a passage it was not given.
- Support varies: not every model or service supports strict schemas, and some cannot combine a
  schema with tool calling in one request. Checking the provider's documentation and probing a
  request settles what is available.

The project uses strict mode, and the `enum` trick above is the part worth explaining out loud. The
list of allowed citation ids is built per request from the chunks that were actually retrieved, so
a citation outside the supplied context is not merely discouraged, it cannot be produced. That the
provider accepts a per-request `enum` in strict mode was confirmed by a probe rather than assumed.

??? example "request_body (response_format)"

    ```python
    if response_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            # strict: the reply must match the schema exactly, not merely be valid JSON.
            "json_schema": {
                "name": response_schema.name,
                "strict": True,
                "schema": response_schema.schema,
            },
        }
    return body
    ```

Source: [`services/api/src/api/generate/openai_compatible.py:145-165`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/generate/openai_compatible.py#L145-L165)

## Rate limits

Why it matters: on a free or shared plan the limit, not the model, is what makes a system unusable.
Handling it is the difference between a pipeline that pauses and one that fails halfway through an
evaluation run.

Hosted models limit how much each account may use, usually per minute and per day, in requests and
in tokens.

- HTTP 429: a request over the limit is refused with status 429, "Too Many Requests", often with
  headers saying when each budget resets, such as `retry-after` or `x-ratelimit-reset-tokens`.
- Waiting and retrying: a client that waits until the reset and retries turns a refusal into a
  delay. A cap on the wait keeps a spent daily budget from turning into a wait of hours.
- Fewer requests: each request spends budget, so a design that makes one request per answer, rather
  than several, fits more questions into the same limit.
- Caching: a request with exactly the same model, messages, and settings at temperature 0 gives the
  same reply, so storing replies keyed by the whole request makes a repeated run free.

All four apply here, because the project runs on a free plan. It makes one request per answer, waits
and retries while the endpoint returns 429, reads the wait from the response headers and falls back
to doubling when none is given, and refuses to wait longer than a cap, since a spent daily budget
resets too late to sit through. Replies are cached under a hash of the whole request body, which is
what makes rerunning an evaluation free: a live repeat took 400 ms and the cached one 0 ms.

The generate method shows the order: build the body, look in the cache, and only then send.

??? example "generate"

    ```python
    def generate(
        self, messages: list[ChatMessage], *, response_schema: ResponseSchema | None = None
    ) -> str:
        """Return the reply to ``messages``, from the cache when this exact request was answered.

        Otherwise send one chat-completion request, waiting and retrying while the endpoint
        answers HTTP 429, and cache the reply.
        """
        body = request_body(self._model, messages, response_schema)
        key = cache_key(body)
        if self.cache is not None:
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        reply = reply_text(self.send(body))
        if self.cache is not None:
            self.cache.put(key, reply)
        return reply
    ```

Source: [`services/api/src/api/generate/openai_compatible.py:82-99`](https://github.com/sid-ak/study_assistant/blob/cb54a4b8647d9477c3cd242856ede811db46019c/services/api/src/api/generate/openai_compatible.py#L82-L99)

Because the cache key is the whole body, and the body carries the temperature of 0, a cached reply
is the reply a live request would give. That equivalence is what makes caching safe to use during
measurement rather than a source of stale numbers.

> A study assistant answers from lecture notes with a hosted model on a free plan of 30 requests per
> minute. Each question makes one request with the top five passages and a strict schema for the
> answer and its cited passage ids. Replies are cached, so rerunning a set of practice questions
> after a change to the user interface spends no quota.

The practical rule is to send a few short passages, instruct the model to answer only from them and
to decline when they do not answer, request the answer and its citations as strict structured
output, check every citation against the context, and treat the rate limit as a budget to plan for.
