# PostToolUse + Stop — `hook_record.py`

Single hook script registered for both events. Source: [hooks/hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py).

## Top-level flow ([hook_record.py:1198](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1198))

```
_run
 │
 ▼
parse stdin event
 │
 ├─ no event.session_id → noop=no-cc-session-id, exit 0
 │
 ▼
stamp _CC_SESSION_ID = event.session_id     ← the sentinel helpers below scope
 │                                            every read/patch/remove to THIS
 ▼                                            tab's registry row
read THIS TAB's registry row (_read_sentinel → session_registry.read_entry)
 │
 ├─ no row             → noop=no-session-for-tab, exit 0
 │
 ▼
hook == PostToolUse?
 │
 ├─ yes → _enrich_sentinel_from_response(tool_name, tool_response)
 │           ├─ _maybe_update_local_sentinel  (session_id, mode, app_root, gen_stream_id)
 │           ├─ _maybe_persist_events_jwt     (write events_jwt file if response carries one)
 │           └─ _maybe_clear_local_state      (pause_local / pause_after_complete)
 │        re-read the row
 │
 ▼
row.session_id present?
 │
 ├─ missing            → noop=sentinel-missing-session-id, exit 0
 │
 ▼
row.mode in {coding, vibe_code, spec, deep_analysis}?
 │
 ├─ no                 → noop=mode-not-recordable(mode=…), exit 0
 │
 ▼
anchor snap: anchors[transcript_path] != session_id?
 │
 ├─ yes → offset = EOF, anchors[path] = session_id   (pre-session lines never leak)
 │
 ▼
hook == PostToolUse → _translate_post_tool(event)
hook == Stop        → _translate_stop(event)
hook == UserPromptSubmit → _translate_user_prompt(event)
 │
 ▼
no records?           → noop=no-records, exit 0
 │
 ▼
for each record:
   ├─ kind == "auto_complete" → POST /api/sessions/{sid}/auto-complete
   └─ else                    → POST /api/events/record/{sid}
exit 0
```

## Gates in detail

### Gate 1 — per-tab row (replaced the cross-tab owner check, 2026-08-10)

The registry is keyed by the firing tab's `cc_session_id`, so `_read_sentinel()` returning a row already MEANS "this tab has an active Catalyst session" — a row can't belong to another tab, and other tabs' rows are invisible here. The old `not-owner(owner=…)` drop can no longer happen; the corresponding noop is now `no-session-for-tab`. Claiming still happens ONLY in PreToolUse — the record path never creates rows (`_patch_sentinel` refuses when no row exists).

### Gate 2 — mode

```python
if new_mode not in ("coding", "vibe_code", "spec", "deep_analysis"):
    ctx.noop_reason = f"mode-not-recordable(mode={new_mode})"
    return 0
```

All four Claude-Code-driven modes stream to the project view via the hook; `menu` has no active work to record. Safe-by-default: a new mode can never leak turns into a build's history unless explicitly added to the tuple.

### Offset anchor snap (2026-06-09; per-tab-safe by construction)

Sync follows the `session_id`, anchored per-transcript (`catalyst-event-sink-anchors.json`, `{transcript_path: session_id}`). The FIRST recordable fire that sees `session_id != anchor[path]` snaps the offset to EOF + re-anchors — pre-session banter and other-Mindspace lines never leak into the new session. Because each CC tab has its OWN transcript file, this machinery needed no changes for multi-session: tab A's anchor/offset never collide with tab B's.

## Spilled-response recovery ([hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py) `_resolve_spilled_response`, NEW 2026-06-01)

**Runs BEFORE enrichment.** Claude Code truncates any tool result larger than its max tool-result size: it saves the real output to `<transcript-dir>/tool-results/*.txt` and replaces the inline result with a stub (`"… exceeds maximum allowed tokens. Output has been saved to <path>"`). The **coding-entry `send_message` response routinely trips this** — PRD `kickoff_message` (~27 KB) + `past_messages` (~20 KB) → ~59 KB. The stub carries NONE of the fields enrichment needs (`mode`/`session_id`/`events_jwt`), so without recovery the sentinel never flips to `coding` and **every later coding turn silently no-ops `mode-not-coding(mode=menu)` — no persistence, no WS** (the 2026-06-01 bug; also hit a build on 2026-05-25). `_resolve_spilled_response` sniffs the stub (`"exceeds maximum allowed tokens"` + `"Output has been saved to "`), reads the spilled `.txt`, and returns its content as a `[{type:text,text:…}]` block so `_parse_tool_response` recovers the dict. Best-effort; returns the response unchanged on any miss. **Manual repair** if a build was stuck pre-fix: read the spill file, write `events_jwt` (the JWT is in it, valid for days) + flip the sentinel `mode` to `coding`.

