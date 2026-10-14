"""Per-tab Catalyst session registry — ``~/.claude/state/catalyst-active-session.json``.

Replaces the single-owner sentinel (one JSON object = one Claude Code tab owns
Catalyst for the whole machine) with an ARRAY of per-tab mappings, so multiple
Claude Code tabs can run independent Catalyst sessions at once:

    {
      "version": 2,
      "sessions": [
        {
          "claude_session_id":   "<CC tab uuid — the row's key>",
          "catalyst_session_id": "<catalyst Mindspace uuid, null until picked>",
          "app_root":            "<EC2 project path>",
          "gen_stream_id":       "<wizard checkpointer thread id>",
          "mode":                "menu | deep_analysis | spec | coding | vibe_code",
          "created_dt":          "<iso8601 utc, date AND time — row birth>",
          "last_updated_dt":     "<iso8601 utc, date AND time — refreshed on use>"
        },
        ...
      ]
    }

Rows untouched for more than ``_GC_DAYS`` days (compared as instants —
``timedelta(days=10)``, not calendar days) are garbage-collected on every save.

Both hooks (`catalyst-block-native.py` PreToolUse, `hook_record.py`
PostToolUse/Stop) import this module; it is the ONLY place that knows the
on-disk shape. The public API speaks the LEGACY flat field names
(``cc_session_id`` / ``session_id`` / ``app_root`` / ``gen_stream_id`` /
``mode`` / ``started_at``) so hook call sites stay unchanged; this module maps
them onto the registry names above.

Concurrency: hooks are separate short-lived subprocesses that can fire in
parallel (multiple tabs, PreToolUse + PostToolUse overlapping). Every mutation
runs read→modify→write under an ``fcntl.flock`` on a SIBLING lock file
(``catalyst-sessions.lock`` — separate because the atomic ``os.replace`` below
swaps the data file's inode, which would orphan a lock held on it). Writes are
atomic (``.tmp`` + ``os.replace``). On platforms without fcntl (Windows) the
lock degrades to a no-op and atomic replace alone protects the file.

Migration: a legacy single-object sentinel (top-level ``cc_session_id``, no
``sessions`` key) is transparently read as one row and rewritten as v2 on the
first mutation — the live session survives the upgrade.

Every helper is best-effort and never raises: a broken registry must not
break a tool call (same contract as the old sentinel helpers).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REGISTRY_PATH = Path.home() / ".claude" / "state" / "catalyst-active-session.json"
_LOCK_PATH = Path.home() / ".claude" / "state" / "catalyst-sessions.lock"

_GC_DAYS = 10           # rows idle longer than this are dropped on save
_TOUCH_THROTTLE_S = 60  # skip the touch() write if last_updated_dt is fresher

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover — Windows: atomic replace only
    _fcntl = None


# ── time helpers ────────────────────────────────────────────────────────────


def _now_iso() -> str:
    """ISO-8601 UTC to the second, Z-suffixed — full date AND time (the GC and
    the touch throttle compare instants, so date-only would break both)."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_iso(ts: str) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp (Z or offset form). None on failure."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ── lock ────────────────────────────────────────────────────────────────────


