# ToDos — clarifications, requests, PRDs (the `todos` tool)

> **Read this when:** you're about to raise something to another employee, answer what was asked of your companion, set up or use the org's project-management tool, or report "where are we on X".

## One shared ToDo list

Catalyst keeps **one ToDo list per company**. Every employee's list is a filter over it (their user id), and a Mindspace is another filter (its id). Your Wingman and every other employee's Wingman read and write the same rows — that is how work moves between people without leaving the workspace.

**Each row is a conversation** between the requester and the assignee (their Wingmen relay both sides). Three kinds:

| kind | what it is |
|---|---|
| `clarification` | a question only that person can answer |
| `request` | work that person must do |
| `prd` | one task per saved PRD — the PRD's own requirement rows live in the org's **project-management tool**, never as ToDos |

**Status is whose move it is** — the only vocabulary anyone sees, derived per viewer:

- **Waiting for your response** — the ball is with you (addressed to you and unanswered, or your ask came back and it's your move).
- **Waiting for <name>'s response** — you raised it; the ball is with them.
- **You replied** — you answered; it's with the other side now.
- **Completed** (or **Cancelled**).

Every `answer` or `comment` by one side hands the ball to the other, and every state change is a timestamped event — the row's thread is its comments and events in order.

**Assignee is a person, exactly.** `mode='people'` lists everyone on Catalyst in the org with their `user_id` — pass it as `assignee_user_id` so the row is stamped to precisely the right person. A name or email also works (unique match links it); someone not on Catalyst stays name-only and links the moment they join. Never refuse to raise something because "they're not on Catalyst".

## The tool — `todos`

| mode | what it does | who may |
|---|---|---|
| `list` | `scope=mine` (on your companion) · `asked` (they raised) · `mindspace` (this Mindspace) · `open` (whole org). Filters: `status`, `kind`. | anyone |
| `show` | `ref` — one row in full: description, answer, tracked tasks, the thread (replies + events) | anyone |
| `people` | everyone in the org with `user_id · name · email` — look up before addressing | anyone |
| `create` | `title` (required), `kind` (`clarification` · `request`), `body`, `assignee_user_id` (from people) or `assignee` (name / email / `me`), `priority`, `due`, `mindspace` (`current` default · `none`) | anyone |
| `answer` | `ref`, `answer`, `final` (`true` → Completed, `false` → a reply; ball to them) | the assignee |
| `comment` | `ref`, `body` — a reply in the thread; hands the ball to the other side | anyone (a third party's comment moves no ball) |
| `update` | `ref` + `status` / `priority` / `due` / `assignee_user_id` / `assignee` / `title` / `body` / `mindspace` | **content (title, description, priority, due, assignee, Mindspace): only the Wingman of the person who created the row**; `status`: requester or assignee |
| `close` | `ref`, `outcome` (`done` · `cancelled`), `note` | the requester |
| `tracker` | the org's project-management tool + how tasks are stored there | anyone |
| `tracker_set` | save that convention (`app`, `instructions`) after asking your companion | anyone |
| `subtasks` | `ref` — the tasks this todo is tracked with in the org's project-management tool (key · title · status · link) | anyone |
| `track` | `ref` + `subtasks=[{key, title, external_id, url, status?, assignee?, due?}]` (+ `app`; default the org's tool) — register the tool's tasks on the todo so they show inside it; re-tracking an `external_id` refreshes it | requester or assignee |
| `subtask_update` | `ref` + `sub` (key · external_id · id) + `status` (`open` · `in_progress` · `done` · `cancelled`) / `external_status` (the tool's own words) / `url` / `title` — after reading the tool | requester or assignee |

The tool is bound on every surface (Analyst, PM, Engineer; ScratchPad and Mindspace). In the **ScratchPad** `mindspace=current` means *none* — rows land unclassified; move to a Mindspace to classify.

**Any row can carry subtasks** — the tasks it is tracked with in the org's project-management tool: a PRD's requirement rows, or a request that becomes several tasks there. The ToDo stays the conversation; its subtasks say where the work is and how far along it is (n/m done, each with its link — the ToDo drawer lists them). Never a second ToDo per task: `track` them on the row you have.

## How it reaches people — the injection

You never poll the ToDo list. On every `/catalyst` landing (`open_scratchpad`) and every Mindspace entry, the response carries:

- `digest` — counts: `assigned_open` (waiting for your companion's response), `waiting_on_others` (their asks the other side holds), `answers_new` (what came back). Turn it into **one line** in the greeting: *"Two things are waiting on you, and <Name> answered your question on <topic>."* Empty → say nothing.
- `todos_block` — the items themselves, two groups: **Waiting for your companion's response** (their move — relay conversationally, then record with `answer` / `comment` / `update` / `close`) and **Back on what they asked** (answers and completions, shown **once** — tell them, carry it into the work, then `close` what is settled).

At a Mindspace entry the block is filtered to that Mindspace; on landing it is org-wide.

## Etiquette (Polyborg rules, kept)

- A question is **self-contained** — the reader has their own context, not yours.
- Ask for the **fact**, never the reasoning behind why you want it.
- **Relay, then record.** Put the open item to your companion in their words; record their answer immediately and faithfully (`answer`). Never answer on their behalf from your own guess.
- **Close only what you raised.** An assignee replies and completes; the requester closes the loop.
- **Edit only what your companion created.** Title, description, priority, due, assignee and Mindspace of someone else's row are theirs — on it you answer, comment, or move the status. (People can still edit in the browser; this is the Wingman's rule.)
- Never delete — `cancelled` is the terminal state, with a `note`.

## Writing a ToDo — the house format

Bodies, answers and replies are **Markdown, short and sharp** — the ToDo page renders them, and the reader has their own context, not yours.

- **Line one = the ask (or the answer) in one sentence.** No preamble, no repetition of the title, no "sample" or "test" disclaimers, no apologies.
- **Then at most four bullets:** what exactly · why it matters · by when · where it is tracked (a link). Bold only a label (`**By:**`), never a sentence.
- **A reply is one or two lines.** A clarification's answer is the fact, not the reasoning.
- **A ToDo carries the ask, the answer and the links — never the analysis.** Numbers, tables, definitions and findings go to the Mindspace's skill or memory (or the PRD); the row links to them. A thread is not your notebook.
- **A correction edits the description** (`update` + `body`) — one row, one current description. Never a chain of corrective replies; if the thread must know, one line: *"Description updated — the 27 Aug figure was over slot riders, not DAU."*
- Read a row before you touch it: `show` (description, answer, tracked tasks, thread).
- Tighten an over-long description with `update` + `body` the moment you notice it.

Shape (not script):

```
Seed the slot calendar with Bengaluru hub capacity for the week of 15 Sep.
- **What:** onboarding staff per hub → half-day capacity (staff × 8 riders) in the shared sheet
- **Why:** the slot calendar can't publish without it
- **By:** Fri 12 Sep
- **Tracked:** two tasks in Wrike → RoadMaps · JAS 2026 · Rider Onboarding Slots
```

## The org's project-management tool

One connected app can be **marked as where the company tracks work**, with free-text instructions for HOW — companies differ (one folder or initiative per quarter; a space per team; "always ask which sprint"). `todos` mode='tracker' reads it; the Tools setup writes it, and so can you (`tracker_set`) after asking your companion. **If the convention isn't set up, always ask how and where tasks should be stored — then save what you learned.**

**The two Catalyst references are YOUR rule, not the convention's.** On every task you create in that tool, stamp the **Mindspace id** and the **PRD id** as custom fields — find them or create them (`external_tools_discover` → `external_tools_execute`); a tool without custom fields carries both in the task body. That stamp is how any Wingman later finds the work from the Mindspace, whatever the org's filing habits.

**Your companion's own style is the third layer — theirs, not the org's.** The convention says *where* work goes; how *they* like it filed lives in their persona as a reference named `NN-tracker-style` (`user_persona` mode='read' reference=…; `list` shows whether it exists; create it with `write_reference` the first time). Read it right after the convention, before you file. What it holds: how they title tasks; how granular (one task per requirement row, or grouped by story); which folder or initiative they pick and why; the fields they always fill (dates, assignees, importance, custom fields) and the ones they never touch; how they word descriptions; what they want asked each time vs decided for them — and, above all, **what they changed after you filed** (renamed, moved, re-dated, split, deleted). That diff is the strongest signal you get: fold it in the moment you see it, so the next filing needs fewer questions. Same discipline as the skill — facts and preferences, never one-off narrative or tool errors.

## The PM's tracking loop

1. `save_prd` — the approved PRD lands in the Mindspace's PRD folder **and** as one `prd` task on your companion's list (automatic, once per PRD file). Its return carries the PRD id, the Mindspace id, and the org's tracker convention.
2. Read your companion's tracker style (the persona's `NN-tracker-style` reference), then create **one task per Requirements-table row** in the org's project-management tool, per the convention and their style (ask what the two leave open — which quarter's folder, say). Stamp both Catalyst references on each.
3. **Register + write back**: `track` the tasks on the PRD's ToDo (`ref=<the PRD's title>`, one subtask per task with its key, title, external_id and url) so they show inside the ToDo; then add each task's ID to the PRD's Requirements table (an '<App> ID' column) and re-save the PRD (same name — it updates in place). The row and the PRD now both say where every requirement is tracked.
4. **Bank the style** (the Curator, silent): what they picked, how they worded it, what they asked you to change — into the persona's `NN-tracker-style` reference.
5. *"Where are we on X?"* — read the row's `subtasks` (or the PRD's Requirements table), query the tool by those IDs, `subtask_update` what moved (status + the tool's own words), and answer in their words: done / in progress / waiting, and on whom. While you're there, compare the tool with what you filed — every difference updates the style reference.
6. No tool marked → the breakdown stays inside the PRD; the `prd` ToDo is the single tracked item.

## Examples (shape, not script)

- *"Ask <Name> which rate card applies for June"* → `people` (find their user_id) → `create kind=clarification assignee_user_id=<id> title="Which rate card applies for June?" body="For the pricing PRD's pay-out check."` → *"Logged ‘Which rate card applies for June?’ → <Name>. Their Wingman relays it on their next landing."*
- Landing shows `‘Which rate card applies for June?’ — replied by <Name> → "Jun 1–7 interim; Jun 8+ new."` → tell your companion (*"<Name> answered your question on the June rate card"*), fold it into the PRD, `close ref="Which rate card applies for June?" note="In the PRD."`.
- Their reply raises a counter-question → `comment ref="Which rate card applies for June?" body="June — payouts week only."` — the ball goes back to them, timestamped.
- *"<Name> should own the address-list upload"* → `create kind=request assignee="<Name>" …` → if they aren't on Catalyst: *"Logged ‘Address-list upload’ → <Name>. Not on Catalyst yet — it links the moment they join."*
- That request becomes three tasks in the org's tool → `track ref="Address-list upload" subtasks=[{key:'1', title:'…', external_id:'…', url:'…'}, …]` → *"<Name>'s address-list upload now tracks 3 tasks (0 done)."* Later: read the tool, `subtask_update ref="Address-list upload" sub='1' status=done external_status='Completed'`.
- `ref` is always the ToDo's title (or its id when you hold one) — never a number, in a call or in a sentence.