## Sentinel enrichment ([hook_record.py:541](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L541))

Only for catalyst-mcp tool responses. The raw `tool_response` is first passed through `_resolve_spilled_response` (above). Three sub-actions:

### `_maybe_update_local_sentinel` ([hook_record.py:392](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L392))

Mirrors the server-side logic from `lifecycle.py`. Mirrors needed because server's `_maybe_update_local_sentinel` writes to the EC2 process's `Path.home()`, useless to the user's local hook.

Branching by response shape:
- `mode in {coding, vibe_code}` AND session_id+app_root+gen_stream_id all present → full sentinel write.
- `kickoff_message` AND session_id+app_root+gen_stream_id → full sentinel write, mode forced to `coding`.
- Otherwise → partial update of whichever fields are present.

**Consistency check** (partial responses only): if this tab's row has a session_id that doesn't match the response's session_id, drop the update (stale response for this tab). A FULL project entry (sid + app_root + gen_stream_id + explicit mode) overrides — that's how switching Mindspaces in the same tab works.

### `_maybe_persist_events_jwt` ([hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py))

When the response carries `events_jwt` (+ `events_jwt_exp`), write to `~/.claude/state/catalyst-events-jwt.json` with chmod 600. The token is IDENTITY-only (no session binding, no cross-check) — `ensure_auth`/`health_check` return it on every activation/reauth, and one file serves every tab.

### `_maybe_clear_local_state` ([hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py))

Per-tab — both branches touch ONLY the firing tab's registry row:

- `pause_local: True` → `session_registry.remove(cc)` (this row only).
- `pause_after_complete: True` → patch this row to `mode=menu, session_id=None`.

**Neither branch touches the events_jwt anymore** — it's identity-scoped (shared by all tabs); only `logout` (PreToolUse Case 0) deletes it.

## Record translation

### `_translate_post_tool` ([hook_record.py:652](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L652))

Skips catalyst-mcp lifecycle calls (`start_coding`, `send_message`, etc.) — those are plumbing, not build content. Only `coding_workspace__*` represents real build steps.

Emits up to 4 records in order:

1. `thinking` — if transcript has thinking blocks since last scan
2. `assistant_text` — if transcript has assistant text since last scan
3. `tool_call` — from event's tool_input
4. `tool_result` — from event's tool_response

Records 1+2 come from `_latest_turn_text(transcript_path)`. Records 3+4 come directly from the event payload — they can't leak from pre-coding history.

### `_translate_stop` ([hook_record.py:728](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L728))

Captures end-of-turn:

1. `thinking` (if present)
2. `assistant_text` (if present)
3. `auto_complete` (if the last non-blank line of assistant_text is `{"status":"completed","summary":"..."}`)

The `auto_complete` record is routed separately — POSTs to `/api/sessions/{sid}/auto-complete` instead of `/api/events/record`. That endpoint runs migrations + start.sh; uses a 120s timeout.

## Auto-complete detection ([hook_record.py:760](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L760))

Requires BOTH:
- `status == "completed"`
- `summary` non-empty (skeleton-emit avoidance)

Otherwise returns None. Tolerates single-quoted JSON-ish form.

## Summary line format ([hook_record.py:1172](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1172))

One line per fire, in `catalyst-event-sink.log`:

```
[abc123] ← hook=PostToolUse tool=Read cc=a5185aa6 session=6b2c027d
         posted=3 kinds=[assistant_text,tool_call,tool_result] http=[200,200,200] dt=124ms
```

`noop=<reason>` appears when nothing got posted. Reasons (drop priority order):
- `no-cc-session-id`
- `no-session-for-tab`  (this tab has no registry row — replaced `no-sentinel` / `not-owner`)
- `sentinel-missing-session-id`
- `mode-not-recordable(mode=…)`
- `unhandled-hook(…)`
- `no-records`
- `no-events-jwt` / `events-jwt-expired` / `events-jwt-session-mismatch` / `events-jwt-malformed`
- `all-posts-failed(http=…)`

## When to update this file

- Gate order changes.
- New `noop_reason` added.
- New record `kind`.
- Sentinel enrichment logic changes.
- `_translate_post_tool` / `_translate_stop` signature or output changes.
