# Troubleshooting

## Symptom → action map

| Symptom | What to do |
|---|---|
| `health_check` returns `backend_up: false` | Tell the user: "Catalyst isn't running on your machine. Start it with `./start.sh` in the catalyst-builder folder, then say 'continue'." |
| Native tools (Read / Edit / Bash / Write / Grep / etc.) are blocked with "use coding_workspace__*" | Expected — a coding session is active. Use the redirect target the hook names. If the user genuinely needs native tools (they're editing local config, not the project), call `abandon_build` first to clear the session marker. |
| `send_message` keeps returning `still_running` for >60 seconds | Brainstorm or migrations stalled. Try `send_message(message="/c", session_id=<id>)` to skip past — if that unblocks, it was just slow. If still stuck, `abandon_build` and offer the user a fresh start. |
| `start_coding` (or auto-handoff after `confirm`) errors with "graph still running after 180s" | A brainstorm question is probably still pending — call `send_message(message="", session_id=<id>)` and check for `needs_input`. If you find one, surface it. If not, the migrations wedged; `abandon_build` and tell the user. |
| `start_coding` errors with "no checkpoint found" | The build's earlier work didn't land. Ask the user to check `health_check` — typically the database connection broke. Once they fix it, `abandon_build` and start over. |
| `coding_workspace__*` tool returns "no active build session" | The session marker dropped. Call `current_session` first — if it returns one, `send_message(message=<their last request>, session_id=<id>)` rebinds. If not, the project needs `send_message` from `list_projects`. |
| A `coding_workspace__bash` returns "fatal" / "unreachable" after retries | Connection to the project workspace dropped. Re-call the same tool — most of the time it rebuilds the connection automatically. If it fails twice, point the user at the Cloud step in the app. |
| Live preview shows the project but the chat pane stops updating | The user's browser tab is stale — have them refresh. Your work is still being saved; refresh just reconnects the live stream. |
| The session marker sticks around for a build that's already over (Claude Code crashed mid-build) | `current_session` to see what's marked → `abandon_build(session_id, reason="stale")`. |
| User wants to run two builds at once | Only one active build per Claude Code at a time. `abandon_build` (or `switch_project`) on the current one before starting the new one. |

## Resetting bad state — order of escalation

Try these in order, from least to most destructive:

1. `abandon_build(session_id)` — cleanest exit. Releases the session marker and marks the project abandoned in the user's history (it stays visible in `list_projects` if they want to inspect it later).
2. Tell the user to clear their local session marker manually (`rm ~/.claude/state/catalyst-active-session.json`) only if `abandon_build` itself failed because Catalyst is down.
3. Tell the user to restart Catalyst (`./start.sh` in the catalyst-builder folder). This drops Catalyst's in-memory state for any active build but never touches saved project history.
4. Tell the user to restart Claude Code itself. Last resort — they lose any unsent messages.

## When the user asks "is the build broken?"

Run `health_check` and `current_session` first.

- If `current_session` shows an active build (`mode: coding`), the build is still in flight; the issue is probably a stalled tool call. Tell them what you were doing and offer to retry or switch direction.
- If it shows `mode: vibe_code`, the initial build completed; the issue is in something you just edited. Read the most recent few turns to remember what you tried, then ask: "I just changed X — is that the part that's broken, or something earlier?"
- If `current_session` returns `{"active": false}`, no build is in progress. Run `list_projects` and see which project the user is talking about, then `send_message` to resume it.

Don't apologize generically. Confirm the state, name what you last did, and offer a concrete next step.
