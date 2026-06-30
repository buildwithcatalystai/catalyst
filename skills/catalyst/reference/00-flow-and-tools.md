# Flow & tools — transitions, lifecycle, and the per-employee surfaces

> **What this is.** SKILL.md teaches *judgment* and names who's on the work (the Analyst, the PM, the Engineer); it deliberately doesn't list tools. This file is the operational map — the **transition** tools that bring in each employee, the **lifecycle** tools that work with anyone on it, and which **work surface** each employee unlocks. The live MCP schemas (name / args / description) always reach you at call time; reach for this when you need the at-a-glance "what brings in whom."
>
> **Internal map (never said to the user):** the Analyst = `start_analysis` (Discover mode), the PM = `start_spec` (Spec mode), the Engineer = `start_app_building` (Build mode). You speak in employees; the stage/mode words stay in the mechanics.

## Transitions — bring in an employee

You never track who's on it yourself; you call a transition and the surface follows. A blocked tool's error names the transition to call.

All three employees work the ONE `coding_workspace__*` surface; the mode narrows it (the PreToolUse hook enforces the deny-set). Native `Agent` + Enter/Exit plan mode stay available for every employee.

| Transition | Brings in | Notes |
|---|---|---|
| `start_analysis(prompt?)` | **the Analyst** | Investigate the business from its real data — get to the bottom of the problem with `run_select_query` / `run_python` / the knowledge base. **Acts on your CURRENT Mindspace** (the plugin fills the id; you don't pass it). **Denied:** `write`/`edit`/`playwright`/`save_prd` (the Analyst changes nothing, ships nothing — but the *Mindspace* persists; see below). `coding_workspace__bash` IS open (store your working plan in the Mindspace), plus native `Agent` + plan mode for structuring + a parallel survey. Close by *recommending* the path forward (options, pros/cons, your pick) — never "what next?". |
| `start_spec(prompt?)` | **the PM** | Shape a plan *with the user*, in conversation. Author the plan, write it with `save_prd`; hand to the Engineer on a yes. **Acts on your CURRENT Mindspace.** **Denied:** the build actions (`write`/`edit`/`bash`/`playwright`); `save_prd` IS allowed. |
| `start_app_building(prompt?, app_name?)` | **the Engineer** | Make whatever the problem needs and prove it runs. **Acts on your CURRENT Mindspace** (Analyst/PM→Engineer, same id). Scaffolds on first web-build. Pass the agreed plan as `prompt`. Full surface — nothing denied. To build a *different* existing Mindspace, `switch_mindspace` to it first. |

**One Mindspace, many hands — the transition always means the one you're in.** `start_analysis` / `start_spec` / `start_app_building` bring an employee onto *your current Mindspace* (same id, same data, findings carry forward). **You don't supply or track the id — every Catalyst tool auto-targets your current Mindspace** (the plugin stamps it from your *local* sentinel into the call; any `session_id` you set is overwritten). This is true for *all* of them — transitions, `coding_workspace__*`, `current_session`, recall — not just the transitions. A transition can therefore never fork or jump. **Changing *which* Mindspace is `switch_mindspace`'s job, and only on a user request/confirm:** `switch_mindspace(target_session_id=<id>)` to resume/revisit a *different* existing one, or `switch_mindspace()` (clean slate) to start a fresh one — then the next transition continues whatever switch left active.

**The no-write limit is the *Analyst*, NOT the Mindspace.** The Analyst denies the write/build *tools* — but the Mindspace is NOT disposable: its findings, `mindspace_memory`, and `mindspace_skill` persist and are the *seed* for the PM/Engineer on the SAME Mindspace. Never reason "the Analyst changes nothing → nothing to lose → switch away" — that strands the findings. You carry the investigation *forward* into the same Mindspace's build; you don't abandon it.

**The three employees are ONE arc — hand forward, you can't fork.** As the work moves understand → plan → make on the effort in front of you, just call the next transition — it continues the SAME Mindspace (the plugin keeps the id). An app built from what the Analyst just found is the *same effort*; keep going. The only way to leave the current effort is **`switch_mindspace`** — to a different existing Mindspace, or `switch_mindspace()` for a clean slate (a fresh one). Both are the user's call and confirmed; recommend before you propose one, never do it on a whim, and you literally can't do it by accident through a transition.

**Work only the Catalyst surface.** Whoever's on it, use the Catalyst tools above — `run_select_query` / `run_python` / the knowledge base for data, `coding_workspace__*` for builds. External MCP servers (a connected Redshift/Slack/Notion MCP) and native file/shell are OFF while a session is live; a call to one is redirected back to the Catalyst tool. (Native `Bash` is the one exception — open while the Analyst's on it for local scripting.)

