---
name: catalyst-plugin
description: Mental map of the Catalyst Claude Code plugin — the two hooks (PreToolUse owner-claim + native-tool block, PostToolUse/Stop event sink), the local state files (sentinel, events_jwt, offsets, pending, debug log), the MCP server registration, the skill+commands surface, and the full sync pipeline that turns CC tool calls into wizard chat history. Use when working in /Users/you/codeGen/catalyst-plugin/ or when the user asks about: catalyst plugin, hooks.json, hook_record.py, catalyst-block-native.py, PreToolUse, PostToolUse, Stop hook, sentinel, catalyst-active-session.json, events_jwt, catalyst-events-jwt.json, offsets, catalyst-event-sink-offsets.json, pending records, owner gate, cross-tab block, native tool block, transcript_path, CC transcript JSONL, hook debug log, /catalyst, /catalyst build/list/status/end, plugin.json, .mcp.json registration, catalyst-mcp HTTP MCP, events_jwt session_id mismatch, sync leak, pre-coding messages syncing.
---

# Catalyst plugin — what runs in Claude Code

The Catalyst plugin is **everything that lives inside the user's Claude Code install**. It does NOT do builds. It binds CC to the wizard backend by registering each tab in a per-tab session registry (multiple tabs run independent Catalyst sessions in parallel — no cross-tab refusal since v0.1.44, 2026-08-10) and streaming each tab's tool calls + narration up to its own Mindspace.

Three surfaces, in order of execution per tool call:

```
CC tool call
   │
   ▼
[PreToolUse hook]  catalyst-block-native.py
   │   • Claim THIS TAB's registry row on its first catalyst-mcp tool
   │   • Inject the row's session_id into every Mindspace-targeting call
   │   • Block native Read/Write/Edit/Bash/Grep in this tab's Build modes
   ▼
[Tool executes]    MCP server (HTTP) or native CC tool
   │
   ▼
[PostToolUse/Stop hook]  hook_record.py
       • Row gate (does THIS tab have a registry row?)
       • Mode gate (row.mode ∈ coding/vibe_code/spec/deep_analysis)
       • Offset anchor snap when the row's session_id changes
       • Translate event → (assistant_text, tool_call, tool_result) records
       • POST each to /api/events/record/{session_id} with events_jwt Bearer
```

## Two flows at a glance

```
Tab claim flow         (no row for this tab) → PreToolUse fires on first catalyst-mcp tool
                                             → adds a registry row {claude_session_id, mode=menu}
                                             → other tabs UNAFFECTED (each claims its own row)

Sync flow              CC turn   →  PostToolUse hook
                       agent narration       └→ _latest_turn_text reads transcript JSONL
                       + tool_use            └→ tool_call/tool_result built from event
                                             └→ POST to wizard /api/events/record/{sid}
                                             └→ events_jwt Bearer auth
```

## Hard facts (invariants — don't relearn)

- **Plugin home (committed):** `/Users/you/codeGen/catalyst-plugin/`. Repo: `github.com/buildwithcatalystai/catalyst` (public).
- **Plugin install path on the user box:** `$CLAUDE_PLUGIN_ROOT` (set by CC when invoking hooks). `.env` discovery order: process env → `$CLAUDE_PLUGIN_ROOT/.env` → `~/codeGen/catalyst-plugin/.env` → `~/codeGen/catalyst-builder/backend/.env`.
- **Hooks are shell-out scripts**, not in-process. CC spawns `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py` per fire and pipes the event JSON to stdin. PreToolUse timeout=5s, PostToolUse/Stop timeout=10s ([hooks.json](../../../codeGen/catalyst-plugin/hooks/hooks.json)).
- **MCP server is HTTP, not stdio.** `.mcp.json` registers `https://buildwithcatalyst.ai/mcp` as `catalyst-mcp` ([.mcp.json](../../../codeGen/catalyst-plugin/.mcp.json)). All tool calls go over the network — the wizard's `mcp_runner.py` is the actual server.
- **Tool-name namespace varies by install path:**
  - Direct install (`~/.claude/.mcp.json`): `mcp__catalyst-mcp__<tool>`
  - Plugin install (`/plugin install catalyst@catalyst-aibuilder`): `mcp__plugin_catalyst_catalyst-mcp__<tool>` (CC turns `:` → `_`)
  - Both hooks pattern-match on the substring `catalyst-mcp__` to handle both. **Never hard-code the full prefix.**
