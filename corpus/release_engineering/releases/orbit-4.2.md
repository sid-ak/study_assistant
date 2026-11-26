# Orbit 4.2 release notes

Released 2025-09-30. Orbit 4.2 is a maintenance release with build-time improvements.

## Build changes

- CI uses the Bazel remote cache for every gateway build, with `--remote_upload_local_results`
  enabled only on CI runners.
- Debug presets enable ccache through `CMAKE_CXX_COMPILER_LAUNCHER`. Clean debug builds on CI take
  about 40 percent less time when the cache is warm.
- The `aarch64` Linux build is cross-compiled on `x86_64` runners with a CMake toolchain file,
  replacing the slower native ARM runners.

## Fixed issues

- A full cache disk no longer fails requests with `E2001`. The cache is bypassed and a warning is
  logged once per minute.
- Fixed a data race in the connection pool reported by ThreadSanitizer, where two threads could
  return the same connection to the idle list.

## Upgrade notes

No configuration changes are required. `ORBIT_CACHE_DIR` must still be writable by the service
user, or the cache is disabled at startup with a warning.
