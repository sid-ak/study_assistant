# REST

> Part of the Projects guide — [back to index](../README.md)

<a id="rest"></a>

You used **Boost.Beast** to implement REST endpoints in C++, exposing internal state and control to
other systems. The focus was correctness under load — clear request parsing, timeouts, and robust
error reporting.

**The error-handling decision, which is the interesting part:** you chose **Boost.LEAF**-style
structured errors over generic exceptions. The reasoning: in a complex test environment, a bare
error code or a generic exception tells you _that_ something failed but not _which layer_ — and that
distinction is essentially the entire debugging cost. LEAF lets each layer attach context (which
file, which offset, which retry, what downstream state) without allocating and without paying for
exception unwinding, and the handler at the top declares exactly which context types it wants.

So a failure could immediately identify itself as input validation, network, timing, or downstream
state, rather than arriving as an undifferentiated "something went wrong."

**Concepts in play:** HTTP server design in C++ · asynchronous I/O (Beast is built on Asio) ·
timeouts and connection lifetime · structured error handling · exceptions vs. explicit error
propagation · designing errors for debuggability.

<a id="restscript"></a>

??? note "Scripts"

    ### ~40s

    > I used Boost.Beast to build REST endpoints in C++ that exposed internal state and control to other
    > systems. The design focus was correctness under load — request parsing, timeouts, connection
    > lifetime.
    >
    > The decision I'd highlight is error handling. I went with structured errors, Boost.LEAF style,
    > rather than generic exceptions. The reasoning is that in a complex test environment the failure
    > modes are varied — input validation, network, timing, downstream state — and a generic exception
    > or a bare error code tells you _that_ something failed but not which layer. That distinction is
    > basically the entire debugging cost.
    >
    > LEAF lets each layer attach its own context — the input, the retry count, the downstream state —
    > without allocating and without paying for exception unwinding, and the handler at the top declares
    > which of that context it actually wants. So by the time a failure reached me I could tell
    > immediately whether it was a client problem, a transport problem, or a state problem, instead of
    > starting from zero.

<a id="restqa"></a>

??? note "QA"

    **Q: Why not just use exceptions?**

    > Three reasons in this context. Exceptions are expensive when actually thrown — unwinding plus a
    > global lock in most unwinder implementations, which serializes threads that throw concurrently.
    > They make error paths invisible in the source, so you can't tell from a function signature what
    > can fail. And in a service, most "errors" aren't exceptional at all — a malformed request is a
    > completely expected condition, and modeling the common case as an exception is both slow and
    > semantically wrong. I'd still use exceptions for constructor failure and genuinely unrecoverable
    > conditions.

    **Q: How is LEAF different from just returning an error code?**

    > A code tells you what failed. LEAF lets each frame _augment_ the error with context as it
    > propagates — the filename, the offset, the retry count — and the handler declares which of that
    > context it wants to see. Critically, it stores that context in thread-local storage rather than in
    > a returned object, so intermediate frames that don't care about the error don't have to carry or
    > copy it. You get the debuggability of a rich exception without the cost of one, and it works with
    > exceptions disabled entirely.

    **Q: What would you use today?**

    > `std::expected` if I were on C++23, or `tl::expected` as a drop-in — it's now the standard
    > vocabulary type for value-or-error and it composes nicely with monadic operations. LEAF still wins
    > when you specifically want _augmentation_ across many frames without threading a context object
    > through every signature. So it depends on whether the value is in the error _type_ or in the
    > accumulated _context_.
