# Debugging recipes

The bug shapes we've actually hit. Each entry: **symptom → first 3 things to check → fix**.

## Pre-coding messages synced to wizard chat

**Symptom**: ChatPane shows project-menu banter ("Here's what you have so far / which Login app?") as if it were part of the build conversation.

**Check**:
1. `~/.claude/state/catalyst-event-sink.log` — look for `posted=N kinds=[assistant_text, …]` right after a `sentinel set: mode=coding`. If the first kinds list contains `assistant_text`, it's this leak.
2. `~/.claude/state/catalyst-event-sink-offsets.json` — was the offset for this transcript present BEFORE the first sync? If absent or 0, the fast-forward didn't fire.
3. `_run` in [hook_record.py:1273](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L1273) — `became_coding` block intact?

**Fix**: the patch in `_run` writes offset = EOF on the `prev_mode → coding` transition. If the patch was reverted, restore it.

## Wrong tab's turns in a Mindspace's chat

**Symptom**: ChatPane for Mindspace X shows narration from work done in a different tab.

Since the per-tab registry (2026-08-10, v0.1.44) there is NO cross-tab owner gate — tabs are isolated by construction: each hook fire reads only the FIRING tab's row (`session_registry.read_entry(event.session_id)`), and offsets/anchors are keyed by the tab's own transcript path. Two tabs deliberately pointed at the SAME Mindspace **interleave in one chat history — that's supported behavior**, not a leak.

**Check** (for a real mix-up):
1. `python3 -c "import sys; sys.path.insert(0,'$HOME/codeGen/catalyst-plugin/hooks'); import session_registry, json; print(json.dumps(session_registry.all_entries(), indent=2))"` — is some row stamped with a `session_id` you didn't expect? Which tab claimed it (`cc_session_id`), when (`last_updated_dt`)?
2. `catalyst-event-sink.log` — the `session=` prefix on each `←` line names where that fire's records went.
3. A stale enrich: `sentinel session_id mismatch (partial)` warnings around the timestamps.

**Fix**: `end` from the mis-stamped tab removes its row; re-enter the right Mindspace via `list_mindspaces` → `switch_mindspace`.

## Stale/wedged registry row

**Symptom**: a tab's row lingers after its CC tab crashed, or `current_session` reports a Mindspace the tab isn't actually in.

**Check**: dump the rows (recipe above) — `last_updated_dt` tells you how stale each is.

**Fix**:
- From that tab (or any new tab you want clean): `end` / `abandon_build` — removes the CALLING tab's row before the call goes through. Note this only frees the caller's own row.
- Rows from crashed tabs age out on their own: the GC drops anything idle >10 days on the next registry save.
- Nuclear: `rm ~/.claude/state/catalyst-active-session.json` — but this now wipes **EVERY tab's session**, not one; only when nothing else is active. The events_jwt is identity-scoped — leave it unless you're switching users (`logout` handles that).

## 401 from `/api/events/record`

**Symptom**: `catalyst-event-sink.log` shows `events_jwt rejected by backend (401)`. ChatPane goes silent mid-build.

**Check**:
1. Compare the file's `exp` field with current time. If past, defense-in-depth should have skipped before the 401 — check that path didn't break. (The JWT is identity-only — there's no session_id in the file to mismatch; the server checks that this identity OWNS the path session_id.)
2. Does the identity own the session? A 403/401 with an ownership detail means the row's `session_id` belongs to another user's Mindspace.
3. Did the backend rotate signing keys? Look at the backend's events JWT route for recent restarts.

**Fix**: 401 on a fresh JWT means backend-side problem (check backend logs). 401 on a stale JWT self-heals — the next `ensure_auth`/`health_check` from ANY tab mints a fresh one.

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
