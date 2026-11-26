# CMake dependencies

Orbit depends on OpenSSL, zlib, and GoogleTest. This guide covers how the CMake build finds them
and how to point it at a non-standard installation.

## find_package and CMAKE_PREFIX_PATH

Installed libraries are located with `find_package`. For OpenSSL the call is
`find_package(OpenSSL 3.0 REQUIRED)`, which defines the imported targets `OpenSSL::SSL` and
`OpenSSL::Crypto`. CMake searches standard system locations first. A library installed elsewhere,
for example by Homebrew under `/opt/homebrew`, is found by adding its prefix to
`CMAKE_PREFIX_PATH`:

```bash
cmake --preset debug -DCMAKE_PREFIX_PATH=/opt/homebrew/opt/openssl@3
```

`OPENSSL_ROOT_DIR` is an alternative hint that only the OpenSSL find module reads.

## Fetching GoogleTest with FetchContent

GoogleTest is not installed system-wide. The test build downloads a pinned release at configure
time with the `FetchContent` module:

```cmake
include(FetchContent)
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
)
FetchContent_MakeAvailable(googletest)
```

Configuring offline fails at this step. Set `FETCHCONTENT_FULLY_DISCONNECTED=ON` to reuse sources
that an earlier configure already downloaded into the build folder.

## Threads

Orbit's worker pool uses `std::thread`. On Linux with glibc older than 2.34, the threading
functions live in a separate library that must be linked explicitly. The portable way is
`find_package(Threads REQUIRED)` followed by linking the `Threads::Threads` target, which adds
`-pthread` where the platform needs it.

```cmake
find_package(Threads REQUIRED)
target_link_libraries(orbit_core PRIVATE Threads::Threads)
```

## vcpkg toolchain

Developers on Windows install dependencies with vcpkg. Its CMake integration is a toolchain file
passed on the first configure:

```bash
cmake --preset debug -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake
```

A toolchain file is read only on the first configure of a build folder. Changing it later has no
effect until the build folder is deleted.
