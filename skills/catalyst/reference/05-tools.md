# Tool catalog — one `coding_workspace__*` surface

> Loaded on demand — the full per-tool reference; the lifecycle tools are in `00-flow-and-tools.md`. **The live MCP tool schemas (name / args / description) always reach you at call time** — this file is the at-a-glance map of what the surface holds.

## One surface, all of it open

Every tool here is open to you — the whole `coding_workspace__*` surface, every native tool, and your companion's own external MCP servers. Pick the one that touches the right place: Catalyst tools for the company's data and the workspace (the app, the Mindspace's files); native tools for your companion's own machine — a file written natively lands on the laptop, not in the app. Plan mode (`EnterPlanMode`/`ExitPlanMode`) stays blocked while a session is live — product work happens in conversation.

Where a call lands: the Mindspace in focus; making tools only in the Mindspace the work belongs to, never at home (`00-flow-and-tools.md`).

## Read & understand

| Tool | What it's for |
|---|---|
| `read` | Read a file. Supports `offset` + `end_line` / `limit`. |
| `grep` | Search file contents. |
| `find` | List files matching a pattern. |
| `get_repo_map` | File structure + symbol index, kept fresh by a daemon. |
| `get_prd` | The PRD product work saved in this Mindspace, when one was shaped — read when they ask you to build what it specified; a build otherwise has nothing to do with it. |
| `db_skill` | The org's **business-understanding** skill for its database — what the business is, its components, how the tables serve each outcome, hard facts + query learnings. **Read this FIRST** (`mode='read'`) for any data work, so you explore tables knowing the business, not cold. Read-only here; the wizard's DB knowledge chat authors it. (Present only once business context has been captured.) |
| `get_all_db_tables` | The lay of the land — every table, its description, its foreign keys. After the skill, start here for data work. Supports a `query` regex + paging. |
| `get_table_detail` | The exact columns + types of specific tables — **column names can't be inferred**; read this before any query/code that touches columns. |
| `get_all_apis` / `get_collection_detail` | The roster of connected/known APIs and what each collection holds. |
| `get_api_endpoint_detail` | The precise request/response shape of specific endpoints. |
| `run_select_query` | **The Warehouse, read** — the org's analytics store, written only by ETL (a job's dump, a derived reporting table), never by an app's transactions; this tool reads it. SELECT/WITH/EXPLAIN, mandatory `LIMIT`, 50-row cap (mysql/postgres/redshift, via-cloud or direct). Answer a question from the data; never where an app keeps its rows. |
| `app_database` | **The app Database, read live** — the transactional store the apps Catalyst builds read and write. `mode='tables'` (every table · its comment · cols · ~rows), `'describe'` (one table's columns, keys, comments), `'query'` (a SELECT with a LIMIT). No snapshot: a column added a moment ago is there on the next call. |
| `run_python` | Your notebook: pandas/numpy + a read-only `query(sql)→DataFrame` on the Warehouse and `app_query(sql)` on the app Database. `df = query("SELECT …")`, then compute — cohorts, distributions, trends, outliers. **State persists across calls.** `mode='interrupt'` aborts a hanging cell (keeps your namespace); `mode='restart'` bounces with explicit `max_mem_mb` (clears namespace, bounds the next workload so a runaway can't take down the EC2). |
| `grep_database_context_files` / `grep_api_context_files` | Search the DB / API docs the user uploaded — the source the schema + API roster were built from. |

## Plan

| Tool | Purpose |
|---|---|
| `save_prd` | Write a build-ready PRD into the Mindspace's `PRD/` folder — the only home; multiple accumulate, the slug comes from the title, re-saving a name updates it. Each saved PRD lands on the companion's list as one `prd` task, and the return carries the org's tracker convention + the Mindspace/PRD ids to stamp; read the newest back with `get_prd` when asked to build. |
| `todo_write` | Plan a multi-step change visibly (`.agent/todo.json`; the wizard UI reads it). Mirror the list to the user in chat — the tool's own return string isn't user-visible. |

## Make & change

The making tools act only in the Mindspace the work belongs to — refused at home.

| Tool | Purpose |
|---|---|
| `app_database_write` | **The writing hand on the app Database** — INSERT/UPDATE/DELETE and DDL on the tables the app owns, one transaction, rows affected back (RETURNING rows too). Comment every table and column you create in the same batch. Never the Warehouse. |
| `write` | Create or overwrite. Paths relative to `app_root`. |
| `edit` | Find-and-replace edit. |
| `bash` | Run a shell command in the project workspace. The dev server is already up — don't reinstall deps or kick off long builds. It also keeps a working plan in the Mindspace. |
| `playwright_test` | Run a Python Playwright script against the **live URL** (never localhost) — the ONE end-to-end validation tool. |

## Automation — it lives in a Mindspace

The making surface also carries the automation families (one executable protocol; one schedule registry):

| Family | Tools |
|---|---|
| Jobs (non-AI shell/http) | `create_job_scaffold`, `edit_job`, `delete_job`, `list_jobs`, `run_job` |
| Schedules (the cron registry) | `add_schedule`, `edit_schedule`, `delete_schedule`, `list_schedules` |
| Triggers (webhook/manual → fan out; `?wait=1` returns an AI Employee's answer) | `create_trigger`, `edit_trigger`, `delete_trigger`, `list_triggers`, `fire_trigger` |
| Trigger Services (reach an employee from Slack/…; a message = a trigger fire, answer back in-thread) | `list_trigger_services` (read first), `wire_trigger_service`, `unwire_trigger_service`; or `create_trigger(service=, conversation=)` to create + wire at once |
| Subagents (autonomous AI checks) | `create_subagent_scaffold`, `edit_subagent`, `delete_subagent`, `list_subagents`, `run_subagent` |
| Connected external tools | `external_tools_discover`, `external_tools_execute` |

(A script, a scheduled job, an AI Employee, an ML model or a web app — each built in the Mindspace of its expertise.)

## Sub-tasking & living context

| Tool | Purpose |
|---|---|
| `Agent` (`coding_workspace__Agent`, or native `Agent`) | Spawn a side investigation in parallel — read-heavy questions ("read these 6 files and tell me which import the deliveries model"). Keep *writes* in the main flow so they land in order. |
| `mindspace_skill` / `mindspace_memory` | THIS Mindspace's durable skill + living memory. Read/recall on entry; write the moment you learn. |
| `user_persona` | Your companion's working model — how they work, not just who they are: role, goals, how they decide and solve problems, what they know, how they like things shaped, how they communicate, their people, rhythm, history, judgment, when to push back, what you may do alone (`read` / `list` / `write` / `write_reference`; the crux arrives as `persona_block` on entry). Every correction, edit, approval, rejection and decision is a data point: say the rule back in one line and **write the pattern at reflect** — the crux into the core doc (whole doc, within budget), the depth and the expert mindmap (`10-expertise-map`) into references; their own Wingman and the nightly refresh write it too, so keep to the crux and never drop what you did not learn this session (`reference/11-persona.md`). An empty read is a **first meeting**: greet them as one and learn them through the work — never announce it, never interview. Their **tracker style** lives in its `NN-tracker-style` reference: read it before filing in the org's project-management tool. |
| `enterprise_trusted_skills` | What your companion can build on, theirs first: their own expertise — every Mindspace they own with a skill, trusted or not yet, the one in focus marked — then the way to everyone else's: when your companion asks colleagues' Wingmen, anything not theirs goes through `ask_wingman` — never read around the colleague; otherwise the company's trusted skills and what's shared with them. Ground an answer in their areas here and in their expert mindmap; open one in full with `read_org_skill('<slug>')`. |
| `ask_wingman` | Ask a colleague's Wingman: `question`, optional `person` (name, email or agent_id). Empty `person` = Catalyst finds whose Wingman holds it — each likely Wingman checks itself, the ones that hold it are asked first, then whom they point to; when nobody has a clue it says so, and you ask your companion who would know. Returns the way, where to look and how sure it is — the work stays yours. The colleagues can see the conversation. Every reply ends with that Wingman's agent_id: ask again with `person=<agent_id>` for anything unclear — the conversation carries on. |
| `correct_wingman_route` | After an `ask_wingman` miss — or an answer your companion overrode — record who actually held it — `actual` = a name, email or Wingman ID, or `"nobody"` (+ an optional `note`). The Curator's call, once the conversation settles it (`reference/09-curator-reflect.md`). |
| `learn_from_recording` | Learn ONE workflow of your companion's (SKILL.md §8) — from a recording they made or uploaded (`list` · `status` · `read` · `ask`), or from what they told you step by step (`walkthrough`) — and bank it as ONE workflow reference under the expertise (`# Workflow — <name>` · Where it happens — every URL, each sign-in and its Vault login · Inputs this run needs · Steps · Decision points · Choices and rules · Where it goes wrong · Gotchas and tricks · Stop and ask when · Not shown · Sources), written so you or an agent can replicate it exactly; `bank` / `walkthrough` on their yes, into the Mindspace in focus or one of theirs by name (`create=true` starts one). |
| `capture_workflow` | The workflow reference of this Mindspace — ONE per workflow (`NN-workflow-<slug>`), from ANY source (SKILL.md §8): a recording, what they told you step by step, a document they shared, a browser run's lesson, a correction. A workflow is browser work (apps · the screens in each · the controls on them and the values they carry — `## Screens and controls`; every step of `## Steps` names its screen and control), AI-worker work (`## How it runs`: a schedule or a trigger firing jobs and AI Employees, each firing the next, one line per link — `- schedule \`<cron>\` → job \`<name>\``, `- job \`<name>\` finishes → employee \`<name>\``, `- employee \`<name>\` → workflow \`<name>\`` — another workflow file of the Mindspace, run as its own run — `- employee \`<name>\` → browser: steps n–m` — static browser steps inline), or both; a Steps row whose where reads `workflow: <name>` is such a run too. `list` · `read` (the reference or the workflow's name) · `status(reference)` — the worker graph against what this Mindspace holds: each node ✓ exists / ✗ missing and each link ✓ wired / ✗ not, with the call that builds or wires it · `capture(title, text, source)` — a told or pasted workflow becomes its reference · `add(reference, section, text, source)` — one piece into one section (mission · where · screens · inputs · steps · runs · decisions · choices · mistakes · gotchas · stop · not_shown) the moment they correct a step, name a mistake or list the options, never at the end · `from_recording(recording_id, answers?)`. Only in their turn. A re-capture merges into the same reference, never a duplicate. |
| `run_workflow` | Hand a workflow to the Browser Agent (SKILL.md §9) — a separate agent that performs the browser steps of a workflow reference (`NN-workflow-<slug>`, or the text) in your companion's browser, leveraging the reference to reach the `goal`, with this run's `inputs`: `start` · `resume(run_id, answer)` when it stopped on a question · `status`. Comes back DONE (what it did and read + what the workflow should learn) or NEEDS YOU (the one question). A workflow whose How-it-runs graph names only workers is not run here — `start` answers with its graph against the Mindspace (build the missing nodes, wire the links, run it once); a mixed one runs its browser steps and names the worker steps for `run_job` / `run_subagent`. `start(workflow=)` takes the reference's name or the workflow's title, so a step that names another workflow is run by that name. An AI Employee with the permission Work in a browser carries this tool itself, as its owner. |
| `browser` | RETIRED from your desk (2026-10-30: every browser action goes through the Browser Agent — `run_workflow` with the whole job; SKILL.md §9). It was: `open` · `snapshot` (everything you can act on, numbered, plus the visible text) · `click` · `type` (text, or `secret=<a saved login>` that never reaches you) · `select` · `press` · `read` · `find` · `wait` · `back` · `screenshot` · `logins` · `close`. One session per person, kept signed in; a workflow reference with steps is followed exactly; anything that leaves a mark only on their yes. |
| `record_screen` | Record their screen from here: a bash command for their machine's own recorder (macOS `screencapture`; Linux / Windows `ffmpeg`) — screen + microphone for the seconds they choose, saved under `~/catalyst-recordings/`; run it in the background, then `upload_recording` the file it printed. |
| `upload_recording` | A recording on their machine (mp4 · webm · mov) → a bash command that uploads it in pieces and starts the reading; then `learn_from_recording`. |
| `todos` | The company's one shared ToDo list — `list` / `show` (one row in full) / `create` (clarification · request) / `answer` / `update` / `close` / `comment` / `people` (user_ids for deterministic assignment) / `tracker` + `tracker_set` (the org's project-management tool and its filing convention) / `track` + `subtasks` + `subtask_update` (the tool's tasks a row is tracked with — link + status, shown inside the ToDo). Rules: `reference/10-todos.md`. |

> `manage_crons` is **gone** — scheduling moved to the unified jobs + schedules + triggers + subagents families above. An older `playwright_flow` JSON-step shortcut was also removed; `playwright_test` covers everything it could.
