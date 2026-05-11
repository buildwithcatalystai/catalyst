#!/usr/bin/env python3
"""PreToolUse hook — single-owner Catalyst scope-lock + cross-tab refusal.

Two responsibilities, in order:

1. **Tab registration on `/catalyst` activation.** When a Claude Code tab
   first invokes any ``mcp__catalyst-mcp__*`` tool (the skill always calls
   ``health_check`` as its first action per SKILL.md §0), this hook fires.
   If no sentinel exists, write one with this tab's ``cc_session_id`` —
   the tab now owns the catalyst session for the rest of its lifetime.

2. **Cross-tab refusal.** If a sentinel exists and a DIFFERENT Claude Code
   tab tries any ``mcp__catalyst-mcp__*`` tool, refuse with a message
   naming the active tab so the user can disambiguate. The owning tab
   continues normally. Non-catalyst tools in either tab are unaffected
   (we only guard the MCP namespace plus a small allowlist for the owner).

3. **Native tool guard for the OWNING tab.** While the sentinel is held by
   this tab, native ``Read``/``Write``/``Edit``/``Bash``/``Grep``/``Glob``/
   ``Agent``/``WebFetch``/``WebSearch`` are refused with redirect messages
   pointing at the matching ``coding_workspace__*`` MCP tool. Native tools
   would silently edit the wrong filesystem (Mac vs EC2), so the block
   prevents drift.

Output contract — Claude Code's CURRENT PreToolUse hook spec (changed mid-2026
from the older ``{"decision":"block"}`` + ``exit 2`` form, which CC now
ignores silently). Required shape:

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",                # or "allow" / "ask"
        "permissionDecisionReason": "<text>"          # visible to assistant
      }
    }

Exit code MUST be 0 — non-zero short-circuits CC before it reads the JSON.
With ``permissionDecision="deny"``, the assistant sees the reason text in
its context and acts on instructions inside it. ``allow``/``ask`` reasons
are user-facing only.
"""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

SENTINEL_PATH = Path.home() / ".claude" / "state" / "catalyst-active-session.json"

# Pattern-match instead of fixed-prefix because Claude Code mangles the
# namespace boundary differently across registration paths:
#
#   Direct (~/.claude/.mcp.json or project .mcp.json)
#     →  mcp__catalyst-mcp__<tool>
#
#   Plugin install (`/plugin install catalyst@catalyst-aibuilder`)
#     →  mcp__plugin_catalyst_catalyst-mcp__<tool>     ← CC turns ":" into "_"
#
# Both end with the literal substring "catalyst-mcp__<tool>". Detecting on
# that marker keeps the hook working regardless of how (or whether) CC
# normalises namespace separators in future versions.
_CATALYST_MARKER = "catalyst-mcp__"

# Bare names of catalyst tools that any tab can ALWAYS call, even from a
# non-owning tab. Escape hatches: a wedged sentinel from a crashed tab can
# be cleared from any fresh terminal by calling abandon_build / end / logout,
# and any tab can read the active state via current_session.
_CROSS_TAB_ALLOWED_BARE = {"abandon_build", "end", "logout", "current_session"}

# Bare names that wipe the local sentinel + events_jwt BEFORE the call goes
# through. Server-side semantics differ (`end`/`abandon_build` mark the
# wizard row as abandoned; `logout` is non-destructive on the server), but
# all three free the local tab — so a fresh sign-in or a different user can
# claim cleanly from this tab without colliding with the previous owner.
_LOCAL_WIPE_BARE = {"abandon_build", "end", "logout"}

# Native tools that are blocked for the OWNING tab during a build, with the
# bare name of the catalyst tool the agent should use instead. We don't
# include the namespace prefix in the redirect — the agent already has the
# real namespaced tool loaded and can pick the right form.
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

# Native tools that are always allowed regardless of catalyst state.
ALLOW_EXACT = {
    "TodoWrite",
    "AskUserQuestion",
    "Skill",
    "SlashCommand",
    "ToolSearch",
    "ExitPlanMode",
    "EnterPlanMode",
}


def _read_sentinel() -> Dict[str, Any]:
    if not SENTINEL_PATH.exists():
        return {}
    try:
        return json.loads(SENTINEL_PATH.read_text())
    except Exception:
        return {}


def _write_sentinel(data: Dict[str, Any]) -> None:
    """Best-effort write — never raise (we'd rather lose the registration
    than crash a tool call)."""
    try:
        SENTINEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SENTINEL_PATH.write_text(json.dumps(data, indent=2))
    except Exception:
        pass


