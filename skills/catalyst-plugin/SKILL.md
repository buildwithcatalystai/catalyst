---
name: catalyst-plugin
description: Mental map of the Catalyst Claude Code plugin — the two hooks (PreToolUse owner-claim + native-tool block, PostToolUse/Stop event sink), the local state files (sentinel, events_jwt, offsets, pending, debug log), the MCP server registration, the skill+commands surface, and the full sync pipeline that turns CC tool calls into wizard chat history. Use when working in /Users/lsn-ashwin/codeGen/catalyst-plugin/ or when the user asks about: catalyst plugin, hooks.json, hook_record.py, catalyst-block-native.py, PreToolUse, PostToolUse, Stop hook, sentinel, catalyst-active-session.json, events_jwt, catalyst-events-jwt.json, offsets, catalyst-event-sink-offsets.json, pending records, owner gate, cross-tab block, native tool block, transcript_path, CC transcript JSONL, hook debug log, /catalyst, /catalyst build/list/status/end, plugin.json, .mcp.json registration, catalyst-mcp HTTP MCP, events_jwt session_id mismatch, sync leak, pre-coding messages syncing.
---

# Catalyst plugin — what runs in Claude Code

The Catalyst plugin is **everything that lives inside the user's Claude Code install**. It does NOT do builds. It binds CC to the wizard backend by claiming ownership of the tab, refusing cross-tab interference, and streaming the agent's tool calls + narration up to the wizard.

Three surfaces, in order of execution per tool call:

```
CC tool call
   │
   ▼
[PreToolUse hook]  catalyst-block-native.py
   │   • Claim sentinel on first catalyst-mcp tool
   │   • Refuse cross-tab catalyst-mcp calls
   │   • Block native Read/Write/Edit/Bash/Grep on owning tab during build
   ▼
[Tool executes]    MCP server (HTTP) or native CC tool
   │
   ▼
[PostToolUse/Stop hook]  hook_record.py
       • Owner gate (sentinel.cc_session_id vs event.session_id)
       • Mode gate (sentinel.mode == coding/vibe_code)
       • Offset fast-forward on first coding entry
       • Translate event → (assistant_text, tool_call, tool_result) records
       • POST each to /api/events/record/{session_id} with events_jwt Bearer
```

## Two flows at a glance

```
Tab claim flow         (no sentinel) → PreToolUse fires on first catalyst-mcp tool
                                     → writes sentinel with cc_session_id, mode=menu
                                     → all other tabs now refused for catalyst-mcp

Sync flow              CC turn   →  PostToolUse hook
                       agent narration       └→ _latest_turn_text reads transcript JSONL
                       + tool_use            └→ tool_call/tool_result built from event
                                             └→ POST to wizard /api/events/record/{sid}
                                             └→ events_jwt Bearer auth
```

## Hard facts (invariants — don't relearn)

- **Plugin home (committed):** `/Users/lsn-ashwin/codeGen/catalyst-plugin/`. Repo: `github.com/ashwiny66/catalyst` (public).
- **Plugin install path on the user box:** `$CLAUDE_PLUGIN_ROOT` (set by CC when invoking hooks). `.env` discovery order: process env → `$CLAUDE_PLUGIN_ROOT/.env` → `~/codeGen/catalyst-plugin/.env` → `~/codeGen/catalyst-builder/backend/.env`.
- **Hooks are shell-out scripts**, not in-process. CC spawns `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py` per fire and pipes the event JSON to stdin. PreToolUse timeout=5s, PostToolUse/Stop timeout=10s ([hooks.json](../../../codeGen/catalyst-plugin/hooks/hooks.json)).
- **MCP server is HTTP, not stdio.** `.mcp.json` registers `http://13.202.117.250:9000/mcp` as `catalyst-mcp` ([.mcp.json](../../../codeGen/catalyst-plugin/.mcp.json)). All tool calls go over the network — the wizard's `mcp_runner.py` is the actual server.
- **Tool-name namespace varies by install path:**
  - Direct install (`~/.claude/.mcp.json`): `mcp__catalyst-mcp__<tool>`
  - Plugin install (`/plugin install catalyst@catalyst-aibuilder`): `mcp__plugin_catalyst_catalyst-mcp__<tool>` (CC turns `:` → `_`)
  - Both hooks pattern-match on the substring `catalyst-mcp__` to handle both. **Never hard-code the full prefix.**
