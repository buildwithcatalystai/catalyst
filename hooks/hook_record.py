"""HTTP-only event sink for the Claude Code event hook.

Invoked from ``~/.claude/hooks/catalyst-event-sink.sh`` on every PostToolUse
and Stop. We translate the Claude Code hook event into one or more
(kind, payload) records and POST each to the wizard's
``/api/sessions/{session_id}/turn`` endpoint, which:

  • appends to the LangGraph PostgresSaver checkpoint at gen_stream_id, and
  • broadcasts a matching WS event for the live ChatPane.

The hook deliberately holds NO database credentials — the wizard backend
owns the persistence implementation. If the wizard later swaps PostgresSaver
for a different store, this module doesn't need to change.

Failures are silent (logged to ``~/.claude/state/catalyst-event-sink.log``)
so a transient backend hiccup never breaks the user's turn.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import uuid4


# ── Logging ─────────────────────────────────────────────────────────────────
#
# Two log files, separate concerns:
#
#   ~/.claude/state/catalyst-event-sink.log
#     The summary log. One line per significant event. Every hook
#     invocation produces an entry line (→) and an exit line (←); refusal
#     sites in between add one INFO line each naming the noop reason.
#     Every line carries a 6-char run_id prefix so concurrent fires are
#     untanglable. This is the primary "what happened" log — keep it
#     scannable.
#
#   ~/.claude/state/catalyst-hook-debug.log  (opt-in: CATALYST_HOOK_DEBUG=1)
#     Verbose payload dump. Dumps the full stdin event JSON, the
#     enriched sentinel state, and any tool_response we acted on.
#     Only used when something looks wrong — flip the env var, reproduce
#     the issue, read the file. Disabled by default so the disk doesn't
#     fill up during normal use.

import contextvars as _contextvars
import threading as _threading_log


_LOG_LOCK = _threading_log.Lock()

# ContextVar holding the current run's 6-char run_id. Set by `_new_run_ctx`
# at the top of `main()`, consumed by the logging filter below so every
# log line emitted during this run is prefixed `[abc123] …`. ContextVars
# are async-safe AND thread-safe — even when the hook subprocess uses
# threads (it doesn't today), each one would see its own value.
_run_id_var: _contextvars.ContextVar[str] = _contextvars.ContextVar("hook_run_id", default="")


class _RunIdFilter(logging.Filter):
    """Inject the current run_id into every log record so the formatter
    can stamp it on the message. Empty (no active run) → no prefix."""

    def filter(self, record: logging.LogRecord) -> bool:
        run_id = _run_id_var.get()
        record.msg = f"[{run_id}] {record.msg}" if run_id else record.msg
        return True


def _setup_logging() -> logging.Logger:
    log_path = Path.home() / ".claude" / "state" / "catalyst-event-sink.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(str(log_path), maxBytes=2_000_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger = logging.getLogger("catalyst-event-sink")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
        logger.addFilter(_RunIdFilter())
    return logger


logger = _setup_logging()


def _debug_enabled() -> bool:
    """Whether verbose payload dumping is on.

    Resolved lazily (NOT at module import) so it can read from the same
    .env files the rest of the config does. CC hook subprocesses don't
    inherit the user's shell env — putting CATALYST_HOOK_DEBUG=1 in a
    .env file under the same search path as CATALYST_MCP_SECRET / etc.
    is the only way to actually enable it for a hook.
    """
    try:
        val = _resolve_config("CATALYST_HOOK_DEBUG", "").strip()
    except Exception:
        # _resolve_config may not be defined yet during early bootstrap;
        # fall back to env only.
        val = (os.environ.get("CATALYST_HOOK_DEBUG") or "").strip()
    return val in ("1", "true", "yes")


def _setup_debug_logger() -> Optional[logging.Logger]:
    """Returns a verbose logger only when ``CATALYST_HOOK_DEBUG=1``. None
    otherwise. Writes to a dedicated file so it never bloats the main
    summary log. Called lazily on first use (see _get_debug_logger)."""
    if not _debug_enabled():
        return None
    debug_path = Path.home() / ".claude" / "state" / "catalyst-hook-debug.log"
    debug_path.parent.mkdir(parents=True, exist_ok=True)
    h = RotatingFileHandler(str(debug_path), maxBytes=5_000_000, backupCount=2)
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    dlog = logging.getLogger("catalyst-event-sink.debug")
    dlog.setLevel(logging.DEBUG)
    if not dlog.handlers:
        dlog.addHandler(h)
        dlog.addFilter(_RunIdFilter())  # same prefix as the summary log
    return dlog


# Cached after first lookup so subsequent dumps don't re-resolve env each time.
_debug_logger: Optional[logging.Logger] = None
_debug_logger_resolved = False


def _get_debug_logger() -> Optional[logging.Logger]:
    """Return the debug logger if CATALYST_HOOK_DEBUG is on, else None.
    Resolves lazily on first call. ``_resolve_config`` reads the .env
    files so this works even though CC doesn't pass env vars to hooks."""
    global _debug_logger, _debug_logger_resolved
    if not _debug_logger_resolved:
        _debug_logger = _setup_debug_logger()
        _debug_logger_resolved = True
    return _debug_logger


@dataclass
class _RunCtx:
    """Per-invocation context. Built at the top of `main()`, threaded
    through every helper that might log, and used by the final summary
    line to emit a single grep-able outcome record.

    Every field is best-effort populated; missing values render as `?`
    so the line always parses.
    """
    run_id: str
    started_at: float = 0.0
    hook: str = "?"           # PostToolUse | Stop | UserPromptSubmit | ...
    tool: str = "?"           # value of event.tool_name (truncated)
    cc_session: str = "?"     # first 8 chars
    session: str = "?"        # catalyst session_id first 8 chars
    owner_match: str = "?"    # 'true' | 'false' | 'no-owner' | 'no-cc-id'
    has_events_jwt: str = "?"  # 'yes' | 'no' | 'expired' | 'mismatch'
    posted_kinds: List[str] = field(default_factory=list)
    http_codes: List[int] = field(default_factory=list)
    post_dt_ms: List[int] = field(default_factory=list)
    noop_reason: str = ""     # set when we exit early without posting

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000) if self.started_at else 0


def _new_run_ctx() -> _RunCtx:
    """Create a fresh ctx AND publish its run_id into the ContextVar so
    every log line for the rest of this invocation gets the prefix —
    even from helpers that don't take ctx (e.g. _maybe_update_local_sentinel,
    _is_owning_tab, _maybe_clear_local_state)."""
    ctx = _RunCtx(run_id=uuid4().hex[:6], started_at=time.monotonic())
    _run_id_var.set(ctx.run_id)
    return ctx


