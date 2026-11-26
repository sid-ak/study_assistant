# Cross-compiling with CMake

Orbit ships an `aarch64` Linux build for ARM servers, produced on `x86_64` CI runners. Building
for a different architecture than the one running the compiler is cross-compiling, and CMake
handles it through a toolchain file.

## The toolchain file

The file `cmake/toolchains/aarch64-linux-gnu.cmake` tells CMake which system it builds for and
which compilers to use:

```cmake
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)
set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
set(CMAKE_SYSROOT /opt/sysroots/aarch64)
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
```

Setting `CMAKE_SYSTEM_NAME` is what switches CMake into cross-compiling mode and sets
`CMAKE_CROSSCOMPILING` to true.

## Finding libraries in the sysroot

The three `CMAKE_FIND_ROOT_PATH_MODE_*` settings control where `find_package` and `find_library`
look. With `LIBRARY` and `INCLUDE` set to `ONLY`, libraries and headers are taken from the sysroot
and never from the build machine, whose `x86_64` libraries would fail to link. Programs are set to
`NEVER` because tools such as `protoc` must run on the build machine.

## Running tests

Tests built for `aarch64` cannot run directly on an `x86_64` runner. Orbit sets
`CMAKE_CROSSCOMPILING_EMULATOR` to `qemu-aarch64 -L /opt/sysroots/aarch64`, and `ctest` then runs
each test binary through QEMU user-mode emulation. Emulated tests run several times slower, so the
`aarch64` job runs only the unit test label: `ctest --preset aarch64 -L unit`.
