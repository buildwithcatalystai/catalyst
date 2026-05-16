# Coding mode — you're the engineer now

> **Read this when:** `send_message` returned `mode: "coding"`, or you're driving an active coding session.

## What the coding-mode handoff gives you

When `send_message` lands in coding mode (or the moment after `confirm` flips the status), the response carries:

- `kickoff_message` — a single string with the workspace path, tech stack summary, the full PRD, the repo map, and the build rules. **This IS your build instruction.** Treat it as your first user-turn brief.
- `app_root` — the project's working directory; every `coding_workspace__*` path is relative to it.
- `frontend_url` / `backend_url` — share with the user once you've made any visible change. They open this URL to see the running app.
- `tools_bound` — the list of `coding_workspace__*` tools that are now operational.
- `entry_kind` — `fresh_handoff` (just out of brainstorm), `interrupted_build` (the prior build was mid-flight), or `vibe_edit` (the app is shipping; user wants a tweak). Frame your first turn back to the user accordingly.

The PRD and repo map are inlined in `kickoff_message`. Don't re-fetch them with `coding_workspace__get_prd` or `coding_workspace__get_repo_map` unless your context has been compacted — calling them when you already have the data is wasteful.

## The contract — what to do, in order

1. **Acknowledge the handoff.** Tell the user "Entering coding mode." once. Don't repeat it.
2. **For data work, ask the database knowledge base first.**
   - `coding_workspace__get_existing_tables_summary` lists every existing table with its purpose and relationships.
   - `coding_workspace__get_table_detail(table_name)` gives exact column names. **Column names cannot be inferred** — call this before writing any code that touches columns.
   - `coding_workspace__run_select_query("SELECT ... LIMIT N")` runs a read-only `SELECT` against the user's live DB (mysql / postgres / redshift, via-cloud or direct). Use it to verify a table actually has rows, to confirm an enum's distinct values, or to sanity-check a query before committing code that depends on its shape. Validator-enforced rules: SELECT/WITH/EXPLAIN only, mandatory `LIMIT` clause, 50-row cap on output.
3. **For external API integrations, ask the API knowledge base.**
   - `coding_workspace__get_existing_apis_summary` shows known endpoints and auth context.
   - `coding_workspace__get_api_endpoint_detail(endpoints=[{method, path}, ...])` returns full request / response shapes for the endpoints you'll call.
4. **For any multi-step task, plan in `coding_workspace__todo_write` AND surface the same plan to the user in chat.** The MCP tool's return string is generic ("Todos have been modified successfully…") and is not user-visible — so on every call, also print the list to the user as a short markdown checklist (e.g. `- [ ] Set up auth route` / `- [x] Wire login form`). One in-progress at a time. When the work is single-step or trivially obvious, skip the todo entirely. The persisted JSON lives in `.agent/todo.json` on the workspace and the wizard's UI reads it from there — your chat-side rendering is the *user-facing* mirror, not a duplicate.
5. **Write code via `coding_workspace__write` (creates) and `coding_workspace__edit` (modifies).** All paths are relative to `app_root`.
6. **Run shell via `coding_workspace__bash`.** It runs in the project workspace by default. Don't reinstall dependencies — the scaffold already did. Don't kick off long-running builds — the dev server is already up.
7. **Search via `coding_workspace__grep` (text) or `coding_workspace__find` (filenames).** Use these instead of running `rg` through `coding_workspace__bash` — the dedicated tools handle output budgets correctly.
8. **Compute via `coding_workspace__run_python`.** Short-lived Python sandbox (15 s cap, stdlib + `pandas==2.3.2` + `numpy==2.2.6`) bound to the project root. Reach for it when you'd otherwise enumerate by hand and risk a wrong filter — set diffs, group-by, JSON validation, schema checks, dry-run of "what would this delete" before issuing a destructive write. Read-only by default. Prefer this over `coding_workspace__bash` + inline shell math.
9. **Sub-agent for parallel investigation** via `coding_workspace__Agent` — useful when you need to read several files quickly to answer one question.
10. **End with the completion JSON.** A single line: `{"status":"completed","summary":"<one-paragraph plain-language summary of what you built>"}`. The skill picks this up automatically and finalizes the build (runs migrations, starts services, hands the user back the live URLs). The line itself never reaches the user-facing transcript.

## Validation before declaring done

Before emitting the completion JSON:

- For frontend work, sanity-check with `coding_workspace__bash` (e.g., `tsc --noEmit` or whatever the stack supports).
- For backend work, smoke-test the relevant endpoint with `coding_workspace__bash` and `curl`.
- For end-to-end visual checks, you have `coding_workspace__playwright_run` / similar — use it on the user-flow you just built.

If the user says "it looks broken" *after* completion, you're already in vibe-coding mode (see [04-vibe-coding.md](04-vibe-coding.md)). Don't re-call `complete_build` for fixes — just edit and tell them.

## Tool-policy enforcement

While a coding session is active, native tools (Read / Edit / Write / Bash / Grep / etc.) are blocked by Catalyst's policy hook. **Always use `coding_workspace__*` instead.** If the hook blocks you, the error message names the right replacement; follow the redirect.

The allowlist still includes `TodoWrite`, `AskUserQuestion`, `Skill`, `SlashCommand`, `ToolSearch`, `ExitPlanMode`, `EnterPlanMode` — so planning + clarifying questions still work normally.

## Persistence is automatic

Every assistant turn, every tool call, every result is recorded as it happens. The wizard's ChatPane shows your work live. Cold reload (next time the user opens the project) shows the same history. **You don't call any save / persist tool** — turn-by-turn recording is automatic.

If the user asks "did that get saved?" the answer is always yes.

## When something goes wrong mid-session

| Symptom | What to do |
|---|---|
| `coding_workspace__*` returns "no active build session" | The session marker dropped. Call `current_session` to see what's tracked, then `send_message(message=<their request>, session_id=<id>)` to re-bind. |
| A `coding_workspace__bash` returns "fatal" after retries | Something broke between Catalyst and the workspace. Tell the user, then re-call the same tool — it will rebuild the connection automatically. If it fails twice, point them at the Cloud step in the app. |
| A tool call hangs for >2 minutes | Move on. The skill stays alive; tell the user "that step's taking longer than usual — let me know if you want me to retry or skip it." |

## Cost note

The coding-mode LLM cost is on the user's account (Claude Code), not Catalyst's. The brainstorm and database steps run on Catalyst's account.
