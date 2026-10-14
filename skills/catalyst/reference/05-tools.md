# Tool catalog — one `coding_workspace__*` surface, narrowed per employee

> Loaded on demand. SKILL.md keeps the lifecycle tools (flow control) + the behavioral one-liners; this is the full per-tool reference. **The live MCP tool schemas (name / args / description) always reach you at call time** — this file is the at-a-glance map of what the surface holds and which employee unlocks what.

## The model: one surface, every gear has all of it

All three gears — the Analyst, the PM, the Engineer — work the **same** `coding_workspace__*` tool surface (the FDE union), whole. Since 2026-10-14 nothing is denied by gear: the sentinel `mode` records the stance, not a tool set, and the FDE `ModeController.DENIED` and the plugin hook's mirror are both empty. What each gear reaches for is discipline:

| Gear (sentinel `mode`) | Reaches for | Leaves alone, by discipline |
|---|---|---|
| **The Analyst** (`deep_analysis`) | read/grep/find + KB + `run_select_query` + `run_python` + `bash` (the plan persists in the Mindspace) | `write`, `edit`, `playwright_test`, `save_prd` — it investigates, it doesn't make |
| **The PM** (`spec`) | the same **plus `save_prd`** (author the plan) and `todos` | the build actions — it shapes, it doesn't build |
| **The Engineer** (`coding` / `vibe_code`) | the full surface (read, write, edit, bash, playwright, automation…) | — |

You never check the mode yourself; the transitions (`start_analysis` / `start_spec` / `start_app_building`) record the stance — see [00-flow-and-tools.md](00-flow-and-tools.md).

**Native host tools are open in every gear** — `Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob`/`WebFetch`/`WebSearch`, native **`Agent`**, `TodoWrite`/`AskUserQuestion`/`Skill`/`SlashCommand`/`ToolSearch`. They act on your companion's own machine; the app and the Mindspace's files live on the workspace and go through `coding_workspace__*` (a file written natively lands on the laptop, not in the app). Plan mode (`EnterPlanMode`/`ExitPlanMode`) stays **blocked** while a session is live — the PM shapes the PRD in conversation and tracks it as a ToDo; there is nothing for plan mode to do.

**External MCP servers are open in every gear** too — a connected Redshift / Slack / Notion MCP is your companion's own tool. For the company's data and the app, the Catalyst tools are the hands that touch the right place.

## Read & understand — live for **every** employee

