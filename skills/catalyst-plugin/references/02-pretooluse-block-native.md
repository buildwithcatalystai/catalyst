# PreToolUse — `catalyst-block-native.py`

Single hook, three responsibilities, executed in order. Source: [hooks/catalyst-block-native.py](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py).

**Multi-session model (2026-08-10, plugin v0.1.44):** the state file is a PER-TAB registry (`session_registry.py`, same path `~/.claude/state/catalyst-active-session.json`) — one row per Claude Code tab. There is **no cross-tab refusal anymore**: any number of tabs run independent Catalyst sessions in parallel (even on the same Mindspace — turns interleave in that one chat history). The old Case 4 (deny + disambiguation prompt), `_CROSS_TAB_ALLOWED_BARE`, and the "owner not stamped" defensive case are all GONE.

## Responsibilities

1. **Tab registration** — claim a registry ROW for this tab on its first catalyst-mcp call.
2. **Per-tab lifecycle** — `end`/`abandon_build`/`logout` remove only the CALLING tab's row; `logout` also deletes the identity-scoped events_jwt.
3. **Native-tool block on the tab's own session** — refuse native FS/shell (`Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob`) in Build with a redirect to `coding_workspace__*`. `Agent`, plan mode, and native WEB (`WebFetch`/`WebSearch`) are in `ALLOW_EXACT` — never blocked, every mode.

## Decision tree

```
fire
 │
 ▼
parse stdin → event{tool_name, session_id (cc tab), ...}
entry = registry.read_entry(cc)          ← THIS TAB's row (or None)
 │
 ▼
Case 0: bare="end"/"abandon_build"/"logout" (catalyst tool)?
 │   yes → registry.remove(cc)  — THIS tab's row only
 │         logout: also unlink events_jwt (identity-scoped), return 0
 │         end/abandon: inject row's session_id, allow with updatedInput
 │
 ▼
Case 1: no row for this tab?
 │   catalyst tool → registry.claim(cc) {mode=menu}, fall through
 │   else          → return 0 (no claim, no block)
 │
 ▼
registry.touch(cc)   ← keeps the row warm for the 10-day GC (throttled 60s)
 │
 ▼
Case 2: this tab's session gate (every tab is "owner" of its own row)
     coding_workspace__* tool denied in this mode? → deny            (_DENIED_BY_MODE: Discover/Spec narrow the surface)
     catalyst-mcp tool?  → inject THIS ROW's session_id, allow
     tool in ALLOW_EXACT (incl. Agent, plan mode)? → allow
     native FS/shell outside Build (mode ∉ {coding,vibe_code})? → allow
     native Bash running the upload/download curl? → allow           (transfer carve-out — local↔workspace, plugin only)
     external MCP (mcp__* not catalyst)? → deny (strict allow-list)
     native FS/shell in Build? → deny + redirect to coding_workspace__*
```

## Key data

### REDIRECTS map ([catalyst-block-native.py](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py))

```python
REDIRECTS = {
    "Read":         "coding_workspace__read",
    "Write":        "coding_workspace__write",
    "Edit":         "coding_workspace__edit",
    "MultiEdit":    "coding_workspace__edit",
    "Bash":         "coding_workspace__bash",
    "Grep":         "coding_workspace__grep",
    "Glob":         "coding_workspace__find",
    "NotebookEdit": "coding_workspace__edit",
}
```

Why redirect: the build's workspace lives on EC2 (or pinned to project's `app_root`). Native FS/shell would silently edit the wrong filesystem. The deny reason names the bare catalyst tool; the agent has the namespaced version loaded and picks the right form. **`Agent` is NOT here** — it moved to `ALLOW_EXACT` 2026-06-08. **`WebFetch`/`WebSearch` are NOT here** — moved to `ALLOW_EXACT` 2026-06-12 (native web is read-only network, no filesystem hazard → allowed in every mode).

### ALLOW_EXACT ([catalyst-block-native.py](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py))

Always allowed for a registered tab, even during build — incl. native WEB (no filesystem hazard):

```python
ALLOW_EXACT = {"TodoWrite", "AskUserQuestion", "Skill",
               "SlashCommand", "ToolSearch",
               "ExitPlanMode", "EnterPlanMode", "Agent",
               "WebFetch", "WebSearch"}
```

### Build-only native block + per-mode workspace gate (Case 2)

