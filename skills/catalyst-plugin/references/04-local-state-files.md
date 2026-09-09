# Local state files — `~/.claude/state/`

Six files the plugin writes (five state + a lock). CC owns the directory; the plugin co-tenants it.

## `catalyst-active-session.json` — per-tab session registry

**One row per Claude Code tab** (multi-session model, 2026-08-10, plugin v0.1.44 — replaced the single-owner sentinel object). The shared module `hooks/session_registry.py` is the ONLY code that knows this shape; both hooks speak the legacy flat field names (`cc_session_id`/`session_id`/`started_at`) through its API (`read_entry`/`claim`/`patch`/`remove`/`touch`/`all_entries`) and each operates strictly on the FIRING tab's row.

### Schema (v2)

```json
{
  "version": 2,
  "sessions": [
    {
      "claude_session_id": "a5185aa6-9036-41a7-b752-c53f13ed3f28",
      "catalyst_session_id": "6b2c027d-4039-450b-a711-ab853485a178",
      "app_root": "/home/ubuntu/projects/6b2c027d-...",
      "gen_stream_id": "6b2c027d:34e704e1:e30cea73617e",
      "mode": "coding",
      "created_dt": "2026-08-08T08:30:40Z",
      "last_updated_dt": "2026-08-10T10:12:03Z"
    }
  ]
}
```

| Field | Source | Notes |
|---|---|---|
| `claude_session_id` | PreToolUse claim | The CC tab UUID — the row's KEY. Immutable. Legacy API name: `cc_session_id`. |
| `catalyst_session_id` | PostToolUse enrichment | Catalyst Mindspace UUID. `switch_mindspace` updates it IN PLACE (same row, no new row). Legacy API name: `session_id`. |
| `app_root` | PostToolUse enrichment | Project path on EC2 (`/home/ubuntu/projects/{slug}`). |
| `gen_stream_id` | PostToolUse enrichment | Wizard's checkpointer thread id: `{app_id}:{user_id}:{uuid[:12]}`. |
| `mode` | PostToolUse enrichment (or `start_analysis`) | `menu` (claimed but no project) / `coding` / `vibe_code` / `spec` / `deep_analysis`. |
| `created_dt` | PreToolUse claim | ISO-8601 UTC, **date AND time to the second**, `Z`-suffixed. Legacy API name: `started_at`. |
| `last_updated_dt` | every use | Same format. Refreshed by `touch()` on each PreToolUse fire (throttled — skipped if <60s old) and on every `patch()`. Drives the GC. |

### GC + locking + migration