def _log_info(ctx: Optional[_RunCtx], msg: str, *args) -> None:
    """Kept for clarity at call sites where we want to be explicit that
    this log line belongs to a specific run. The ContextVar already
    handles the prefix; ctx is accepted for documentation only."""
    logger.info(msg, *args)


def _log_warn(ctx: Optional[_RunCtx], msg: str, *args) -> None:
    logger.warning(msg, *args)


def _log_debug_payload(ctx: _RunCtx, label: str, payload: Any) -> None:
    """Dump a payload to the debug log when CATALYST_HOOK_DEBUG=1. No-op
    when the debug logger isn't configured. Truncates large payloads to
    keep one record manageable. ctx is accepted for symmetry; the
    ContextVar-based filter handles the run_id prefix automatically."""
    dlog = _get_debug_logger()
    if dlog is None:
        return
    try:
        serialized = json.dumps(payload, default=str)[:8000]
    except Exception as exc:
        serialized = f"<unserializable: {type(exc).__name__}: {exc}>"
    dlog.debug("%s: %s", label, serialized)


# ── Sentinel ────────────────────────────────────────────────────────────────


SENTINEL_PATH = Path.home() / ".claude" / "state" / "catalyst-active-session.json"

# Events JWT — minted by the wizard backend inside McpRunner.start_coding /
# enter_coding_mode, embedded in the tool response, persisted here by
# `_maybe_persist_events_jwt` (called from `_enrich_sentinel_from_response`).
# The hook reads this file on every PostToolUse during coding mode and
# posts to /api/events/record/{session_id} with Authorization: Bearer.
#
# File presence is itself a signal: events_jwt file exists ⇔ we are
# currently in coding mode for this session. Deleted on /catalyst end
# or `complete_build` (see _maybe_clear_local_state below).
EVENTS_JWT_PATH = Path.home() / ".claude" / "state" / "catalyst-events-jwt.json"


def _read_events_jwt() -> Optional[Dict[str, Any]]:
    """Return the events_jwt file contents, or None if missing/unparseable."""
    if not EVENTS_JWT_PATH.exists():
        return None
    try:
        return json.loads(EVENTS_JWT_PATH.read_text())
    except Exception as exc:
        logger.warning("events_jwt read failed: %s", exc)
        return None


def _write_events_jwt(
    events_jwt: str,
    exp_iso: str,
    session_id: str,
    gen_stream_id: str,
) -> bool:
    """Write events_jwt to disk with chmod 600. Atomic via os.replace.
    Returns True on success."""
    try:
        EVENTS_JWT_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "events_jwt": events_jwt,
            "exp": exp_iso,
            "session_id": session_id,
            "gen_stream_id": gen_stream_id,
            "issued_at": _now_iso(),
        }
        tmp = EVENTS_JWT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2))
        os.chmod(tmp, 0o600)
        os.replace(tmp, EVENTS_JWT_PATH)
        return True
    except Exception as exc:
        logger.warning("events_jwt write failed: %s", exc)
        return False


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(tz=timezone.utc).isoformat()


def _read_sentinel() -> Optional[Dict[str, Any]]:
    if not SENTINEL_PATH.exists():
        return None
    try:
        return json.loads(SENTINEL_PATH.read_text())
    except Exception as exc:
        logger.warning("sentinel read failed: %s", exc)
        return None


def _write_sentinel_full(session_id: str, app_root: str, gen_stream_id: str, mode: str) -> bool:
    """Mirror of catalyst-mcp's ``sentinel.write_sentinel`` — full session
    write that preserves cc_session_id + started_at (claimed by the
    PreToolUse hook). Returns True if anything actually changed."""
    return _patch_sentinel({
        "session_id": session_id,
        "app_root": app_root,
        "gen_stream_id": gen_stream_id,
        "mode": mode,
    })


def _patch_sentinel(updates: Dict[str, Any]) -> bool:
    """Patch the local sentinel with the given fields. Returns True iff at
    least one field actually changed. Best-effort — never raises.

    ``None`` values in ``updates`` MEAN "clear this field" (sets it to
    None in the stored JSON) — used by ``pause_after_complete`` to drop
    session_id while preserving mode=menu. Empty strings / empty dicts
    are treated as no-op."""
    try:
        if not SENTINEL_PATH.exists():
            return False
        current = json.loads(SENTINEL_PATH.read_text())
    except Exception as exc:
        logger.warning("sentinel patch read failed: %s", exc)
        return False
    changed = False
    for k, v in (updates or {}).items():
        # Distinguish "clear this field" (None) from "skip" (empty string / dict).
        if v == "" or v == {}:
            continue
        if current.get(k) != v:
            current[k] = v
            changed = True
    if not changed:
        return False
    try:
        SENTINEL_PATH.write_text(json.dumps(current, indent=2))
    except Exception as exc:
        logger.warning("sentinel patch write failed: %s", exc)
        return False
    return True


# Substring marker — matches both `mcp__catalyst-mcp__*` (direct install)
# and `mcp__plugin_catalyst_catalyst-mcp__*` (plugin install, CC mangles
# `:` → `_`). See catalyst-block-native.py for the same pattern.
_CATALYST_TOOL_MARKER = "catalyst-mcp__"


def _bare_catalyst_tool(tool_name: str) -> str:
    """Return everything after the catalyst-mcp__ namespace, or empty
    string if not a catalyst tool."""
    if not tool_name or _CATALYST_TOOL_MARKER not in tool_name:
        return ""
    return tool_name.rsplit(_CATALYST_TOOL_MARKER, 1)[-1]


def _parse_tool_response(response: Any) -> Dict[str, Any]:
    """Unwrap an MCP tool response into the JSON dict the tool returned.

    Accepts every shape Claude Code's hook payload has used for MCP tool
    responses across versions:

      1. Bare content list (current CC contract):
             [{"type": "text", "text": "<json>"}]
         CC passes the content array directly as ``tool_response`` for
         ``mcp__*`` tools — there is no enclosing dict.

      2. Wrapped dict (older/spec form):
             {"content": [{"type": "text", "text": "<json>"}]}

      3. Bare dict (some non-MCP hooks):
             {"key": "value", ...}

    Returns the parsed JSON dict on success, ``{}`` if nothing usable
    can be extracted. Never raises.
    """
    # Shape 1: bare content list.
    if isinstance(response, list):
        for block in response:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    continue
        return {}

    if not isinstance(response, dict):
        return {}

    # Shape 2: wrapped dict with `content` list.
    content = response.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        return parsed
                except Exception:
                    continue

    # Shape 3: response is itself the dict (or shape 2 fell through with
    # no parseable text block — return the wrapper, which may have
    # session_id / app_root / etc. on it directly).
    return response


