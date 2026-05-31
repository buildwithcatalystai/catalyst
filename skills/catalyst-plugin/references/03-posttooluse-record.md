# PostToolUse + Stop — `hook_record.py`

Single hook script registered for both events. Source: [hooks/hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py).

## Top-level flow ([hook_record.py:1198](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1198))

```
_run
 │
 ▼
parse stdin event
 │
 ▼
read sentinel
 │
 ├─ missing            → noop=no-sentinel, exit 0
 │
 ▼
owner gate (sentinel.cc_session_id vs event.session_id)
 │
 ├─ mismatch           → noop=not-owner(owner=…), exit 0
 │
 ▼
hook == PostToolUse?
 │
 ├─ yes → _enrich_sentinel_from_response(tool_name, tool_response)
 │           ├─ _maybe_update_local_sentinel  (session_id, mode, app_root, gen_stream_id)
 │           ├─ _maybe_persist_events_jwt     (write events_jwt file if response carries one)
 │           └─ _maybe_clear_local_state      (pause_local / pause_after_complete)
 │        re-read sentinel
 │
 ▼
sentinel.session_id present?
 │
 ├─ missing            → noop=sentinel-missing-session-id, exit 0
 │
 ▼
sentinel.mode in {coding, vibe_code}?
 │
 ├─ no                 → noop=mode-not-coding(mode=…), exit 0    [NEW gate]
 │
 ▼
became_coding edge?  (prev_mode wasn't coding OR prev_sid empty OR prev_sid changed)
 │
 ├─ yes → fast-forward offset to EOF of transcript file          [NEW write]
 │
 ▼
hook == PostToolUse → _translate_post_tool(event)
hook == Stop        → _translate_stop(event)
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

### Gate 1 — owner ([hook_record.py:573](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L573))

Compares `sentinel.cc_session_id` (the owner) to `event.session_id` (this firing tab). Three outcomes:

- Empty owner → defer (`hook deferred: sentinel has no owner yet`). PreToolUse claims the sentinel; PostToolUse never does.
- Owner == this tab → pass.
- Owner != this tab → BLOCKED (`cc_session=X is not the owner — record dropped`).

This stops cross-tab leakage.

### Gate 2 — mode ([hook_record.py:1265](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1265), NEW)

```python
if new_mode not in ("coding", "vibe_code"):
    ctx.noop_reason = f"mode-not-coding(mode={new_mode})"
    return 0
```

Brainstorm/menu/db_finalize phases persist natively via the wizard's LangGraph. The hook has nothing useful to record there. **`deep_analysis` deliberately falls through this gate too** — it's not in the sync allowlist, so research turns are a no-op (ephemeral, no app row to persist to). Safe-by-default: a new mode can never leak turns into a build's history unless it's explicitly added to the `(coding, vibe_code)` tuple.

### Offset fast-forward on coding entry ([hook_record.py:1273](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1273), NEW)

```python
became_coding = (
    prev_mode not in ("coding", "vibe_code")
    or not prev_sid
    or prev_sid != session_id
)
if became_coding:
    eof = len(Path(transcript_path).read_text(...).splitlines())
    _write_offset(transcript_path, eof)
```

Stops pre-coding banter (project menu, "which Login app?", etc.) from being scooped up by the first `_latest_turn_text` scan. Fires exactly once per coding entry; subsequent calls see `prev_mode == coding` and skip.

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

**Consistency check**: if local sentinel has a session_id that doesn't match the response's session_id, drop the update (cross-tab race / stale response).

### `_maybe_persist_events_jwt` ([hook_record.py:498](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L498))

When the response carries `events_jwt` + `events_jwt_exp`, write to `~/.claude/state/catalyst-events-jwt.json` with chmod 600. Cross-checks: response's session_id must match the sentinel's session_id.

### `_maybe_clear_local_state` ([hook_record.py:464](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L464))

- `pause_local: True` → unlink sentinel + events_jwt.
- `pause_after_complete: True` → patch sentinel to `mode=menu, session_id=None`; unlink events_jwt.

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
- `no-sentinel`
- `not-owner(owner=…)`
- `sentinel-missing-session-id`
- `mode-not-coding(mode=…)`
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
