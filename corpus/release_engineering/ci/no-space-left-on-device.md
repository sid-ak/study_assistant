# CI failure: No space left on device during the image build

The job that builds Orbit's container image failed on one self-hosted runner, at different steps
on each retry.

## Symptom

```text
#14 [build 6/9] RUN cmake --build --preset release
#14 41.27 /usr/bin/ld: final link failed: No space left on device
ERROR: failed to solve: process "/bin/sh -c cmake --build --preset release" did not complete
successfully: exit code: 1
```

## Cause

The runner's Docker build cache had grown for months without being pruned and filled the disk.
`docker system df` showed 180 GB of build cache on a 200 GB volume. Which step failed depended on
which step first needed more space, which is why retries failed in different places.

## Fix

Build cache older than three days was removed on the runner:

```bash
docker builder prune --force --filter until=72h
```

## Prevention

A scheduled job runs the same prune command on every runner each night, and the runner's health
check fails when free disk space drops below 20 percent, so a full runner is taken out of the pool
before it fails a build.