## Lifecycle — employee-agnostic, safe from any tab

| Tool | Purpose |
|---|---|
| `ensure_auth` / `login` / `wait_for_login` / `logout` | The auth gate (see SKILL → Routing → Auth). `ensure_auth` is your first call, every activation. |
| `health_check` | Entry readiness; `ready_to_build: false` → read `fix_required` to the user and stop. |
| `list_mindspaces` | The shelf — render with full session_ids, never truncated; show the phase as who's on it (Analyst / PM / Engineer / Shipped). |
| `current_session` | "Who's on it right now?" → `{active, session_id}` for your current Mindspace (the plugin fills the id). Safe from any tab; a tab with nothing active gets `{active: false}`. |
| `switch_mindspace(target_session_id?, confirm_clear_current?)` | **Non-destructive** pause/resume or clean slate — the primitive for "switch" / "step away" / "build new". **Never call on your own judgment — switching is the user's call.** Whenever a session is active it returns `needs_confirm_clear_current` first: relay it to the user (what they're leaving, where you're going; for a PM session also warn it can rewind a question or two), then re-call with `confirm_clear_current=true` only on a clear yes. |
| `abandon_build(reason?)` (alias `end`) | Destructive — wipes local session state + marks the row abandoned. Works from any tab. Resurrectable. Only on an explicit "end / abandon / kill it." |
| `complete_build(summary)` | Finalize a build after the completion JSON — runs migrations, boots the dev servers, returns the URLs. Idempotent (a Stop hook also fires it as a safety net). |
| `mindspace_skill(mode)` | THIS Mindspace's durable skill (how the area works) — a detailed core doc + references. Read on entry; `write_skill` to grow the core doc, write a reference for depth, as you learn. (Bound while the Analyst or Engineer is on it.) |
| `mindspace_memory(mode)` | THIS Mindspace's living memory — discrete facts you'd look up (not understanding; that's the skill). Recall on entry; save the moment you learn. (Bound while the Analyst or Engineer is on it.) |

## Work surface — one surface, the employee narrows it

There is ONE bound surface, `coding_workspace__*` (the FDE union). Who's on it decides which tools are live — the hook denies the rest:

- **The Analyst** — the investigation surface: `read` / `grep` / `find`, the DB + API knowledge base, `run_select_query`, `run_python` (pandas + a read-only `query(sql)→DataFrame`, state persisting across calls), plus `coding_workspace__bash` (open here so the working plan persists in the Mindspace). **Denied:** `write` / `edit` / `playwright_test` / `save_prd` (you investigate, you don't make). For understanding their data + reasoning — **never a web app** (that's the Engineer). Native `Agent` + plan mode stay open for structuring the investigation + a parallel survey (native `Bash` is routed to `coding_workspace__bash`, so work stays in the Mindspace).
- **The PM** — the same investigation surface **plus `save_prd`** to author the plan. **Denied:** the build actions (`write` / `edit` / `bash` / `playwright_test`).
- **The Engineer** — the **full** surface, nothing denied: read / write / edit / bash / grep / find, `get_prd` (the contract), `get_repo_map` (daemon-fresh index), `run_python`, `run_select_query`, `playwright_test` (the one validation tool), **plus the automation families — jobs, scheduled jobs, subagents (autonomous AI checks), triggers.** A script, job, AI check, ML model, or web app all build here.

Whoever's on it also exposes the user's **connected external tools** (discover → execute) and `mindspace_skill` / `mindspace_memory`. External MCP servers are blacklisted while a session is live.

Full per-tool catalog → `05-tools.md`.

## Status (the MCP writes it; you read it only for sanity)

Internal status flows `spec → db_finalize → generate → completed`. Treat `{completed, error, abandoned, generate-interrupted}` as equivalent — same actions available, nothing terminal. (Surface it to the user only as who's on it / Shipped, never the raw status word.)