- **The active-session file is a PER-TAB registry (multi-session, 2026-08-10, v0.1.44)** — same path `~/.claude/state/catalyst-active-session.json`, now `{"version":2,"sessions":[...]}` with ONE ROW PER CC TAB. Owned by `hooks/session_registry.py` (the only code that knows the shape; both hooks call its legacy-shaped API — `read_entry`/`claim`/`patch`/`remove`/`touch`/`all_entries`):
  - Row fields: `claude_session_id` (the tab — row key), `catalyst_session_id` (Mindspace), `app_root`, `gen_stream_id`, `mode` (`menu` | `coding` | `vibe_code` | `spec` | `deep_analysis`), `created_dt`, `last_updated_dt` (both full ISO-8601 UTC date+time, `Z`-suffixed).
  - **Any number of tabs run Catalyst in parallel** — the cross-tab refusal is GONE; two tabs may even hold the same Mindspace (turns interleave in that one chat history). `switch_mindspace` updates the calling tab's row IN PLACE.
  - **Rows are claimed only by PreToolUse**, never by PostToolUse. `end`/`abandon_build`/`logout` remove ONLY the calling tab's row (PreToolUse, BEFORE the call); only `logout` also deletes the identity-scoped events_jwt.
  - **GC:** rows idle >10 days (`last_updated_dt`, compared as instants) are dropped on every save; `touch()` keeps the active tab's row warm (60s throttle). Mutations are `flock`-serialized on sibling `catalyst-sessions.lock` + atomic-replaced. A legacy single-object sentinel migrates to one v2 row on the first fire.
