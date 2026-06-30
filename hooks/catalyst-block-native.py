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
   this tab, native ``Read``/``Write``/``Edit``/``Bash``/``Grep``/``Glob`` are
   refused with redirect messages pointing at the matching
   ``coding_workspace__*`` MCP tool — in EVERY live mode (menu/brainstorm/spec/
   coding/vibe_code/deep_analysis). Native FS/shell would silently touch the
   wrong filesystem (Mac vs EC2), so the block prevents drift; the EC2 shell
   ``coding_workspace__bash`` is open in Discover instead, so a research
   session's scratch persists in the Mindspace, not on the laptop.
   ALLOW_EXACT (``Agent``, plan mode, ``TodoWrite``, and native WEB
   ``WebFetch``/``WebSearch``) is never touched — **native web access is
   allowed in every mode** (read-only network, no filesystem hazard).
   ONE further carve-out: native ``Bash`` running the Catalyst file-transfer
   curl (``upload_to_workspace`` / ``download_from_workspace`` — bytes between
   the user's LOCAL disk and the workspace over HTTPS) IS permitted in any mode,
   because that file lives on the laptop and the remote shell can't reach it.

4. **Session-id injection (the routing source of truth).** The Catalyst MCP is
   HTTP-remote and HOLDS NO active-session state — on a host shared by every
   plugin user, a server-side "active session" would be the last writer's, not
   yours (this is what once renamed a Mindspace nobody picked). So this hook
   stamps the CURRENT ``session_id`` — from the LOCAL per-machine sentinel —
   into EVERY catalyst-mcp tool call that targets a Mindspace, via
   ``hookSpecificOutput.updatedInput``. The server routes purely on that arg.
   Empty local session_id → the field is omitted → the server mints a fresh
   Mindspace (only after a ``switch_mindspace`` clean-slate). The agent never
   chooses the Mindspace; ``switch_mindspace`` (its own ``target_session_id``,
   user-confirmed) is the only way to change which one is active.

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
    # The native Agent (Task) tool + plan mode — Claude's & Codex's own sub-tasking
    # and planning. This is the sanctioned way for an agent to fan out / parallelize
    # its work; creating a Mindspace SUBAGENT for that is forbidden (subagents are
    # user-request-only). NOTE: a spawned native subagent runs under the parent's
    # cc_session_id, so its OWN native FS/shell calls are still governed by this block
    # while a build is active — it should drive the project via coding_workspace__*.
    "Agent",
    # Native WEB access — allowed in EVERY mode (2026-06-12). WebFetch/WebSearch are
    # read-only network reads with NO filesystem hazard (the whole reason the block
    # exists), so the agent can pull docs / look things up directly rather than route
    # through coding_workspace__web_search. Moved OUT of REDIRECTS into here.
    "WebFetch",
    "WebSearch",
}


# Per-mode workspace-tool deny-sets — mirror the FDE ModeController's DENIED.
# The agent does all stages on the ONE coding_workspace__* surface; the mode
# narrows it:
#   deep_analysis (Discover) → investigate: no write/edit/playwright/save_prd.
#       `coding_workspace__bash` IS open here (intentionally diverges from FDE's
#       DENIED["deep_analysis"]) so the agent can store its working plan IN the
#       Mindspace workspace (persisted on the EC2), not on the laptop. Native
#       Bash is blocked → routed to coding_workspace__bash (see Case 3 below).
#   spec          (Spec)     → shape the plan: no build actions; save_prd allowed.
#   coding/vibe   (Build)    → nothing denied (full surface).
# These open/close as the agent calls start_analysis / start_spec /
# start_app_building. (Agent + Enter/ExitPlanMode are native ALLOW_EXACT — never
# touched by this gate, so they stay available in every mode incl. Discover.)
_CODING_WS_MARKER = "coding_workspace__"
_DENIED_BY_MODE = {
    "deep_analysis": {"write", "edit", "playwright_test", "save_prd"},
    "spec": {"write", "edit", "bash", "playwright_test"},
}

