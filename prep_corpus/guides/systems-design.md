# Systems Design

> **Interview:** August 6, 2026 · NetApp Systems Software Engineer (Level 3–5 pipeline)
>
> **The framing that matters most:** this is **not** a FAANG "design Twitter" interview. NetApp is
> hiring a systems software engineer for ONTAP, WAFL, protocols, and replication. The design
> questions skew toward **component-level design in C++** — design a cache, a thread pool, an
> allocator, a metadata structure — and toward **storage-shaped distributed problems** —
> replication, consistency, failure handling. If you spend the interview drawing load balancers and
> CDNs, you've answered the wrong question.
>
> **How this doc relates to the others.** `guides/networking_and_storage/` is the _domain knowledge_ —
> what WAFL is, how NFS works, what a snapshot costs. This doc is the _method_: how to run a design
> conversation, what to estimate, which building blocks to reach for, and how to talk about
> tradeoffs. Read 03 for facts, read this for structure.

---

## Index

### Part I — Method

| Section                       | What it covers                                                    |
| ----------------------------- | ----------------------------------------------------------------- |
| [Shape](#shape)               | What NetApp actually means by "systems design"                    |
| [Framework](#framework)       | Six steps with a time budget for a 45-minute interview            |
| [Requirements](#requirements) | The questions to ask before drawing anything                      |
| [Estimation](#estimation)     | Back-of-envelope math, and when to skip it                        |
| [Interfaces](#interfaces)     | API and data model — the step candidates skip and shouldn't       |
| [Deepdive](#deepdive)         | Going deep on one component without being asked twice             |
| [Tradeoffs](#tradeoffs)       | Naming tensions _is_ the answer, not a postscript                 |
| [Signals](#signals)           | What they're grading, in their own words from the recruiter email |

### Part II — Building Blocks

| Section                         | What it covers                                           |
| ------------------------------- | -------------------------------------------------------- |
| [Numbers](#numbers)             | Latency and throughput numbers to have memorized         |
| [Caching](#caching)             | Eviction, write policies, invalidation, coherence        |
| [Concurrency](#concurrency)     | Threading models and the locking ladder                  |
| [Queues](#queues)               | Back-pressure, bounded buffers, and what to do when full |
| [Indexes](#indexes)             | B-tree vs. LSM vs. hash — the actual decision criteria   |
| [Durability](#durability)       | WAL, journaling, fsync, and what "committed" means       |
| [Replication](#replication)     | Sync vs. async, quorum, log shipping                     |
| [Partitioning](#partitioning)   | Sharding, consistent hashing, rebalancing                |
| [Resilience](#resilience)       | Idempotency, retries, timeouts, circuit breakers         |
| [Observability](#observability) | Designing for debuggability — your strongest angle       |

### Part III — Practice Problems

| Section                     | What it covers                                           |
| --------------------------- | -------------------------------------------------------- |
| [Component](#component)     | C++ object-level designs — the most likely question type |
| [Storage](#storage)         | Full-system storage problems                             |
| [Walkthrough](#walkthrough) | One complete worked example, start to finish             |

### Part IV — Your Material

| Section                 | What it covers                              |
| ----------------------- | ------------------------------------------- |
| [Projects](#projects)   | Your six projects as design answers, mapped |
| [Rapidfire](#rapidfire) | Q&A                                         |

---

## Part I — Method

### Shape

Three kinds of design question exist. Know which one you're being asked, because the right answer to
one is the wrong answer to another.

| Type                        | Example                                       | Likelihood here | What they want                                    |
| --------------------------- | --------------------------------------------- | --------------- | ------------------------------------------------- |
| **Component / object**      | "Design a thread-safe LRU cache."             | **High**        | C++ classes, data structures, locking, complexity |
| **Subsystem**               | "Design the metadata layer for a filesystem." | **High**        | On-disk layout, indexing, crash consistency       |
| **Distributed / web-scale** | "Design a URL shortener."                     | Low             | Sharding, load balancing, caching tiers           |

**The tell is the vocabulary.** If they say "class," "interface," "data structure," or "API," it's
component-level and you should be writing C++ within five minutes. If they say "system," "service,"
or "cluster," go up a level. **If you're unsure, ask** — _"Would you like me to work at the class
level or the system level?"_ is a completely legitimate opening question and it signals judgment
rather than confusion.

**Why component-level dominates for this role.** The JD says "design, implement, and enhance
features within ONTAP," "analyze and improve existing code paths," and "participate in design and
code reviews." That's a description of somebody who designs _modules inside a large C++ codebase_,
not somebody who draws cluster diagrams. Prepare accordingly.

---

### Framework

Six steps. For a 45-minute question, roughly:

| Step                      | Time      | Output                                               |
| ------------------------- | --------- | ---------------------------------------------------- |
| 1. Clarify requirements   | 5–8 min   | Functional list, non-functional list, explicit scope |
| 2. Estimate scale         | 3–5 min   | Throughput, capacity, whether it fits in memory      |
| 3. Define the interface   | 5 min     | API signatures or class declaration                  |
| 4. Sketch the design      | 8–10 min  | Components and data flow                             |
| 5. Deep dive              | 10–15 min | One or two components in real detail                 |
| 6. Failures and tradeoffs | 5–8 min   | What breaks, what you'd trade, what you'd measure    |

**The single biggest mistake is starting at step 4.** Candidates hear the problem and start drawing.
Steps 1–3 are where seniority shows: a Level 5 engineer establishes constraints before committing to
a structure, because the constraints determine the structure.

**Announce your plan at the start.** _"Let me start by pinning down requirements and scale, then
I'll define the interface, sketch the architecture, and go deep wherever you'd like. Stop me any
time you want to steer."_ Thirty seconds, and it converts the interview from an interrogation into a
collaboration — which is exactly what the recruiter email said they're grading.

---

### Requirements

Never design against an unstated spec. Ask until you have all four categories.

**Functional — what must it do?**

- What operations does it support? (The API is the spec.)
- Who calls it — one thread, many threads, many machines?
- What's explicitly out of scope? _Get them to say this._ It's the cheapest way to shrink the
  problem to something you can do well in 45 minutes.

**Non-functional — how well must it do it?**

- **Latency target**, and at which percentile. "p99 under 1 ms" is a completely different design
  from "average under 100 ms."
- **Throughput** — operations per second.
- **Durability** — is losing the last second of writes acceptable? This one question determines
  whether you need a WAL and an `fsync` on the critical path.
- **Consistency** — must a read see the immediately preceding write? From the same client, or any
  client?
- **Availability** — what's the acceptable downtime, and is degraded service better than no service?

**Constraints — what can't you change?**

- Memory budget. In embedded or kernel-adjacent contexts this is the binding constraint.
- Existing interfaces you must match. (Very relevant at NetApp: ONTAP is decades old.)
- Single node or distributed? Don't assume distributed — many storage problems are single-node.

**Scale — how big?**

- Number of items, size of each, growth rate.
- Read:write ratio. **Ask this always.** A 100:1 read-heavy workload and a write-heavy one produce
  opposite designs (cache-and-index vs. log-and-compact).

**The four questions to ask if you only get to ask four:**

1. What's the read:write ratio?
2. What's the latency target, and at what percentile?
3. Can we lose recent writes on a crash?
4. Single node, or does this need to survive a node failure?

---

### Estimation

**Do it when scale determines structure. Skip it when it doesn't.** For "design a thread-safe LRU
cache," back-of-envelope traffic math is theater — say so and move on: _"Scale here is really about
how much memory we're given, so let me ask that instead of estimating traffic."_ That's a better
signal than performing arithmetic nobody needs.

**When it does matter, the question you're answering is usually one of three:**

1. **Does it fit in memory?** If yes, the design collapses to a hash map and you've saved everyone
   twenty minutes. This is the highest-value estimate in systems design.
2. **Is it I/O bound or CPU bound?** Determines where to spend the design effort.
3. **Does one machine suffice?** Determines whether you're having a distributed conversation at all.

**Round aggressively.** 86,400 seconds/day ≈ **10⁵**. A year ≈ **3 × 10⁷** seconds. Say "call it"
out loud when you round — it shows the rounding is deliberate.

**Worked example — a metadata cache:**

> 100 million files, 200 bytes of metadata each → 20 GB. That doesn't fit comfortably in a cache
> alongside data, so I need either an eviction policy with a good hit rate or an on-disk index with
> memory holding only the hot set. Say we can afford 4 GB — that's 20 million entries, so a 20% hot
> set. I'd design for that ratio and measure the actual hit rate, because at 20% the eviction policy
> choice matters a lot; at 90% it barely matters.

That's what good estimation looks like: three numbers, one conclusion, and a statement about what
you'd measure.

---

### Interfaces

**The step most candidates skip, and skipping it is a real signal at Level 4–5.** The API _is_ the
design. Write it down before you draw boxes.

For a component-level question, write the class declaration:

```cpp
template <typename Key, typename Value>
class LruCache {
public:
    explicit LruCache(size_t capacity);

    // Returns nullopt if absent. Marks the entry most-recently-used.
    std::optional<Value> get(const Key& k);

    // Inserts or updates. Evicts LRU if at capacity.
    void put(const Key& k, Value v);

    size_t size() const noexcept;
};
```

Then say the things the signatures don't:

- **Thread safety:** "This is not thread-safe; I'll add that in a moment, and I want to talk about
  where the lock goes because it's the interesting part."
- **Ownership:** does `put` copy, move, or take a reference? At NetApp this matters — say `Value&&`
  and explain the move.
- **Error handling:** exceptions, error codes, or `expected`? Pick one and justify it. In a
  kernel-adjacent or embedded path, error codes; in application code, exceptions are fine.
- **Why `optional` over a sentinel:** it makes "absent" unrepresentable-as-a-valid-value, which is
  the same compile-time-safety argument you made for the ORM.

For a system-level question, write the wire API instead — the operations, their arguments, and what
they return. Same principle.

---

### Deepdive

After the sketch, **pick the interesting component yourself and go deep without being asked.**
Waiting to be told which part to detail is passive; choosing correctly demonstrates judgment.

**Choose the component where the hard problem lives:**

| System          | The component worth deep-diving                |
| --------------- | ---------------------------------------------- |
| Cache           | Eviction policy and the locking strategy       |
| Key-value store | The on-disk index and compaction               |
| Filesystem      | Crash consistency — journaling or COW          |
| Replication     | Failure and reconciliation, not the happy path |
| Thread pool     | The queue, and shutdown                        |
| Rate limiter    | The algorithm and where state lives            |

**Going deep means concrete.** Data structures with names. Complexity per operation. Where the lock
is held and for how long. What happens on the failure path. If you're still saying "we'd have a
service that handles this," you haven't gone deep — you've gone longer.

**Say the invariant.** Every good design has one sentence that, if violated, means the system is
broken: _"The hash map and the list always contain exactly the same key set"_ · _"A block is never
referenced by two live inodes unless its refcount says so"_ · _"Nothing is acknowledged to the
client until it's in the log and the log is on stable media."_ Naming the invariant is the single
most senior-sounding thing you can do in a design interview, and it's also just good engineering.

---

### Tradeoffs

**Naming the tension is the answer.** There's no correct design, only a defensible one, and the
recruiter email says explicitly that they evaluate whether you can "discuss design decisions and
tradeoffs."

The recurring tensions in storage and systems work:

| Tension                                        | The two sides                                                     |
| ---------------------------------------------- | ----------------------------------------------------------------- |
| **Latency vs. throughput**                     | Batching raises throughput and raises latency. Both, always.      |
| **Consistency vs. availability**               | Under partition you pick one. See CAP in guide 03.                |
| **Durability vs. write latency**               | `fsync` on the critical path, or acknowledge early and risk loss. |
| **Space vs. time**                             | Indexes, caches, and dedupe tables all cost memory to save I/O.   |
| **Read amplification vs. write amplification** | B-tree favors reads, LSM favors writes. You pick your poison.     |
| **Simplicity vs. performance**                 | Every optimization is complexity someone maintains at 3 a.m.      |
| **Predictability vs. average speed**           | Amortized-fast with an O(n) worst case is a p99.9 problem.        |
| **Fine-grained locks vs. contention**          | More locks means more parallelism and more deadlock surface.      |

**The format for stating one:** _"I'd go with X. It costs us Y, but the requirement we agreed on was
Z, and X serves Z better. If Y turned out to matter more than we thought, the change would be
[specific alternative], and the signal that we needed it would be [specific metric]."_

That last clause — **what would make you change your mind, and how you'd know** — is what separates
"has opinions" from "has judgment." You already do this instinctively; the ORM disagreement story is
exactly this move. Do it deliberately here.

---

### Signals

From the recruiter's own words in `context/Topics.md`, they are grading:

| What they said                                    | What to actually do                                                                         |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| "Explain your thought process"                    | Narrate continuously. Silence reads as being stuck even when you're not.                    |
| "Discuss design decisions and tradeoffs"          | Never state a choice without its cost. See [Tradeoffs](#tradeoffs).                         |
| "It's perfectly fine to ask clarifying questions" | This is an invitation, not a courtesy. Ask five before designing.                           |
| "Work collaboratively with the interviewer"       | Check in: _"Does that direction seem right, or would you rather I go deeper on the index?"_ |
| "Draw from experiences you've had"                | Anchor at least one decision in something you shipped. See [Projects](#projects).           |

**The failure mode to avoid:** treating it as an exam where you produce The Answer. It's a
simulation of a design review with a colleague. Behave like the colleague.

---

## Part II — Building Blocks

### Numbers

Have these loaded. You don't need precision — you need the right order of magnitude, instantly.

#### Latency ladder

| Operation                             | Time            | Relative         |
| ------------------------------------- | --------------- | ---------------- |
| L1 cache reference                    | ~1 ns           | 1×               |
| L2 cache reference                    | ~4 ns           | 4×               |
| L3 cache reference                    | ~15 ns          | 15×              |
| Uncontended mutex lock/unlock         | ~20 ns          | 20×              |
| Main memory (DRAM) reference          | ~100 ns         | 100×             |
| Cache miss (the number from guide 01) | ~200–300 cycles | —                |
| System call                           | ~0.1–1 µs       | ~1,000×          |
| Context switch                        | ~1–5 µs         | ~10,000×         |
| NVMe SSD random read                  | ~20–100 µs      | ~100,000×        |
| SATA SSD random read                  | ~100–500 µs     | —                |
| Round trip within a datacenter        | ~0.5 ms         | ~500,000×        |
| **HDD seek**                          | **~5–10 ms**    | **~10,000,000×** |
| Round trip US ↔ Europe                | ~150 ms         | —                |

**The two ratios that drive every storage design:**

- **Memory is ~1,000× faster than SSD; SSD is ~100× faster than a disk seek.** This is why caching
  is the entire discipline.
- **A disk seek costs more than 10 million L1 references.** Which is why B-trees optimize for
  _fewer, larger_ reads rather than fewer comparisons — see [Indexes](#indexes).

#### Throughput

| Medium                  | Bandwidth                | IOPS                |
| ----------------------- | ------------------------ | ------------------- |
| DRAM                    | 20–100 GB/s              | —                   |
| NVMe SSD (PCIe Gen4 ×4) | ~7 GB/s                  | 500k–1M             |
| SATA SSD                | ~550 MB/s                | ~50k–100k           |
| HDD (7,200 rpm)         | ~150–250 MB/s sequential | **~100–200 random** |
| 10 GbE                  | 1.25 GB/s                | —                   |
| 25 GbE                  | 3.1 GB/s                 | —                   |
| 100 GbE                 | 12.5 GB/s                | —                   |

**The HDD line is the one to internalize.** ~150 MB/s sequential but only ~150 random IOPS. That
ratio — three orders of magnitude between sequential and random — is _the_ reason log-structured
filesystems and LSM trees exist, and it's the foundation of WAFL's "write anywhere" design. If you
can explain that in one sentence, you've demonstrated you understand storage rather than just
memorizing it.

#### Arithmetic shortcuts

- 86,400 s/day ≈ **10⁵**. So 1,000 QPS ≈ 10⁸ requests/day.
- 1 year ≈ **3 × 10⁷** seconds.
- 2¹⁰ ≈ 10³ · 2²⁰ ≈ 10⁶ · 2³⁰ ≈ 10⁹.
- 1 million items × 1 KB = **1 GB**. Most capacity estimates reduce to this one.

---

### Caching

Every storage system is a cache hierarchy. This is the most likely deep-dive topic for this role.

**Eviction policies:**

| Policy         | How it works                               | Good for                           | Weakness                                    |
| -------------- | ------------------------------------------ | ---------------------------------- | ------------------------------------------- |
| **LRU**        | Evict least recently used                  | General purpose, temporal locality | A single large scan flushes the whole cache |
| **LFU**        | Evict least frequently used                | Stable, skewed access patterns     | Slow to adapt; old hot items linger         |
| **FIFO**       | Evict oldest inserted                      | Trivially cheap                    | Ignores access entirely                     |
| **ARC**        | Adaptive balance of recency and frequency  | Mixed workloads                    | Patented history, more state                |
| **CLOCK**      | Approximate LRU with a reference bit       | Low overhead, no list surgery      | Approximate                                 |
| **2Q / LRU-K** | Separate probationary and protected queues | **Scan resistance**                | More tuning                                 |

**The scan-resistance point is the good one.** Plain LRU is catastrophic under a sequential scan — a
backup job reading every block evicts the entire working set. Real storage caches use segmented
approaches for exactly this reason. Volunteering that shows you've thought past the textbook.

**Write policies:**

| Policy            | Behavior                                  | Tradeoff                                                                                 |
| ----------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| **Write-through** | Write to cache and backing store together | Safe, slow — every write pays backing latency                                            |
| **Write-back**    | Write to cache, flush later               | Fast, loses data on crash unless the cache is durable (NVRAM — this is what NetApp does) |
| **Write-around**  | Write to backing store, bypass cache      | Avoids polluting cache with write-once data                                              |

**Invalidation is the hard part.** TTL is simple and stale; explicit invalidation is correct and
easy to get wrong; versioning avoids the problem by making stale entries detectable. Say which and
why.

**In C++, the standard implementation** is a hash map from key to list iterator, plus a
doubly-linked list ordered by recency. Both operations O(1). `std::list::splice` moves a node to the
front without invalidating iterators — that's the detail that makes it work, and it's worth naming.

---

### Concurrency

The JD names concurrency explicitly. Expect to be pushed here.

#### Threading models

| Model                    | Shape                                       | When it's right                                                |
| ------------------------ | ------------------------------------------- | -------------------------------------------------------------- |
| **Thread per request**   | One thread per connection                   | Low concurrency, simple code                                   |
| **Thread pool + queue**  | Fixed workers pulling from a shared queue   | The default. Bounded resource usage                            |
| **Event loop / reactor** | Single thread, non-blocking I/O, epoll      | Many idle connections                                          |
| **Shard per core**       | Partition state so each core owns its slice | **Highest performance — no shared mutable state, so no locks** |

**Shard-per-core is the answer that impresses at a storage company.** It's how modern high-
performance storage stacks are built (SPDK, Seastar, ScyllaDB): pin a thread per core, partition the
data by key, and route requests to the owning core. Locking disappears because sharing disappears.
The cost is cross-shard operations and load imbalance if the partitioning is uneven. Name both.

#### The locking ladder — climb only as far as you must

1. **No sharing.** Partition the data. Always try this first.
2. **One coarse mutex.** Correct, simple, and often fast enough. _Start here and say you're starting
   here._
3. **Reader-writer lock.** Only helps if reads massively dominate; `shared_mutex` has real overhead
   and can be slower than a plain mutex under mixed load.
4. **Fine-grained / striped locks.** Lock per bucket or per shard. More parallelism, more deadlock
   surface — establish a lock ordering and say so.
5. **Lock-free (atomics, CAS).** Hard to get right, hard to test, and a memory-ordering minefield —
   see guide 01's memory-model section. Justify it with a measurement, never with a preference.
6. **RCU / hazard pointers.** Read-mostly structures where readers must never block. Reclamation is
   the hard part.

**The mature answer, and the one to actually give:** _"I'd start with a single mutex and measure. If
the profile showed contention, I'd shard the lock by key hash — that's usually enough. I'd only go
lock-free with a benchmark proving it's worth the complexity, because lock-free code is hard to test
and the failure mode is a race that reproduces once a month in the field."_ That's judgment, and it
maps directly onto the argument you already make about predictability over average speed.

**Have ready:** deadlock (and the four conditions), lock ordering, false sharing and `alignas(64)`,
the double-checked locking idiom and why it needs atomics, and why ARM's weak memory ordering
exposes bugs x86 hides. All are in guide 01.

---

### Queues

**Bounded, always.** An unbounded queue converts a throughput problem into an out-of-memory crash —
it doesn't absorb overload, it defers and amplifies it.

**When the queue is full, you have four options, and picking one is the design decision:**

| Strategy        | Behavior                    | Right when                                       |
| --------------- | --------------------------- | ------------------------------------------------ |
| **Block**       | Producer waits              | Producer can afford to slow down                 |
| **Drop newest** | Reject the incoming item    | Load shedding; fresh data isn't special          |
| **Drop oldest** | Evict from the head         | **Telemetry, metrics — newest is most valuable** |
| **Fail fast**   | Return an error immediately | Caller has a fallback                            |

**This is your OpenTelemetry story.** You handled back-pressure by dropping spans rather than
blocking, because the design rule was _telemetry must never crash or stall the application_. That's
a real, specific, defensible answer to a question interviewers ask abstractly — use it.

**Also know:** single-producer/single-consumer ring buffers can be lock-free with just two atomic
indices and acquire/release ordering; MPMC is substantially harder. Batching improves throughput and
hurts latency — always both.

---

### Indexes

The decision that shapes any storage system. Know the three and their criteria.

| Structure      | Read                       | Write                     | Range queries | Amplification                      |
| -------------- | -------------------------- | ------------------------- | ------------- | ---------------------------------- |
| **Hash index** | O(1)                       | O(1)                      | ✗ **No**      | Low read, low write                |
| **B+-tree**    | O(log_B n), 3–4 disk reads | O(log_B n), random writes | ✓ Excellent   | **Read-optimized**, high write amp |
| **LSM tree**   | O(levels), Bloom-filtered  | O(1) amortized append     | ✓ Good        | **Write-optimized**, high read amp |

**The B-tree sentence** (also in the Big-O guide, and worth saying here too): _"A B-tree and a
balanced BST are both logarithmic in comparisons, but the B-tree's log is base-hundreds instead of
base-2, so it's 3 levels deep instead of 30. When every level is a disk read, that difference is the
entire design."_

**The LSM sentence:** _"LSM turns random writes into sequential appends, which matters enormously on
spinning disks — three orders of magnitude between random and sequential IOPS — and still matters on
SSDs because of erase-block granularity and write amplification. You pay for it on reads, which is
why Bloom filters are standard: they answer 'definitely not here' without a disk read."_

**Bloom filters:** probabilistic, no false negatives, tunable false positives. O(k) hashes. The
right answer whenever "avoid a lookup that's usually going to miss" comes up.

---

### Durability

**"When is a write safe?" is the question underneath most storage design.**

**Write-ahead logging (WAL):** append the intent to a sequential log and `fsync` it, _then_ apply
the change to the main structure. On crash, replay the log. Sequential log writes are fast; the
random main-structure update can be lazy. This is the single most reusable durability pattern —
databases, filesystems, and NVRAM-backed storage controllers all do it.

**Copy-on-write (the WAFL approach):** never overwrite live data. Write new blocks, then atomically
swap the root pointer. The on-disk state is _always_ consistent, so there's no journal and no
`fsync` ordering puzzle — and snapshots become O(1) because the old tree is already there. Covered
in depth in guide 03.

**The layers a write passes through, and where it can be lost:**

application buffer → OS page cache → device write cache → stable media

`fsync` pushes through the page cache. Whether it pushes through the _device_ cache depends on the
device honoring flush commands — which is exactly why enterprise storage uses battery- or
capacitor-backed NVRAM: acknowledge as soon as it's in NVRAM, which is durable but ~1,000× faster
than disk. **That's the design trick worth being able to explain.**

**Say the acknowledgment invariant explicitly:** _"Nothing is acknowledged to the client until it's
in stable storage — and 'stable' here means NVRAM, not disk, which is what makes the latency
acceptable."_

---

### Replication

| Mode             | Behavior                            | RPO                | Cost                                                             |
| ---------------- | ----------------------------------- | ------------------ | ---------------------------------------------------------------- |
| **Synchronous**  | Ack only after the replica confirms | **Zero data loss** | Write latency = network round trip; a slow replica stalls writes |
| **Asynchronous** | Ack locally, ship later             | Loss window = lag  | Fast, but recent writes die with the primary                     |
| **Semi-sync**    | Wait for one replica, not all       | Small window       | A middle ground worth naming                                     |

**The distance argument:** synchronous replication over 100 km adds ~1 ms round trip _per write_.
That's why MetroCluster (sync, campus/metro distances) and SnapMirror (async, arbitrary distance)
are different products solving different problems. Knowing _why_ they're different is more valuable
than knowing that they are.

**Quorum:** with N replicas, W + R > N guarantees a read sees the latest write. N=3, W=2, R=2 is the
standard configuration and worth being able to recite. Majority quorum (⌊N/2⌋+1) is what makes
consensus protocols work.

**Split-brain** is the failure mode that matters: two nodes both believe they're primary and both
accept writes. Prevented by quorum, fencing, or an external tiebreaker/witness. **Name this
unprompted** in any HA design — it's the failure interviewers probe for.

---

### Partitioning

**Sharding strategies:**

| Strategy               | Behavior                 | Problem                                                                           |
| ---------------------- | ------------------------ | --------------------------------------------------------------------------------- |
| **Range**              | Keys A–M here, N–Z there | Hotspots; sequential keys all land on one shard                                   |
| **Hash**               | `hash(key) % N`          | Even distribution, but **no range queries**, and changing N reshuffles everything |
| **Consistent hashing** | Keys and nodes on a ring | Adding a node moves only ~1/N of keys                                             |

**Consistent hashing with virtual nodes** is the standard answer: each physical node owns many
points on the ring, which smooths distribution and makes rebalancing incremental. Know that adding a
node moves ~1/N of the data rather than nearly all of it — that's the entire reason the technique
exists.

**Rebalancing is the hard part, not the hashing.** Moving data while serving traffic requires
double-writes or a read-through-both period, and a way to know when the move is complete. Saying
that shows you've thought about operating the system, not just designing it.

---

### Resilience

**Idempotency.** A retry must be safe. Achieve it with request IDs and a dedup window, or by
designing operations to be naturally idempotent (`set x = 5`, not `increment x`). **You've shipped
this** — the Affordit CQRS/message-broker work involved delivery semantics and idempotency. Use it.

**Timeouts.** Every remote call needs one. No timeout means a hung dependency becomes a hung caller,
which becomes a cascading outage. Timeouts should be shorter than the caller's own deadline.

**Retries with exponential backoff and jitter.** Without jitter, retries synchronize and produce a
thundering herd that keeps a recovering system down.

**Circuit breakers.** After N consecutive failures, stop calling and fail fast; probe periodically.
Turns a slow cascading failure into a fast local one.

**Graceful degradation.** Serving stale data beats serving nothing, for most read paths. Decide _per
operation_ whether that's true — for storage metadata, often it isn't.

**Failure domains.** Don't put both replicas in the same rack, on the same power supply, or behind
the same switch. Ask what the failure domain is; it's a question that signals operational
experience.

---

### Observability

**Design for debuggability, and say so unprompted. This is your differentiator** — you built an
observability stack for a multi-threaded ADAS system, so you can speak to it from experience while
most candidates treat it as an afterthought bullet.

What to include in a design:

- **Metrics** — counters and latency histograms per operation. Histograms, not averages: an average
  latency hides exactly the tail that matters commercially.
- **Tracing** — a request ID propagated across component boundaries so a slow request can be
  attributed. This is the thing that turns "the system is slow" into "the index lookup is slow."
- **Structured logs** at boundaries and on error paths, with stable attribute names.
- **The design rule:** _instrumentation must never crash or stall the thing it observes._ Isolated
  exporters, swallowed-and-counted failures, bounded queues that drop rather than block.

**The line to use:** _"I'd want a latency histogram per operation and a request ID propagated
through the stack from day one. I built the telemetry layer for a multi-threaded ADAS stack, and the
thing I took away is that observability added afterward tells you a system is slow, while
observability designed in tells you why."_

---

## Part III — Practice Problems

### Component

**The most likely question type for this role. Practice these out loud with a timer.**

#### 1. Thread-safe LRU cache

Already on your Day 3 plan. The extensions are where the interview goes:

- **Where does the lock go?** One mutex around both structures is correct and simple. Note that even
  `get` mutates state (it reorders the list), so a reader-writer lock buys you nothing without
  redesign — **this is the trap, and spotting it unprompted is a strong signal.**
- **Sharding:** N independent caches keyed by `hash(key) % N`. Near-linear scaling, but the LRU
  ordering becomes per-shard rather than global — approximate, and usually fine. Name the
  approximation.
- **TTL:** lazy expiry on access is cheap but leaks memory for never-touched keys; a sweeper thread
  costs a thread; a min-heap by expiry costs O(log n) per insert.
- **Scan resistance:** see [Caching](#caching). Segmented LRU or 2Q.
- **The invariant:** the map and the list always hold exactly the same key set.

#### 2. Thread pool

- Bounded task queue (`std::function<void()>` or a type-erased alternative — mention the allocation
  cost of `std::function` and that a small-buffer-optimized alternative avoids it).
- Condition variable for worker wakeup; **spurious wakeups mean you predicate the wait**.
- **Shutdown is the interesting part**: drain vs. discard, joining workers, and making sure no task
  is enqueued after shutdown begins. Most candidates forget shutdown entirely.
- Extensions: work stealing (per-worker deques, steal from the back), priority tiers, and why an
  unbounded queue is a bug.

#### 3. Bounded producer-consumer queue

- Mutex + two condition variables (not-full, not-empty). Classic and correct.
- Then: lock-free SPSC ring buffer with two atomic indices, acquire/release ordering, and a
  power-of-two capacity so the modulo is a mask. Explain why MPMC is much harder.
- False sharing: pad the head and tail indices to separate cache lines, `alignas(64)`. **Mentioning
  this unprompted is a strong systems signal.**

#### 4. Slab / pool allocator

Very ONTAP-adjacent. Fixed-size blocks carved from large chunks, free list threaded through the free
blocks themselves (zero metadata overhead), O(1) alloc and free, no fragmentation within a class.
Per-CPU or per-thread caches to avoid lock contention on the hot path. Tradeoff: internal
fragmentation when object sizes don't fit the size classes.

#### 5. Async logger

Your OTel experience applies directly. Lock-free or lightly-locked ring buffer, background flusher
thread, bounded with a drop-oldest policy, timestamps captured at the call site rather than at
flush. Tradeoff: log loss on crash unless you flush synchronously at fatal severity.

#### 6. File descriptor / handle table

Array indexed by a small integer, free-list for reclaimed slots, generation counter in the handle to
catch use-after-close (a stale handle has the wrong generation and is rejected rather than silently
aliasing a new file). **The generation-counter detail is the one that impresses.**

---

### Storage

Larger problems. For each, the framing that gets you to a good answer fast:

#### Design a key-value store

Start single-node. Ask the read:write ratio — it picks your index. Write path: WAL → memtable →
flush to sorted files → compact. Read path: memtable → Bloom filter → files. Then discuss compaction
strategy (leveled vs. tiered: read amp vs. write amp), then only if asked go distributed with
consistent hashing and quorum replication.

#### Design a filesystem metadata layer

Inodes, directory entries, and the block map. The interesting decisions: how directories are indexed
(linear vs. hashed vs. B-tree — matters enormously for a million-entry directory), how large files
are addressed (direct blocks, then indirect, double-indirect), and crash consistency (journaling vs.
copy-on-write). Guide 03's WAFL material is the deep-dive content.

#### Design snapshots

The COW answer: retain the old root pointer instead of freeing its blocks; the snapshot is O(1)
regardless of dataset size. Then the hard parts, which is where the real conversation is — block
reference counting, space accounting (deleting a file may free nothing), and snapshot deletion
requiring you to determine which blocks are no longer referenced by anything.

#### Design a replication pipeline

Snapshot-based delta shipping: take a snapshot, compute the block-level delta against the last
replicated snapshot, ship it, and atomically make it visible at the destination. Discuss sync vs.
async and RPO, network efficiency (dedupe and compress in flight), resumability after interruption,
and how you verify the destination matches.

#### Design a rate limiter / QoS layer

Token bucket (allows bursts, which is usually what you want) vs. leaky bucket (smooths output) vs.
sliding window. Where the state lives is the real question — per-node is simple and lets aggregate
traffic exceed the limit; shared state is accurate and adds a hop on every request. Storage-specific
angle: QoS on IOPS _and_ bandwidth, because a thousand 4 KB reads and ten 1 MB reads are very
different loads.

#### Design a dedupe engine

Hash each block, keep a hash → block-address table, and refcount shared blocks. The real decisions:
inline (costs write latency) vs. post-process (costs a background scan and temporary space);
fixed-block vs. variable/content-defined chunking; and how you handle hash collisions — byte compare
to be safe, or trust a strong hash and say why.

---

### Walkthrough

**"Design a thread-safe, bounded cache for filesystem metadata."** A realistic question for this
role. Here's the shape of a strong 45 minutes.

**1. Clarify (5 min).**

> "A few questions first. What's being cached — inodes, directory entries, or block maps? What's the
> read:write ratio? Is this a single node, or does it need coherence across a cluster? What's the
> memory budget? And on a miss, do we block the caller or is there an async path?"

_Assume the answers: inodes, 95:5 read-heavy, single node for now, 4 GB, blocking on miss._

**2. Estimate (3 min).**

> "200 bytes per inode plus overhead — call it 256. 4 GB gives us about 16 million entries. If the
> filesystem holds 100 million files, we're caching roughly 16% of them, so the hit rate depends
> entirely on locality and the eviction policy earns its keep. That's the number I'd want to measure
> first."

**3. Interface (5 min).**

```cpp
class InodeCache {
public:
    InodeCache(size_t capacity_bytes, size_t shard_count);

    // Blocks on miss while loading from disk.
    std::shared_ptr<const Inode> get(InodeId id);

    void insert(InodeId id, std::shared_ptr<const Inode> inode);
    void invalidate(InodeId id);          // on external modification
    CacheStats stats() const noexcept;    // hits, misses, evictions, bytes
};
```

> "`shared_ptr<const Inode>` because a reader must be able to hold an inode after it's evicted —
> otherwise eviction invalidates a pointer someone is using. `const` because cached entries are
> immutable; a modification produces a new entry rather than mutating a shared one, which sidesteps
> a whole class of races. And I'm putting `stats()` in the interface from the start, deliberately."

**4. Sketch (8 min).**

> "N shards, each an independent LRU: a hash map from inode ID to list iterator, plus a
> recency-ordered intrusive list, under one mutex per shard. Route by `hash(id) % N`. With 16 shards
> we get roughly 16× the lock parallelism, and the cost is that LRU ordering is per-shard rather
> than global — approximate, which is fine for a cache. On a miss: take the shard lock, confirm the
> miss, release the lock, read from disk, re-acquire, insert. **Releasing the lock across the I/O is
> the important part** — holding a mutex across a 100 µs disk read would serialize the entire shard.
> That does mean two threads can miss on the same inode concurrently, so I'd either accept the
> duplicate read or install a placeholder entry that the second thread waits on."

**5. Deep dive (12 min).** Pick eviction and coherence:

> "Plain LRU is a problem here. Any full-filesystem traversal — a backup, a `find`, an antivirus
> scan — touches every inode once and flushes the entire working set. I'd use a segmented LRU: new
> entries land in a probationary segment and only get promoted on a second access. A scan populates
> probation and never disturbs the protected set. Costs a bit of bookkeeping and a tuning parameter
> for the split.
>
> The invariant is that the map and the list hold exactly the same key set, and bytes-used equals
> the sum of the entries. I'd assert both in debug builds.
>
> On coherence: if another node or the local write path modifies an inode, this cache is stale. For
> a single node, the write path calls `invalidate` — and I'd want that to be structurally enforced
> rather than remembered, ideally by routing all inode writes through one function that does both.
> That's the same reasoning as a code generator being a single source of truth: a manual step
> somebody has to remember is a bug with a delay fuse."

**6. Failures and tradeoffs (7 min).**

> "What breaks: a hot shard if the hash is uneven — I'd measure per-shard hit rates rather than
> assume. Memory accounting drifting if entries vary in size. And unbounded growth if invalidation
> is missed, which is the failure I'd instrument for specifically.
>
> The main tradeoff is shard count: more shards means less contention and worse LRU quality, plus
> more per-shard fragmentation. I'd start at 16, measure contention with a lock profiler, and
> adjust. If the profile came back with contention still dominating, the next step wouldn't be more
> shards — it'd be moving to a per-core model where each core owns its inode range and there's no
> shared mutable state at all.
>
> I'd also want a latency histogram on `get`, split by hit and miss, because the average will be
> dominated by hits and hide everything interesting about the miss path."

**Notice what that answer does:** it asks before designing, states an invariant, names the lock-
across-I/O trap, chooses scan-resistant eviction with a reason, connects to a real project, and ends
with what it would _measure_ rather than what it's certain about. That's the whole method.

---

## Part IV — Your Material

### Projects

Anchor design answers in things you shipped. The recruiter email says explicitly that they want you
to "draw from experiences you've had in previous projects."

| Design topic                         | Your evidence                                                                                                                        |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| **Back-pressure / overload**         | OTel — exporters isolated, failures swallowed and counted, spans dropped rather than blocking. Telemetry must never stall the app.   |
| **Observability by design**          | OTel — RAII span scopes, atomic counters, stable attribute conventions                                                               |
| **Resource lifetime / shutdown**     | OTel — the static destruction-order crash and the weak-pointer singleton fix                                                         |
| **Contracts between components**     | Schema Bridge — codegen as single source of truth; `static_assert`s on `sizeof` and `offsetof` making layout a compile-time contract |
| **Dependency ordering**              | Schema Bridge — topological sort over the type reference graph, cycle detection failing the build                                    |
| **Compile-time vs. runtime safety**  | ORM — CRTP + reflection moving schema errors from runtime to build time                                                              |
| **Idempotency / delivery semantics** | Affordit — CQRS with a message broker                                                                                                |
| **Automation and platform limits**   | Dependency Sync — the 20-repo YAML ceiling, and the hashtag auto-resolve incident                                                    |
| **Caching and build performance**    | AKS + Bicep — remote build execution and caching                                                                                     |
| **Ordered rollout / lifecycle**      | Azure IoT nested edge — device lifecycle, cert auth, ordered manifest rollout                                                        |
| **Cross-platform / ABI**             | Cross-compiled aarch64 and x86 — alignment, endianness, weak memory ordering                                                         |

**The honest gap, and how to hold it.** You haven't designed a filesystem or a distributed storage
system. Say it early, once, without flinching: _"I haven't built storage systems — here's how I'd
approach this, and tell me where the storage-specific reality differs from my assumptions."_ That's
a strength when volunteered and a weakness when discovered. It also converts the interview into
collaboration, which is what they said they're grading.

---

### Rapidfire

| Question                                   | Answer                                                                                                                                                         |
| ------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| First thing you do in a design interview?  | Clarify requirements and explicitly agree what's out of scope. Never design against an unstated spec.                                                          |
| Read-heavy vs. write-heavy — what changes? | Read-heavy: cache and index (B-tree). Write-heavy: log and compact (LSM). It's the first question I ask.                                                       |
| Where do you put the lock in a cache?      | One mutex per shard. Note that `get` mutates recency order, so a reader-writer lock doesn't help without a redesign.                                           |
| Why not hold the lock across a disk read?  | It serializes the whole shard for ~100 µs. Release it, do the I/O, re-acquire — and handle the duplicate-miss race explicitly.                                 |
| Bounded or unbounded queue?                | Always bounded. Unbounded turns an overload into an OOM crash instead of shedding load.                                                                        |
| Queue is full — what do you do?            | Depends on the data. For telemetry, drop oldest — newest is most valuable and stalling the producer is unacceptable. That's what I did on the OTel work.       |
| Sync or async replication?                 | Zero-RPO requirement forces sync, and you pay a network round trip per write. Async is fast with a loss window equal to the lag. Distance decides in practice. |
| How do you prevent split-brain?            | Quorum, fencing, or an external witness. Two nodes both accepting writes is the failure mode that actually loses data.                                         |
| When is a write durable?                   | When it's on stable media — which for enterprise storage means battery-backed NVRAM, not disk. That's what makes the acknowledgment latency acceptable.        |
| Why are B-trees right for disk?            | The base of the logarithm is the branching factor, so depth is 3–4 instead of 30. Each level is a disk read; that's the whole argument.                        |
| Consistent hashing — why?                  | Adding a node moves ~1/N of the keys instead of nearly all of them. Virtual nodes smooth the distribution.                                                     |
| How would you scale a single-node design?  | Partition by key first — no shared mutable state is better than any locking scheme. Then replicate for availability, then worry about cross-shard operations.  |
| What's the invariant of your design?       | Have one ready for anything you design. It's the most senior-sounding sentence available to you.                                                               |
| How do you know your design is right?      | I don't — I know what I'd measure and what result would make me change it. Naming that is the answer.                                                          |
