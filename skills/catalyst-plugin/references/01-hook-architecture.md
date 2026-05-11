# Hook architecture

CC's hook system spawns one subprocess per registered hook per event. Hooks are shell-out scripts; nothing runs in-process with CC.

## Registered hooks ([hooks/hooks.json](../../../codeGen/catalyst-plugin/hooks/hooks.json))

| Event | Script | Timeout | Purpose |
|---|---|---|---|
| `PreToolUse` | `catalyst-block-native.py` | 5s | Claim sentinel, gate cross-tab, block native FS tools on owning tab |
| `PostToolUse` | `hook_record.py` | 10s | Sync tool call + narration to wizard |
| `Stop` | `hook_record.py` | 10s | Sync end-of-turn narration + detect auto-complete signal |

Both hooks are `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/<script>.py` — `$CLAUDE_PLUGIN_ROOT` is set by CC to the plugin's install dir.

## Per-fire lifecycle

```
CC about to run tool X
   │
   ▼
fork ─→ python3 catalyst-block-native.py
        │   stdin: {hook_event_name, session_id, tool_name, tool_input, ...}
        │   stdout: PreToolUse decision JSON
        │   exit:   0 ALWAYS (non-zero makes CC ignore stdout)
        ▼
CC reads stdout JSON
   │
   ├─ permissionDecision=allow / no JSON → run tool
   │     │
   │     ▼
   │   Tool executes
   │     │
   │     ▼
   │   fork ─→ python3 hook_record.py
   │           │   stdin: {hook_event_name="PostToolUse", tool_name, tool_response, transcript_path, session_id, ...}
   │           │   stdout: ignored
   │           │   exit:   0 ALWAYS
   │           └─ side-effects: HTTP POST to wizard, write logs/state files
   │
   └─ permissionDecision=deny → tool refused, reason shown to assistant

(At end of autonomous run)
   │
   ▼
fork ─→ python3 hook_record.py  (Stop event)
        │   stdin: {hook_event_name="Stop", transcript_path, session_id, ...}
        └─ Extract any trailing assistant_text + auto_complete detection
```

## stdin payload shapes

### Common fields (all events)
- `hook_event_name`: `"PreToolUse" | "PostToolUse" | "Stop"`
- `session_id`: CC tab's UUID (mismatch with sentinel's `cc_session_id` → cross-tab)
- `transcript_path`: absolute path to `{session_id}.jsonl`

### PreToolUse / PostToolUse extras
- `tool_name`: e.g. `"mcp__plugin_catalyst_catalyst-mcp__send_message"`, `"Bash"`, `"Read"`
- `tool_input`: args dict
- `tool_response` (PostToolUse only): tool's return value. For MCP tools this is usually `[{"type": "text", "text": "<json>"}]` (bare content list).

## Output contracts

### PreToolUse (CURRENT contract — changed mid-2026)

Must emit JSON to stdout, exit 0:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "<text the assistant sees>"
  }
}
```

`permissionDecision` ∈ `{"allow", "deny", "ask"}`. With `deny`, the assistant receives `permissionDecisionReason` in its context.

**Old form is dead.** `{"decision":"block"}` + `exit 2` is silently ignored — CC just runs the tool. The error mode is invisible; you only notice when blocks stop working.

**Exit code must be 0.** Non-zero → CC short-circuits before reading stdout.

### PostToolUse / Stop

No structured contract. Stdout is logged but not parsed. Exit code is checked — non-zero is logged but doesn't affect CC. Convention: **always exit 0**, log failures via `logger.warning`.

## Why each runs as a subprocess

CC could in principle host hooks in-process, but the subprocess model:
- Survives hook crashes (CC keeps working)
- Lets the hook use any Python (no version coupling to CC)
- Reads CC's stdin event without an FFI surface
- Lets the user kill a wedged hook without restarting CC

Cost: ~50ms cold-start per fire. Acceptable.

## Idempotency / re-entry

Hooks can re-fire on the same tool call if CC retries. PreToolUse claim is idempotent (overwrite same JSON). PostToolUse sync is NOT — duplicate fires would post the same record twice. CC doesn't currently retry, so this isn't observed.

## What's NOT a hook

- MCP tool calls go over HTTP to `http://13.202.117.250:9000/mcp` (wizard's `mcp_runner.py`). Hooks observe calls but don't implement them.
- WebSocket streaming from wizard to its own UI is a separate channel — not relevant inside CC.

## When to update this file

- New hook event registered/removed → here + `hooks.json`.
- Hook timeout changes → here + `hooks.json`.
- Output contract changes → update PreToolUse section + both hook scripts.