def _is_catalyst_mcp_tool(tool_name: str) -> bool:
    """Match any tool name from the catalyst MCP server, regardless of how
    CC namespaced it (direct vs plugin install). See _CATALYST_MARKER."""
    return tool_name.startswith("mcp__") and _CATALYST_MARKER in tool_name


def _bare_catalyst_tool(tool_name: str) -> str:
    """Return the bare tool name (everything after 'catalyst-mcp__'), or ''
    if not a catalyst MCP tool. ``rsplit(_, 1)`` so that if the bare name
    itself happens to contain the marker (theoretical), we still split on
    the rightmost — which is the namespace boundary."""
    if not _is_catalyst_mcp_tool(tool_name):
        return ""
    parts = tool_name.rsplit(_CATALYST_MARKER, 1)
    return parts[1] if len(parts) == 2 else ""


def _is_allowed_for_owner(tool_name: str) -> bool:
    if tool_name in ALLOW_EXACT:
        return True
    if _is_catalyst_mcp_tool(tool_name):
        return True
    # Allow other MCP servers (Slack, Notion, etc.) — we only guard
    # the local FS/shell surface for the owning tab.
    if tool_name.startswith("mcp__"):
        return True
    return False


def _format_started_at(started_at: str) -> str:
    """Friendly-ish timestamp for the refusal message."""
    if not started_at:
        return "(unknown time)"
    return started_at


