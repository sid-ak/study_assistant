# Python fundamentals rapid-fire

> Part of [Gaps](README.md) in [AI, RAG & Python](../README.md)


## Why it comes up

"Be prepared to speak at depth" plus "Python preferred" means quick conceptual checks are likely between coding questions. Each answer here fits in one or two sentences.

**The GIL, threads, processes and asyncio.**

- The **GIL** (global interpreter lock) lets only one thread run Python bytecode at a time in CPython. It's released during I/O and inside many C extensions.
- **Threads** suit I/O-bound work, like many HTTP calls or reading files.
- **Processes** (`multiprocessing`, `ProcessPoolExecutor`) suit CPU-bound work, since each process has its own GIL.
- **asyncio** suits lots of concurrent I/O on one thread, with cooperative switching at each `await`. That's what MCP and your LangGraph agent use. Blocking calls go through `asyncio.to_thread`.
- Python 3.13 added an optional free-threaded build with no GIL. It's experimental, so mention it only if asked.

**`is` vs `==`.** `==` compares values, using `__eq__`. `is` compares identity: whether they're the same object. Use `is` only for `None` and other singletons.

**Shallow vs. deep copy.** `copy.copy` (or `list(x)` or `x[:]`) copies the outer container but shares the inner objects. `copy.deepcopy` copies everything recursively. The classic bug: `grid = [[0]*3]*3` puts the same row in all three places. Use `[[0]*3 for _ in range(3)]`.

**Mutable default arguments.** `def f(x=[])` creates the list once, when the function is defined, so every call shares it. Use `x=None`, then `x = [] if x is None else x`. In a dataclass, use `field(default_factory=list)`.

**Iterators vs. generators.**

- An **iterable** is anything you can loop over. An **iterator** is the object doing the looping, with `__next__`, and it can only be used up once.
- A **generator** is the easy way to write an iterator: a function with `yield`. It's lazy, so it handles huge files with constant memory.
- A generator expression `(x for x in xs)` is the lazy version of a list comprehension.

**List vs. tuple vs. set vs. dict.**

- A list is mutable and ordered.
- A tuple is immutable, so it's hashable and can be a dict key if its contents are.
- A set gives O(1) average membership tests.
- A dict gives O(1) average lookups and has preserved insertion order since Python 3.7.

**How exceptions propagate.**

- An exception travels up the call stack until an `except` catches it.
- `finally` always runs.
- `else` on a `try` runs only if nothing was raised.
- `raise NewError(...) from err` chains the original cause.
- Catch the narrowest exception you can. A bare `except:` also catches `KeyboardInterrupt`.

**Decorators.** A function that takes a function and returns a new one, usually a wrapper. `@retry` above is an example, and so are `@property`, `@classmethod`, `@dataclass` and `@functools.lru_cache`.

**Context managers.** An object with `__enter__` and `__exit__`, used with `with`. Cleanup is guaranteed even if an exception is raised. You can write one with `@contextmanager` and a single `yield`.

**`*args` and `**kwargs`.** They collect extra positional arguments into a tuple and keyword arguments into a dict. The same symbols unpack a list or dict when you call a function. A bare `*` in a signature makes the following parameters keyword-only, which you used in study_assistant.

**`@staticmethod` vs `@classmethod`.** A static method gets no `self` or `cls`. A class method gets `cls`, which is useful for alternative constructors like `from_config`.

**Dataclass vs. Pydantic.**

- A dataclass generates `__init__`, `__repr__` and `__eq__`, with no validation at runtime.
- Pydantic validates and converts types at runtime and generates a JSON Schema. That's why it's common for LLM tool inputs and structured output.

**Duck typing and Protocols.** Python cares what an object can do, not what class it is. `typing.Protocol` writes that down for type checkers. study_assistant swaps fakes for real components this way.

**Big-O of built-ins to know.**

- `x in list` is O(n). `x in set` and `x in dict` are O(1) on average.
- `list.append` is amortized O(1). `list.insert(0, x)` and `list.pop(0)` are O(n), so use `collections.deque` for a queue.
- `heapq.heappush` and `heapq.heappop` are O(log n).
- `sorted` is O(n log n) and stable.
