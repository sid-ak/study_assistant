# CI failure: undefined reference to pthread_create

The `linux-oldest` job failed at link time after a change to the worker pool, while every other
Linux job passed.

## Symptom

```text
/usr/bin/ld: CMakeFiles/orbit_core.dir/src/pool.cpp.o: in function `orbit::Pool::start()':
pool.cpp:(.text+0x1a4): undefined reference to `pthread_create'
collect2: error: ld returned 1 exit status
ninja: build stopped: subcommand failed.
```

## Cause

The `linux-oldest` job runs on Ubuntu 20.04, whose glibc is 2.31. Before glibc 2.34, the POSIX
thread functions live in a separate library, `libpthread`, which must be linked explicitly. Newer
images ship glibc 2.34 or later, where those functions moved into the C library itself, so the
missing link flag only mattered on the oldest image. `orbit_core` had started using `std::thread`
directly but never linked a threads library.

## Fix

Link the CMake threads target, which adds `-pthread` on platforms that need it and nothing where
it is not needed:

```cmake
find_package(Threads REQUIRED)
target_link_libraries(orbit_core PRIVATE Threads::Threads)
```

Adding `-lpthread` by hand to `CMAKE_EXE_LINKER_FLAGS` also links, but it is not portable and
applies to every target in the build.

## Prevention

Keep a CI job on the oldest supported distribution, so link problems that newer C libraries hide
are caught before release.
