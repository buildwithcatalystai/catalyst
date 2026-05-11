# PreToolUse — `catalyst-block-native.py`

Single hook, three responsibilities, executed in order. Source: [hooks/catalyst-block-native.py](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py).

## Responsibilities

1. **Tab registration** — claim the sentinel on the first catalyst-mcp call from any tab.
2. **Cross-tab refusal** — deny catalyst-mcp calls from non-owning tabs.
3. **Native-tool block on owning tab** — refuse `Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob`/`Agent`/`WebFetch`/`WebSearch` with a redirect to `coding_workspace__*`.

## Decision tree

```
fire
 │
 ▼
parse stdin → event{tool_name, session_id (cc tab), ...}
 │
 ▼
is bare="end" or "abandon_build" (catalyst tool)?
 │   yes → unlink sentinel, return 0 (allow call through)
 │
 ▼
sentinel exists?
 │   no  → if catalyst tool: claim {cc_session_id, mode=menu}; return 0
 │         else: return 0 (no claim, no block)
 │
 ▼
sentinel owner matches event.session_id?
 │
 ├─ yes (owning tab) ───────────────────────┐
 │                                          │
 │   tool in ALLOW_EXACT? ──── yes → allow  │
 │   is MCP tool (any server)? ─ yes → allow│
 │   is in REDIRECTS map? ───── yes → deny with redirect text
 │   else                              → allow
 │                                          │
 ▼ no (different tab)
   is non-catalyst tool?            → allow (don't punish unrelated work)
   in CROSS_TAB_ALLOWED_BARE?       → allow (end/abandon/current_session)
   else                              → deny with disambiguation prompt
```

## Key data

### REDIRECTS map ([catalyst-block-native.py:75](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py#L75))

```python
REDIRECTS = {
    "Read":         "coding_workspace__read",
    "Write":        "coding_workspace__write",
    "Edit":         "coding_workspace__edit",
    "MultiEdit":    "coding_workspace__edit",
    "Bash":         "coding_workspace__bash",
    "Grep":         "coding_workspace__grep",
    "Glob":         "coding_workspace__find",
    "Agent":        "coding_workspace__Agent",
    "WebFetch":     "coding_workspace__web_search",
    "WebSearch":    "coding_workspace__web_search",
    "NotebookEdit": "coding_workspace__edit",
}
```

Why redirect: the build's workspace lives on EC2 (or pinned to project's `app_root`). Native tools would silently edit the wrong filesystem. The deny reason names the bare catalyst tool; the agent has the namespaced version loaded and picks the right form.

### ALLOW_EXACT ([catalyst-block-native.py:90](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py#L90))

Always allowed for owning tab, even during build:

```python
ALLOW_EXACT = {"TodoWrite", "AskUserQuestion", "Skill",
               "SlashCommand", "ToolSearch",
               "ExitPlanMode", "EnterPlanMode"}
```

These don't touch the filesystem.

### CROSS_TAB_ALLOWED_BARE ([catalyst-block-native.py:69](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py#L69))

```python
_CROSS_TAB_ALLOWED_BARE = {"abandon_build", "end", "current_session"}
```

Even from a non-owning tab, these always work. They're the escape hatches for a wedged sentinel from a crashed owner tab.

## Sentinel claim on first call

When sentinel is absent AND the tool is a catalyst-mcp tool:

```python
_write_sentinel({
    "cc_session_id": cc_session_id,        # the CLAIMING tab
    "started_at": "<UTC ISO>",
    "session_id": None,                     # no build yet
    "app_root": "",
    "gen_stream_id": "",
    "mode": "menu",                         # not coding yet
})
```

This happens on `ensure_auth` (the skill's first call). After this point, every other tab gets cross-tab-refused for any catalyst tool.

## Tool-name namespace pattern matching

CC mangles the namespace differently per install path:

- Direct: `mcp__catalyst-mcp__<tool>`
- Plugin: `mcp__plugin_catalyst_catalyst-mcp__<tool>` (CC turns `:` → `_`)

Both end with substring `catalyst-mcp__`. Detection via substring match, not prefix:

```python
_CATALYST_MARKER = "catalyst-mcp__"
def _is_catalyst_mcp_tool(name):
    return name.startswith("mcp__") and _CATALYST_MARKER in name
```

**Never hard-code the full prefix** — breaks when install path changes.

## Deny-reason text is assistant-facing

With `permissionDecision="deny"`, the assistant sees `permissionDecisionReason` in context. That text is structured as instructions: e.g. for cross-tab refusal, it tells the assistant to ask the user whether to switch tabs or end the other session. The assistant follows the embedded instructions on its next turn.

This is how the plugin gets the assistant to react to a block — there's no direct "show this to the user" channel; the assistant translates.

## Debug log

Every fire writes one line to `~/.claude/state/catalyst-hook-debug.log` (UNCONDITIONAL — not gated by `CATALYST_HOOK_DEBUG`):

```
2026-05-11 17:08:55 FIRED tool='mcp__plugin_catalyst_catalyst-mcp__ensure_auth' cc=a5185aa6 is_catalyst=True sentinel_exists=False sentinel_owner=''
2026-05-11 17:08:55   → CLAIMED sentinel cc=a5185aa6
```

This is the log to read when "why isn't the sentinel getting claimed?" or "why is my tab being refused?".

## When to update this file

- REDIRECTS / ALLOW_EXACT / CROSS_TAB_ALLOWED_BARE changes.
- New case added to the decision tree.
- Deny-reason text restructured (the assistant-facing instructions matter — review them when touching).
