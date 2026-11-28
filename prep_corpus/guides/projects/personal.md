# Personal Projects — Portfolio & Framing

> Part of the **Projects & Experience** guide — [back to index](README.md) ·
> the AI/ML ones are covered in depth in [04-ai.md](ai.md)

---

## Portfolio

**The portfolio, and what each one is for.**

| Project                                                                                                                                             | What it is                                                                                                               | What it proves here                                                                                                 |
| --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| **[Study Assistant](https://github.com/sid-ak/study_assistant)** — _lead with this_                                                                 | Local, single-user agentic RAG assistant over course materials, answering with citations back to the exact slide or page | Systems design under real constraints, decisions you can defend, storage-adjacent thinking                          |
| **[Cloudflare AI Assistant](https://github.com/sid-ak/cf_ai_assistant)**                                                                            | Real-time stateful chat app on Cloudflare's edge — Angular SSR, Workers AI, Durable Objects                              | Distributed state, session isolation, shipping something live                                                       |
| **[Trade-War Retaliation Pipeline](https://github.com/sid-ak/trade_war_retaliation_prediction_pipeline)** — _master's research, not a side project_ | Leakage-free ML pipeline predicting which sanction instrument a G20 nation deploys                                       | Methodological rigor and honesty about a modest result. Frame it as graduate research — see [Education](../behavioral.md#education) |
| **[JP Morgan Home Value Prediction](https://github.com/sid-ak/JPHomeValue)**                                                                        | Seasonality forecast web app from the JPMC virtual program, May 2022                                                     | Early full-stack breadth; don't spend interview time here                                                           |
| **[VLSI Tester](https://github.com/sid-ak/VLSITester)**                                                                                             | Python test generator for single stuck-at faults — fault collapsing, simulation, D-Algorithm                             | Hardware-adjacent fundamentals; a nice footnote for a systems role                                                  |

---

The top three are AI/ML and have their own file — see [04-ai.md](ai.md) for the Study Assistant
deep dive, the Cloudflare and trade-war projects, and the spoken scripts. The remaining two are
below.

---

## JPMorgan

### JP Morgan Home Value Prediction

**JP Morgan Home Value Prediction** — a single-page app from the JPMC virtual experience program
using Python, Firebase, Angular, and the Google Maps API, with TensorFlow feature selection
driving a seasonality forecast. Mention as early breadth if asked about your background; don't
lead with it.

---

## VLSI

### VLSI Tester

**VLSI Tester** — a Python CLI implementing automatic test generation for single stuck-at faults:
fault collapsing, fault class listing, faulted versus fault-free simulation, and test generation
via the D-Algorithm. _Useful because_ it's the one project on the list that sits closest to
hardware, and it signals you're comfortable a layer below application code.

---

## Why

### If they push on "why side projects at all, at three years in?"

The purpose shifts once you have professional experience. Nobody's checking whether you can code —
your job proves that. **Personal projects now answer one question: what do you do when nobody is
assigning you anything?** Which makes the motivation more informative than the technology.

Your honest motivation for Study Assistant is the strongest of the three standard framings — _"I
wanted to understand how X works, so I built one"_ — and it's the right one for a systems role. You
didn't build a RAG app to have a RAG app; you built one to unwind the whole stack yourself, which is
why everything runs locally and why the eval loop is owned in-house instead of trusted to a vendor.
Say it that way.

---

## Script

The spoken versions (A/B/C) all lead with Study Assistant, so they live with the AI projects —
see [04-ai.md → AIScript](ai.md#aiscript).