def _maybe_update_local_sentinel(payload: Dict[str, Any]) -> None:
    """Client-side mirror of catalyst-mcp's ``_maybe_update_local_sentinel``
    in [tools/lifecycle.py:780-801](catalyst_mcp/tools/lifecycle.py#L780).

    Server-side ran the same logic but wrote to the EC2 process's
    Path.home() — useless to the user's local hook. This runs the same
    branches on the client so the local sentinel tracks the server's view.

    Consistency check: if the local sentinel already has a session_id AND
    the response carries a different session_id, we DON'T clobber — that's
    a stale response or a cross-tab race, log it and skip. The current
    in-flight session keeps ownership.
    """
    mode = payload.get("mode")
    sid = payload.get("session_id") or ""
    app_root = payload.get("app_root") or ""
    gen_stream_id = payload.get("gen_stream_id") or ""

    if not sid:
        # Log which catalyst-mcp tool returned a response with no
        # session_id field — helps debug "sentinel never gets set"
        # symptoms. We list the top-level keys (NOT values; values can
        # contain secrets like events_jwt) so it's safe to log.
        tool_name = payload.get("__tool_name__", "?")
        keys = sorted(k for k in payload.keys() if k != "__tool_name__")
        logger.info(
            "sentinel enrich skipped: tool=%s no session_id in response; keys=%s",
            tool_name, keys,
        )
        return  # Nothing to enrich from.

    # Session_id consistency check. The local sentinel is the truth of
    # "which build this tab is bound to"; if a tool's response says
    # otherwise, that's a sign of cross-tab interference or a stale
    # response we re-received. Drop the update loudly rather than
    # silently flipping the user to a different build.
    current = _read_sentinel() or {}
    current_sid = (current.get("session_id") or "").strip()
    if current_sid and current_sid != sid:
        logger.warning(
            "sentinel session_id mismatch: local=%s response=%s tool=%s — "
            "ignoring update (stale response or cross-tab race?)",
            current_sid[:8], sid[:8], payload.get("__tool_name__", "?"),
        )
        return

    # Same branching as lifecycle.py:_maybe_update_local_sentinel.
    if mode in ("coding", "vibe_code") and sid and app_root and gen_stream_id:
        if _write_sentinel_full(sid, app_root, gen_stream_id, mode):
            logger.info("sentinel set: mode=%s session_id=%s", mode, sid[:8])
    elif payload.get("kickoff_message") and sid and app_root and gen_stream_id:
        if _write_sentinel_full(sid, app_root, gen_stream_id, "coding"):
            logger.info("sentinel set (kickoff): mode=coding session_id=%s", sid[:8])
    else:
        # Brainstorm / menu / needs_input — partial update, only what's present.
        update: Dict[str, Any] = {"session_id": sid}
        if mode:
            update["mode"] = mode
        if app_root:
            update["app_root"] = app_root
        if gen_stream_id:
            update["gen_stream_id"] = gen_stream_id
        if _patch_sentinel(update):
            logger.info(
                "sentinel partial update: session_id=%s%s%s%s",
                sid[:8],
                f" mode={mode}" if mode else "",
                f" app_root={app_root}" if app_root else "",
                f" gen_stream_id={gen_stream_id[:24]}" if gen_stream_id else "",
            )


def _maybe_clear_local_state(payload: Dict[str, Any]) -> None:
    """Mirror of catalyst-mcp's ``_maybe_clear_local_state`` in
    [tools/lifecycle.py:804-829](catalyst_mcp/tools/lifecycle.py#L804).

    Also clears the events_jwt file alongside the sentinel — the JWT is
    bound to the coding-mode lifecycle, so it dies with the sentinel.

    ``pause_local: True``     → delete sentinel + events_jwt (abandon / end).
    ``pause_after_complete``  → flip sentinel to mode='menu', clear
                                session_id, delete events_jwt (build done;
                                a new coding entry will mint a fresh one).
    """
    if payload.get("pause_local"):
        try:
            SENTINEL_PATH.unlink(missing_ok=True)
            logger.info("sentinel cleared (pause_local)")
        except Exception as exc:
            logger.warning("sentinel clear failed: %s", exc)
        try:
            EVENTS_JWT_PATH.unlink(missing_ok=True)
            logger.info("events_jwt cleared (pause_local)")
        except Exception as exc:
            logger.warning("events_jwt clear failed: %s", exc)
    elif payload.get("pause_after_complete"):
        # session_id=None means "clear this field" — handled by _patch_sentinel.
        if _patch_sentinel({"mode": "menu", "session_id": None}):
            logger.info("sentinel transitioned: mode=menu, session_id cleared (pause_after_complete)")
        try:
            EVENTS_JWT_PATH.unlink(missing_ok=True)
            logger.info("events_jwt cleared (pause_after_complete)")
        except Exception as exc:
            logger.warning("events_jwt clear failed: %s", exc)


def _maybe_persist_events_jwt(payload: Dict[str, Any]) -> None:
    """When a coding-entry response carries an events_jwt, persist it
    alongside the sentinel. Called from `_enrich_sentinel_from_response`
    on every PostToolUse for a catalyst-mcp tool.

    Coding-entry responses (start_coding, enter_coding_mode) include
    ``events_jwt`` + ``events_jwt_exp`` in the payload. Brainstorm /
    db-finalize / menu responses don't carry these fields — silent no-op.

    Consistency check: the events_jwt's session_id MUST match the active
    sentinel's session_id. Mismatch = stale response (cross-tab race or
    re-delivery) — refuse to overwrite the file.
    """
    token = (payload.get("events_jwt") or "").strip()
    if not token:
        return
    exp = (payload.get("events_jwt_exp") or "").strip()
    sid = (payload.get("session_id") or "").strip()
    gen_stream_id = (payload.get("gen_stream_id") or "").strip()
    if not sid or not gen_stream_id:
        logger.warning(
            "events_jwt present but session_id/gen_stream_id missing in payload — refusing to persist"
        )
        return

    # Cross-check against the just-written sentinel (which _maybe_update_local_sentinel
    # called immediately before us, so it's freshly populated).
    sentinel = _read_sentinel() or {}
    sentinel_sid = (sentinel.get("session_id") or "").strip()
    if sentinel_sid and sentinel_sid != sid:
        logger.warning(
            "events_jwt session_id mismatch: sentinel=%s response=%s — refusing to persist",
            sentinel_sid[:8], sid[:8],
        )
        return

    if _write_events_jwt(token, exp, sid, gen_stream_id):
        logger.info(
            "events_jwt persisted: session=%s exp=%s",
            sid[:8], exp,
        )


