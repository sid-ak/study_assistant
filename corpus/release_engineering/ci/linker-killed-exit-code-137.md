# CI failure: linker killed with exit code 137

Debug builds on the standard Linux runners started failing after the test suite grew, always
while linking test binaries.

## Symptom

```text
collect2: fatal error: ld terminated with signal 9 [Killed]
compilation terminated.
ninja: build stopped: subcommand failed.
Error: Process completed with exit code 137.
```

## Cause

Exit code 137 is 128 plus 9, meaning the process was killed by signal 9, `SIGKILL`. Here the
Linux out-of-memory killer sent it. Ninja runs as many jobs as the runner has cores, and several
large test binaries with full debug information were being linked at the same time. Each link
needed over 2 GB, and together they exceeded the runner's 7 GB of memory.

## Fix

Link jobs now run in a Ninja job pool that allows two at a time, while compile jobs keep full
parallelism:

```cmake
set_property(GLOBAL PROPERTY JOB_POOLS link_pool=2)
set(CMAKE_JOB_POOL_LINK link_pool)
```

Debug builds also link with `lld` through `-fuse-ld=lld`, which uses less memory than GNU `ld`
for these binaries.

## Prevention

The CI summary prints the peak memory of the build step, so a build approaching the runner's
limit is visible before it fails.
