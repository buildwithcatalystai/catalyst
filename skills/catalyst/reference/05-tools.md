# Tool catalog — one `coding_workspace__*` surface, narrowed per employee

> Loaded on demand. SKILL.md keeps the lifecycle tools (flow control) + the behavioral one-liners; this is the full per-tool reference. **The live MCP tool schemas (name / args / description) always reach you at call time** — this file is the at-a-glance map of what the surface holds and which employee unlocks what.

## The model: one surface, the employee narrows it

All three employees — the Analyst, the PM, the Engineer — work the **same** `coding_workspace__*` tool surface (the FDE union). You don't switch namespaces; who's on it decides which tools on that surface are live. The PreToolUse hook enforces the per-employee deny-set (the sentinel `mode` is the internal switch), mirroring the FDE `ModeController.DENIED`:

| Employee (sentinel `mode`) | Denied on the surface | Net usable surface |
|---|---|---|
| **The Analyst** (`deep_analysis`) | `write`, `edit`, `playwright_test`, `save_prd` | investigate + store the plan: read/grep/find + KB + `run_select_query` + `run_python` + **`bash`** (open here so the plan persists in the Mindspace) |
| **The PM** (`spec`) | `write`, `edit`, `bash`, `playwright_test` | the same set **minus `bash`, plus `save_prd`** (author the plan) |
| **The Engineer** (`coding` / `vibe_code`) | — nothing — | the full surface (read, write, edit, bash, playwright, automation…) |

You never check the mode yourself. A blocked tool's error names the transition to call (`start_app_building` to bring in the Engineer, etc.). The transitions (`start_analysis` / `start_spec` / `start_app_building`) open and close these sets — see [00-flow-and-tools.md](00-flow-and-tools.md).

**Native Claude Code tools** are mostly OFF while any session is live — `Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob`/`WebFetch`/`WebSearch` are redirected to their `coding_workspace__*` equivalent whoever's on it. Carve-outs available for **every** employee including the Analyst: native **`Agent`** (parallel sub-tasking) and **`EnterPlanMode`/`ExitPlanMode`** (plus `TodoWrite`/`AskUserQuestion`/`Skill`/`SlashCommand`/`ToolSearch`). Note `coding_workspace__bash` is open for **the Analyst** too (so the working plan persists in the Mindspace) — native `Bash` just routes there; there's no laptop-local shell carve-out.

**External MCP servers are blacklisted** while a Catalyst session is active — a connected Redshift / Slack / Notion MCP is denied with a redirect. Strict allow-list: only the Catalyst surface + the few native tools above. Do the work with the Catalyst tools.

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
| `run_select_query` | Read-only SELECT (SELECT/WITH/EXPLAIN, mandatory `LIMIT`, 50-row cap) against their live DB (mysql/postgres/redshift, via-cloud or direct). Verify a table has rows, confirm an enum's values, sanity-check a query before coding against its shape. |
| `run_python` | Your notebook: pandas/numpy + a read-only `query(sql)→DataFrame`. `df = query("SELECT …")`, then compute — cohorts, distributions, trends, outliers. **State persists across calls.** `mode='interrupt'` aborts a hanging cell (keeps your namespace); `mode='restart'` bounces with explicit `max_mem_mb` (clears namespace, bounds the next workload so a runaway can't take down the EC2). |
| `grep_database_context_files` / `grep_api_context_files` | Search the DB / API docs the user uploaded — the source the schema + API roster were built from. |

## Plan — the PM & the Engineer

| Tool | Purpose |
|---|---|
| `save_prd` | Write the agreed plan to the PRD (`.agent/prd.md` + a `PRD/` copy). **Allowed for the PM & Engineer; denied for the Analyst.** The Engineer reads it back via `get_prd`. |
| `todo_write` | Plan a multi-step change visibly (`.agent/todo.json`; the wizard UI reads it). Mirror the list to the user in chat — the tool's own return string isn't user-visible. |

## Make & change — the Engineer (with one Analyst exception, `bash`)

`write` / `edit` / `playwright_test` are **Engineer-only** (denied for the Analyst & PM). `bash` is the exception: it's open for **the Engineer** *and* **the Analyst** (for the Analyst only to store the plan / script the investigation — not to make a web app; that boundary is instruction-side). It stays denied for **the PM**.

| Tool | Purpose |
|---|---|
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
| Triggers (webhook/manual/event → fan out) | `create_trigger`, `edit_trigger`, `delete_trigger`, `list_triggers`, `fire_trigger` |
| Subagents (autonomous AI checks) | `create_subagent_scaffold`, `edit_subagent`, `delete_subagent`, `list_subagents`, `run_subagent` |
| Connected external tools | `external_tools_discover`, `external_tools_execute`, `list_external_connected_apps` |

(A script, a scheduled job, an AI check, an ML model, or a web app **all build here** — the Analyst is for *understanding* data + reasoning, never for shipping one of these.)

## Sub-tasking & living context

| Tool | Purpose |
|---|---|
| `Agent` (`coding_workspace__Agent`, or native `Agent`) | Spawn a side investigation in parallel — read-heavy questions ("read these 6 files and tell me which import the deliveries model"). Keep *writes* in the main flow so they land in order. |
| `mindspace_skill` / `mindspace_memory` | THIS Mindspace's durable skill + living memory. Read/recall on entry; write the moment you learn. (Bound for the Analyst + Engineer.) |

> `manage_crons` is **gone** — scheduling moved to the unified jobs + schedules + triggers + subagents families above. An older `playwright_flow` JSON-step shortcut was also removed; `playwright_test` covers everything it could.