- **events_jwt is IDENTITY-only and shared by every tab.** Path: `~/.claude/state/catalyst-events-jwt.json`. Returned by `ensure_auth`/`health_check` (every activation + reauth) and the build-entry transitions; persisted by `_maybe_persist_events_jwt` in PostToolUse. NOT session-bound — one token authenticates all tabs' record-POSTs (the session travels in the POST path). Deleted ONLY by `logout` (user changed); `end`/`abandon_build`/`pause_after_complete` leave it alone so one tab finishing can't de-auth the others. Missing file → hook is a silent no-op.
- **Oversized coding-entry responses are recovered from CC's spill file** (`_resolve_spilled_response`, 2026-06-01). The coding-entry `send_message` payload (PRD kickoff + chat history, ~59 KB) exceeds CC's max tool-result size; CC saves it to `<transcript-dir>/tool-results/*.txt` and hands the hook only a stub. Without recovery the enrich path sees no `mode`/`session_id`/`events_jwt` → sentinel never flips to `coding` → **every coding turn no-ops `mode-not-coding` (no persistence, no WS)**. The hook now detects the stub and reads the spill file before enrichment. Symptom if it ever regresses: event-sink log shows `noop=mode-not-coding(mode=menu)` with `enrich shape: response_keys=<str len=…> parsed_keys=[]`.
- **Offsets are line-count snapshots, not deltas.** Path: `~/.claude/state/catalyst-event-sink-offsets.json`. Keyed by **absolute transcript path** (`event.transcript_path` from CC, not derived from sentinel). Value = `len(lines)` at last scan. Re-stamped on every `_latest_turn_text` call. **Snapped to EOF when the active `session_id` changes** (see anchor fact below) to prevent pre-session / other-Mindspace banter leaking.
- **Sync follows the `session_id`, anchored per-transcript (2026-06-09, replaced the mode-based `became_coding` fast-forward).** A sibling file `~/.claude/state/catalyst-event-sink-anchors.json` (path → session_id) records which session the offset is anchored to. The FIRST recordable fire that sees `session_id != anchor[path]` (empty→set on entry, OR a switch to a different Mindspace) snaps the offset to EOF + re-anchors, before any extraction. **Why the change:** the old `became_coding` read `prev_sid` from the *sentinel*, which the enrich rewrites every fire — so if the exact entry tool fire missed (e.g. `start_analysis` firing with no `transcript_path`), the next fire saw `prev_sid == session_id` and skipped the snap, scooping the whole menu backlog into the new Mindspace (observed: `start_analysis` → `noop=no-records` then the next fire `posted=22`). The anchor is keyed on the *session_id itself*, so whichever recordable fire first sees the new session does the snap. Sync runs only while `session_id` is set (the missing-session-id gate stops it on return to menu). ([hook_record.py `_read_anchor`/`_write_anchor`](../../../codeGen/catalyst-plugin/hooks/hook_record.py))
- **CC transcript filename = `{cc_session_id}.jsonl`** under `~/.claude/projects/{cwd-encoded}/`. CWD encoding flips slashes to dashes (`/Users/you/codeGen` → `-Users-you-codeGen`). The hook does NOT derive this path — CC passes it via `event["transcript_path"]`.
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
- **Native tools always allowed for the owning tab during a build:** `TodoWrite`, `AskUserQuestion`, `Skill`, `SlashCommand`, `ToolSearch`, `EnterPlanMode`, `ExitPlanMode`, **`Agent`**, and native WEB **`WebFetch`/`WebSearch`** ([catalyst-block-native.py `ALLOW_EXACT`](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py)). **`Agent` was opened 2026-06-08** (moved OUT of the `REDIRECTS` map into `ALLOW_EXACT`) so agents fan out via Claude's/Codex's own native sub-tasking + plan mode — NOT by creating a Mindspace subagent (those are user-request-only). **`WebFetch`/`WebSearch` were opened 2026-06-12** (moved OUT of `REDIRECTS` into `ALLOW_EXACT`) — native web is read-only network with no filesystem hazard, so native web access is allowed in EVERY mode (was redirected to `coding_workspace__web_search`). Caveat: a spawned native subagent runs under the parent's `cc_session_id`, so ITS own native FS/shell is still governed by this block during a build — it should drive the remote project via `coding_workspace__*`. Native FS/shell tools (`Read`/`Write`/`Edit`/`Bash`/`Grep`/`Glob`) are denied with a redirect to `coding_workspace__*` **ONLY in Build modes** (`coding`/`vibe_code`) — in **every other mode (Analyst=`deep_analysis`, PM=`brainstorm`, Curator, `menu`) native tools are OPEN** (restored 2026-07-23, plugin v0.1.43, via `_WORKSPACE_BOUND_MODES = {"coding","vibe_code"}`; reinstates the pre-2026-06-09 behaviour so those employees can read/inspect the user's **LOCAL** files — the Engineer stays workspace-bound because the app lives on EC2/app_root). Implementation: Case 3 returns ALLOW for any `REDIRECTS` key when `mode not in _WORKSPACE_BOUND_MODES`. The only native-`Bash` exception inside Build is the upload/download transfer curl — see `references/02`. (History: deep_analysis's "all native" carve-out was removed 2026-06-09, then this broader Build-only rule replaced the every-mode block 2026-07-23.) **Per-mode workspace gate (2026-06-09, `_DENIED_BY_MODE`, mirrors FDE `ModeController.DENIED`):** the block also narrows the `coding_workspace__*` surface by sentinel `mode` — `deep_analysis` (Discover) denies `write`/`edit`/`playwright_test`/`save_prd`; `spec` denies `write`/`edit`/`bash`/`playwright_test`; `coding`/`vibe_code` (Build) deny nothing. **`coding_workspace__bash` is intentionally OPEN in Discover** (diverges from FDE's `DENIED["deep_analysis"]`) so the agent persists its working plan IN the Mindspace workspace; native `Bash` is no longer special-cased — it routes to `coding_workspace__bash` like the other natives. **External MCPs (`mcp__*` that aren't catalyst-mcp) are BLACKLISTED** while a session is active (strict allow-list: Catalyst tools + the ALLOW_EXACT natives). The "Analysis is data + scripts + crons, never a web app" rule stays INSTRUCTION-side only (skill + `start_analysis` description), deliberately not a hook backstop. **NOTE:** line below ("session-LESS … `analysis_workspace__*`") is SUPERSEDED — Discover is now session-FULL on the `coding_workspace__*` union; see [[project_plugin_fde_alignment_20260609]].
- **Deep Analysis (`mode=deep_analysis`) is a third, session-LESS mode** parallel to brainstorm/app building. Entered via the `start_analysis` lifecycle tool (writes `mode=deep_analysis`, `session_id=null`). It binds a read-only, org-scoped tool surface namespaced `analysis_workspace__*` (DB/API knowledge + `run_select_query` + `run_python` + `manage_crons` + uploads grep) that dispatches to the **session-less** builder route `POST /api/mcp/analysis/tool` (org resolved from the JWT, NOT a session). The PostToolUse event-sink is a no-op in this mode (Gate 2 only syncs coding/vibe_code) — research is ephemeral, no app row. **App-building mode is entered by the `start_app_building` lifecycle tool (renamed 2026-06-04 from `start_coding`; old name kept as an un-advertised back-compat alias; internal `mode` value stays `coding`/`vibe_code`).** Exit analysis by building: `start_app_building(session_id)` / `send_message` / `restart_brainstorm` / `switch_mindspace` flip the mode off `deep_analysis` via the normal sentinel paths. **(Mindspace rename 2026-06-05:** LLM tool names `list_projects`→`list_mindspaces`, `switch_project`→`switch_mindspace`, `recall_project_history`→`recall_mindspace_history`, `manage_project_skill`/`manage_project_memory`→`mindspace_skill`/`mindspace_memory` — old names kept as un-advertised back-compat dispatch aliases; internal mode values + `coding_workspace__*`/`analysis_workspace__*` namespaces unchanged. Both prompts now anchor on the living-Mindspace skill+memory model.)** **(FDPM repositioning 2026-06-06:** user-facing stage labels are now **Discover / Spec / Build** for internal modes `deep_analysis` / `brainstorm` / `coding` (values UNCHANGED — surfaced as shared language now, reversing "never name the mode"). Persona → forward-deployed PM. Plugin `SKILL.md` (0.1.17) rewritten to the FDPM voice (fluid entry, unbiased, universal Build incl. autonomous AI checks + ML models + production discipline); an **"On the word Build"** note keeps the tool split honest — web app = `coding_workspace__*` (Build), data/scripts/crons = `analysis_workspace__*` (Discover); Build never claims crons/run_python. `reference/*.md` + `lifecycle.py` descriptions relabeled. **Plugin Spec is UNCHANGED** — still the brainstorm graph via `send_message`/`restart_brainstorm`. The **FDE agent** (flag-off) goes further: Spec is a real `ModeController` gate mode entered via **`start_spec`** (`restart_brainstorm` aliased), PRD shaped **in-agent** (no graph) on one shared checkpoint via a thin **`save_prd`** tool (`.agent/prd.md` + `PRD/` copy; Spec/Build only).)** **(AI-employee reposition 2026-06-26, plugin 0.1.33 — PLUGIN-ONLY, no MCP redeploy:** out-loud language flipped from stage names to the landing's three AI employees — **the Analyst** (=Discover / `start_analysis` / `deep_analysis`), **the PM** (=Spec / `start_spec` / `brainstorm`), **the Engineer** (=Build / `start_app_building` / `coding`·`vibe_code`). One operator that *narrates which employee is on the work* ("bringing in the Analyst…", "handing to the Engineer…"); **`Discover`/`Spec`/`Build` are now INTERNAL mechanics only — never said to the user.** Rewrote `skills/catalyst/SKILL.md` (persona, banner now `Analyst · PM · Engineer`, routing boxes, per-employee sections, don'ts, frontmatter) + `reference/00-06` + `plugin.json`/`marketplace.json` descriptions; user audience generalized off "a PM" (collided with the PM employee). **Backend `lifecycle.py` descriptions UNCHANGED** (still say Discover/Spec/Build internally) — the LLM maps each transition to the employee it brings in. Mode values, tool names, hook deny-sets, sentinel, status all unchanged.)**
- **Per-tab lifecycle verbs:** `end` / `abandon_build` / `logout` remove ONLY the calling tab's registry row (PreToolUse Case 0, BEFORE the call goes through — the remote MCP can't reach the user's disk); `end`/`abandon_build` get the row's `session_id` injected so the stateless server abandons the CALLER's build. There are no cross-tab escape hatches anymore because there is nothing cross-tab to escape — a wedged row from a crashed tab ages out via the 10-day GC, or `rm` the whole registry file (wipes ALL tabs — last resort).
- **Subagents inherit the parent's `cc_session_id` and can SELF-CLAIM the parent tab's registry row** (observed 2026-05-31; still true under the per-tab registry — the registry keys rows by `cc_session_id`, not parent-vs-subagent). So when an Explore / general-purpose subagent (running under the parent's session) calls any `coding_workspace__*` MCP tool — which it might choose to do because the project's CLAUDE.md surfaces those tools prominently — the PreToolUse hook claims a fresh `mode=menu` row under the parent's id. Since 2026-07-23 (v0.1.43) `mode=menu` leaves native tools OPEN, so the old hard deadlock only bites if the row later lands in a Build mode — but the claimed row still hijacks session-id injection for the parent's own catalyst calls. Mitigations: do exploration directly with native Read/Bash/Grep (no subagents) when working in catalyst-builder / enterprise_ai_developer_v2; OR append "DO NOT use any `coding_workspace__*` or `mcp__plugin_catalyst_catalyst-mcp__*` tools" to the subagent prompt. Recovery: call `mcp__plugin_catalyst_catalyst-mcp__end` from that tab (removes the tab's row), then retry without subagents. The full debug recipe lives in [[feedback_explore_subagent_sentinel_trap]].

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
| Per-tab session registry (was: sentinel) | `~/.claude/state/catalyst-active-session.json` |
| Registry module (only code that knows the shape) | [hooks/session_registry.py](../../../codeGen/catalyst-plugin/hooks/session_registry.py) |
| Registry mutation lock | `~/.claude/state/catalyst-sessions.lock` |
| Events JWT (identity-scoped, all tabs) | `~/.claude/state/catalyst-events-jwt.json` |
| Offsets | `~/.claude/state/catalyst-event-sink-offsets.json` |
| Anchors (session_id the offset is anchored to, per transcript) | `~/.claude/state/catalyst-event-sink-anchors.json` |
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
