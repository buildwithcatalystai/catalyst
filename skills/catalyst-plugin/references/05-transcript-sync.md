# Transcript sync — how CC turns become wizard chat

The piece that turns "agent narrates between tool calls" into "the wizard's ChatPane shows it." Source: `_latest_turn_text` + `_translate_post_tool` + `_translate_stop` in [hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py).

## CC transcript JSONL — the upstream

CC writes one JSON object per line to `~/.claude/projects/{cwd-encoded}/{cc_session_id}.jsonl`.

- **Path provenance**: comes from `event["transcript_path"]`. CC is the writer and tells the hook where it's writing. The hook never derives the path.
- **Filename = cc_session_id**: but this is a CC convention, not something the hook depends on.
- **CWD encoding**: slashes flipped to dashes. `/Users/you/codeGen` → `-Users-you-codeGen`.
- **Append-only**: line count only grows during a tab's lifetime.
- **One file per tab**, not per project. Two tabs on same repo → two JSONL files.

## Entry shapes ([hook_record.py:872](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L872))

Each line is `{"message": {...}, ...}`. Within `message`:

| `role` | What it carries |
|---|---|
| `"user"` | Real user prompts OR tool_results (distinguished by content shape — tool_results have `[{"type":"tool_result", ...}]`) |
| `"assistant"` | Assistant turn — mix of `text`, `thinking`, `tool_use` content blocks |

The hook only extracts from `role: "assistant"` entries. Within those, it splits content blocks by type:
- `text` → `assistant_text` payload
- `thinking` → `thinking` payload
- `tool_use` → SKIPPED (the `tool_call` record comes from `event.tool_input` instead)

## `_latest_turn_text` ([hook_record.py:832](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L832))

```python
def _latest_turn_text(path):
    lines = Path(path).read_text(...).splitlines()
    offsets = _read_offsets()
    start = int(offsets.get(path, 0))
    if start > len(lines):
        start = 0  # self-heal on rotation

    text_parts, thinking_parts = [], []
    for line in lines[start:]:
        entry = json.loads(line)
        msg = entry.get("message")
        if msg.get("role") != "assistant":
            continue
        for block in msg.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "thinking":
                thinking_parts.append(block["thinking"])

    _write_offset(path, len(lines))   # advance cursor
    return "\n".join(thinking_parts), "\n".join(text_parts)
```

Three properties:

1. **Incremental** — only scans lines `[start:]`. Start comes from offsets file.
2. **Self-stamping** — writes EOF as new offset before returning.
3. **No `tool_use` extraction** — those go through `PostToolUse`'s direct `event` payload, NOT the transcript.

## Why `tool_use` blocks aren't extracted from transcript

The transcript records what happened. The hook fires PER tool call with the same data in `event.tool_input` / `event.tool_response`. Extracting from transcript would either:
- Duplicate (already emitting from event)
- Drift (transcript might log differently than event)

Cleaner: use `event` for the structured tool fields; use transcript only for the unstructured narration that happens BETWEEN tool calls.

## What `_translate_post_tool` emits ([hook_record.py:652](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L652))

For one PostToolUse fire:

```
records = []
thinking, text = _latest_turn_text(event.transcript_path)
if thinking:  records.append({"kind": "thinking", ...})
if text:      records.append({"kind": "assistant_text", ...})
records.append({"kind": "tool_call",   "payload": {tool_name, args, call_id, label}})
records.append({"kind": "tool_result", "payload": {tool_name, content, call_id, label}})
```

`call_id` correlates `tool_call` and `tool_result` on the wizard side. Comes from `event.tool_use_id` (CC mints) or a uuid fallback.

`label` is rendered by `_format_label` ([hook_record.py:907](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L907)) — short human-readable string like `"$ ls /tmp"`, `"Read: foo.py"`, `"sub-agent: investigate auth"`. Used by ChatPane to render the tool card.

## What `_translate_stop` emits ([hook_record.py:728](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L728))

End-of-turn extraction:

```
thinking, text = _latest_turn_text(event.transcript_path)
records = []
if thinking:  records.append({"kind": "thinking", ...})
if text:      records.append({"kind": "assistant_text", ...})
auto = _detect_completion_signal(text)
if auto:      records.append({"kind": "auto_complete", "payload": auto})
```

Auto-complete is what makes "the agent emits a final JSON line → build flips to completed → wizard kicks off deploy" work end-to-end without an explicit `complete_build` tool call. The agent's prompt ends every reply with this JSON; the Stop hook fires when CC decides the run is done; the JSON is detected and POSTed to `/auto-complete`.

## Why text-extraction happens on PostToolUse, not just Stop

CC's autonomous loop emits one assistant message containing many content blocks (text, tool_use, text, tool_use, …) THEN runs tools THEN emits more blocks. **Stop fires only once** at the end of the whole autonomous run.

Without per-PostToolUse extraction, the intermediate narration ("I'll do X / now let me check Y") would only land in chat AFTER the entire build run finishes — too late to be useful. PostToolUse picks it up turn-by-turn.

The offset machinery ensures the same text isn't emitted twice — once on PostToolUse, then again on the trailing Stop.

## The pre-coding leak we fixed

Before the fast-forward patch:

- Offset for a new transcript was 0 the first time `_latest_turn_text` ran.
- First PostToolUse after `send_message` would scan from line 0, scooping up all pre-coding banter ("Here's what you have so far / which Login app?").
- All of it shipped as one `assistant_text` payload.

After ([hook_record.py:1273](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1273)):

- `_run` detects the `prev_mode → coding` edge.
- Stamps `offsets[transcript_path] = len(lines)` BEFORE `_translate_post_tool` runs.
- First `_latest_turn_text` call sees the floor at EOF; pre-coding text is invisible.

## When to update this file

- `_latest_turn_text` extraction logic changes (new content block types, role filtering).
- New record `kind`.
- Auto-complete detection rules change.
- Offset reset/self-heal logic changes.