- **Sentinel is the single source of truth** for "is there an active Catalyst session, and which tab owns it":
  - Path: `~/.claude/state/catalyst-active-session.json`
  - Fields: `cc_session_id` (owner), `started_at`, `session_id` (catalyst build id), `app_root`, `gen_stream_id`, `mode` (`menu` | `coding` | `vibe_code` | `brainstorm`).
  - **Owner is claimed only by PreToolUse**, never by PostToolUse. The record hook is read-only on ownership.
  - Deleted on `end`/`abandon_build` (PreToolUse handles this BEFORE the call goes through).
- **events_jwt presence = "in coding mode."** Path: `~/.claude/state/catalyst-events-jwt.json`. Minted by the wizard inside `send_message`'s coding-entry response; persisted by `_maybe_persist_events_jwt` in PostToolUse. Missing file → hook is a silent no-op (brainstorm/menu phases use native LangGraph persistence; hook has nothing to sync).
- **Offsets are line-count snapshots, not deltas.** Path: `~/.claude/state/catalyst-event-sink-offsets.json`. Keyed by **absolute transcript path** (`event.transcript_path` from CC, not derived from sentinel). Value = `len(lines)` at last scan. Re-stamped on every `_latest_turn_text` call. **Fast-forwarded to EOF on the coding-entry edge** ([hook_record.py:1265](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1265)) to prevent pre-coding banter leaking.
- **CC transcript filename = `{cc_session_id}.jsonl`** under `~/.claude/projects/{cwd-encoded}/`. CWD encoding flips slashes to dashes (`/Users/lsn-ashwin/codeGen` → `-Users-lsn-ashwin-codeGen`). The hook does NOT derive this path — CC passes it via `event["transcript_path"]`.
- **Two log files** in `~/.claude/state/`:
  - `catalyst-event-sink.log` — one summary line per hook fire (always-on). Rotating: 2 MB × 2 backups.
  - `catalyst-hook-debug.log` — verbose payload dump. Opt-in via `CATALYST_HOOK_DEBUG=1` in any `.env` in the discovery path. Rotating: 5 MB × 2 backups.
  - PreToolUse writes raw `FIRED tool=… cc=…` lines to the debug log unconditionally (no env flag) for owner-claim diagnostics.
- **Failed POSTs land in `catalyst-event-sink-pending.jsonl`** (best-effort dump, line-per-record). No automated retry — the file is for postmortem.
- **PreToolUse output contract changed mid-2026.** Old form (`{"decision":"block"}` + `exit 2`) is silently ignored by current CC. Current required shape:
  ```json
  {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<text the assistant sees>"}}
  ```
  Exit code MUST be 0 — non-zero short-circuits CC before it reads stdout. With `permissionDecision="deny"`, the assistant receives `reason` in its context and can act on instructions inside it.