def _emit_deny(reason: str) -> int:
    """Emit a PreToolUse deny decision in the current Claude Code hook
    contract. Exit code MUST be 0 — non-zero makes CC ignore the JSON
    silently and the tool call proceeds. The assistant sees ``reason`` in
    its context when permissionDecision="deny", so we can stuff
    instructions ("ask the user X") into it."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


def _debug_log(line: str) -> None:
    """Diagnostic — every hook invocation appends a single line to
    ~/.claude/state/catalyst-hook-debug.log. Best-effort, never raise."""
    try:
        debug_path = Path.home() / ".claude" / "state" / "catalyst-hook-debug.log"
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        with debug_path.open("a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
    except Exception:
        pass


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        _debug_log(f"PARSE_FAIL raw_len={len(raw)} raw_head={raw[:80]!r}")
        return 0  # malformed input — don't block

    cc_session_id = (event.get("session_id") or "").strip()
    tool_name = event.get("tool_name", "") or ""
    sentinel = _read_sentinel()
    is_cat = _is_catalyst_mcp_tool(tool_name)
    _debug_log(
        f"FIRED tool={tool_name!r} cc={cc_session_id[:8]} "
        f"is_catalyst={is_cat} sentinel_exists={bool(sentinel)} "
        f"sentinel_owner={(sentinel.get('cc_session_id','') or '')[:8]!r}"
    )

    # ── Case 0: end / abandon_build / logout wipes the local sentinel ───
    # The remote MCP server's `end`/`logout` tools manage their own state but
    # cannot reach the user's local sentinel — so even after a successful
    # call the next ensure_auth would still see the dead owner and refuse.
    # Delete the sentinel + events_jwt BEFORE allowing the call through.
    # Idempotent — safe to fire from any tab (the cross-tab allowlist covers
    # all three bare names for exactly this reason).
    #
    # Server-side semantics differ:
    #   - `end` / `abandon_build`: marks wizard row as abandoned (destructive)
    #   - `logout`: signs the user out but preserves all sessions (resumable)
    # Local effect is identical: tab is freed for the next sign-in.
    bare_name = _bare_catalyst_tool(tool_name) if is_cat else ""
    if is_cat and bare_name in _LOCAL_WIPE_BARE:
        events_jwt_path = Path.home() / ".claude" / "state" / "catalyst-events-jwt.json"
        try:
            SENTINEL_PATH.unlink(missing_ok=True)
            _debug_log(f"  → DELETED local sentinel ({bare_name} by cc={cc_session_id[:8]})")
        except Exception as exc:
            _debug_log(f"  → sentinel unlink failed: {exc}")
        try:
            events_jwt_path.unlink(missing_ok=True)
            _debug_log(f"  → DELETED events_jwt ({bare_name} by cc={cc_session_id[:8]})")
        except Exception as exc:
            _debug_log(f"  → events_jwt unlink failed: {exc}")
        return 0  # allow the tool call to proceed

    # ── Case 1: no sentinel yet ─────────────────────────────────────────
    # Tab registration happens on the first ``mcp__catalyst-mcp__*`` call.
    # Other tools (no catalyst yet) just pass through.
    if not sentinel:
        if cc_session_id and is_cat:
            _write_sentinel({
                "cc_session_id": cc_session_id,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": None,
                "app_root": "",
                "gen_stream_id": "",
                "mode": "menu",
            })
            _debug_log(f"  → CLAIMED sentinel cc={cc_session_id[:8]}")
        else:
            _debug_log(f"  → no claim (cc empty? {not cc_session_id} | not catalyst tool? {not is_cat})")
        return 0

    owner_cc_id = (sentinel.get("cc_session_id") or "").strip()

    # ── Case 2: sentinel exists but owner not yet stamped ───────────────
    # Edge case — shouldn't happen under the new flow, but defensive.
    # Stamp this tab as owner if it's the first mcp call.
    if not owner_cc_id:
        if cc_session_id and _is_catalyst_mcp_tool(tool_name):
            sentinel["cc_session_id"] = cc_session_id
            _write_sentinel(sentinel)
            owner_cc_id = cc_session_id
        else:
            return 0

    # ── Case 3: this is the owning tab ──────────────────────────────────
    if owner_cc_id == cc_session_id:
        if _is_allowed_for_owner(tool_name):
            return 0
        # Native tool — refuse with redirect to the bare tool name. The
        # agent already has the actual namespaced catalyst tools loaded
        # (whatever prefix CC chose) and can pick the right one.
        redirect_bare = REDIRECTS.get(tool_name) or "coding_workspace__*"
        mode = sentinel.get("mode", "menu")
        reason = (
            f"Native `{tool_name}` is blocked while a Catalyst session is "
            f"active (mode={mode}). The build's workspace lives on EC2 (or "
            f"is locked to the project's app_root); native tools would "
            f"silently edit the wrong file. Use the catalyst tool "
            f"`{redirect_bare}` instead (the namespaced version your "
            f"toolset already has loaded) — it routes to the correct "
            f"workspace automatically.\n\n"
            f"To unlock native tools, end the Catalyst session first: "
            f"call `abandon_build` or `current_session` (catalyst-mcp "
            f"tools, namespaced as your toolset registered them)."
        )
        return _emit_deny(reason)

    # ── Case 4: a DIFFERENT tab. ────────────────────────────────────────
    # Non-catalyst tools are unaffected — we don't punish unrelated work
    # in other tabs.
    if not _is_catalyst_mcp_tool(tool_name):
        return 0

    # Cross-tab escape hatches: any tab can always call abandon_build (to
    # clear a wedged sentinel from a crashed owner) and current_session
    # (to inspect what's active without trying to use it).
    if _bare_catalyst_tool(tool_name) in _CROSS_TAB_ALLOWED_BARE:
        return 0

    # All other catalyst tools — refuse loudly, name the active tab so the
    # user can disambiguate, and tell them how to break the lock.
    started_at = _format_started_at(sentinel.get("started_at", ""))
    short_owner = owner_cc_id[:8] if owner_cc_id else "(unknown)"
    # The agent should TELL THE USER, in plain language, that another
    # Claude tab is using Catalyst — and offer two paths. The user is
    # almost certainly non-technical, so frame it as a choice, not a
    # tool-call menu. The agent reads this `reason` and translates it
    # into something warm + actionable for the user.
    reason = (
        f"Another Claude tab is currently using Catalyst (the session "
        f"started at {started_at}, transcript id `{short_owner}…`).\n\n"
        f"Tell the user, in plain language, that they have two options:\n"
        f"\n"
        f"  1. **Go back to the other tab and continue there.** That tab "
        f"     is the one with Catalyst already open — no work is lost.\n"
        f"\n"
        f"  2. **End the other session and take over from this tab.** "
        f"     Just say 'end' (or 'abandon') and the agent will kill the "
        f"     other session — wipes the local sentinel and abandons any "
        f"     in-flight build on the wizard. Then this tab can use "
        f"     Catalyst freely.\n"
        f"\n"
        f"WAIT for the user's choice before doing anything. If they say "
        f"'end' / 'kill' / 'abandon' / 'take over from here', call "
        f"`mcp__catalyst-mcp__end` (no args needed — it reads the active "
        f"session from the local sentinel). If they say 'I'll go to the "
        f"other tab' / 'never mind', do nothing — just acknowledge.\n"
        f"\n"
        f"The user can also do this without you: from any terminal, "
        f"running `rm ~/.claude/state/catalyst-active-session.json` "
        f"clears the sentinel manually. Mention this only if asked."
    )
    return _emit_deny(reason)


if __name__ == "__main__":
    sys.exit(main())