# Session routing is CLIENT-SIDE. The remote MCP server holds NO active-session
# state (on a shared host that would be another user's), so this hook stamps the
# CURRENT session_id — from the LOCAL sentinel — into EVERY catalyst-mcp tool call
# that targets a Mindspace. The server then routes purely on that arg. When the
# sentinel HAS a session it always wins (overwrites the agent's value). When the
# sentinel is EMPTY, only the stage TRANSITIONS may fall back to an agent-supplied
# session_id — that's the legitimate "resume the Mindspace I just found in
# list_mindspaces" path; without it, an end→resume would silently FORK a new
# Mindspace (the v0.1.23 regression this guards against). Workspace tools never
# resurrect from an agent value. switch_mindspace's target_session_id (where to GO)
# is a separate arg we never overwrite.
#
# Carve-outs from the general "inject current session" rule:
#   _NO_SESSION_BARE — tools with no Mindspace target (account / listing).
#       Injecting an unused session_id is harmless but we skip them to keep
#       payloads clean.
#   switch_mindspace — NOT carved out: it gets session_id (= current) injected
#       like everything else, which the server reads as the Mindspace to leave;
#       its target_session_id (the agent's pick of where to GO) is a different
#       arg that _inject_current_session never touches, so it's preserved.
#   end / abandon_build / logout — in _LOCAL_WIPE_BARE, handled in Case 0 (the
#       local wipe). end + abandon still get session_id injected THERE so the
#       server abandons the caller's build (handle_abandon_build reads args).
_NO_SESSION_BARE = {
    "health_check", "ensure_auth", "logout", "list_mindspaces", "list_projects",
}

# The stage-transition / enter verbs. These are the RESUME-or-enter calls — the
# one place the agent may legitimately name a Mindspace to (re)enter (e.g. resume
# an abandoned one it found via list_mindspaces). So for these ONLY, when the
# sentinel has no active session, we fall back to the agent-supplied session_id
# instead of stripping it (which would silently fork a new Mindspace). When the
# sentinel DOES have a session, it still wins (continue the current one). Plain
# workspace tools are NOT in here: they must always follow the active sentinel and
# never resurrect a session from an agent value.
_TRANSITION_BARE = {"start_analysis", "start_spec", "start_app_building", "start_coding"}


def _inject_current_session(
    event: Dict[str, Any], sentinel: Dict[str, Any], *, allow_agent_fallback: bool = False
) -> Dict[str, Any]:
    """Return the tool_input with the session_id the call should route to.

    Routing truth is the LOCAL sentinel (the remote MCP holds no session state):
      - sentinel HAS a session_id → use it, overwriting whatever the agent sent
        (active session wins — the multi-tenant safety guarantee).
      - sentinel EMPTY:
          * allow_agent_fallback (transitions only) → keep the agent's session_id
            if it supplied one (resume that Mindspace); else omit → server mints
            fresh.
          * otherwise → strip session_id (server mints fresh / errors).
    """
    cur_sid = (sentinel.get("session_id") or "").strip()
    tool_input = dict(event.get("tool_input") or {})
    if not cur_sid and allow_agent_fallback:
        agent_sid = (tool_input.get("session_id") or "").strip()
        if agent_sid:
            tool_input["session_id"] = agent_sid   # resume the agent-named Mindspace
        else:
            tool_input.pop("session_id", None)      # nothing to resume → fresh
        return tool_input
    if cur_sid:
        tool_input["session_id"] = cur_sid
    else:
        tool_input.pop("session_id", None)
    return tool_input


def _is_mode_denied_tool(mode: str, tool_name: str) -> bool:
    """True if ``tool_name`` is a ``coding_workspace__*`` tool denied in ``mode``
    (per ``_DENIED_BY_MODE``, mirroring FDE's DENIED)."""
    denied = _DENIED_BY_MODE.get(mode)
    if not denied or _CODING_WS_MARKER not in tool_name:
        return False
    bare = tool_name.rsplit(_CODING_WS_MARKER, 1)[-1]
    return bare in denied


# Workspace file-transfer carve-out. ``upload_to_workspace`` /
# ``download_from_workspace`` RETURN a curl the agent must run with NATIVE bash:
# the file lives on the USER'S LOCAL disk and the bytes POST/GET straight over
# HTTPS to these endpoints (never through the conversation, so any size works).
# ``coding_workspace__bash`` runs on the REMOTE EC2 and cannot see the laptop, so
# this is the ONE native-shell op the workspace block must permit — in any mode.
# Match is narrow (a curl to a Catalyst transfer endpoint), NOT a general bash
# escape: a command must contain ``curl`` AND a transfer endpoint marker.
_WORKSPACE_TRANSFER_MARKERS = ("/api/events/upload/", "/api/events/download/")


