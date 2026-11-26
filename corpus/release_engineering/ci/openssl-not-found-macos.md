# CI failure: Could NOT find OpenSSL on macOS

The `macos-arm64` job failed at configure time on a freshly provisioned runner.

## Symptom

```text
CMake Error at /opt/homebrew/share/cmake/Modules/FindPackageHandleStandardArgs.cmake:233 (message):
  Could NOT find OpenSSL, try to set the path to OpenSSL root folder in the
  system variable OPENSSL_ROOT_DIR (missing: OPENSSL_CRYPTO_LIBRARY
  OPENSSL_INCLUDE_DIR) (Required is at least version "3.0")
```

## Cause

macOS does not ship OpenSSL headers. The runner installs OpenSSL with Homebrew as `openssl@3`,
which Homebrew installs keg-only: it stays under `/opt/homebrew/opt/openssl@3` and is not linked
into `/opt/homebrew/include` or `/opt/homebrew/lib`, so CMake's default search paths do not reach
it. The old runner image had a manually linked copy that the new image lacked.

## Fix

Pass Homebrew's prefix for the formula to CMake in the configure step:

```bash
cmake --preset release -DCMAKE_PREFIX_PATH="$(brew --prefix openssl@3)"
```

`OPENSSL_ROOT_DIR` set to the same path works too, but `CMAKE_PREFIX_PATH` also covers other
keg-only dependencies when more prefixes are listed, separated by semicolons.

## Prevention

The macOS job now sets `CMAKE_PREFIX_PATH` in its environment from `brew --prefix` for every
keg-only dependency, so no runner relies on manually linked libraries.
