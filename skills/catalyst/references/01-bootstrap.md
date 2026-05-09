# Bootstrap & required state

> **Read this when:** the user wants to build something but `health_check` came back with a failed precondition, or you need to recover from a partially-set-up account.

## What `health_check` tells you

It returns a small status block. Two fields decide whether you can proceed:

- `ready_to_build` — `true` means everything below is in order; go ahead. `false` means surface the `fix_required` message verbatim and stop.
- `fix_required` (when present) — short, plain-language reason. Repeat it to the user without translation.

Other fields (`db_connected`, `aws_connected`, `api_kb_count`, etc.) flesh out the *why* in the failure cases below.

## Failure → action map

| Field | Bad value | What to tell the user |
|---|---|---|
| `backend_up` | `false` | "Catalyst isn't running on your machine. Start it with the usual `./start.sh` in the catalyst-builder folder, then say 'continue'." |
| `db_connected` | `false` | "Catalyst doesn't have a database wired up yet. Open the Catalyst app in your browser, go to the Database step, and connect one. Then come back here." |
| `api_kb_count` | `0` | "Heads up — your API knowledge base is empty. Optional, but if you'll integrate with any external service, the API step in the app gives me a much better foundation. Want to set that up first or push through?" |
| `aws_connected` | `false` | "We can build this locally, but to share previews and persist your project across machines, finish the Cloud step in the app first. Want to set that up, or run local-only?" |
| `instance_id` empty (when `aws_connected=true`) | half-set-up cloud | "Looks like the Cloud step didn't finish cleanly. Open the app and re-run that step." |

Don't second-guess these — the user owns setup. Point them at the app step that owns the gap, then wait.

## Identity is opaque to you

The skill authenticates with Catalyst using a JWT bearer token configured at install time. You don't read it, set it, or pass it through — every tool call carries it automatically. If `health_check` returns an authentication error, tell the user their Catalyst install isn't complete and to recheck the token they were given.

## What the catalyst app does that the skill doesn't

The skill is a thin layer over the Catalyst app. The skill doesn't handle setup. If the user asks you to:

- Set up cloud
- Connect a database for the first time
- Upload an OpenAPI spec or Postman collection
- Run the database or API agent to enrich descriptions
- Verify access permissions

…point them at the corresponding step in the app. They open it in their browser, click through the wizard, and come back when it's done.

## When the backend stops responding mid-build

If `send_message` (or any other tool) comes back with a connection error, Catalyst is down on the user's machine. Nothing is lost.

What to do:

1. Tell the user: "Catalyst stopped responding — restart it with `./start.sh` and say 'continue' when it's back."
2. When they say continue, call `send_message(message="", session_id=<same id>)`. The build resumes exactly where it paused. Every question and answer so far is remembered; you don't lose progress.

The user doesn't need to abandon, reset, or restart Claude Code.

## What lives where (only what you might need)

You almost never need to read these directly — every tool you call works without you knowing the path. The only one you'll touch is the active-session marker, and even that only via `current_session`.

| What | How you read it |
|---|---|
| Active build session | `current_session` tool |
| Recent project list | `list_projects` tool |
| Account / setup status | `health_check` tool |
