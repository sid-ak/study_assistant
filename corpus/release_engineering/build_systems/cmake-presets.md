# CMake presets

Orbit's CMake build is driven by presets defined in `CMakePresets.json` at the repository root. A
preset names a complete configuration, so every developer and every CI job configures the build
the same way instead of passing a long list of `-D` options by hand.

## Configure presets

A configure preset sets the generator, the build folder, and cache variables. Orbit defines
three:

- `debug`: `CMAKE_BUILD_TYPE=Debug`, no optimization, full debug information.
- `release`: `CMAKE_BUILD_TYPE=Release`, optimized with `-O3` and no assertions.
- `relwithdebinfo`: optimized with `-O2`, and debug information kept for profiling.

All three use the Ninja generator and write to `build/<preset name>`.

```bash
cmake --preset release
cmake --build --preset release
```

## Build types

`CMAKE_BUILD_TYPE` only applies to single-configuration generators such as Ninja and Unix
Makefiles. Multi-configuration generators, such as Visual Studio and `Ninja Multi-Config`, ignore
it and take the configuration at build time with `cmake --build build --config Release`. Leaving
`CMAKE_BUILD_TYPE` empty with a single-configuration generator produces a build with no
optimization flags at all, which is a common cause of unexpectedly slow benchmark numbers.

## Compile commands for editors

Every Orbit preset sets `CMAKE_EXPORT_COMPILE_COMMANDS=ON`. CMake then writes
`compile_commands.json` into the build folder, listing the exact compiler command for every
source file. Language servers such as clangd read it to resolve include paths and macros. Link
it to the repository root once:

```bash
ln -s build/debug/compile_commands.json compile_commands.json
```

## Compiler caching with ccache

The `debug` and `relwithdebinfo` presets set `CMAKE_CXX_COMPILER_LAUNCHER=ccache`. CMake then
prefixes every compile command with `ccache`, which returns a stored object file when the
preprocessed source and flags match an earlier compile. Check the hit rate with `ccache -s`.
Release builds in CI do not use ccache, so release artifacts are always compiled from scratch.
