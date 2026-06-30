# Vibe-edit mode — iterate after the build is shipping

> **Read this when:** the user wants to keep changing a project after the initial build completed, or asks about live changes appearing in the preview.

## What "vibe-edit" means here

After `complete_build` runs, the project's status flips to "completed" but the session is **not closed**. You can keep using `coding_workspace__*` tools to make changes. Every change continues to land in the same project history the wizard's ChatPane is reading. The running app updates live — typically the user just refreshes their preview tab and sees the change.

The only practical difference between a fresh Engineer handoff and vibe-editing:

- In a fresh build, you start from a kickoff message that includes the full PRD + repo map.
- In vibe-edit, you don't get a fresh kickoff. The user describes the change they want and you use the tools (`coding_workspace__get_repo_map`, `coding_workspace__get_prd`, `coding_workspace__read`) to figure out where it goes.

Both feel identical to the user. The wizard's history is one continuous thread.

## A typical vibe-edit turn

User: "add a CSV export button on the deliveries table"

You:

1. `coding_workspace__get_repo_map` to find where the deliveries page lives.
2. `coding_workspace__read` to inspect the relevant file(s).
3. Decide: frontend-only change, or do we need a new endpoint too?
4. If backend: `coding_workspace__get_all_apis` first (maybe an export endpoint already exists), or `coding_workspace__get_table_detail("deliveries")` for the columns to export.
5. `coding_workspace__write` / `coding_workspace__edit` to apply the change.
6. Optionally `coding_workspace__bash` for a quick sanity check (`tsc --noEmit`, lint, smoke test).
7. Tell the user: "Done — refresh your preview to see the new button."

The dev servers are already running and reload on file changes; you don't restart anything yourself.

## Don't break the persistence chain

Every assistant turn during vibe-edit lands in the **same** Mindspace history as the original build. This means:

- **Do** keep calling `coding_workspace__*` tools for any change — the session stays bound; the edits land in order.
- The current Mindspace is the active one; bringing another employee back in (e.g. `start_spec` to re-plan with the PM) continues it — it never forks.

If the user wants a genuinely *new* Mindspace, that's the moment for `switch_mindspace()` (clean slate), then `start_app_building`.

## When you reopen Claude Code on an existing project

If the user's Claude Code session restarts (closed terminal, etc.):

1. Call `current_session` — if it still tracks the project, `start_app_building` continues it (the plugin keeps the id; you don't pass one).
2. If not, run `list_mindspaces`, find the one they want, and `switch_mindspace(target_session_id=<id>)` to re-activate it — then the next transition continues it. (You can't target a Mindspace through a transition; `switch_mindspace` is the only way to point at a specific one. After a clean restart there's nothing active to leave, so the confirm is a no-op.)

## When to call `complete_build` vs `abandon_build` vs nothing

- `complete_build` — call **once** per build session, when the initial build first emits the completion JSON. Don't call it again for vibe-edits.
- `abandon_build` — the user is done with this project, **or** the build wedged unrecoverably and a fresh start is the only path. Clears the session marker so native tools work again.
- nothing — vibe-editing indefinitely on the same project. The session stays bound; tools stay live.

## What the user sees

The user has the Catalyst app open in their browser, on the project they're working on. They see:

- **Preview tab** — the running app. Refreshes on every change you make.
- **Chat pane** — the full conversation history. Your turns appear live as you make them; cold reload reads the same history.

When you finish a change, tell the user where to look ("refresh the preview", or "open the new page at /reports") instead of waiting for them to ask.

## Sub-agents

`coding_workspace__Agent` is available — it spawns a side investigation in parallel. Good for read-heavy questions:

- "Read these 6 files and tell me which ones import the deliveries model" — way faster than 6 sequential reads.
- "Search for everywhere we calculate revenue" — sub-agent with grep + read.

Bad uses:

- Anything that writes — keep edits in the main flow so they land in order in the project history.
