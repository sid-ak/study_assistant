# Sync

> Part of the Projects guide — [back to index](../README.md)

<a id="sync"></a>

## The situation

Cross-team dependencies were drifting. Library syncs between repositories were manual and therefore
inconsistent — different people did them at different times with different results. **You identified
this as a slow-moving correctness problem nobody owned**, and rather than doing the sync correctly
once, you decided to build a system that would do it correctly forever.

## What you built

A **fully automated "one command" sync tool** — Bash driving the `az` CLI against the Azure DevOps
API — that managed external repositories with no human in the loop, running weekly.

**Why `git clone --bare`** — this is a good depth question and you have a real answer:

| Clone type   | What it is                                                                                  | Why not / why                                                                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full clone   | Git metadata **plus** a checked-out working directory                                       | Heavy. You pay disk and time to materialize files you'll never read. Worse: files exist on disk that a pipeline step could accidentally modify.                  |
| `--mirror`   | Bare, plus maps _all_ refs including remote-tracking refs and sets up for exact replication | Too aggressive — it brings over refs you didn't want and configures the repo for a push-mirror relationship you're not asking for.                               |
| **`--bare`** | **Git metadata only. No working directory.**                                                | **Fastest, smallest, and there's no working tree to accidentally modify mid-pipeline. It's the cleanest representation of "I want the history, not the files."** |

## The two hard problems

**Problem 1 — an undocumented platform ceiling.** Azure Pipelines YAML has a **20-repository limit**
per file. You discovered this by hitting it. Rather than bloating or restructuring the main
template, you wrote Bash that **dynamically generates additional YAML files** once the limit is
reached — so the main template stays clean and readable, and the system scales past a constraint the
platform doesn't document.

**Problem 2 — the "hashtag" incident.** This is the more instructive one, and the more valuable
interview story.

After rollout, the project manager noticed that **work items were closing on their own.**

Root cause: Git commits in the synced repositories contained hashtags in their messages. Azure
DevOps parses `#1234` in a commit message as a command to resolve work item 1234. Your bare clones
were replaying those commits into the DevOps portal, which was dutifully interpreting them and
closing tickets that had nothing to do with anything — "zombie" ticket closures.

**What makes this a good story:**

- The bug was **not in your code.** It was an interaction between your code and a platform behavior
  you didn't know existed. That's the most realistic kind of production bug.
- You initially felt stuck, because it was platform-level behavior you didn't control.
- **You took ownership anyway** rather than declaring it out of scope.
- You researched the Azure DevOps API and modified the script to **temporarily toggle off the
  auto-resolve setting for the duration of the sync**, then restore it.
- You **documented the edge case** so the broader DevOps org wouldn't rediscover it independently.

That last point is the difference between fixing a bug and improving an organization.

## Results

- **100% automated** updates every Friday. Zero manual input.
- Eliminated dependency drift across teams.
- Eliminated the risk of accidental work-item data loss in Azure DevOps.
- Documented a platform edge case for the wider organization.

<a id="syncstar"></a>

??? note "STAR"

    **Situation.** Our cross-team library dependencies were drifting because syncs between repositories
    were done manually and inconsistently — different people, different times, different results. Nobody
    owned it, so it was a slow-moving correctness problem that only surfaced as confusing build failures
    downstream.

    **Task.** I decided the right fix wasn't to do the sync correctly once, it was to make manual
    syncing unnecessary. I set out to build a fully automated tool that managed the external repos end
    to end with no human in the loop.

    **Action.** I built it as a Bash script driving the `az` CLI against the Azure DevOps API, using
    `git clone --bare` for the sync itself — bare because it pulls only Git metadata with no working
    directory, so it's faster, uses far less disk, and there's no checked-out tree for a pipeline step
    to accidentally modify mid-run. Two things made it harder than expected. First, I hit an
    undocumented 20-repository limit in Azure Pipelines YAML, so rather than bloating the main template
    I wrote logic to dynamically generate additional YAML files once the ceiling was reached, keeping
    the primary template clean. Second — and this one was on me to own — after rollout our PM noticed
    work items closing by themselves. I traced it to commits in the synced repos containing hashtags,
    which Azure DevOps parses as commands to resolve work items. My bare clones were replaying those
    commits and the portal was closing unrelated tickets. It was platform behavior I didn't control and
    I was stuck for a bit, but I researched the DevOps API and modified the script to temporarily toggle
    off the auto-resolve setting during the sync and restore it afterward.

    **Result.** Fully automated updates every Friday with zero manual input, and dependency drift
    stopped being a thing we dealt with. It also eliminated the risk of accidental work-item data loss.
    I documented the hashtag edge case so the broader DevOps team wouldn't independently rediscover it —
    that felt like the more durable part of the fix.