**Native FS/shell is blocked ONLY in Build (`coding`/`vibe_code`) — OPEN
everywhere else (2026-07-23, plugin v0.1.43).** `_WORKSPACE_BOUND_MODES =
{"coding","vibe_code"}`; in Case 2, after the ALLOW_EXACT / catalyst-mcp checks,
any `REDIRECTS` key (`Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob`) returns ALLOW
when `mode not in _WORKSPACE_BOUND_MODES`. So the **Analyst (`deep_analysis`),
PM (`brainstorm`), Curator, and `menu`** get native tools on the user's LOCAL
machine; only the **Engineer** stays bound to `coding_workspace__*` because the
app lives on EC2/app_root and a native tool would edit the wrong filesystem.
`WebFetch`/`WebSearch` are in `ALLOW_EXACT` → open in **every** mode incl. Build.
History: the `deep_analysis` "all native" carve-out was removed 2026-06-09 (every-
mode block), then this broader Build-only rule restored local access 2026-07-23.
The Build-mode deny text points to `upload_to_workspace` for pulling a local file
into a build.

Two refinements layered on top:

- **Per-mode workspace gate** (`_DENIED_BY_MODE`, mirrors FDE `ModeController.DENIED`): narrows the `coding_workspace__*` surface by the row's `mode` — `deep_analysis` (Discover) denies `write`/`edit`/`playwright_test`/`save_prd`; `spec` denies `write`/`edit`/`bash`/`playwright_test`; `coding`/`vibe_code` (Build) deny nothing. Checked first in Case 2 (`_is_mode_denied_tool`); only matches `coding_workspace__*` tool names.
- **Workspace file-transfer carve-out** (added 2026-06-12, plugin v0.1.28): native `Bash` running the Catalyst **upload/download curl** is allowed in **any** mode. `upload_to_workspace` / `download_from_workspace` return a curl that runs on the CALLER's shell — the file is on the user's LOCAL disk and bytes POST/GET straight to `/api/events/{upload,download}` over HTTPS; `coding_workspace__bash` (remote EC2) can't reach the laptop, so this native-shell op MUST be permitted. Match is narrow — `_is_workspace_transfer_bash`: command contains `curl` AND `/api/events/upload/` or `/api/events/download/` (not a general bash escape: `echo /api/events/upload/` without `curl` is still denied). **These transfer tools are bound on the plugin/MCP surfaces only, NOT the wizard FDE agent** (the FDE user is in a browser with no shell; `build_fde_surface` pops them — wizard users transfer via the Code-tab UI).

External MCPs (`mcp__*` that aren't catalyst-mcp) are **blacklisted** while that tab has an active session (strict allow-list: catalyst-mcp tools + the ALLOW_EXACT natives). A tab with NO row is unaffected — the gate is per-tab now.

### _LOCAL_WIPE_BARE

```python
_LOCAL_WIPE_BARE = {"abandon_build", "end", "logout"}
```

Tools whose PreToolUse fire **removes the CALLING tab's registry row BEFORE the call goes through** (per-tab — other tabs' sessions keep working). `end`/`abandon_build` additionally get the row's `session_id` injected so the stateless server abandons the CALLER's build. **Only `logout` deletes `catalyst-events-jwt.json`** — the token is identity-scoped (shared by every tab), so it dies when the signed-in user changes, and only then; one tab ending its build must not de-auth the others (they re-mint on their next `ensure_auth`/`health_check`).

## Row claim on first call

When this tab has no row AND the tool is a catalyst-mcp tool:

```python
registry.claim(cc_session_id)
# → row {claude_session_id, catalyst_session_id=None, mode="menu",
#        created_dt=now, last_updated_dt=now}
```

This happens on `ensure_auth` (the skill's first call). Other tabs are NOT affected — each claims its own row on its own first call. The claim falls through to the normal gate (unlike the old code which returned immediately), so even the first call gets session-id injection semantics.

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

With `permissionDecision="deny"`, the assistant sees `permissionDecisionReason` in context. That text is structured as instructions (e.g. the Build-mode block tells it which `coding_workspace__*` tool to use instead). The assistant follows the embedded instructions on its next turn.

This is how the plugin gets the assistant to react to a block — there's no direct "show this to the user" channel; the assistant translates.

## Debug log

Every fire writes one line to `~/.claude/state/catalyst-hook-debug.log` (UNCONDITIONAL — not gated by `CATALYST_HOOK_DEBUG`):

```
2026-08-10 10:40:55 FIRED tool='mcp__plugin_catalyst_catalyst-mcp__ensure_auth' cc=a5185aa6 is_catalyst=True row_exists=False row_session='' row_mode=''
2026-08-10 10:40:55   → CLAIMED registry row cc=a5185aa6
```

This is the log to read when "why isn't the tab's row getting claimed?" or "which session is this tab stamped to?".

## When to update this file

- REDIRECTS / ALLOW_EXACT / _LOCAL_WIPE_BARE changes.
- New case added to the decision tree.
- Registry shape / claim semantics change (`session_registry.py`).
- Deny-reason text restructured (the assistant-facing instructions matter — review them when touching).