- **PostToolUse/Stop ignore exit codes for routing.** They always exit 0 (uncaught exceptions are logged + swallowed). Failures appear only in `catalyst-event-sink.log` as `noop=<reason>` or `http=<code>`.
- **Three native tools are always allowed for the owning tab during a build:** `TodoWrite`, `AskUserQuestion`, `Skill`, `SlashCommand`, `ToolSearch`, `EnterPlanMode`, `ExitPlanMode` ([catalyst-block-native.py:90](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py#L90)). All other native FS/shell tools are denied with a redirect to `coding_workspace__*`.
- **Cross-tab escape hatches:** Any tab can always call `end`, `abandon_build`, `current_session` even when another tab owns the sentinel ([catalyst-block-native.py:69](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py#L69)). `end` + `abandon_build` PreToolUse handler deletes the local sentinel BEFORE allowing the call through (the remote MCP can't reach the user's disk).

## Key paths

| What | Where |
|---|---|
| PreToolUse hook | [hooks/catalyst-block-native.py](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py) |
| PostToolUse + Stop hook | [hooks/hook_record.py](../../../codeGen/catalyst-plugin/hooks/hook_record.py) |
| Hook registration | [hooks/hooks.json](../../../codeGen/catalyst-plugin/hooks/hooks.json) |
| MCP registration | [.mcp.json](../../../codeGen/catalyst-plugin/.mcp.json) |
| Plugin manifest | [.claude-plugin/plugin.json](../../../codeGen/catalyst-plugin/.claude-plugin/plugin.json) |
| Marketplace entry | [.claude-plugin/marketplace.json](../../../codeGen/catalyst-plugin/.claude-plugin/marketplace.json) |
| Slash commands | [commands/build.md](../../../codeGen/catalyst-plugin/commands/build.md), `list.md`, `status.md`, `end.md` |
| Main skill | [skills/catalyst/SKILL.md](../../../codeGen/catalyst-plugin/skills/catalyst/SKILL.md) |
| Sentinel | `~/.claude/state/catalyst-active-session.json` |
| Events JWT | `~/.claude/state/catalyst-events-jwt.json` |
| Offsets | `~/.claude/state/catalyst-event-sink-offsets.json` |
| Pending failures | `~/.claude/state/catalyst-event-sink-pending.jsonl` |
| Summary log | `~/.claude/state/catalyst-event-sink.log` |
| Debug log | `~/.claude/state/catalyst-hook-debug.log` |
| CC transcript JSONL | `~/.claude/projects/{cwd-encoded}/{cc_session_id}.jsonl` |

## Routing table — when to read which reference

| If the question is about… | Read |
|---|---|
| What runs on every tool call, hook ordering, exit semantics, output contracts | `references/01-hook-architecture.md` |
| PreToolUse: tab claim, native-tool block, cross-tab refusal, the redirect map | `references/02-pretooluse-block-native.md` |
| PostToolUse/Stop: sentinel enrichment, owner+mode gates, offset machinery, record translation | `references/03-posttooluse-record.md` |
| Sentinel, events_jwt, offsets, pending, log files: schemas + lifecycle | `references/04-local-state-files.md` |
| `transcript_path` provenance, JSONL format, what `_latest_turn_text` extracts | `references/05-transcript-sync.md` |
| Plugin packaging: `.mcp.json`, `plugin.json`, marketplace, `.env` discovery, install paths | `references/06-plugin-packaging.md` |
| Common bug shapes: pre-coding leak, cross-tab leak, stuck sentinel, 401 jwt, malformed payload, namespace mismatch | `references/07-debugging-recipes.md` |

## Update protocol

Code change → reference to edit:

| Change | File |
|---|---|
| New hook event type registered | `references/01-hook-architecture.md` + `hooks.json` |
| Native-tool block list, redirect map, ALLOW_EXACT | `references/02-pretooluse-block-native.md` |
| Owner/mode gate logic, new offset behavior, new record kind | `references/03-posttooluse-record.md` |
| New file in `~/.claude/state/`, schema change to sentinel/jwt/offsets | `references/04-local-state-files.md` |
| `_translate_post_tool` / `_translate_stop` / `_latest_turn_text` change | `references/05-transcript-sync.md` |
| `.mcp.json` URL, `.env` discovery order, plugin.json fields | `references/06-plugin-packaging.md` |
| New troubleshooting recipe | `references/07-debugging-recipes.md` |

**Do not edit SKILL.md for detail changes** — only when the *set* of references or a Hard Fact invariant changes. Always confirm `file:line` citations in references against the live code before editing.