<a id="syncscript"></a>

??? note "Scripts"

    ### Version A — Ownership / automation framing (~70s)

    > Our cross-team library dependencies kept drifting because the syncs were manual, and manual meant
    > inconsistent. Nobody owned it, so it showed up as confusing build failures downstream that were
    > nobody's problem in particular.
    >
    > I decided the fix wasn't to do the sync properly once — it was to make doing it manually
    > unnecessary. So I built a one-command automated sync, Bash driving the `az` CLI against the Azure
    > DevOps API.
    >
    > I used `git clone --bare` deliberately. A full clone checks out a working directory, which is
    > heavy and — more importantly — puts files on disk that a later pipeline step could accidentally
    > modify. A mirror is too aggressive about refs. Bare gives you exactly the Git metadata and nothing
    > else, which is the cleanest thing to sync.
    >
    > Two things made it interesting. I hit an undocumented 20-repo limit in Azure Pipelines YAML, so I
    > wrote logic to dynamically generate additional YAML files once we crossed it rather than bloating
    > the main template.
    >
    > And then the one I actually learned from. After rollout, our PM noticed work items closing on
    > their own. It turned out commits in the synced repos had hashtags in the messages, and Azure
    > DevOps parses those as commands to resolve tickets. My sync was replaying those commits and the
    > portal was dutifully closing unrelated work items. That was platform behavior, not my code, and I
    > was stuck for a bit — but I took ownership of it, researched the DevOps API, and scripted a
    > temporary toggle of the auto-resolve setting for the duration of the sync.
    >
    > End result was 100% automated weekly updates with zero manual input. And I documented that edge
    > case so nobody else in the org had to rediscover it, which honestly felt like the more useful
    > half.

    ### Version B — "Tell me about a mistake" (~50s)

    > I automated our cross-team repository syncs, and after rollout our PM told me work items were
    > closing on their own. That was me.
    >
    > The synced commits contained hashtags in their messages, and Azure DevOps interprets a hashtag
    > followed by a number as a command to resolve that work item. My bare clones were replaying that
    > history into the portal, which was closing tickets that had nothing to do with the sync.
    >
    > Two things I'd point to. First, I owned it immediately — it was technically platform behavior
    > rather than a bug in my script, and it would have been easy to frame it that way, but the impact
    > was mine and so was the fix. Second, I'd been thinking about the sync purely as a data movement
    > problem and hadn't considered that the _content_ of what I was moving would be interpreted by the
    > destination system. That's the lesson I actually took: when you automate something, ask what the
    > receiving system does with the payload, not just whether the payload arrives.
    >
    > The fix was an API call to temporarily disable auto-resolve during the sync window. And I wrote it
    > up for the wider DevOps team, because it was the kind of thing that would bite the next person
    > identically.

<a id="syncqa"></a>

??? note "QA"

    **Q: Why `--bare` instead of a full clone or `--mirror`?**

    > A full clone materializes a working directory, which costs time and disk for files the pipeline
    > never reads — and it leaves a checked-out tree that a subsequent step could modify, which makes
    > the sync non-idempotent in a way that's hard to notice. `--mirror` is bare plus it maps _all_ refs
    > including remote-tracking ones and configures the repo for exact push-mirror replication, which
    > was more coupling than I wanted. `--bare` is precisely "the history, none of the files," which is
    > exactly what a sync needs.

    **Q: How did you handle failures mid-sync?**

    > The script was written to be idempotent and re-runnable — a failed run could be re-executed
    > without leaving things half-updated, which matters when you're running unattended weekly. Failures
    > surfaced in the pipeline rather than being swallowed, so a silent no-op wasn't possible. If I were
    > extending it, the next thing I'd add is a dry-run mode and a diff summary so a human could see
    > what _would_ change before a run that touches many repos.

    **Q: Why weekly rather than on every change?**

    > Weekly matched how the consuming teams actually worked — they wanted a predictable, stable
    > dependency snapshot they could plan around, not a moving target that could change under them
    > mid-sprint. Continuous syncing would have meant a build could break at any moment because an
    > upstream team merged something. There's a real tradeoff there between freshness and stability, and
    > for cross-team dependencies I think stability wins. If a team needed something urgently they could
    > trigger a run manually.

    **Q: What would you do differently?**

    > Two things. I'd test against a _realistic_ corpus of commit messages rather than clean ones — the
    > hashtag bug would have shown up immediately in a staging environment with real history. And Bash
    > was the right tool to get it working, but as it grew — dynamic YAML generation, API calls, error
    > handling — it outgrew what Bash is good at. I'd rewrite it in Python for testability, because a
    > shell script with that much logic is very hard to unit test, and untestable automation is a
    > liability once other people depend on it.
