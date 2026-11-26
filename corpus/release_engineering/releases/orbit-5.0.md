# Orbit 5.0 release notes

Released 2026-02-10. Orbit 5.0 removes deprecated options and changes the default concurrency
limit.

## Breaking changes

- `--orbit-workers` is removed. Use `--orbit-max-inflight`, introduced in 4.1. Starting the
  server with the removed flag fails with error `E1001` (unknown option).
- The default for `--orbit-max-inflight` changes from unlimited to 256. Deployments that relied
  on unlimited concurrency must set the flag explicitly.
- The minimum CMake version is now 3.28, for C++20 module scanning. CI images with older CMake
  fail at configure time.

## New features

- `orbit-config validate <file>` checks a configuration file without starting the server and
  exits non-zero on the first error.
- Requests rejected because the in-flight limit is reached return HTTP `429` with error `E1050`
  (too many in-flight requests) and a `Retry-After` header.

## Fixed issues

- Error `E1013` (request body too large) now reports the configured limit in its message.

## Upgrade notes

Search deployment scripts for `--orbit-workers` before upgrading. Run
`orbit-config validate` against every configuration file; it reports removed options by name.
