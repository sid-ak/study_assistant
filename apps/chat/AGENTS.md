# study_chat — Agent Context

`study_chat` is the `study-chat` command: a local Streamlit chat page that runs the `api` agent once
per message. It is a stopgap ahead of the React frontend planned in `apps/web`. See the root
[`AGENTS.md`](../../AGENTS.md) for project-wide context and
[`docs/architecture.md`](../../docs/architecture.md) for where it sits. The ADRs that bind it are the
local single-user scope (0003) and the retrieval boundary (0001).

## Surface

- `study-chat`: runs `streamlit run` on `study_chat/app.py`, listening on `localhost` only, with
  Streamlit's usage statistics off and its Deploy button hidden. Run it from the repo root, like
  `study-ask`: `.env`, the MCP server's working folder, and the reply cache are resolved from there.
- The page: a chat box and the conversation so far. Each message shows the agent's answer with its
  numbered sources (document and heading path) and the searches made, the no-answer line when the
  documents did not answer, or the error a failed run reported.
- `study_chat.reply`: `respond(question) -> Reply` runs one agent run and never raises for a model,
  search, or settings failure; `format_answer(answer)` is the Markdown the page shows.
- The corpus is whichever database `DATABASE_URL` names. The variable in the environment wins over
  `.env` and is forwarded to the MCP server, so
  `DATABASE_URL=postgresql://…/study_prep uv run study-chat` points the page at another corpus.

## Conventions

- A consumer of `api`, never a reimplementer. The page calls `api.cli.answer_question`, and
  shares the no-answer line and the searches line with `study-ask` (`api.cli.NO_ANSWER`,
  `api.cli.searches_line`) rather than restating them.
- Streamlit reruns `app.py` on every interaction. Earlier turns live in `st.session_state`, so they
  are redrawn and never sent to the agent again; the page tests pin this.
- `app.py` calls `reply.respond` through the module, so tests replace it with a scripted responder
  and drive the page with `streamlit.testing.v1.AppTest`, with no model, search server, or database.

## Known drift from the architecture

- The architecture puts the user interface in `apps/web` (React) over FastAPI with SSE. This page
  imports the agent directly instead, so it does not stream, and it reaches the agent in-process
  rather than over HTTP.
- No approval step: the page always runs the one-shot path. `--review` and `--resume` remain
  CLI-only.
- Each message starts the MCP server and stops it again, as one `study-ask` does. Opening it was
  measured at about 1 s against about 0.4 s per search, small next to generation, so no connection
  is kept between messages.
