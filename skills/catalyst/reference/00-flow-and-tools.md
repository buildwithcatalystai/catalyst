# Flow & tools — where every call lands, and how you move

> The live MCP schemas (name / args / description) reach you at call time. This is the at-a-glance map: which Mindspace a call acts on, how you move between Mindspaces, and the lifecycle tools. All of it is mechanics — to your companion there is only you.

## Every call acts on the Mindspace you are in

- The plugin stamps your current Mindspace into every Catalyst call; any `session_id` you set is overwritten. You never supply or track an id.
- Making tools are refused at home — `write`, `edit`, `app_database_write`, `save_prd`, `evolve_skill`, jobs, schedules, triggers, AI Employees and their tools. An app, an AI Employee or a scheduled job belongs to the Mindspace of its expertise: focus on that one first, or start it.

## Moving between Mindspaces

- `focus_on_expertise(target='<name>')` — pick one up by name, in the background, with one line as you go. The server resolves the name over yours and those shared with you for editing. `not_found` carries the candidates — ask which, never guess. `read_only` is a colleague's trusted Mindspace — read it with `read_org_skill`.
- `focus_on_expertise(target='home')` — back home when no specific expertise is in play.
- `focus_on_expertise(target='<two to four words>', create=true)` — start the Mindspace for a new expertise, on your companion's nod. Focus first: `create` is for when nothing matches.
- It asks first (`needs_confirm_clear_current`) only when work is in flight where you are — a build, or a Spec Q&A that rewinds a question or two. Relay it; re-call with `confirm_clear_current=true` on a clear yes.
- On entry, orient: `mindspace_skill` and `mindspace_memory` — absorb them before you do anything there.
- One problem is one arc in one Mindspace: what you found, the PRD and the build carry forward. Never leave it to "start clean" for the next step of the same work.

## Working on the Mindspace

| Tool | Purpose |
|---|---|
| `start_spec(prompt?)` | Shape a PRD with them, one question at a time, grounded in the Mindspace's real data and systems; `save_prd` on their yes. Detail: `02-spec-bridge.md`. |
| `start_app_building(prompt?, app_name?)` | Build on this Mindspace — a script, a job, an AI Employee, a model or a web app (scaffolds on the first web build). Pass the ask, or the PRD direction, as `prompt`. The app's files go through `coding_workspace__*`, never native `Write`/`Edit` — those act on the laptop. Detail: `03-build-loop.md`. |
| `complete_build(summary)` | Finalize a build after the completion JSON — runs migrations, boots the dev servers, returns the URLs. Idempotent; a Stop hook fires it as a safety net. |

**Which hand for what.** Catalyst tools touch the company — `run_select_query` / `run_python` / the knowledge base for its data, `coding_workspace__*` for the workspace (the app, the Mindspace's files). Native file and shell tools, and their external MCP servers, act on your companion's own machine. Everything is open; reach for the one that touches the right place.

## Lifecycle

| Tool | Purpose |
|---|---|
| `ensure_auth(home=true)` | **The first call of every activation.** Checks sign-in and opens home. `authenticated:false` → say what `message` says, do it, stop. `status:error` → read `fix_required`. Ok → open on `brief_block` (today's brief). `persona_status: 'new'` is a **first meeting** — greet them as one by `user_name`; otherwise *"Welcome back, <name>"*. Relay `todos_block`. `persona_block` is how they work — read it before anything of substance. `directory_block` places them in the company (read, never recite); `mindspace_of_interest` is where they left off — focus on it by name the moment their first message is about it; `firsts` counts what is still ahead (a zero) — teach it in one line when it happens. |
| `ensure_auth` | No `home`: checks sign-in only, without moving the tab — for `/catalyst status|list|end`. |
| `logout` | Signs out; read its `message` verbatim. |
| `health_check` | On demand, when the first call or a workspace tool errors; `ready_to_build: false` → read `fix_required` to the user and stop. Never on landing. |
| `list_mindspaces` | Home first (`home: true`), then theirs and those shared with them — when they ask to see or pick one. Full ids, never truncated; the phase in plain words (exploring / planning / building / shipped). |
| `current_session` | `{active, session_id}` for the Mindspace you are in. A tab with nothing active gets `{active: false}`. |
| `focus_on_expertise(target, create?, confirm_clear_current?)` | Above. Focusing never builds — the work is picked up where it stands; building is `start_app_building`'s call. Non-destructive: the Mindspace you leave keeps its skill, memory and history. |
| `abandon_build(reason?)` (alias `end`) | Destructive — wipes local session state and marks the row abandoned (resurrectable). Only on an explicit "end / abandon / kill it." |

`mindspace_skill`, `mindspace_memory`, `todos` and every work tool → `05-tools.md`.

## Status (the MCP writes it; you read it only for sanity)

Internal status flows `spec → db_finalize → generate → completed`. Treat `{completed, error, abandoned, generate-interrupted}` as equivalent — same actions available, nothing terminal. To your companion it is only exploring / planning / building / shipped — never the raw word.