def _enrich_sentinel_from_response(tool_name: str, response: Any) -> None:
    """Top-level entry point called from main() on every PostToolUse for a
    catalyst-mcp tool. Routes to the lifecycle helpers above."""
    bare = _bare_catalyst_tool(tool_name)
    if not bare:
        return
    payload = _parse_tool_response(response)
    # TEMP DIAGNOSTIC: log the parsed shape so we can see what catalyst-mcp
    # is actually returning. Keys only (no values; values may contain
    # secrets like events_jwt). Remove once sentinel-update flow is verified.
    try:
        resp_type = type(response).__name__
        resp_keys = (
            sorted(response.keys()) if isinstance(response, dict)
            else f"<{resp_type} len={len(response) if response else 0}>"
        )
        payload_keys = sorted(payload.keys()) if isinstance(payload, dict) else f"<{type(payload).__name__}>"
        logger.info(
            "enrich shape: tool=%s response_keys=%s parsed_keys=%s",
            bare, resp_keys, payload_keys,
        )
    except Exception as exc:
        logger.warning("enrich shape log failed: %s", exc)
    if not isinstance(payload, dict):
        return
    # Stamp the tool name on the payload so consistency-check logs name the source.
    payload = {**payload, "__tool_name__": bare}
    _maybe_update_local_sentinel(payload)
    _maybe_persist_events_jwt(payload)
    _maybe_clear_local_state(payload)


def _is_owning_tab(sentinel: Dict[str, Any], cc_session_id: str) -> bool:
    """Membership check — drop the record if this hook event didn't come
    from the owning Claude Code tab.

    Ownership is claimed by the PreToolUse block hook the moment a tab
    first invokes a ``mcp__catalyst-mcp__*`` tool (i.e. when ``/catalyst``
    activates and calls ``health_check``). Record hooks (PostToolUse,
    Stop) are read-only on this — they NEVER claim, only check. That way
    an unrelated tab's tool call (e.g. someone running a different MCP
    server in a second tab) can't accidentally register itself as the
    catalyst owner via the record path.

    Returns True if the firing tab is the owner (record should be posted).
    False if the sentinel hasn't been claimed yet OR if a different tab
    owns it.
    """
    if not cc_session_id:
        return False
    owner = (sentinel.get("cc_session_id") or "").strip()
    if not owner:
        # Sentinel exists but owner not yet stamped — wait for the
        # PreToolUse hook to register first. Don't post yet.
        logger.info(
            "hook deferred: sentinel has no owner yet, "
            "waiting for PreToolUse to register (cc_session=%s)",
            cc_session_id[:8],
        )
        return False
    if owner == cc_session_id:
        return True
    # INFO not WARNING: cross-tab firing is expected behavior, not an
    # error. The owning tab will (separately) handle the same hook on its
    # own subprocess. Spamming WARNINGs here clutters the log for the
    # actual problems.
    logger.info(
        "BLOCKED: cc_session=%s is not the owner — record dropped "
        "(owner=%s, catalyst session=%s)",
        cc_session_id[:8], owner[:8], (sentinel.get("session_id") or "")[:8],
    )
    return False


# ── Translate Claude Code hook event → list of (kind, payload) ──────────────


# Pattern markers — pattern-match instead of fixed prefix because Claude
# Code mangles the namespace boundary differently across registration
# paths (direct .mcp.json vs plugin install). See block-native hook for
# the same convention. Both forms end with these markers:
#
#   Direct:  mcp__catalyst-mcp__<tool>            (CATALYST marker after "mcp__")
#   Plugin:  mcp__plugin_catalyst_catalyst-mcp__<tool>
#
# Phase-4 marker spans the whole boundary so we don't mistake a tool name
# that happens to contain the substring "coding_workspace__" anywhere else.
_PHASE4_MARKER = "catalyst-mcp__coding_workspace__"
_CATALYST_MARKER = "catalyst-mcp__"


def _is_catalyst_tool(tool_name: str) -> bool:
    """True if the tool comes from the catalyst MCP server, regardless of
    how CC namespaced it (direct vs plugin install)."""
    return tool_name.startswith("mcp__") and _CATALYST_MARKER in tool_name


def _is_phase4_tool(tool_name: str) -> bool:
    """True if the tool is one of the coding_workspace__* phase-4 tools
    (the actual build-step tools, not lifecycle plumbing)."""
    return tool_name.startswith("mcp__") and _PHASE4_MARKER in tool_name


def _bare_phase4_name(tool_name: str) -> str:
    """Strip everything up to and including the phase-4 marker; returns
    e.g. 'read' for 'mcp__plugin_catalyst_catalyst-mcp__coding_workspace__read'."""
    if not _is_phase4_tool(tool_name):
        return tool_name
    return tool_name.rsplit(_PHASE4_MARKER, 1)[1]


