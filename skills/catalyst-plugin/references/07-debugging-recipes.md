# Debugging recipes

The bug shapes we've actually hit. Each entry: **symptom → first 3 things to check → fix**.

## Pre-coding messages synced to wizard chat

**Symptom**: ChatPane shows project-menu banter ("Here's what you have so far / which Login app?") as if it were part of the build conversation.

**Check**:
1. `~/.claude/state/catalyst-event-sink.log` — look for `posted=N kinds=[assistant_text, …]` right after a `sentinel set: mode=coding`. If the first kinds list contains `assistant_text`, it's this leak.
2. `~/.claude/state/catalyst-event-sink-offsets.json` — was the offset for this transcript present BEFORE the first sync? If absent or 0, the fast-forward didn't fire.
3. `_run` in [hook_record.py:1273](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1273) — `became_coding` block intact?

**Fix**: the patch in `_run` writes offset = EOF on the `prev_mode → coding` transition. If the patch was reverted, restore it.

## Cross-tab leakage (different tab's text in this build's chat)

**Symptom**: ChatPane shows narration that the build agent never said.

**Check**:
1. `catalyst-event-sink.log` — search for `BLOCKED: cc_session=X is not the owner`. If you DON'T see them around the timestamps in question, owner gate isn't firing.
2. Sentinel `cc_session_id` — does it match the tab you THINK is the owner? Use `cat ~/.claude/state/catalyst-active-session.json`.
3. `_is_owning_tab` in [hook_record.py:573](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L573) — logic intact?

**Fix**: if owner is empty, PreToolUse never claimed. Look at `catalyst-hook-debug.log` for `FIRED tool=… is_catalyst=False` — the first call wasn't a catalyst tool, so no claim. The fix is to ensure `ensure_auth` is the FIRST tool the skill calls (it always should be).

## Stuck sentinel (can't start new build, "another tab is using Catalyst")

**Symptom**: PreToolUse refuses every catalyst tool with cross-tab message, but no other tab is open.

**Check**:
1. `cat ~/.claude/state/catalyst-active-session.json` — what's the owner? `started_at` time?
2. Is the owning CC tab still running? If it crashed, the sentinel stayed.

**Fix**: Either:
- Call `end` or `abandon_build` from ANY tab — both are in `CROSS_TAB_ALLOWED_BARE`, and PreToolUse unlinks the sentinel BEFORE the call goes through.
- Or manually: `rm ~/.claude/state/catalyst-active-session.json` (sentinel itself) and `rm ~/.claude/state/catalyst-events-jwt.json` (JWT bound to sentinel lifecycle).

## 401 from `/api/events/record`

**Symptom**: `catalyst-event-sink.log` shows `events_jwt rejected by backend (401)`. ChatPane goes silent mid-build.

**Check**:
1. Compare `catalyst-events-jwt.json`'s `session_id` with the path session_id in the log line. Mismatch → stale JWT from previous build.
2. Compare `exp` field with current time. If past, defense-in-depth should have skipped before the 401 — check that path didn't break.
3. Did the backend rotate signing keys? Look at the backend's events JWT route for recent restarts.

**Fix**: 401 on a fresh JWT means backend-side problem (check backend logs). 401 on a stale JWT means the sentinel didn't get rewritten on coding entry — the next `send_message` will mint a fresh one and recover.

## Hook doesn't fire at all

**Symptom**: No new lines in `catalyst-event-sink.log` even though tool calls are happening.

**Check**:
1. Is the plugin actually installed? `/plugin list` inside CC.
2. `$CLAUDE_PLUGIN_ROOT/hooks/hooks.json` — does it exist? Right shape?
3. Try running the hook script directly: `echo '{}' | python3 $CLAUDE_PLUGIN_ROOT/hooks/hook_record.py`. Should write an entry+summary line.

**Fix**: typically a plugin reinstall (`/plugin uninstall` + `/plugin install`) or CC restart. Hook registration is read on plugin load.

## PreToolUse blocks not working

