# Python scripting for HackerRank

> Part of [Gaps](README.md) in [AI, RAG & Python](../README.md)


## Why it comes up

The recruiter said "Programming and Scripting (Python preferred)" and HackerRank. The JD says "Comfortable working in Linux, with build systems and Python." Your LeetCode practice covers algorithms. What's missing is everyday scripting: parsing text, reading files and stdin, regex, and small utilities. Several common idioms have no coverage on your site at all.

## Drill 1: a log parser (about 25 minutes, from a blank file)

Write it without looking, then compare against this version.

??? note "The log parser, written out"

    ```python
    #!/usr/bin/env python3
    """Count errors by type in a build log and print the top N."""
    import argparse
    import logging
    import re
    import sys
    from collections import Counter, defaultdict
    from pathlib import Path

    LINE = re.compile(
        r"^(?P<ts>\S+ \S+)\s+(?P<level>ERROR|WARN|INFO)\s+\[(?P<module>[\w.]+)\]\s+(?P<msg>.*)$"
    )
    log = logging.getLogger(__name__)

    def read_lines(path: Path):
        """Yield lines one at a time, so a 10 GB log never sits in memory."""
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                yield line.rstrip("\n")

    def parse(lines):
        for n, line in enumerate(lines, start=1):
            m = LINE.match(line)
            if m:
                yield m.groupdict()
            else:
                log.debug("skipping line %d", n)

    def main(argv=None) -> int:
        ap = argparse.ArgumentParser(description=__doc__)
        ap.add_argument("logfile", type=Path)
        ap.add_argument("-n", "--top", type=int, default=5)
        args = ap.parse_args(argv)
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

        by_level = Counter()
        errors_by_module = defaultdict(list)
        for rec in parse(read_lines(args.logfile)):
            by_level[rec["level"]] += 1
            if rec["level"] == "ERROR":
                errors_by_module[rec["module"]].append(rec["msg"])

        print(dict(by_level))
        worst = sorted(errors_by_module.items(), key=lambda kv: len(kv[1]), reverse=True)
        for module, msgs in worst[: args.top]:
            print(f"{module:30} {len(msgs):5}  e.g. {msgs[0][:60]}")
        return 0

    if __name__ == "__main__":
        sys.exit(main())
    ```

**What it exercises:** generators (`yield`), `with`, named regex groups, `Counter`, `defaultdict`, `sorted(key=lambda ...)`, slicing, f-string alignment, `argparse`, `logging` and `sys.exit` with a return code.

## Drill 2: a retry decorator with exponential backoff (about 15 minutes)

This is relevant because LLM APIs rate-limit (your Groq adapter hits this) and CI infrastructure is flaky.

??? note "The retry decorator, written out"

    ```python
    import functools
    import random
    import time

    def retry(times=3, base=0.5, exceptions=(Exception,)):
        """Retry a function with exponential backoff plus jitter."""
        def decorator(fn):
            @functools.wraps(fn)            # keeps fn's name and docstring
            def wrapper(*args, **kwargs):
                for attempt in range(times):
                    try:
                        return fn(*args, **kwargs)
                    except exceptions:
                        if attempt == times - 1:
                            raise           # out of retries: re-raise the original error
                        delay = base * 2 ** attempt + random.uniform(0, base)
                        time.sleep(delay)
            return wrapper
        return decorator

    @retry(times=4, exceptions=(TimeoutError, ConnectionError))
    def fetch_build_status(build_id: str) -> dict: ...
    ```

**Points to say out loud:**

- The three layers: `retry(...)` returns a decorator, which returns a wrapper.
- `functools.wraps` keeps the wrapped function's name and docstring.
- **Jitter** stops many clients from retrying at the same moment, which is called a thundering herd.
- Only retry errors that might go away on their own. A 400 Bad Request will fail again.
- Only retry operations that are idempotent (see [large logs and tool permissions](large-logs-and-tool-permissions.md)).

## Idioms to have at your fingertips

| Need | Idiom |
|------|-------|
| Read all of stdin (HackerRank) | `data = sys.stdin.read().split()` or `for line in sys.stdin:` |
| Build a list or dict in one line | `[x*x for x in xs if x > 0]`, `{k: v for k, v in pairs}` |
| Sort by a field, with ties | `sorted(rows, key=lambda r: (-r["count"], r["name"]))` |
| Top K | `heapq.nlargest(k, items, key=...)` or `Counter.most_common(k)` |
| Group things | `defaultdict(list)` |
| Count things | `Counter(iterable)` |
| Number items | `for i, x in enumerate(xs, start=1)` |
| Walk two lists together | `zip(a, b, strict=True)` |
| Accept any arguments | `def f(*args, **kwargs)`, where `args` is a tuple and `kwargs` a dict |
| Run a shell command | `subprocess.run(["git", "log", "--oneline"], capture_output=True, text=True, check=True)` |
| Find files | `Path("logs").rglob("*.log")` |
| Parse JSON | `json.loads(s)` / `json.load(f)`, and `json.dumps(obj, indent=2)` |
| Parse CSV | `csv.DictReader(f)` |
| All regex matches | `re.findall(pat, s)` or `for m in re.finditer(pat, s): m.group("name")` |
| Debug output, not prints | `logging.getLogger(__name__)` with `log.info("x=%s", x)` |

**HackerRank habits:**

- Read the input format carefully, since stdin parsing is where silly bugs happen.
- Test with the sample input first, then with an empty input and a single item.
- State the time and space complexity before you start typing.
