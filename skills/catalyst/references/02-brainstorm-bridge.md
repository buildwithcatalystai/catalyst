# Brainstorm round-trip — needs_input → reply → next question

> **Read this when:** you're about to surface a brainstorm question to the user, or the brainstorm seems wedged.

## The loop

While the App Builder Graph is driving (status `brainstorm` or `db_finalize`):

1. You call `send_message(message=<reply>, session_id=<id>)`.
2. The build pushes your reply through, runs another loop, and returns one of:
   - `status: "needs_input"` with a `question` — surface to the user, wait, and call `send_message` again with their reply.
   - `status: "still_running"` — the build is mid-thought (typically running a database migration). Tell the user "running migrations…", call `send_message(message="", session_id=<id>)` after a beat to re-poll, **or** just call `drain_question(session_id)` directly.
   - `status: "ready_to_code"` — brainstorm is done, the app is about to start being built. Tell the user "Entering coding mode." Then send any non-empty message via `send_message` and you'll receive the coding-mode payload.
   - `status: "error"` — something broke. `abandon_build` and tell the user.

That's the entire mechanic. Every brainstorm question, the user's reply, the database confirmation, the migration progress — all of it flows through `send_message`.

## Strict rules

1. **Pass questions through verbatim.** Brainstorm uses a strict 6-section format (About / Archetype / User Stories / APIs / DB Schema / Design Notes). Don't summarize, paraphrase, or rewrite. The user expects the same shape every turn. If you reformat, the next turn's response can drift.

2. **When the user signals confirm, call `confirm(session_id)`** instead of putting their natural-language confirmation through `send_message`. The build expects an explicit confirmation hook to leave brainstorm and start migrations + scaffolding.

3. **A brainstorm question can include the entire PRD draft.** Around the 5th–6th turn the build typically returns "here's the PRD, ok to proceed?" — that's normal. Show it to the user as-is and ask if it looks right. Their "yes / ship it / looks good" → call `confirm`.

## When brainstorm wedges

Symptoms:

- `send_message` keeps returning `still_running` for >60 seconds.
- The user's wizard ChatPane shows the last question but no further events.

What to do, in order:

1. Try `send_message(message="/c", session_id=<id>)`. If the build was just slow to wrap up, this skips to confirm and unblocks.
2. If still stuck after another long wait, `abandon_build(session_id, reason="wedged")` and tell the user: "Something stalled on Catalyst's end — I marked this build as abandoned. Want to start fresh?"
3. If multiple builds wedge in a row, the right answer for the user is still abandon-and-restart. If they ask why, just say something genuine broke on Catalyst's side and the team can look at it later.

## Why your work is preserved

Every brainstorm question and answer is saved as it happens. If the user's machine restarts, Claude Code crashes, or Catalyst is restarted, your build keeps everything up to the last answered question. Resume by calling `send_message(message="", session_id=<id>)` — you'll be handed the next outstanding question (or a confirmation of where things landed).

You don't need to track this yourself. You don't need to re-state what's been answered. The build remembers.
