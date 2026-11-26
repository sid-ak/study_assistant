# Bazel basics

Orbit's newer services build with Bazel. This guide covers the commands and options used day to
day.

## Targets and labels

Bazel builds targets, and a label names one target: `//services/gateway:server` is the `server`
target declared in `services/gateway/BUILD.bazel`. The pattern `//...` means every target in the
workspace, and `//services/...` every target under `services/`.

```bash
bazel build //services/gateway:server
bazel test //...
```

## Compilation modes

The `-c` (`--compilation_mode`) option picks one of three modes:

- `fastbuild`: the default. No optimization and minimal debug information, for the fastest
  edit-compile cycle.
- `dbg`: no optimization, full debug information (`-g`).
- `opt`: optimized (`-O2`) with assertions disabled through `-DNDEBUG`.

Release artifacts are always built with `-c opt`.

## Configs in .bazelrc

Groups of options are named in the repository's `.bazelrc` and selected with `--config`. Orbit
defines:

```text
build:asan --copt=-fsanitize=address --copt=-fno-omit-frame-pointer --linkopt=-fsanitize=address
build:tsan --copt=-fsanitize=thread --linkopt=-fsanitize=thread
build:ci --config=remote-cache --keep_going --test_output=errors
```

So `bazel test --config=asan //...` builds and runs every test under AddressSanitizer.

## Querying the build graph

`bazel query` answers questions about dependencies without building anything. Two common uses:

```bash
bazel query 'deps(//services/gateway:server)'
bazel query 'rdeps(//..., //lib/codec:codec)'
```

The first lists everything the server depends on. The second lists every target that depends on
the codec library, which is the set to rebuild and retest after changing it.
