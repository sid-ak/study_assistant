# Sanitizers

Sanitizers are compiler instrumentation that detects memory and concurrency errors while tests
run. Orbit's CI runs the full test suite under AddressSanitizer and UndefinedBehaviorSanitizer on
every pull request, and under ThreadSanitizer nightly.

## AddressSanitizer

AddressSanitizer (ASan) detects out-of-bounds accesses, use-after-free, and double frees. It is
enabled at compile and link time with `-fsanitize=address`, and adding `-fno-omit-frame-pointer`
gives readable stack traces. Leak detection is on by default on Linux and is controlled at run
time through the environment:

```bash
ASAN_OPTIONS=detect_leaks=1:abort_on_error=1 ./build/asan/orbit_tests
```

Instrumented code runs about twice as slowly and uses noticeably more memory.

## UndefinedBehaviorSanitizer

UndefinedBehaviorSanitizer (UBSan) detects operations whose behavior the C++ standard leaves
undefined, such as signed integer overflow and misaligned pointers. It is enabled with
`-fsanitize=undefined` and combines with ASan in the same build. By default UBSan prints a report
and continues; Orbit adds `-fno-sanitize-recover=all` so the first report fails the test.

## ThreadSanitizer

ThreadSanitizer (TSan) detects data races: two threads accessing the same memory without
synchronization, at least one of them writing. It is enabled with `-fsanitize=thread` and cannot
be combined with ASan in one binary, which is why it runs as a separate nightly job. TSan slows
code by five to fifteen times.

## Suppressions

A report from third-party code that cannot be fixed is suppressed with a file passed through the
sanitizer's options, for example `TSAN_OPTIONS=suppressions=tsan.supp`. Every suppression in
Orbit's `sanitizers/` folder carries a comment linking the upstream bug.
