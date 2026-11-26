# Orbit 4.1 release notes

Released 2025-06-17. Orbit 4.1 adds the response cache and a Bazel build for the gateway.

## New features

- Response cache: identical read requests within a configurable window are served from memory.
  Enable it with `--orbit-cache-ttl=<seconds>`; the default `0` disables it. The cache lives in
  `ORBIT_CACHE_DIR`, which defaults to `/var/cache/orbit`.
- The gateway service now builds with Bazel as well as CMake. Bazel targets live under
  `//services/gateway`.

## Deprecations

- `--orbit-workers` is deprecated in favor of `--orbit-max-inflight`, which limits concurrent
  requests instead of threads. Both are accepted in 4.1; 5.0 removes `--orbit-workers`.

## Fixed issues

- The health endpoint returned `200` while the server was still loading its configuration. It now
  returns `503` until startup finishes.
- Error `E1027` (upstream timeout) is now logged with the upstream's address.

## Known issues

- With the response cache enabled, a cache folder on a full disk makes requests fail with
  `E2001` (cache write failed) instead of bypassing the cache. Fixed in 4.2.
