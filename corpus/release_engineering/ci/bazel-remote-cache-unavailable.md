# CI failure: Bazel remote cache UNAVAILABLE

Gateway builds on CI took about three times longer than usual for a day. No job failed, so the
problem was found from build-time dashboards rather than from a red build.

## Symptom

Every cached action printed a warning before running locally:

```text
WARNING: Remote Cache: UNAVAILABLE: io exception
INFO: Elapsed time: 1412.322s, Critical Path: 389.10s
INFO: 4120 processes: 4120 linux-sandbox.
```

A healthy build reports most processes as `remote cache hit`.

## Cause

The TLS certificate on `cache.orbit.internal` had expired. Bazel's gRPC client refused the TLS
handshake, every cache lookup failed, and Bazel treated each failure as a cache miss and built
the action locally.

## Fix

The certificate was renewed and the cache service restarted. The next build reported over 90
percent remote cache hits again.

## Prevention

- An alert fires when the certificate is within 14 days of expiry.
- A second alert fires when the CI remote cache hit rate drops below 50 percent for an hour,
  which catches any cause of a silent cache outage, not only certificates.
