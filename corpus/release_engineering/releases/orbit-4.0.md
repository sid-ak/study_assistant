# Orbit 4.0 release notes

Released 2025-03-04. Orbit 4.0 moves the build to CMake presets and raises the minimum toolchain.

## Breaking changes

- The minimum CMake version is now 3.25. Older versions fail at configure time with
  `CMake 3.25 or higher is required`.
- The minimum compilers are GCC 12 and Clang 15, because Orbit now compiles as C++20.
- The `--orbit-legacy-config` command-line flag is removed. Configuration files in the old INI
  format must be converted to TOML with `orbit-config migrate`.

## New features

- `CMakePresets.json` defines `debug`, `release`, and `relwithdebinfo` presets.
- The server reads `ORBIT_LOG_LEVEL` from the environment, accepting `error`, `warn`, `info`, and
  `debug`. The default is `info`.

## Fixed issues

- Requests larger than 64 KiB no longer truncate silently; they are rejected with error `E1013`
  (request body too large).
- Shutdown no longer hangs when a worker thread is blocked on a slow client.

## Upgrade notes

Delete existing build folders before configuring with a preset. A build folder created by an
older configure keeps its cached generator, and CMake refuses to switch generators in place.