def _is_workspace_transfer_bash(event: Dict[str, Any]) -> bool:
    """True iff this native Bash call is the Catalyst upload/download curl
    (local-disk ↔ workspace transfer). See ``_WORKSPACE_TRANSFER_MARKERS``."""
    cmd = ((event.get("tool_input") or {}).get("command") or "")
    if "curl" not in cmd:
        return False
    return any(marker in cmd for marker in _WORKSPACE_TRANSFER_MARKERS)


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
    """Strict allow-list while a Catalyst session is active — mirrors FDE, whose
    agent only ever has the Catalyst surface. ONLY catalyst-mcp tools + the
    native plumbing in ALLOW_EXACT (Agent, plan mode, TodoWrite, …) pass here.
    External MCP servers (loadshare, Slack, Notion, …) are NOT allowed — they're
    handled (denied) in Case 3. (Native Bash in Discover is also handled there.)
    """
    if tool_name in ALLOW_EXACT:
        return True
    if _is_catalyst_mcp_tool(tool_name):
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


def _emit_allow_updated_input(updated_input: Dict[str, Any]) -> int:
    """Allow the tool call but REPLACE its input args. Used to stamp the current
    session_id (from the local sentinel) into the stage transitions, so the remote
    MCP server gets the caller's active Mindspace without reading any server-side
    sentinel. Exit 0; CC parses ``updatedInput`` (PreToolUse contract)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": updated_input,
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
        # Capture the current session_id BEFORE wiping the sentinel — end /
        # abandon_build need it injected so the (stateless) server abandons the
        # CALLER's build (handle_abandon_build reads args.session_id; it no longer
        # reads a server-side sentinel).
        wipe_sid = (sentinel.get("session_id") or "").strip()
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
        # end / abandon_build → stamp the caller's session_id so the server
        # abandons the right build. logout is non-destructive server-side; no
        # session needed → plain allow.
        if bare_name in ("end", "abandon_build"):
            tool_input = dict(event.get("tool_input") or {})
            if wipe_sid:
                tool_input["session_id"] = wipe_sid
            else:
                tool_input.pop("session_id", None)
            _debug_log(f"  → ALLOW {bare_name} + inject session_id={wipe_sid[:8] or '(none)'}")
            return _emit_allow_updated_input(tool_input)
        return 0  # logout — allow the tool call to proceed

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
    # Claim it as a FRESH session for this tab: stamp the owner AND reset the
    # project fields. A new owner must NOT inherit a stale session_id from an
    # orphaned sentinel — that's exactly how a transition would continue/rename
    # a Mindspace the user never picked. Treat it like a clean Case-1 claim.
    if not owner_cc_id:
        if cc_session_id and _is_catalyst_mcp_tool(tool_name):
            sentinel["cc_session_id"] = cc_session_id
            sentinel["session_id"] = None
            sentinel["app_root"] = ""
            sentinel["gen_stream_id"] = ""
            sentinel["mode"] = "menu"
            _write_sentinel(sentinel)
            owner_cc_id = cc_session_id
        else:
            return 0

    # ── Case 3: this is the owning tab ──────────────────────────────────
    if owner_cc_id == cc_session_id:
        mode = sentinel.get("mode", "menu")
        # Fix #2 — per-mode tool whitelisting (the plugin's gate, mirroring the
        # FDE ModeController's DENIED). Discover (read-only) and Spec (plan, no
        # build) narrow the shared coding_workspace surface; Build denies nothing.
        # Checked BEFORE _is_allowed_for_owner — but it only matches
        # coding_workspace__* tools, so native Agent/plan (ALLOW_EXACT) and other
        # MCPs fall through and stay allowed in every mode.
        if _is_mode_denied_tool(mode, tool_name):
            _debug_log(f"  → DENY {tool_name} (mode={mode} denied)")
            if mode == "deep_analysis":
                return _emit_deny(
                    f"`{tool_name}` is blocked in Discover — this is read-only "
                    "investigation, you change nothing here. Dig with "
                    "run_select_query / run_python / the knowledge base. When the "
                    "work turns to making something, call `start_spec` (to shape a "
                    "plan) or `start_app_building` (to build)."
                )
            return _emit_deny(
                f"`{tool_name}` is a Build tool — you're in Spec, where you shape "
                "the plan, not the app. Write the PRD with `save_prd`, show it to "
                "the user, and on a clear yes call `start_app_building` to build — "
                "then write/edit/bash/playwright open up."
            )
        # ── Inject the CURRENT session into EVERY catalyst tool call ────────
        # The remote MCP holds NO active-session state (shared host), so this is
        # the sole source of routing truth: stamp session_id from the LOCAL
        # sentinel (overwriting any value the agent supplied) into every
        # catalyst-mcp tool that targets a Mindspace — coding_workspace__*,
        # transitions, switch_mindspace, current_session, record_turn, recall_*,
        # complete_build, … Empty sentinel session_id → drop it → server mints a
        # fresh Mindspace (only after a switch_mindspace clean-slate). The agent
        # never picks the Mindspace; switch_mindspace is the only change, gated.
        # Carve-outs: no-session tools (account/listing) are left untouched and
        # just allowed; switch_mindspace's target_session_id is the agent's pick
        # and is preserved — we add session_id (= current) alongside it.
        if is_cat and bare_name not in _NO_SESSION_BARE:
            # Transitions may resume an agent-named Mindspace when the sentinel
            # is empty (post-end / fresh tab); workspace tools always follow the
            # active sentinel. See _inject_current_session / _TRANSITION_BARE.
            _is_transition = bare_name in _TRANSITION_BARE
            tool_input = _inject_current_session(
                event, sentinel, allow_agent_fallback=_is_transition,
            )
            stamped = tool_input.get("session_id", "")
            _src = "sentinel" if (sentinel.get("session_id") or "").strip() else (
                "agent-resume" if (_is_transition and stamped) else "fresh"
            )
            _debug_log(f"  → ALLOW {bare_name} + inject session_id={stamped[:8] or '(fresh)'} [{_src}]")
            return _emit_allow_updated_input(tool_input)
        if _is_allowed_for_owner(tool_name):
            return 0
        # ── Workspace file-transfer carve-out ──────────────────────────────
        # upload_to_workspace / download_from_workspace return a curl the agent
        # runs with NATIVE bash — the file is on the USER'S LOCAL disk and the
        # bytes POST/GET straight over HTTPS to /api/events/{upload,download}.
        # coding_workspace__bash runs on the REMOTE EC2 and can't reach the laptop,
        # so this native-shell op MUST be permitted (in every mode). Narrow match
        # on the Catalyst transfer endpoints (curl + endpoint), not a bash escape.
        if tool_name == "Bash" and _is_workspace_transfer_bash(event):
            _debug_log("  → ALLOW native Bash (workspace file-transfer curl)")
            return 0
        # NOTE: native Bash is NO LONGER carved out in Discover. The EC2 shell
        # `coding_workspace__bash` is open in deep_analysis instead (see
        # _DENIED_BY_MODE above) so the agent's plan/scratch persists IN the
        # Mindspace workspace rather than on the laptop. So native Bash falls
        # through to the redirect below → coding_workspace__bash, in every mode.
        # (Agent + Enter/ExitPlanMode stay always-allowed via ALLOW_EXACT.)
        # External MCP server (any mcp__* that isn't catalyst-mcp — those passed
        # _is_allowed_for_owner above). BLACKLISTED while a Catalyst session is
        # active: Catalyst is a strict allow-list (Catalyst tools + native
        # plumbing only), mirroring FDE whose agent only has the Catalyst surface.
        if tool_name.startswith("mcp__"):
            _debug_log(f"  → DENY external MCP {tool_name} (Catalyst allow-list)")
            return _emit_deny(
                f"`{tool_name}` is an external MCP — blocked while a Catalyst "
                "session is active. Do the work with Catalyst's own tools: "
                "run_select_query / run_python / the knowledge base for data, the "
                "coding_workspace tools for builds. To use other MCPs, end the "
                "Catalyst session first (abandon_build / current_session)."
            )
        # Native FS/shell tool — refuse with a redirect to the matching
        # coding_workspace tool. Spec + Build both protect the project's
        # workspace (EC2 / app_root); there is no allow-all-native mode.
        redirect_bare = REDIRECTS.get(tool_name) or "coding_workspace__*"
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
