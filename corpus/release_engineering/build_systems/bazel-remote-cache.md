# Bazel remote cache

A remote cache stores build outputs keyed by a hash of each action's inputs, so a target already
built by CI or another developer is downloaded instead of rebuilt. Orbit's cache runs at
`grpcs://cache.orbit.internal`.

## Enabling the cache

The `remote-cache` config in `.bazelrc` sets the endpoint:

```text
build:remote-cache --remote_cache=grpcs://cache.orbit.internal
build:remote-cache --remote_timeout=30s
```

Developers read from the cache but do not write to it, so a result built on a laptop never
reaches release builds. Their `.bazelrc` adds `--remote_upload_local_results=false`. Only CI jobs
upload.

## Local disk cache

`--disk_cache=~/.cache/bazel-disk` keeps a second cache on the local disk, which survives
`bazel clean` and is shared between checkouts of the repository. It is checked before the remote
cache. The disk cache has no size limit by default and must be pruned by hand.

## Diagnosing cache misses

A target that rebuilds when it was expected to hit the cache has an input that differs between
machines. Common causes:

- An absolute path, such as a home folder, embedded in a compile command.
- An environment variable leaking into actions. `--incompatible_strict_action_env` gives every
  action a fixed `PATH` instead of the caller's.
- Different compiler versions on the two machines.

Compare two builds by writing an execution log on each with
`--execution_log_json_file=exec.json` and diffing the logged inputs of the target that missed.

## When the cache is unreachable

A failed cache lookup is treated as a miss: Bazel prints a warning naming the remote cache and
runs the action locally. A cache outage therefore makes builds slower rather than failing them.
`--remote_timeout` bounds how long each cache request waits before giving up. Its default is 60
seconds; Orbit sets 30 seconds so an unreachable endpoint costs less time per action.
