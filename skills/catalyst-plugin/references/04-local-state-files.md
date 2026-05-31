# Local state files — `~/.claude/state/`

Five files the plugin writes. CC owns the directory; the plugin co-tenants it.

## `catalyst-active-session.json` — sentinel

**Single source of truth** for "is there an active Catalyst session, and which tab owns it." Read by both hooks; written by PreToolUse (claim) and PostToolUse (enrich).

### Schema

```json
{
  "cc_session_id": "a5185aa6-9036-41a7-b752-c53f13ed3f28",
  "started_at": "2026-05-11T11:38:55Z",
  "session_id": "6b2c027d-4039-450b-a711-ab853485a178",
  "app_root": "/home/ubuntu/projects/6b2c027d-...",
  "gen_stream_id": "6b2c027d:34e704e1:e30cea73617e",
  "mode": "coding"
}
```

| Field | Source | Notes |
|---|---|---|
| `cc_session_id` | PreToolUse claim | The CC tab UUID that owns this sentinel. Set once, never overwritten. |
| `started_at` | PreToolUse claim | UTC ISO timestamp. Displayed in cross-tab refusal text. |
| `session_id` | PostToolUse enrichment | Catalyst build UUID (also called "session id" by the wizard). |
| `app_root` | PostToolUse enrichment | Project path on EC2 (`/home/ubuntu/projects/{slug}`). |
| `gen_stream_id` | PostToolUse enrichment | Wizard's checkpointer thread id: `{app_id}:{user_id}:{uuid[:12]}`. |
| `mode` | PostToolUse enrichment (or `start_analysis`) | `menu` (claimed but no project) / `coding` / `vibe_code` / `brainstorm` / `deep_analysis`. `deep_analysis` is org-level research: `session_id=null`, PreToolUse ALLOWS native tools, event-sink is a no-op. Set by the `start_analysis` lifecycle tool; flipped off by the normal build-entry tools (send_message / restart_brainstorm / switch_project). |

### Lifecycle

```
[absent]
   │
   │ first catalyst-mcp tool call (any tab)
   │ PreToolUse claim
   ▼
{cc_session_id, started_at, session_id=None, mode=menu}
   │
   │ send_message returns coding-entry response
   │ PostToolUse enrichment
   ▼
{...all fields populated..., mode=coding}
   │
   │ end / abandon_build
   │ PreToolUse handler (BEFORE the call) unlinks
   ▼
[absent]

OR

   │ complete_build returns pause_after_complete=true
   │ PostToolUse _maybe_clear_local_state
   ▼
{...preserved..., mode=menu, session_id=None}
   │
   │ next send_message
   ▼
{..., mode=coding}  (new build)
```

### Who reads it

- PreToolUse: ownership check, native-tool gate.
- PostToolUse: ownership check, mode gate, session_id for HTTP path.
- The skill (`catalyst-mcp` server-side): does NOT read it directly — the local hook mirrors server state to disk.

## `catalyst-events-jwt.json` — coding-mode JWT

**Presence = "in coding mode for this build."** Written by PostToolUse when a tool response carries `events_jwt`; deleted on `pause_local`/`pause_after_complete`.

### Schema

```json
{
  "events_jwt": "eyJ...",
  "exp": "2026-05-16T11:39:58+00:00",
  "session_id": "6b2c027d-...",
  "gen_stream_id": "6b2c027d:34e704e1:e30cea73617e",
  "issued_at": "2026-05-11T11:39:58+00:00"
}
```

File permissions: `0600`. Written atomically (`.tmp` + `os.replace`).

### Auth flow

PostToolUse uses this for every POST:

```
Authorization: Bearer <events_jwt>
```

Backend (wizard) validates the JWT, extracts the `session_id` claim, compares against the path session_id, accepts or rejects (401).

Failure modes the hook handles:
- File absent → silent no-op (we're not in coding mode).
- `session_id` mismatch (file's vs record's) → skip POST, log warning.
- `exp` past → skip POST (defense-in-depth before the 401).
- HTTP 401 → drop the record (next coding entry mints a fresh JWT).

### Why a separate file from the sentinel

Two reasons:
1. **File mode**: events_jwt is 0600 (secret); sentinel is 0644 (state).
2. **Lifecycle**: sentinel persists across menu↔coding flips; events_jwt is born + killed per build (each `pause_after_complete` wipes it; each `send_message` mints fresh).

## `catalyst-event-sink-offsets.json` — transcript line cursor

Per-transcript "lines already scanned" cursor. Used by `_latest_turn_text` to do incremental scans.

### Schema

```json
{
  "/Users/lsn-ashwin/.claude/projects/-Users-lsn-ashwin-codeGen/a5185aa6-....jsonl": 67,
  "/Users/lsn-ashwin/.claude/projects/-Users-lsn-ashwin-codeGen/7192e240-....jsonl": 75
}
```

Keys are **absolute paths** (from `event.transcript_path`). Values are line counts at last write.

### Writers

Two write sites:

1. **`_latest_turn_text`** (every scan) — `_write_offset(path, len(lines))` after extracting text. Re-stamps to current EOF.
2. **`_run` coding-entry fast-forward** (NEW) — when `became_coding=True`, stamps to EOF before any extraction. Prevents pre-coding banter leak.

### Reader

`_latest_turn_text`: `start = int(offsets.get(path, 0))`. Missing key → start at 0 (pre-fast-forward bug source).

### Self-healing

If `start > len(lines)` (transcript rotated), reset to 0. CC almost never rotates these.

## `catalyst-event-sink-pending.jsonl` — failed POSTs

Best-effort dump of records that couldn't be delivered. Line-per-record JSON:

```json
{"session_id": "6b2c027d-...", "record": {"kind": "tool_call", "payload": {...}}}
```

**Not retried automatically.** Lives for postmortem. Tail it after a build to see what got lost.

## `catalyst-event-sink.log` — summary log

One line per hook fire, plus a few lines for sentinel-shape/decision events. Rotating: 2 MB × 2 backups.

### Format

```
2026-05-11 17:09:58,747 [INFO] [bd3bbb] enrich shape: tool=send_message response_keys=<list len=1> parsed_keys=['app_name', ...]
2026-05-11 17:09:58,747 [INFO] [bd3bbb] sentinel set: mode=coding session_id=6b2c027d
2026-05-11 17:10:03,388 [INFO] [df024d] ← hook=PostToolUse tool=ToolSearch cc=a5185aa6 session=6b2c027d posted=3 kinds=[assistant_text,tool_call,tool_result] http=[200,200,200] dt=379ms
```

Every fire has an entry line (`→`) and a summary line (`←`). The `[run_id]` (6-char hex) prefix correlates them. Use `grep "[<run_id>]"` to pull all lines for one fire.

## `catalyst-hook-debug.log` — verbose payload dump

Two writers:
- **PreToolUse**: unconditional. Single line per fire, `FIRED tool=… cc=…`.
- **PostToolUse**: opt-in via `CATALYST_HOOK_DEBUG=1` in any `.env` in the discovery path. Dumps full stdin event JSON + parsed sentinel state + tool_response. Rotating: 5 MB × 2 backups.

The opt-in form exists because dumping every PostToolUse stdin would fill the disk during a real build. Flip the var when something looks wrong, reproduce, read the file, flip it off.

## When to update this file

- New field in any state file → schema section.
- New file in `~/.claude/state/` → add a section.
- File permissions change → note it.
- New writer site for an existing file → list it under "Writers".
