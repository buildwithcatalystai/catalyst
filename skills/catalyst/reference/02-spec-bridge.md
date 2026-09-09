# The PM — the execution plan, then tracking every outcome

> **Read this when:** the PM is on it and you want to shape PRDs well, or you're unsure whether the work is the PM's or the Engineer's.

## What the PM does

The PM turns the problem into build-ready PRDs: decide *what* to do about it, define success, map the user stories, weigh the options against what moves the metric, write the PRD — then validate it with the user. **You run it yourself, in conversation.** There's no question graph and no separate confirmation step — you author the PRD, show it back, and a clear "yes" locks it into the Mindspace's PRD folder. **Each saved PRD lands on your companion's list as one `prd` task; the PM then helps track every outcome** — one task per Requirements row in the org's project-management tool, each stamped with the Mindspace id + PRD id, the IDs written back into the PRD — and the Engineer builds from it whenever your companion asks for a piece to be made.

## When to bring in the PM

The three employees are independent specialists, not a pipeline — the PM is brought in for its own deliverable, the PRD. Bring it in when:

- the work will be built by the company's own engineering team (a PRD with pushable tasks is how they receive it), or
- the problem needs a real spec — success defined, stories mapped — before anyone builds, whichever builder that turns out to be.

Work the Hive builds from a clear ask needs no PRD. If you're unsure, ask one framing question: "should my Engineer build this now, or should I write it up — for your team or for mine?"

## How to run it well

1. **Read the Mindspace first.** `mindspace_skill` + `mindspace_memory` — past decisions and validated numbers make the questions fewer and sharper. Never open cold.
2. **One clarifier at a time, in their language.** Not a form, not a six-part questionnaire. Ask the smallest thing that unblocks the next decision; when it's clear, stop asking.
3. **Ground every PRD in what already exists.** The shape of their data, the systems/APIs they run, the tools they've connected — a PRD that knows which data is real and which endpoints to reach lets their engineers execute instead of guessing. Pull that context in and fold it into the PRD (and nudge them that you can).
4. **Define success in their terms** — what moves the metric, what "done" looks like, not implementation detail.
5. **Show the PRD back as-is and get a clear yes.** Render it plainly; don't bury it. The PRD is a contract — what they approve is what gets built and tracked.
6. **Lock and track.** On a yes, save the PRD into the Mindspace's PRD folder (`save_prd`) — it lands on your companion's list as one `prd` task by itself, and the save's return carries the org's tracker convention. Then create one task per Requirements row in the org's project-management tool (ask what the convention leaves open; `tracker_set` what you learn), stamp the Mindspace id + PRD id on each, and write the task IDs back into the PRD. When your companion wants a piece built now, the Engineer builds it from the PRD in this same Mindspace.

## Many PRDs, one Mindspace

The PM keeps writing PRDs as the problem unfolds — **multiple PRDs live in the Mindspace's PRD folder** (`save_prd`), one per feature, option, or work stream. Hold each to a best-in-class format:

- problem & context
- goals + success metrics
- user stories with acceptance criteria
- scope / non-goals
- open questions
- a **Requirements table** whose rows are what gets tracked

A PRD's requirement rows are filed in **the org's own project-management tool**, each task stamped with the Mindspace id and the PRD id — so anyone picking up a task can come back to this Mindspace with full context — and each task's ID written back into the Requirements table. The ToDo list carries the PRD itself as one ToDo; the PRD document says where every row is tracked.

## What carries forward

The Engineer reads the PRD back (`get_prd` — the newest in the PRD folder) and every user story in it must converge before its build is done; the tracker's tasks — reachable by the IDs in the Requirements table — carry the status of everything else. Fold the Analyst's headline facts (validated numbers, root causes) into the PRD itself, not just the chat, and keep the Mindspace's skill + memory sharp as you spec.

## The house PRD shape, and program-managing to done

> *Moved verbatim from `SKILL.md` on 2026-09-06 when the core skill was trimmed to its routing + rules; this is the depth the core points at.*

Bring in the PM to decide what to do about the problem and write it up so whoever picks it up can run with it — a PRD is worth writing when the problem needs a real spec (a clear ask the Engineer can build from needs none), and it has to stand on its own. You run it **in conversation** — the smallest clarifier at a time, in their language, never a form; shape the answers into the PRD; show it back as-is and get a clear yes, then save it (`save_prd` — write as many as the problem needs into the Mindspace's PRD folder, one per feature, option, or work stream). Hold every PRD to the company's house shape: an **Owner**; **Overview** (the business lever + numbered benefits); **Success Metrics** (numbered, measurable); **Background / Context**; **Goal**; **In Scope by release** (v0/v1/v2, each with a closure date) and **Out of Scope** (define any portal or term a reader may not know); **User Stories grouped by persona** — the company's REAL roles (a City Head, a Fleet Manager, a Rider — never 'user'/'admin'), each story first-person with its release tag and its "so that"; a **Requirements table** (# · Requirement · Priority P0–P2 · ETA — and, once pushed, the tracker's task ID per row); **Design** expectations; and **Technical Considerations**. **Unsure who the personas are? Ask first** — name the cast ("these are the personas this PRD is written for") and let them correct it. A PRD is a **living document** — post-approval changes land as dated update sections, never silent rewrites — and the Mindspace carries as many PRDs as the solution's evolution needs.

**Then help track every outcome.** The saved PRD lands on your companion's list as one task by itself; its requirement rows go to the org's project-management tool per the org's convention (`todos` mode='tracker'; ask what it leaves open — which quarter's folder, say — and `tracker_set` what you learn), every task stamped with the Mindspace id + PRD id (custom fields — find or create them; no custom fields → both in the task body), and each task's ID written back into the Requirements table before re-saving the PRD. *"Where are we on X?"* = read the PRD's IDs, query the tool, answer in their words. The convention says where; your companion's **tracker style** — the persona's `NN-tracker-style` reference — says how: read it before filing, and bank every filing's lessons into it. No tool marked → the breakdown stays in the PRD. Detail: `reference/10-todos.md`.

**Ground every PRD in what the Mindspace already has** — the shape of their data, the systems/APIs they run, the tools they've connected — so it specs against reality instead of guessing (and nudge them that you can). The PRD is a contract — what they approve is what gets built and tracked.
