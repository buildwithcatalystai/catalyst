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

CATALYST_MCP_PREFIX = "mcp__catalyst-mcp__"

# Tools allowed for the OWNING tab (everything else gets blocked while sentinel is held)
ALLOW_PREFIXES = (CATALYST_MCP_PREFIX,)
ALLOW_EXACT = {
    "TodoWrite",
    "AskUserQuestion",
    "Skill",
    "SlashCommand",
    "ToolSearch",
    "ExitPlanMode",
    "EnterPlanMode",
}

# Catalyst MCP tools that any tab is ALWAYS allowed to call, even from a
# non-owning tab. These are escape hatches: a wedged sentinel from a crashed
# tab can be cleared from any fresh terminal by calling abandon_build /
# end_build, and any tab can read the active state via current_session.
CROSS_TAB_ALLOWED_CATALYST_TOOLS = {
    f"{CATALYST_MCP_PREFIX}abandon_build",
    f"{CATALYST_MCP_PREFIX}end",
    f"{CATALYST_MCP_PREFIX}current_session",
}

REDIRECTS = {
    "Read":      "mcp__catalyst-mcp__coding_workspace__read",
    "Write":     "mcp__catalyst-mcp__coding_workspace__write",
    "Edit":      "mcp__catalyst-mcp__coding_workspace__edit",
    "MultiEdit": "mcp__catalyst-mcp__coding_workspace__edit",
    "Bash":      "mcp__catalyst-mcp__coding_workspace__bash",
    "Grep":      "mcp__catalyst-mcp__coding_workspace__grep",
    "Glob":      "mcp__catalyst-mcp__coding_workspace__find",
    "Agent":     "mcp__catalyst-mcp__coding_workspace__Agent",
    "WebFetch":  "mcp__catalyst-mcp__coding_workspace__web_search",
    "WebSearch": "mcp__catalyst-mcp__coding_workspace__web_search",
    "NotebookEdit": "mcp__catalyst-mcp__coding_workspace__edit",
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
    return tool_name.startswith(CATALYST_MCP_PREFIX)


def _is_allowed_for_owner(tool_name: str) -> bool:
    if tool_name in ALLOW_EXACT:
        return True
    for prefix in ALLOW_PREFIXES:
        if tool_name.startswith(prefix):
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


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0  # malformed input — don't block

    cc_session_id = (event.get("session_id") or "").strip()
    tool_name = event.get("tool_name", "") or ""
    sentinel = _read_sentinel()

    # ── Case 1: no sentinel yet ─────────────────────────────────────────
    # Tab registration happens on the first ``mcp__catalyst-mcp__*`` call.
    # Other tools (no catalyst yet) just pass through.
    if not sentinel:
        if cc_session_id and _is_catalyst_mcp_tool(tool_name):
            _write_sentinel({
                "cc_session_id": cc_session_id,
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": None,
                "app_root": "",
                "gen_stream_id": "",
                "mode": "menu",
            })
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
        # Native tool — refuse with redirect.
        redirect = REDIRECTS.get(tool_name) or "the matching mcp__catalyst-mcp__coding_workspace__* tool"
        mode = sentinel.get("mode", "menu")
        reason = (
            f"Native `{tool_name}` is blocked while a Catalyst session is "
            f"active (mode={mode}). The build's workspace lives on EC2 (or "
            f"is locked to the project's app_root); native tools would "
            f"silently edit the wrong file. Use `{redirect}` instead — it "
            f"routes to the correct workspace automatically.\n\n"
            f"To unlock native tools, end the Catalyst session first: "
            f"`mcp__catalyst-mcp__abandon_build` or `mcp__catalyst-mcp__current_session` "
            f"to inspect what's active."
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
    if tool_name in CROSS_TAB_ALLOWED_CATALYST_TOOLS:
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