def _translate_post_tool(event: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """One PostToolUse → emits any pending assistant text/thinking the
    model spoke just before this tool call, then a tool_call + tool_result
    record for the tool itself.

    Why pending-text first: Claude Code's autonomous loop emits
    ``[text]`` and ``[tool_use]`` blocks in the same assistant message,
    then runs tools, then emits more text, etc. ``Stop`` fires only once
    at the end of the whole autonomous run, so without this hook the
    intermediate narration ("I'll do X / now let me check Y") never
    reaches the wizard's chat history. Extracting on PostToolUse picks
    up that text live, between tool cards.
    """
    tool_name = event.get("tool_name") or ""
    if not tool_name:
        return None
    # Skip catalyst-mcp's own lifecycle calls (start/confirm/complete/etc.) —
    # those are skill plumbing, not build content. Only ``coding_workspace__*``
    # represents actual build steps.
    if _is_catalyst_tool(tool_name) and not _is_phase4_tool(tool_name):
        return None

    args = event.get("tool_input") or {}
    response = event.get("tool_response") or {}
    if isinstance(response, dict):
        result = response.get("content")
        if isinstance(result, list):
            parts = [
                b.get("text", "") for b in result
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            result = "\n".join(parts)
        elif not isinstance(result, str):
            result = json.dumps(response, default=str)
    else:
        result = str(response)

    bare = _bare_phase4_name(tool_name) if _is_phase4_tool(tool_name) else tool_name

    call_id = event.get("tool_use_id") or f"toolu_{uuid4().hex[:12]}"
    label = _format_label(bare, args)

    out: List[Dict[str, Any]] = []

    # Pending text/thinking emitted between previous tool and this one.
    transcript_path = event.get("transcript_path")
    if transcript_path:
        try:
            thinking_text, assistant_text = _latest_turn_text(transcript_path)
        except Exception as exc:
            logger.warning("post_tool transcript parse failed: %s", exc)
            thinking_text, assistant_text = "", ""
        if thinking_text:
            out.append({"kind": "thinking", "payload": {"text": thinking_text}})
        if assistant_text:
            out.append({"kind": "assistant_text", "payload": {"text": assistant_text}})

    out.extend([
        {
            "kind": "tool_call",
            "payload": {
                "tool_name": bare, "args": args,
                "call_id": call_id, "label": label,
            },
        },
        {
            "kind": "tool_result",
            "payload": {
                "tool_name": bare, "call_id": call_id,
                "content": result, "label": label,
            },
        },
    ])
    return out


def _translate_stop(event: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """End-of-turn → captures (1) any thinking blocks, (2) the assistant
    text from the most recent assistant turn, and (3) an ``auto_complete``
    record if the assistant text ends with the completion-protocol JSON
    line. The auto_complete record is consumed in ``main()`` and routed to
    the wizard backend's auto-complete endpoint instead of /turn.
    """
    transcript_path = event.get("transcript_path")
    if not transcript_path:
        return None
    try:
        thinking_text, assistant_text = _latest_turn_text(transcript_path)
    except Exception as exc:
        logger.warning("transcript parse failed: %s", exc)
        return None

    out: List[Dict[str, Any]] = []
    if thinking_text:
        out.append({"kind": "thinking", "payload": {"text": thinking_text}})
    if assistant_text:
        out.append({"kind": "assistant_text", "payload": {"text": assistant_text}})

    auto = _detect_completion_signal(assistant_text)
    if auto is not None:
        out.append({"kind": "auto_complete", "payload": auto})

    return out or None


_COMPLETION_PREFIXES = ('{"status"', "{'status'")


def _detect_completion_signal(assistant_text: str) -> Optional[Dict[str, Any]]:
    """Return ``{"summary": "..."}`` if the assistant's last non-blank line
    is a completion-protocol JSON object with both ``status == "completed"``
    AND a non-empty ``summary``. Otherwise return None.

    We require BOTH fields because an empty summary suggests the model is
    still mid-thought (e.g. emitted the JSON skeleton then stopped).
    """
    if not assistant_text:
        return None
    lines = [ln for ln in assistant_text.rstrip().split("\n") if ln.strip()]
    if not lines:
        return None
    last = lines[-1].lstrip()
    if not any(last.startswith(p) for p in _COMPLETION_PREFIXES):
        return None
    try:
        # Tolerate single-quoted JSON-ish form by normalizing ' → "
        candidate = last if last.startswith('{"') else last.replace("'", '"')
        blob = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(blob, dict):
        return None
    if (blob.get("status") or "").lower() != "completed":
        return None
    summary = (blob.get("summary") or "").strip()
    if not summary:
        return None
    return {"summary": summary}


def _is_tool_result_user(msg: Dict[str, Any]) -> bool:
    """A user-role transcript entry that's actually a tool_result, not a
    real human message. Tool results have content like
    ``[{"type": "tool_result", "tool_use_id": "...", ...}]``."""
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            return True
    return False


_PROCESSED_OFFSET_PATH = Path.home() / ".claude" / "state" / "catalyst-event-sink-offsets.json"


def _read_offsets() -> Dict[str, int]:
    try:
        return json.loads(_PROCESSED_OFFSET_PATH.read_text())
    except Exception:
        return {}


def _write_offset(transcript_path: str, offset: int) -> None:
    """Persist how many lines of *transcript_path* we've already extracted
    text/thinking from. Stop hook fires once per autonomous agent run, but
    a single autonomous run can span many tool calls + intermediate
    assistant messages. Without an offset, each Stop re-extracts every
    prior assistant message in the transcript, producing duplicates in
    the wizard's chat history. Tracking the line offset gives us
    incremental "since last Stop" extraction."""
    try:
        _PROCESSED_OFFSET_PATH.parent.mkdir(parents=True, exist_ok=True)
        offsets = _read_offsets()
        offsets[transcript_path] = offset
        _PROCESSED_OFFSET_PATH.write_text(json.dumps(offsets))
    except Exception as exc:
        logger.warning("offset write failed: %s", exc)


def _latest_turn_text(path: str) -> tuple[str, str]:
    """Extract assistant text + thinking that's accumulated since the last
    Stop fire on this transcript.

    Claude Code's autonomous loop emits a single agent "turn" as many JSONL
    entries: ``[text]``, ``[tool_use]``, then ``user/tool_result``, then
    more ``[text]``, ``[tool_use]``, etc. Stop fires only once per
    autonomous run (when the agent emits a final response with no further
    tool calls), but the intermediate ``[text]`` entries between tool
    rounds are real user-facing narration and need to land in the wizard's
    chat history.

    Strategy:
      1. Read all lines.
      2. Skip the prefix we've already processed on a previous Stop fire
         for this transcript (file path → byte/line offset stored in
         ``catalyst-event-sink-offsets.json``).
      3. Walk forward through the unprocessed tail, collecting text +
         thinking blocks from every ``role:"assistant"`` entry. Skip
         ``[tool_use]`` blocks (those go through PostToolUse) and
         ``role:"user"`` entries (real prompts AND tool_results).
      4. After extraction, persist the new offset so the next Stop only
         picks up content emitted after this point.

    Returns ``(thinking_text, assistant_text)``; either may be empty.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return "", ""

    offsets = _read_offsets()
    start = int(offsets.get(path, 0))
    if start > len(lines):
        # transcript was truncated/rotated — re-process from the top.
        start = 0

    text_parts: List[str] = []
    thinking_parts: List[str] = []
    for line in lines[start:]:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                t = block.get("type")
                if t == "text":
                    text_parts.append(block.get("text", ""))
                elif t == "thinking":
                    thinking_parts.append(block.get("thinking", ""))
        elif isinstance(content, str):
            text_parts.append(content)

    # Advance offset to end-of-file so the next Stop fire only sees new
    # entries appended after this point.
    _write_offset(path, len(lines))

    return (
        "\n".join(t for t in thinking_parts if t).strip(),
        "\n".join(t for t in text_parts if t).strip(),
    )


def _short_path(path: str) -> str:
    """Strip the EC2 project-root prefix from a path so the wizard chat
    shows project-relative paths (mirrors ``agent_runner._short_path`` in
    the wizard backend). Cases handled:

      /home/ubuntu/projects/<sid>/backend/app/main.py → backend/app/main.py
      /Users/.../output/<id>/start.sh                 → start.sh
      projects/<uuid>/frontend/page.tsx               → frontend/page.tsx
      <uuid>/start.sh                                 → start.sh

    Falls back to last 3 segments for unrecognised absolute paths.
    """
    import re
    s = str(path or "")
    if not s:
        return ""
    m = re.search(r"/(?:output|projects)/[^/]+/(.+)$", s)
    if m:
        return m.group(1)
    m = re.match(r"^(?:projects/)?([0-9a-f-]{8,})/(.+)$", s)
    if m:
        return m.group(2)
    parts = s.rstrip("/").split("/")
    return "/".join(parts[-3:]) if len(parts) > 3 else s


def _format_label(name: str, args: Dict[str, Any]) -> str:
    try:
        if name in ("read", "write", "edit"):
            return f"{name.capitalize()}: {_short_path(args.get('path', '?'))}"
        if name == "bash":
            cmd = str(args.get("command", "") or "")[:120]
            # Drop a leading ``cd <abs path> && `` prefix that the agent
            # routinely prepends; show only the actual command.
            if " && " in cmd:
                head, tail = cmd.split(" && ", 1)
                if head.strip().startswith("cd "):
                    cmd = tail
            # Strip remaining absolute project paths inside the command.
            import re
            cmd = re.sub(r"/home/ubuntu/projects/[^/]+/", "", cmd)
            return f"$ {cmd[:80]}"
        if name == "grep":
            return f"grep: {args.get('pattern', '?')} in {_short_path(args.get('path', '.'))}"
        if name == "find":
            return f"find: {args.get('pattern', '?')} in {_short_path(args.get('path', '.'))}"
        if name == "Agent":
            return f"sub-agent: {args.get('description', 'investigation')[:60]}"
        if name == "todo_write":
            return f"todos: {len(args.get('todos', []))} items"
        if name == "get_table_detail":
            # The tool's actual arg is `table_names: List[str]` — looking up
            # `table_name` (singular) always missed and rendered "DB: ?". Read
            # the list first; fall back to legacy singular if anyone ever
            # sends it that way.
            names = args.get("table_names")
            if isinstance(names, list) and names:
                head = str(names[0])
                tail = f" (+{len(names) - 1})" if len(names) > 1 else ""
                return f"DB: {head}{tail}"
            return f"DB: {args.get('table_name', '?')}"
        if name == "run_select_query":
            q = (args.get("query") or "").strip().splitlines()[0] if args.get("query") else ""
            preview = (q[:80] + "…") if len(q) > 80 else q
            return f"SQL: {preview or '?'}"
        if name == "run_python":
            code = (args.get("code") or "").strip().splitlines()[0] if args.get("code") else ""
            preview = (code[:80] + "…") if len(code) > 80 else code
            return f"py: {preview or '?'}"
        return name
    except Exception:
        return name


# ── HTTP POST to the wizard ─────────────────────────────────────────────────


PENDING_PATH = Path.home() / ".claude" / "state" / "catalyst-event-sink-pending.jsonl"


def _append_pending(session_id: str, record: Dict[str, Any]) -> None:
    """Best-effort dump of a record we couldn't deliver. Lets a human (or
    a future replay tool) see the gap. Never raises."""
    try:
        PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"session_id": session_id, "record": record})
        with PENDING_PATH.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:
        logger.warning("pending append failed: %s", exc)


# ── Config resolution (env var → plugin .env) ─────────────────────────
#
# CC hook subprocesses don't inherit the user's shell env, so process env
# alone often returns "" for CATALYST_BACKEND_URL and CATALYST_MCP_SECRET.
# The plugin ships a committed `.env` (with public defaults pointing at
# the EC2 deployment) inside its install dir; the resolver reads that as
# the canonical source. Set the same vars in the user's shell env to
# override per-machine without touching the file.
#
# Layered (first hit wins):
#   1. process env                          ← user override
#   2. $CLAUDE_PLUGIN_ROOT/.env             ← plugin-committed defaults
#   3. ~/codeGen/catalyst-plugin/.env       ← dev box (working copy)
#   4. ~/codeGen/catalyst-builder/backend/  ← wizard backend (dev box;
#      .env                                   same Supabase, same secret)

_PLUGIN_ENV_CANDIDATES = (
    # Plugin install dir — values committed to the public plugin repo,
    # so a fresh `/plugin install catalyst@catalyst-aibuilder` just works.
    *(
        [Path(os.environ["CLAUDE_PLUGIN_ROOT"]) / ".env"]
        if os.environ.get("CLAUDE_PLUGIN_ROOT")
        else []
    ),
    # Dev box: working copy of the plugin repo.
    Path.home() / "codeGen" / "catalyst-plugin" / ".env",
    # Dev box: wizard backend (same secret as the prod plugin .env).
    Path.home() / "codeGen" / "catalyst-builder" / "backend" / ".env",
)


def _read_env_file(path: Path) -> Dict[str, str]:
    """Parse a `KEY=value` .env file into a dict. Strips surrounding
    quotes from the value. Best-effort; returns {} on any error."""
    out: Dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            out[k.strip()] = v
    except Exception:
        pass
    return out


def _resolve_config(key: str, default: str = "") -> str:
    """Look up *key* in (1) env vars, (2) the .env-search-path. Caches
    the merged .env contents on the function dict so we read each file
    at most once per process."""
    val = (os.environ.get(key) or "").strip()
    if val:
        return val
    merged: Optional[Dict[str, str]] = _resolve_config.__dict__.get("_merged")
    if merged is None:
        merged = {}
        for p in _PLUGIN_ENV_CANDIDATES:
            if not p.exists():
                continue
            file_kv = _read_env_file(p)
            # First-hit-wins: don't overwrite a value loaded from an
            # earlier (higher-priority) file.
            for k, v in file_kv.items():
                if k not in merged and v:
                    merged[k] = v
        _resolve_config.__dict__["_merged"] = merged
    return (merged.get(key) or default).strip()


def _resolve_mcp_secret() -> str:
    return _resolve_config("CATALYST_MCP_SECRET", "")


def _resolve_backend_url() -> str:
    return _resolve_config("CATALYST_BACKEND_URL", "http://localhost:8000")


def _post_turn(
    backend_url: str,
    session_id: str,
    record: Dict[str, Any],
    *,
    ctx: Optional[_RunCtx] = None,
) -> bool:
    """POST one turn record to the wizard's events endpoint.

    Auth: reads ``~/.claude/state/catalyst-events-jwt.json`` and sends
    ``Authorization: Bearer <events_jwt>``. The file is written by
    `_maybe_persist_events_jwt` when the agent transitions into coding
    mode (via start_coding / enter_coding_mode responses).

    Silent no-op when:
      - events_jwt file is missing (we're not in coding mode — brainstorm/
        db phases persist natively via the wizard's LangGraph; hook has
        nothing useful to record),
      - file's session_id doesn't match the active session_id (stale JWT
        from a previous build).

    On 401 (events_jwt rotated server-side, or natural exp): logs and
    drops the record. Next coding-mode entry will mint a fresh JWT.

    When ``ctx`` is supplied, records the per-call HTTP code + duration
    onto it for the final summary line.
    """
    creds = _read_events_jwt()
    if not creds:
        # No events_jwt → not in coding mode → no-op.
        if ctx is not None:
            ctx.has_events_jwt = "no"
        return False

    jwt_token = (creds.get("events_jwt") or "").strip()
    file_sid = (creds.get("session_id") or "").strip()
    if not jwt_token or not file_sid:
        _log_warn(ctx, "events_jwt file present but malformed: %r", creds)
        if ctx is not None:
            ctx.has_events_jwt = "malformed"
        return False

    # Cross-check: the events_jwt is bound to one specific session_id.
    if file_sid != session_id:
        _log_warn(
            ctx,
            "events_jwt session mismatch: file=%s record=%s — skipping POST",
            file_sid[:8], session_id[:8],
        )
        if ctx is not None:
            ctx.has_events_jwt = "mismatch"
        return False

    # Defense-in-depth exp check.
    exp_str = (creds.get("exp") or "").strip()
    if exp_str:
        try:
            from datetime import datetime, timezone
            exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            if exp_dt <= datetime.now(tz=timezone.utc):
                _log_info(
                    ctx,
                    "events_jwt expired (exp=%s) — dropping record; next coding entry refreshes",
                    exp_str,
                )
                if ctx is not None:
                    ctx.has_events_jwt = "expired"
                return False
        except Exception:
            pass

    if ctx is not None:
        ctx.has_events_jwt = "yes"

    url = f"{backend_url.rstrip('/')}/api/events/record/{session_id}"
    body = json.dumps(record).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}",
    }
    req = urlrequest.Request(url, data=body, headers=headers, method="POST")
    t0 = time.monotonic()
    http_code = 0
    try:
        with urlrequest.urlopen(req, timeout=15.0) as resp:
            http_code = resp.status
            if resp.status >= 400:
                _log_warn(ctx, "POST %s -> %s", url, resp.status)
                return False
            return True
    except urlerror.HTTPError as exc:
        http_code = exc.code
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            detail = "(no body)"
        if exc.code == 401:
            # JWT rejected — likely key rotation or natural exp the
            # client-side check missed. Drop the record; the next coding
            # entry mints a fresh JWT and recovers.
            _log_info(
                ctx,
                "events_jwt rejected by backend (401): %s — drop record, will refresh on next coding entry",
                detail,
            )
            return False
        _log_warn(ctx, "POST %s -> HTTP %s: %s", url, exc.code, detail)
        return False
    except Exception as exc:
        _log_warn(ctx, "POST %s failed: %s", url, exc)
        return False
    finally:
        if ctx is not None:
            ctx.http_codes.append(http_code)
            ctx.post_dt_ms.append(int((time.monotonic() - t0) * 1000))


# ── Entry point ─────────────────────────────────────────────────────────────


def main(stream=None) -> int:
    """Read Claude Code hook JSON from stdin → POST one or more turn records
    to the wizard's events endpoint. Always exits 0.

    All logging routes through a per-invocation ``_RunCtx`` so every log
    line carries a 6-char run_id, and a single summary line ("← …") is
    emitted in ``finally`` regardless of how the run exits. That summary
    is the line you grep for when debugging — it names the hook event,
    the tool that fired it, the active session, what got posted (or why
    nothing did), HTTP outcomes, and total wall time.
    """
    ctx = _new_run_ctx()
    try:
        return _run(ctx, stream)
    except Exception as exc:
        # Any uncaught exception is a hook bug. Log it loudly so we see
        # it in the summary line; never re-raise — hook subprocess always
        # exits 0.
        _log_warn(ctx, "unhandled exception: %s: %s", type(exc).__name__, exc)
        ctx.noop_reason = ctx.noop_reason or f"exception:{type(exc).__name__}"
        return 0
    finally:
        _emit_summary(ctx)


def _emit_summary(ctx: _RunCtx) -> None:
    """Single grep-able summary line per invocation: outcome + timing +
    correlations. The run_id prefix is added automatically by the
    logging filter.

    Format examples:
      [abc123] ← hook=PostToolUse tool=mcp__catalyst-mcp__send_message
                cc=12345678 session=87654321 posted=2
                kinds=[talk,tool_call] http=[200,200] dt=98ms
      [def456] ← hook=PostToolUse tool=Read cc=12345678 session=87654321
                noop=not-owner(owner=abcd1234) dt=12ms
    """
    line = (
        f"← hook={ctx.hook} tool={(ctx.tool or '?')[:60]} "
        f"cc={ctx.cc_session} session={ctx.session}"
    )
    if ctx.posted_kinds:
        kinds_str = ",".join(ctx.posted_kinds)
        http_str = ",".join(str(c) for c in ctx.http_codes) or "?"
        line += f" posted={len(ctx.posted_kinds)} kinds=[{kinds_str}] http=[{http_str}]"
    if ctx.noop_reason:
        line += f" noop={ctx.noop_reason}"
    line += f" dt={ctx.elapsed_ms()}ms"
    logger.info(line)


def _run(ctx: _RunCtx, stream) -> int:
    """The actual hook-handling body — separated from ``main`` so the
    ``finally`` block in ``main`` always emits its summary line even when
    we early-return here. Sets ``ctx.noop_reason`` at each refusal site so
    the summary line names WHY nothing got posted."""
    raw = (stream or sys.stdin).read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        _log_warn(ctx, "hook stdin not JSON: %s; raw=%r", exc, raw[:200])
        ctx.noop_reason = "stdin-not-json"
        return 0

    # Stamp the entry context from the inbound event payload. All fields
    # are best-effort — missing values render as `?` in the summary.
    ctx.hook = (event.get("hook_event_name") or os.getenv("CLAUDE_HOOK_EVENT") or "?").strip()
    ctx.tool = (event.get("tool_name") or "?").strip()
    cc_session_id = (event.get("session_id") or "").strip()
    ctx.cc_session = (cc_session_id or "?")[:8]

    # Entry line: every hook fire gets one. Lets you spot a missed/extra
    # fire even before any decisions are made.
    _log_info(
        ctx,
        "→ hook=%s tool=%s cc=%s",
        ctx.hook, ctx.tool[:60], ctx.cc_session,
    )
    _log_debug_payload(ctx, "stdin_event", event)

    sentinel = _read_sentinel()
    if sentinel is None:
        ctx.noop_reason = "no-sentinel"
        return 0  # no active build → no-op

    # Hard ownership check: if cc_session_id doesn't match the sentinel
    # owner, drop the record. Logged at INFO (not WARNING) because this is
    # the expected case for hooks firing in non-owning tabs — happens
    # constantly during cross-tab Claude Code use; not an error.
    if not _is_owning_tab(sentinel, cc_session_id):
        ctx.owner_match = "false"
        owner = (sentinel.get("cc_session_id") or "")[:8]
        ctx.noop_reason = f"not-owner(owner={owner})"
        return 0
    ctx.owner_match = "true"

    # When a session-info-bearing catalyst tool just ran (confirm,
    # send_message, start_build, claim_phase_generate, current_session),
    # enrich the local sentinel from the response BEFORE the
    # missing-session-id check.
    prev_mode = (sentinel.get("mode") or "").strip()
    prev_sid = (sentinel.get("session_id") or "").strip()
    if ctx.hook == "PostToolUse":
        _enrich_sentinel_from_response(
            event.get("tool_name") or "", event.get("tool_response"),
        )
        # Re-read so the rest of this function sees the freshly patched fields.
        sentinel = _read_sentinel() or sentinel
        _log_debug_payload(ctx, "tool_response", event.get("tool_response"))

    session_id = sentinel.get("session_id") or ""
    if not session_id:
        _log_warn(ctx, "sentinel missing session_id: %r", sentinel)
        ctx.noop_reason = "sentinel-missing-session-id"
        return 0
    ctx.session = session_id[:8]

    # Gate 2: only sync when sentinel is in coding mode. Brainstorm /
    # db_finalize / menu phases persist natively via the wizard's
    # LangGraph; the hook has nothing useful to record there.
    new_mode = (sentinel.get("mode") or "").strip()
    if new_mode not in ("coding", "vibe_code"):
        ctx.noop_reason = f"mode-not-coding(mode={new_mode or 'unset'})"
        return 0

    # First-time coding entry on this transcript: fast-forward the offset
    # to the current EOF so pre-coding narration (menu banter, project
    # selection, etc.) doesn't get scooped up by the first
    # _latest_turn_text scan. Identified by the sentinel transition:
    # either session_id flipped from empty → set, OR mode flipped into
    # coding from anything else (menu, brainstorm, ...).
    became_coding = (
        prev_mode not in ("coding", "vibe_code")
        or not prev_sid
        or prev_sid != session_id
    )
    if became_coding:
        transcript_path = event.get("transcript_path")
        if transcript_path:
            try:
                eof = len(
                    Path(transcript_path)
                    .read_text(encoding="utf-8", errors="replace")
                    .splitlines()
                )
                _write_offset(transcript_path, eof)
                logger.info(
                    "transcript offset fast-forwarded to %d on coding entry "
                    "(session=%s, prev_mode=%s)",
                    eof, session_id[:8], prev_mode or "unset",
                )
            except Exception as exc:
                logger.warning("offset fast-forward failed: %s", exc)

    if ctx.hook == "PostToolUse":
        records = _translate_post_tool(event)
    elif ctx.hook == "Stop":
        records = _translate_stop(event)
    else:
        ctx.noop_reason = f"unhandled-hook({ctx.hook})"
        return 0

    if not records:
        ctx.noop_reason = "no-records"
        return 0

    backend_url = _resolve_backend_url()
    auto_complete_payload: Optional[Dict[str, Any]] = None
    attempted = 0  # how many records we tried to POST (excl. auto_complete)
    for rec in records:
        if rec.get("kind") == "auto_complete":
            # Routed separately to /auto-complete — don't send to /turn
            # because the wizard's _kind_to_messages doesn't know this kind
            # and would 400.
            auto_complete_payload = rec.get("payload") or {}
            continue
        attempted += 1
        ok = _post_turn(backend_url, session_id, rec, ctx=ctx)
        if ok:
            ctx.posted_kinds.append(rec.get("kind", "?"))

    if auto_complete_payload is not None:
        attempted += 1
        ok = _post_auto_complete(backend_url, session_id, auto_complete_payload, ctx=ctx)
        if ok:
            ctx.posted_kinds.append("auto_complete")

    # If we tried to post records but every attempt was a no-op or failure,
    # name the reason in the summary so the operator doesn't see a blank
    # outcome line. Common case: events_jwt file missing (brainstorm phase)
    # — has_events_jwt was set inside _post_turn's no-op path.
    if attempted > 0 and not ctx.posted_kinds and not ctx.noop_reason:
        if ctx.has_events_jwt == "no":
            ctx.noop_reason = "no-events-jwt"
        elif ctx.has_events_jwt == "expired":
            ctx.noop_reason = "events-jwt-expired"
        elif ctx.has_events_jwt == "mismatch":
            ctx.noop_reason = "events-jwt-session-mismatch"
        elif ctx.has_events_jwt == "malformed":
            ctx.noop_reason = "events-jwt-malformed"
        elif ctx.http_codes:
            ctx.noop_reason = f"all-posts-failed(http={','.join(str(c) for c in ctx.http_codes)})"
        else:
            ctx.noop_reason = "all-posts-failed"

    return 0


def _post_auto_complete(
    backend_url: str,
    session_id: str,
    payload: Dict[str, Any],
    *,
    ctx: Optional[_RunCtx] = None,
) -> bool:
    """POST to /api/sessions/{id}/auto-complete. Mirrors _post_turn's failure
    handling — best-effort, never raises.

    Auth: same events_jwt the rest of the hook uses. The backend's
    /auto-complete route accepts ``Authorization: Bearer <events_jwt>``
    with a session_id-claim-vs-path check (same as /api/events/record).

    Silent no-op when:
      - events_jwt file is missing (we're not in coding mode — the user
        emitted a completion JSON without ever entering coding; rare),
      - file's session_id doesn't match the path session_id (stale JWT
        from a previous build).

    When ``ctx`` is supplied, records the HTTP code + duration onto it
    for the final summary line.
    """
    creds = _read_events_jwt()
    if not creds:
        # No events_jwt — can't authenticate. Auto-complete is a safety net;
        # the agent's own `complete_build` call is the canonical path and
        # is unaffected by this no-op.
        if ctx is not None:
            ctx.has_events_jwt = "no"
        return False

    jwt_token = (creds.get("events_jwt") or "").strip()
    file_sid = (creds.get("session_id") or "").strip()
    if not jwt_token or not file_sid:
        _log_warn(ctx, "events_jwt file present but malformed: %r", creds)
        if ctx is not None:
            ctx.has_events_jwt = "malformed"
        return False

    if file_sid != session_id:
        _log_warn(
            ctx,
            "events_jwt session mismatch for auto-complete: file=%s path=%s",
            file_sid[:8], session_id[:8],
        )
        if ctx is not None:
            ctx.has_events_jwt = "mismatch"
        return False

    if ctx is not None:
        ctx.has_events_jwt = "yes"

    url = f"{backend_url.rstrip('/')}/api/sessions/{session_id}/auto-complete"
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt_token}",
    }
    req = urlrequest.Request(url, data=body, headers=headers, method="POST")
    t0 = time.monotonic()
    http_code = 0
    try:
        # Longer timeout: this runs migrations + start.sh on EC2.
        with urlrequest.urlopen(req, timeout=120.0) as resp:
            http_code = resp.status
            if resp.status >= 400:
                _log_warn(ctx, "POST %s -> %s", url, resp.status)
                return False
            return True
    except urlerror.HTTPError as exc:
        http_code = exc.code
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            detail = "(no body)"
        _log_warn(ctx, "POST %s -> HTTP %s: %s", url, exc.code, detail)
        return False
    except Exception as exc:
        _log_warn(ctx, "POST %s failed: %s", url, exc)
        return False
    finally:
        if ctx is not None:
            ctx.http_codes.append(http_code)
            ctx.post_dt_ms.append(int((time.monotonic() - t0) * 1000))


if __name__ == "__main__":
    sys.exit(main())