class _Lock:
    """flock on a sibling lock file; no-op where fcntl is unavailable."""

    def __enter__(self):
        self._fh = None
        if _fcntl is None:
            return self
        try:
            _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(_LOCK_PATH, "a")
            _fcntl.flock(self._fh.fileno(), _fcntl.LOCK_EX)
        except Exception:
            self._fh = None  # degrade to unlocked, never block the tool call
        return self

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                _fcntl.flock(self._fh.fileno(), _fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                self._fh.close()
            except Exception:
                pass
        return False


# ── raw load / save ─────────────────────────────────────────────────────────


def _load_rows() -> List[Dict[str, Any]]:
    """Parse the registry file into a list of v2 rows. Handles:
    v2 shape, legacy single-object sentinel (wrapped as one row), garbage."""
    try:
        if not REGISTRY_PATH.exists():
            return []
        data = json.loads(REGISTRY_PATH.read_text())
    except Exception:
        return []
    if isinstance(data, dict) and isinstance(data.get("sessions"), list):
        return [r for r in data["sessions"] if isinstance(r, dict)]
    # Legacy single-object sentinel → one row.
    if isinstance(data, dict) and (data.get("cc_session_id") or data.get("session_id")):
        now = _now_iso()
        return [{
            "claude_session_id": (data.get("cc_session_id") or "").strip(),
            "catalyst_session_id": data.get("session_id"),
            "app_root": data.get("app_root") or "",
            "gen_stream_id": data.get("gen_stream_id") or "",
            "mode": data.get("mode") or "menu",
            "created_dt": data.get("started_at") or now,
            "last_updated_dt": now,
        }]
    return []


def _gc(rows: List[Dict[str, Any]], keep_id: str = "") -> List[Dict[str, Any]]:
    """Drop rows idle > _GC_DAYS (as instants, timedelta-based). A row whose
    timestamp won't parse is treated as just-used (kept). ``keep_id`` (the row
    being written this call) is never dropped."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=_GC_DAYS)
    out = []
    for r in rows:
        if r.get("claude_session_id") == keep_id:
            out.append(r)
            continue
        ts = _parse_iso(r.get("last_updated_dt") or "")
        if ts is None or ts >= cutoff:
            out.append(r)
    return out


def _save_rows(rows: List[Dict[str, Any]], keep_id: str = "") -> None:
    """GC + atomic write. Best-effort, never raises."""
    try:
        rows = _gc(rows, keep_id=keep_id)
        REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = REGISTRY_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"version": 2, "sessions": rows}, indent=2))
        os.replace(tmp, REGISTRY_PATH)
    except Exception:
        pass


# ── legacy-shape mapping ────────────────────────────────────────────────────

# registry field ↔ legacy sentinel field (what the hooks' call sites speak)
_TO_LEGACY = {
    "claude_session_id": "cc_session_id",
    "catalyst_session_id": "session_id",
    "created_dt": "started_at",
}
_FROM_LEGACY = {v: k for k, v in _TO_LEGACY.items()}


def _row_to_legacy(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        out[_TO_LEGACY.get(k, k)] = v
    return out


def _legacy_key(key: str) -> str:
    return _FROM_LEGACY.get(key, key)


# ── public API (legacy-shaped) ──────────────────────────────────────────────


def read_entry(claude_session_id: str) -> Optional[Dict[str, Any]]:
    """This tab's row in LEGACY sentinel shape (cc_session_id / session_id /
    app_root / gen_stream_id / mode / started_at [+ last_updated_dt]), or
    None if the tab has no row. Lock-free read."""
    cc = (claude_session_id or "").strip()
    if not cc:
        return None
    for row in _load_rows():
        if row.get("claude_session_id") == cc:
            return _row_to_legacy(row)
    return None


def claim(claude_session_id: str) -> Dict[str, Any]:
    """Insert a fresh row for this tab (mode=menu, no Mindspace yet).
    Idempotent — an existing row is returned untouched. Legacy-shaped."""
    cc = (claude_session_id or "").strip()
    if not cc:
        return {}
    with _Lock():
        rows = _load_rows()
        for row in rows:
            if row.get("claude_session_id") == cc:
                return _row_to_legacy(row)
        now = _now_iso()
        row = {
            "claude_session_id": cc,
            "catalyst_session_id": None,
            "app_root": "",
            "gen_stream_id": "",
            "mode": "menu",
            "created_dt": now,
            "last_updated_dt": now,
        }
        rows.append(row)
        _save_rows(rows, keep_id=cc)
        return _row_to_legacy(row)


def patch(claude_session_id: str, updates: Dict[str, Any]) -> bool:
    """Apply LEGACY-shaped updates to this tab's row. Semantics mirror the old
    ``_patch_sentinel``: ``None`` = clear the field, ``""``/``{}`` = skip.
    Returns True iff at least one field actually changed. No row → False
    (patching never claims; that's PreToolUse's job)."""
    cc = (claude_session_id or "").strip()
    if not cc or not updates:
        return False
    with _Lock():
        rows = _load_rows()
        for row in rows:
            if row.get("claude_session_id") != cc:
                continue
            changed = False
            for k, v in updates.items():
                if v == "" or v == {}:
                    continue
                rk = _legacy_key(k)
                if rk == "claude_session_id":
                    continue  # the key is immutable
                if row.get(rk) != v:
                    row[rk] = v
                    changed = True
            if changed:
                row["last_updated_dt"] = _now_iso()
                _save_rows(rows, keep_id=cc)
            return changed
        return False


def remove(claude_session_id: str) -> bool:
    """Drop this tab's row only (per-tab end / abandon / logout).
    Other tabs' rows are untouched. True iff a row was removed."""
    cc = (claude_session_id or "").strip()
    if not cc:
        return False
    with _Lock():
        rows = _load_rows()
        kept = [r for r in rows if r.get("claude_session_id") != cc]
        if len(kept) == len(rows):
            return False
        _save_rows(kept)
        return True


def _is_v2_file() -> bool:
    """True when the on-disk file is already registry-shaped (v2)."""
    try:
        data = json.loads(REGISTRY_PATH.read_text())
        return isinstance(data, dict) and isinstance(data.get("sessions"), list)
    except Exception:
        return False


def touch(claude_session_id: str) -> None:
    """Refresh last_updated_dt for this tab. Throttled: skips the write when
    the stored value is fresher than _TOUCH_THROTTLE_S (PreToolUse fires on
    EVERY tool call — no point rewriting the file each time). A still-legacy
    (v1) file bypasses the throttle so the migration persists on the very
    first fire (legacy rows get a fresh last_updated_dt on every load, which
    would otherwise defer the rewrite indefinitely)."""
    cc = (claude_session_id or "").strip()
    if not cc:
        return
    row = None
    for r in _load_rows():
        if r.get("claude_session_id") == cc:
            row = r
            break
    if row is None:
        return
    if _is_v2_file():
        ts = _parse_iso(row.get("last_updated_dt") or "")
        if ts is not None:
            age = (datetime.now(tz=timezone.utc) - ts).total_seconds()
            if 0 <= age < _TOUCH_THROTTLE_S:
                return
    with _Lock():
        rows = _load_rows()
        for r in rows:
            if r.get("claude_session_id") == cc:
                r["last_updated_dt"] = _now_iso()
                _save_rows(rows, keep_id=cc)
                return


def all_entries() -> List[Dict[str, Any]]:
    """Every row, legacy-shaped — diagnostics / status.sh."""
    return [_row_to_legacy(r) for r in _load_rows()]
