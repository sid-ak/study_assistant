# 3. Deployment scope: local single-user

- Status: Accepted
- Date: 2026-06-13

## Context

"Personal study assistant" could mean several things, and the interpretation decides whether
authentication and multi-tenancy exist as concerns at all. Three options were considered:

1. Local single-user — runs on the developer's machine via Docker Compose; one user, no auth,
   secrets via `.env`. Simplest; CI builds and tests images but does not deploy.
2. Cloud-deployable, single-user — same single-user model but designed to deploy to a cloud host
   (managed Postgres, registry push, prod vs. local config). More infra surface — and the local
   `bge` models are heavy to host in the cloud anyway (see
   [ADR 0002](0002-local-embedding-and-reranking.md)).
3. Multi-user with auth — per-user corpora and authentication from day one. The most
   infrastructure: an auth layer, per-user data isolation, and user migrations. Overkill for a
   personal tool unless it will be shared.

## Decision

Adopt local single-user: the system runs on the developer's machine via Docker Compose, with no
authentication and secrets supplied through `.env`. A single corpus, a single user.

To avoid a future rewrite, the database schema keeps a `user_id` seam (a `user_id` column on the
relevant tables, defaulted for the single local user) so authentication and per-user isolation can
be layered on later without restructuring the data model — but none of that is built now.

## Consequences

- Simplest possible footprint: no auth layer, no session/JWT handling, no per-user isolation
  logic. Development effort goes into retrieval and orchestration instead.
- Secrets live in `.env`, documented via `.env.example`. This is acceptable for a single-user
  local tool and is not a model for a shared deployment.
- CI builds and tests images but does not deploy — there is no cloud target, registry push, or
  prod configuration to maintain.
- The `user_id` seam preserves an upgrade path to authenticated multi-user use; adopting it
  later would mean adding an auth layer and populating the seam, not reshaping the schema.
- This decision aligns the deployment story with [ADR 0002](0002-local-embedding-and-reranking.md):
  on-machine models and an on-machine, single-user runtime reinforce the same all-local goal.