- **GC:** on every save, rows whose `last_updated_dt` is more than **10 days** behind now (`timedelta(days=10)` — instants, not calendar days) are dropped. Unparseable timestamp → treated as just-used (kept), never expired. The row being written is never dropped.
- **Locking:** every mutation is read→modify→write under `fcntl.flock` on the sibling **`catalyst-sessions.lock`** (separate file because the atomic `.tmp` + `os.replace` write swaps the data file's inode). No fcntl (Windows) → no-op lock, atomic replace only.
- **Migration:** a legacy single-object sentinel (top-level `cc_session_id`, no `sessions` key) is read as one row and rewritten as v2 on the first mutation (`touch` bypasses its throttle while the file is still v1, so the first fire persists the upgrade). The live session survives.

### Lifecycle (per row — tabs are independent)

```
[no row for this tab]
   │
   │ first catalyst-mcp tool call FROM THIS TAB
   │ PreToolUse claim
   ▼
{claude_session_id, mode=menu, catalyst_session_id=null}
   │
   │ entry response (start_analysis / start_app_building / send_message …)
   │ PostToolUse enrichment
   ▼
{...all fields populated..., mode=coding|deep_analysis|spec}
   │
   ├─ switch_mindspace → catalyst_session_id updated IN PLACE (same row)
   │
   │ end / abandon_build FROM THIS TAB
   │ PreToolUse handler (BEFORE the call) removes THIS row only
   ▼
[no row for this tab — other tabs' rows untouched]

OR
   │ complete_build returns pause_after_complete=true
   │ PostToolUse _maybe_clear_local_state
   ▼
{...row kept..., mode=menu, catalyst_session_id=null}

OR
   │ 10 days idle
   ▼
[row garbage-collected on the next save]
```

There is NO cross-tab refusal: two tabs may even hold the SAME Mindspace (their turns interleave in that one chat history).

### Who reads it

- PreToolUse: this tab's row → mode gate, session-id injection, claim/remove/touch.
- PostToolUse: this tab's row → recordable-mode gate, session_id for the HTTP path, enrich/clear.
- The skill (`catalyst-mcp` server-side): does NOT read it — the server is stateless; routing travels as the injected `session_id` arg.
- `catalyst_mcp/status.sh`: cats the whole file for diagnostics (`session_registry.all_entries()` from Python).

## `catalyst-sessions.lock` — registry mutation lock

Zero-byte sibling of the registry; `fcntl.flock` target for read→modify→write cycles. Exists because `os.replace` swaps the data file's inode, which would orphan a lock held on the data file itself. Safe to delete when no hook is mid-fire.

## `catalyst-events-jwt.json` — identity JWT (shared by every tab)

**Identity-only, NOT session-bound** — one token authenticates record-POSTs for ALL tabs. Written by PostToolUse whenever a tool response carries `events_jwt` (`ensure_auth`/`health_check` return it on every activation/reauth). Deleted ONLY by `logout` (the signed-in user changed) — `end`/`abandon_build`/`pause_after_complete` no longer touch it, so one tab finishing its build can't de-auth the others.

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

### Why a separate file from the registry

Two reasons:
1. **File mode**: events_jwt is 0600 (secret); the registry is 0644 (state).
2. **Scope**: the registry is per-tab (rows come and go with each tab's session); the events_jwt is per-IDENTITY (one token for all tabs, lives until `logout` or natural exp — refreshed by any tab's `ensure_auth`/`health_check`).

## `catalyst-event-sink-offsets.json` — transcript line cursor

Per-transcript "lines already scanned" cursor. Used by `_latest_turn_text` to do incremental scans.

### Schema

```json
{
  "/Users/you/.claude/projects/-Users-you-codeGen/a5185aa6-....jsonl": 67,
  "/Users/you/.claude/projects/-Users-you-codeGen/7192e240-....jsonl": 75
}
```

Keys are **absolute paths** (from `event.transcript_path`). Values are line counts at last write.

### Writers

Two write sites:

1. **`_latest_turn_text`** (every scan) — `_write_offset(path, len(lines))` after extracting text. Re-stamps to current EOF.
2. **`_run` session-id anchor snap** (2026-06-09, replaced the mode-based `became_coding` fast-forward) — when the active `session_id != anchor[path]`, stamps the offset to EOF + re-anchors, before any extraction. Prevents pre-session / other-Mindspace banter leak.

### Reader

`_latest_turn_text`: `start = int(offsets.get(path, 0))`. Missing key → start at 0 (pre-anchor bug source).

## `catalyst-event-sink-anchors.json` — session_id the offset is anchored to

Per-transcript map `{absolute_transcript_path: session_id}`. Records which Mindspace the offset cursor is currently anchored to. **The sync window follows the `session_id`:** the first recordable hook fire that sees `session_id != anchor[path]` (empty→set on entry, or a switch to a different Mindspace) snaps the offset to EOF and rewrites the anchor — so the new session's stream starts clean and pre-session / other-session lines never leak. Keyed on the session_id itself (not the sentinel's volatile `prev_sid`), so the snap is robust even if the exact entry tool fire lacked a `transcript_path`. Writers: `_write_anchor`; reader: `_read_anchor`.

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
