# Vibe-coding mode — iterate after the build is shipping

> **Read this when:** the user wants to keep changing a project after the initial build completed, or asks about live changes appearing in the preview.

## What "vibe-coding" means here

After `complete_build` runs, the project's status flips to "completed" but the session is **not closed**. You can keep using `coding_workspace__*` tools to make changes. Every change continues to land in the same project history the wizard's ChatPane is reading. The running app updates live — typically the user just refreshes their preview tab and sees the change.

The only practical difference between fresh-build coding and vibe-coding:

- In a fresh build, you start from a kickoff message that includes the full PRD + repo map.
- In vibe-coding, you don't get a fresh kickoff. The user describes the change they want and you use the tools (`coding_workspace__get_repo_map`, `coding_workspace__get_prd`, `coding_workspace__read`) to figure out where it goes.

Both feel identical to the user. The wizard's history is one continuous thread.

## A typical vibe-coding turn

User: "add a CSV export button on the deliveries table"

You:

1. `coding_workspace__get_repo_map` to find where the deliveries page lives.
2. `coding_workspace__read` to inspect the relevant file(s).
3. Decide: frontend-only change, or do we need a new endpoint too?
4. If backend: `coding_workspace__get_existing_apis_summary` first (maybe an export endpoint already exists), or `coding_workspace__get_table_detail("deliveries")` for the columns to export.
5. `coding_workspace__write` / `coding_workspace__edit` to apply the change.
6. Optionally `coding_workspace__bash` for a quick sanity check (`tsc --noEmit`, lint, smoke test).
7. Tell the user: "Done — refresh your preview to see the new button."

The dev servers are already running and reload on file changes; you don't restart anything yourself.

## Don't break the persistence chain

Every assistant turn during vibe-coding lands in the **same** project history as the original build. This means:

- **Don't** call `send_message(message=<idea>)` with no `session_id` for an iteration. That spawns a new project. The old project is left frozen and the new one starts from scratch.
- **Do** keep calling `coding_workspace__*` tools for any change in the current session.

If the user wants a *new* project, that's the moment for `switch_project` (or `send_message` with no session_id).

## When you reopen Claude Code on an existing project

If the user's Claude Code session restarts (closed terminal, etc.):

1. Call `current_session` — if it's still tracking the project, you're back in.
2. If not, run `list_projects`, find the one they want, and call `send_message(message=<their next request>, session_id=<id>)`. The skill rebinds tools and gets you ready to keep iterating.

You don't need to call any other "rebind" or "resume" tool. `send_message` covers it.

## When to call `complete_build` vs `abandon_build` vs nothing

- `complete_build` — call **once** per build session, when the initial build first emits the completion JSON. Don't call it again for vibe-edits.
- `abandon_build` — the user is done with this project, **or** the build wedged unrecoverably and a fresh start is the only path. Clears the session marker so native tools work again.
- nothing — vibe-coding indefinitely on the same project. The session stays bound; tools stay live.

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