**Symptom**: Native `Read`/`Bash` work during a build (should be denied).

**Check**:
1. `catalyst-hook-debug.log` — is the PreToolUse firing? Look for `FIRED tool=Read …`.
2. Output contract — old form (`{"decision":"block"}` + `exit 2`) is silently ignored. Current form is `{"hookSpecificOutput": {...}}`.
3. Sentinel mode — check `mode` field. If `mode=menu` (no active build), native tools are intentionally allowed.

**Fix**: if hook fires but block doesn't take effect, you're hitting the contract change. Verify `_emit_deny` in [catalyst-block-native.py:156](../../../codeGen/catalyst-plugin/hooks/catalyst-block-native.py#L156) emits the new shape.

## "Sentinel session_id mismatch" warnings

**Symptom**: `catalyst-event-sink.log` shows `sentinel session_id mismatch: local=X response=Y`.

**Check**:
1. Did you have two builds running in close succession? The tab might have cached a response from the prior build.
2. Was `end` called between builds?

**Fix**: this is a defensive log line, not a bug. The hook refuses to clobber. Usually self-resolves on the next coding entry. If persistent, `end` to reset.

## `tool_response` not parsing (`parsed_keys=<...>`)

**Symptom**: `catalyst-event-sink.log` shows `enrich shape: tool=... parsed_keys=<...>` where `<...>` is a type name, not a list.

**Check**:
1. `CATALYST_HOOK_DEBUG=1` in `.env`, reproduce, then look at the verbose log. The tool_response is some unexpected shape (not bare-list, not wrapped dict).
2. Is this a new catalyst-mcp tool that returns a non-JSON string?

**Fix**: `_parse_tool_response` ([hook_record.py:337](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L337)) handles three shapes; a fourth would need adding. Usually it's a bug on the MCP side returning something weird.

## Wizard's ChatPane not updating live

**Symptom**: Tool calls are POSTing successfully (200s in log), but ChatPane doesn't show them.

**Check**:
1. Are you on the right project? ChatPane scopes by session_id.
2. Wizard's WebSocket connected? Check browser devtools.
3. Backend's `/api/events/record` route — is it broadcasting WS events after persisting?

**Fix**: this isn't a plugin problem — POSTs returning 200 means the plugin's job is done. Debug on the wizard side (broadcast logic in `server.py`).

## Pending records pile up in `catalyst-event-sink-pending.jsonl`

**Symptom**: File grows unboundedly.

**Check**:
1. Is the backend reachable? `curl $CATALYST_BACKEND_URL/api/health`.
2. Look at `catalyst-event-sink.log` for `POST … failed: …` lines.

**Fix**: the file is best-effort — no auto-retry. After backend recovers, the records are lost (unless you write a replay tool). Truncate if it gets large: `truncate -s 0 ~/.claude/state/catalyst-event-sink-pending.jsonl`.

## Auto-complete doesn't trigger

**Symptom**: Agent emits the completion JSON, but build doesn't flip to completed.

**Check**:
1. Is the JSON on the LAST non-blank line of the assistant text? `_detect_completion_signal` ([hook_record.py:760](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L760)) only checks the last line.
2. Does it have BOTH `status: "completed"` AND non-empty `summary`?
3. Was Stop hook fired? Look for `← hook=Stop` in the log.

**Fix**: the agent's prompt needs to emit the JSON as the literal final line. Any trailing prose after the JSON breaks detection.

## Namespace doesn't match (tool block bypassed)

**Symptom**: Native tool block works for some tools but not others.

**Check**:
1. Exact tool name from `event.tool_name` — does it contain `catalyst-mcp__` substring?
2. Is the tool one of the `REDIRECTS` keys?

**Fix**: If CC adds a new install path that mangles the namespace differently, update both hooks' marker constant + `_bare_*` parsers. Pattern-match on substring, never on prefix.

## When to update this file

Add a new recipe whenever:
- A new failure mode is observed in production.
- A fix is applied — record the symptom + check + fix so the next person doesn't re-derive.
