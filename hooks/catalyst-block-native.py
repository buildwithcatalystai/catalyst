#!/usr/bin/env python3
"""PreToolUse hook — per-tab Catalyst session registry + scope-lock.

Multi-session model (2026-08-10): the old single-owner sentinel (one JSON
object = one tab owns Catalyst machine-wide, every other tab refused) is now a
PER-TAB REGISTRY — ``session_registry.py`` keeps an array of
``{claude_session_id, catalyst_session_id, mode, …, created_dt,
last_updated_dt}`` rows in the same file. Each tab reads/writes only its own
row; there is NO cross-tab refusal anymore — any number of Claude Code tabs run
independent Catalyst sessions in parallel (two tabs may even hold the same
Mindspace; their turns interleave in that one chat history). Rows idle >10
days are garbage-collected.

Responsibilities, in order:

1. **Tab registration on `/catalyst` activation.** When a Claude Code tab
   first invokes any ``mcp__catalyst-mcp__*`` tool (the skill always calls
   ``health_check`` as its first action per SKILL.md §0), this hook fires.
   If this tab has no registry row yet, claim one (mode=menu) — the row is
   this tab's Catalyst state for the rest of its lifetime.

2. **Per-tab lifecycle.** ``end`` / ``abandon_build`` / ``logout`` remove only
   the CALLING tab's row (other tabs keep working). ``logout`` additionally
   deletes the identity-scoped events_jwt (the signed-in user changed — every
   tab re-mints on its next ensure_auth/health_check).

3. **Native tool guard for the OWNING tab — BUILD-ONLY (2026-07-23).** Native
   ``Read``/``Write``/``Edit``/``Bash``/``Grep``/``Glob`` are blocked (redirected
   to the matching ``coding_workspace__*`` MCP tool) **only while the Engineer is
   on the work — i.e. mode ∈ {coding, vibe_code} (Build)**. There the workspace
   lives on EC2 / an app_root and native FS/shell would silently touch the wrong
   filesystem, so the block prevents drift. In **every other mode — the Analyst
   (deep_analysis), the PM (brainstorm), the Curator, and menu — native tools are
   OPEN** (the pre-2026-06-09 behaviour, restored on user request) so those
   employees can read/inspect files on the user's own machine. See
   ``_WORKSPACE_BOUND_MODES``. ALLOW_EXACT (``Agent``, plan mode, ``TodoWrite``,
   and native WEB ``WebFetch``/``WebSearch``) is never touched — **native web
   access is allowed in every mode incl. Build** (read-only network, no FS hazard).
   ONE further carve-out even inside Build: native ``Bash`` running the Catalyst
   file-transfer curl (``upload_to_workspace`` / ``download_from_workspace`` —
   bytes between the user's LOCAL disk and the workspace over HTTPS) IS permitted
   in any mode, because that file lives on the laptop and the remote shell can't
   reach it.

4. **Session-id injection (the routing source of truth).** The Catalyst MCP is
   HTTP-remote and HOLDS NO active-session state — on a host shared by every
   plugin user, a server-side "active session" would be the last writer's, not
   yours (this is what once renamed a Mindspace nobody picked). So this hook
   stamps the CURRENT ``session_id`` — from THIS TAB's registry row —
   into EVERY catalyst-mcp tool call that targets a Mindspace, via
   ``hookSpecificOutput.updatedInput``. The server routes purely on that arg.
   Empty row session_id → the field is omitted → the server mints a fresh
   Mindspace (only after a ``switch_mindspace`` clean-slate). The agent never
   chooses the Mindspace; ``switch_mindspace`` (its own ``target_session_id``,
   user-confirmed) is the only way to change which one is active — it updates
   the calling tab's row IN PLACE (no new row).

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

# The registry module lives next to this script (both in the plugin's hooks/
# dir, spawned as `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/<name>.py`) — make the
# import robust regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import session_registry as registry
except Exception:  # pragma: no cover — a broken registry must not block tools
    registry = None

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

# Bare names that wipe THIS TAB's registry row BEFORE the call goes through.
# Server-side semantics differ (`end`/`abandon_build` mark the wizard row as
# abandoned; `logout` is non-destructive on the server), but the local effect
# is per-tab: only the calling tab's row is removed — other tabs' sessions
# keep working. `logout` additionally deletes the identity-scoped events_jwt
# (the signed-in user changed; every tab re-mints on its next ensure_auth).
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

# Modes where native FS/shell (Read/Write/Edit/Bash/Grep/Glob) stays BOUND to the
# remote workspace (redirected to coding_workspace__*). These are the Engineer's
# Build modes — the app lives on EC2 / an app_root and a native tool would edit the
# wrong filesystem. Every OTHER mode (the Analyst=deep_analysis, the PM=brainstorm,
# the Curator, and menu) gets native tools OPEN so those employees can work with the
# user's local files (restored 2026-07-23; the pre-2026-06-09 behaviour). Native web
# (WebFetch/WebSearch) + the upload/download transfer curl stay allowed in ALL modes.
_WORKSPACE_BOUND_MODES = {"coding", "vibe_code"}

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
    handled (denied) in Case 2. (Native Bash in Discover is also handled there.)
    """
    if tool_name in ALLOW_EXACT:
        return True
    if _is_catalyst_mcp_tool(tool_name):
        return True
    return False


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
    is_cat = _is_catalyst_mcp_tool(tool_name)
    entry = registry.read_entry(cc_session_id) if (registry and cc_session_id) else None
    _debug_log(
        f"FIRED tool={tool_name!r} cc={cc_session_id[:8]} "
        f"is_catalyst={is_cat} row_exists={entry is not None} "
        f"row_session={((entry or {}).get('session_id') or '')[:8]!r} "
        f"row_mode={(entry or {}).get('mode', '')!r}"
    )
    if registry is None:
        # session_registry import failed (broken install) — never block tools.
        _debug_log("  → registry unavailable; pass-through")
        return 0

    # ── Case 0: end / abandon_build / logout wipes THIS TAB's row ───────
    # The remote MCP server's `end`/`logout` tools manage their own state but
    # cannot reach the user's local registry — so remove the calling tab's
    # row BEFORE allowing the call through. Per-tab: other tabs' sessions
    # keep working. Idempotent — safe even when this tab has no row.
    #
    # Server-side semantics differ:
    #   - `end` / `abandon_build`: marks wizard row as abandoned (destructive)
    #   - `logout`: signs the user out but preserves all sessions (resumable)
    # logout ALSO deletes the events_jwt — it's identity-scoped (not
    # session-bound), so it dies when the signed-in user changes, and ONLY
    # then: one tab ending its build must not de-auth the other tabs.
    bare_name = _bare_catalyst_tool(tool_name) if is_cat else ""
    if is_cat and bare_name in _LOCAL_WIPE_BARE:
        # Capture the current session_id BEFORE wiping the row — end /
        # abandon_build need it injected so the (stateless) server abandons the
        # CALLER's build (handle_abandon_build reads args.session_id; it no longer
        # reads a server-side sentinel).
        wipe_sid = ((entry or {}).get("session_id") or "").strip()
        if registry.remove(cc_session_id):
            _debug_log(f"  → REMOVED registry row ({bare_name} by cc={cc_session_id[:8]})")
        if bare_name == "logout":
            events_jwt_path = Path.home() / ".claude" / "state" / "catalyst-events-jwt.json"
            try:
                events_jwt_path.unlink(missing_ok=True)
                _debug_log(f"  → DELETED events_jwt (logout by cc={cc_session_id[:8]})")
            except Exception as exc:
                _debug_log(f"  → events_jwt unlink failed: {exc}")
            return 0  # logout — allow the tool call to proceed
        # end / abandon_build → stamp the caller's session_id so the server
        # abandons the right build.
        tool_input = dict(event.get("tool_input") or {})
        if wipe_sid:
            tool_input["session_id"] = wipe_sid
        else:
            tool_input.pop("session_id", None)
        _debug_log(f"  → ALLOW {bare_name} + inject session_id={wipe_sid[:8] or '(none)'}")
        return _emit_allow_updated_input(tool_input)

    # ── Case 1: no row for this tab yet ─────────────────────────────────
    # Tab registration happens on the first ``mcp__catalyst-mcp__*`` call —
    # claim a fresh row (mode=menu, no Mindspace) and fall through to the
    # normal per-tab gate below. Non-catalyst tools in an unregistered tab
    # just pass through (no Catalyst state → nothing to guard).
    if entry is None:
        if cc_session_id and is_cat:
            entry = registry.claim(cc_session_id) or {}
            _debug_log(f"  → CLAIMED registry row cc={cc_session_id[:8]}")
        else:
            _debug_log(f"  → no claim (cc empty? {not cc_session_id} | not catalyst tool? {not is_cat})")
            return 0

    # Keep this tab's row warm so the 10-day GC only reaps genuinely idle
    # tabs. Throttled inside the registry (skips if refreshed <60s ago).
    registry.touch(cc_session_id)

    # ── Case 2: this tab's own session gate ─────────────────────────────
    mode = entry.get("mode", "menu")
    # Per-mode tool whitelisting (the plugin's gate, mirroring the FDE
    # ModeController's DENIED). Discover (read-only) and Spec (plan, no
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
    # The remote MCP holds NO active-session state (shared host), so this
    # tab's registry row is the sole source of routing truth: stamp its
    # session_id (overwriting any value the agent supplied) into every
    # catalyst-mcp tool that targets a Mindspace — coding_workspace__*,
    # transitions, switch_mindspace, current_session, record_turn, recall_*,
    # complete_build, … Empty row session_id → drop it → server mints a
    # fresh Mindspace (only after a switch_mindspace clean-slate). The agent
    # never picks the Mindspace; switch_mindspace is the only change, gated.
    # Carve-outs: no-session tools (account/listing) are left untouched and
    # just allowed; switch_mindspace's target_session_id is the agent's pick
    # and is preserved — we add session_id (= current) alongside it.
    if is_cat and bare_name not in _NO_SESSION_BARE:
        # Transitions may resume an agent-named Mindspace when the row is
        # empty (post-end / fresh tab); workspace tools always follow the
        # active row. See _inject_current_session / _TRANSITION_BARE.
        _is_transition = bare_name in _TRANSITION_BARE
        tool_input = _inject_current_session(
            event, entry, allow_agent_fallback=_is_transition,
        )
        stamped = tool_input.get("session_id", "")
        _src = "sentinel" if (entry.get("session_id") or "").strip() else (
            "agent-resume" if (_is_transition and stamped) else "fresh"
        )
        _debug_log(f"  → ALLOW {bare_name} + inject session_id={stamped[:8] or '(fresh)'} [{_src}]")
        return _emit_allow_updated_input(tool_input)
    if _is_allowed_for_owner(tool_name):
        return 0
    # ── Native tools OPEN outside Build (Analyst / PM / Curator / menu) ──
    # Only the Engineer's Build modes (coding/vibe_code) bind native FS/shell
    # to the remote workspace; in every other mode the employee may read and
    # inspect files on the user's own machine directly. REDIRECTS holds exactly
    # the native FS/shell names (Read/Write/Edit/Bash/Grep/Glob), so external
    # MCPs still fall through to the deny below. (2026-07-23 restore.)
    if tool_name in REDIRECTS and mode not in _WORKSPACE_BOUND_MODES:
        _debug_log(f"  → ALLOW native {tool_name} (mode={mode}: native open outside Build)")
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
    # NOTE: reaching here means mode ∈ Build (coding/vibe_code) — native FS/shell
    # in Analyst/PM/Curator/menu already returned ALLOW above. The transfer curl
    # carve-out just above still fires in Build so a build can pull local files.
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
    # Native FS/shell tool in a BUILD mode (coding/vibe_code) — refuse with a
    # redirect to the matching coding_workspace tool. The Engineer's app lives on
    # EC2 / an app_root; a native tool would edit the wrong filesystem. (Native
    # tools are OPEN for the Analyst/PM/Curator — those returned ALLOW above.)
    redirect_bare = REDIRECTS.get(tool_name) or "coding_workspace__*"
    reason = (
        f"Native `{tool_name}` is blocked in Build (mode={mode}) — the "
        f"Engineer's app lives on EC2 (or is locked to the project's "
        f"app_root), so native tools would silently edit the wrong file. Use "
        f"`{redirect_bare}` instead (the namespaced version your toolset "
        f"already has loaded) — it routes to the correct workspace "
        f"automatically. To pull a file off the user's laptop into the build, "
        f"call `upload_to_workspace` and run the curl it returns.\n\n"
        f"Native tools are open for the Analyst / PM / Curator. To unlock them "
        f"here too, end the Catalyst session first (`abandon_build` / "
        f"`current_session`)."
    )
    return _emit_deny(reason)


if __name__ == "__main__":
    sys.exit(main())