| Tool | What it's for |
|---|---|
| `read` | Read a file. Supports `offset` + `end_line` / `limit`. |
| `grep` | Search file contents. |
| `find` | List files matching a pattern. |
| `get_repo_map` | File structure + symbol index, kept fresh by a daemon. (Engineer) |
| `get_prd` | Read the PRD — the contract. (PM / Engineer) |
| `db_skill` | The org's **business-understanding** skill for its database — what the business is, its components, how the tables serve each outcome, hard facts + query learnings. **Read this FIRST** (`mode='read'`) for any data work, so you explore tables knowing the business, not cold. Read-only here; the wizard's DB knowledge chat authors it. (Present only once business context has been captured.) |
| `get_all_db_tables` | The lay of the land — every table, its description, its foreign keys. After the skill, start here for data work. Supports a `query` regex + paging. |
| `get_table_detail` | The exact columns + types of specific tables — **column names can't be inferred**; read this before any query/code that touches columns. |
| `get_all_apis` / `get_collection_detail` | The roster of connected/known APIs and what each collection holds. |
| `get_api_endpoint_detail` | The precise request/response shape of specific endpoints. |
| `run_select_query` | **The Warehouse, read** — the org's analytics store, written only by ETL (a job's dump, a derived reporting table), never by an app's transactions; this tool reads it. SELECT/WITH/EXPLAIN, mandatory `LIMIT`, 50-row cap (mysql/postgres/redshift, via-cloud or direct). Answer a question from the data; never where an app keeps its rows. |
| `app_database` | **The app Database, read live** — the transactional store the apps Catalyst builds read and write. `mode='tables'` (every table · its comment · cols · ~rows), `'describe'` (one table's columns, keys, comments), `'query'` (a SELECT with a LIMIT). No snapshot: a column added a moment ago is there on the next call. |
| `run_python` | Your notebook: pandas/numpy + a read-only `query(sql)→DataFrame` on the Warehouse and `app_query(sql)` on the app Database. `df = query("SELECT …")`, then compute — cohorts, distributions, trends, outliers. **State persists across calls.** `mode='interrupt'` aborts a hanging cell (keeps your namespace); `mode='restart'` bounces with explicit `max_mem_mb` (clears namespace, bounds the next workload so a runaway can't take down the EC2). |
| `grep_database_context_files` / `grep_api_context_files` | Search the DB / API docs the user uploaded — the source the schema + API roster were built from. |

## Plan — the PM & the Engineer

| Tool | Purpose |
|---|---|
| `save_prd` | Write a build-ready PRD into the Mindspace's `PRD/` folder — the only home; multiple accumulate, the slug comes from the title, re-saving a name updates it. **Allowed for the PM & Engineer; denied for the Analyst.** Each saved PRD lands on the companion's list as one `prd` task, and the return carries the org's tracker convention + the Mindspace/PRD ids to stamp; the Engineer reads the newest back with `get_prd` when asked to build. |
| `todo_write` | Plan a multi-step change visibly (`.agent/todo.json`; the wizard UI reads it). Mirror the list to the user in chat — the tool's own return string isn't user-visible. |

## Make & change — the Engineer (with one Analyst exception, `bash`)

`write` / `edit` / `playwright_test` are **the Engineer's by discipline** — open to every gear, reached for only when building. `bash` serves the Analyst too (to store the plan / script the investigation — not to make a web app). None of this is a hook deny any more; the boundary is instruction-side.

| Tool | Purpose |
|---|---|
| `app_database_write` | **The writing hand on the app Database** — INSERT/UPDATE/DELETE and DDL on the tables the app owns, one transaction, rows affected back (RETURNING rows too). Comment every table and column you create in the same batch. Denied for the Analyst and the PM; never the Warehouse. |
| `write` | Create or overwrite. Paths relative to `app_root`. (Engineer only) |
| `edit` | Find-and-replace edit. (Engineer only) |
| `bash` | Run a shell command in the project workspace (Engineer **and** Analyst). The dev server is already up — don't reinstall deps or kick off long builds. For the Analyst, use it to persist your working plan in the Mindspace. |
| `playwright_test` | Run a Python Playwright script against the **live URL** (never localhost) — the ONE end-to-end validation tool. (Engineer only) |

## Automation — the Engineer builds it

The making surface also carries the automation families (one executable protocol; one schedule registry):

| Family | Tools |
|---|---|
| Jobs (non-AI shell/http) | `create_job_scaffold`, `edit_job`, `delete_job`, `list_jobs`, `run_job` |
| Schedules (the cron registry) | `add_schedule`, `edit_schedule`, `delete_schedule`, `list_schedules` |
| Triggers (webhook/manual → fan out; `?wait=1` returns an AI Employee's answer; every org has `ask-the-hive` → the Hive Analyst) | `create_trigger`, `edit_trigger`, `delete_trigger`, `list_triggers`, `fire_trigger` |
| Trigger Services (reach an employee from Slack/…; a message = a trigger fire, answer back in-thread) | `list_trigger_services` (read first), `wire_trigger_service`, `unwire_trigger_service`; or `create_trigger(service=, conversation=)` to create + wire at once |
| Subagents (autonomous AI checks) | `create_subagent_scaffold`, `edit_subagent`, `delete_subagent`, `list_subagents`, `run_subagent` |
| Connected external tools | `external_tools_discover`, `external_tools_execute` |

(A script, a scheduled job, an AI check, an ML model, or a web app **all build here** — the Analyst is for *understanding* data + reasoning, never for shipping one of these.)

## Sub-tasking & living context

| Tool | Purpose |
|---|---|
| `Agent` (`coding_workspace__Agent`, or native `Agent`) | Spawn a side investigation in parallel — read-heavy questions ("read these 6 files and tell me which import the deliveries model"). Keep *writes* in the main flow so they land in order. |
| `mindspace_skill` / `mindspace_memory` | THIS Mindspace's durable skill + living memory. Read/recall on entry; write the moment you learn. (Bound for the Analyst + Engineer.) |
| `user_persona` | Your companion's working model — how they work, not just who they are: role, goals, how they decide and solve problems, what they know, how they like things shaped, how they communicate, their people, rhythm, history, judgment, when to push back, what you may do alone (`read` / `write` / `write_reference` / `list`; the crux arrives as `persona_block` on entry). Learn from every correction, edit, approval, rejection and decision (`reference/11-persona.md`). An empty read is a **first meeting**: greet them as one and learn them through the work — never announce it, never interview. Their **tracker style** lives in its `NN-tracker-style` reference: read it before filing in the org's project-management tool; update it after every filing and whenever the tool differs from what you filed. |
| `todos` | The company's one shared ToDo list — `list` / `show` (one row in full) / `create` (clarification · request) / `answer` / `update` / `close` / `comment` / `people` (user_ids for deterministic assignment) / `tracker` + `tracker_set` (the org's project-management tool and its filing convention) / `track` + `subtasks` + `subtask_update` (the tool's tasks a row is tracked with — link + status, shown inside the ToDo). Rules: `reference/10-todos.md`. |

> `manage_crons` is **gone** — scheduling moved to the unified jobs + schedules + triggers + subagents families above. An older `playwright_flow` JSON-step shortcut was also removed; `playwright_test` covers everything it could.
