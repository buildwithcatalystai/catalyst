#!/usr/bin/env python3
"""SessionStart hook — the python3 twin of statusline_install.js, run by
`statusline_hook.sh` where node is absent. It wires the status line into Claude Code
for THIS runtime: the settings entry runs `python3 …statusline.py` (the .js twin
writes `node …statusline.js`), and an entry written for a runtime this machine no
longer has is updated in place. Otherwise identical: the stable symlink (or the
renderer's absolute forward-slash path where symlinks fail), the entry written once,
any existing status line kept in chain.json and rendered after ours, the one-time
systemMessage, the session's state record, 7-day pruning. Portable: no POSIX-only
module. Prints nothing except that one JSON message.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time

HOME = os.path.expanduser("~")
CAT_DIR = os.path.join(HOME, ".catalyst-claude")
ROOT = os.path.join(CAT_DIR, "statusline")
STATE_DIR = os.path.join(ROOT, "state")
LINK = os.path.join(CAT_DIR, "statusline-current")
CHAIN_FILE = os.path.join(ROOT, "chain.json")
INSTALLED = os.path.join(ROOT, "installed")
SETTINGS = os.path.join(HOME, ".claude", "settings.json")
RUNTIME = "python3"
SCHEMA = 1


def renderer_path() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "statusline", "statusline.py"))


def refresh_link() -> str:
    """Point the stable symlink at this runtime's renderer; return the command to run it."""
    target = renderer_path()
    os.makedirs(CAT_DIR, exist_ok=True)
    try:
        if not (os.path.islink(LINK) and os.readlink(LINK) == target):
            if os.path.lexists(LINK):
                os.unlink(LINK)
            os.symlink(target, LINK)
        if os.path.islink(LINK):
            return f"{RUNTIME} ~/.catalyst-claude/statusline-current"
    except Exception:
        pass
    return f'{RUNTIME} "{target.replace(os.sep, "/")}"'


def _ours(cmd: str) -> bool:
    return "catalyst-claude" in cmd or ("statusline" in cmd and "catalyst" in cmd)


def _runtime_of(cmd: str) -> str:
    return cmd.strip().split(" ", 1)[0] if cmd.strip() else ""


def install_setting(command: str) -> str:
    """installed · updated · present · kept · error."""
    try:
        settings = {}
        if os.path.exists(SETTINGS):
            with open(SETTINGS, encoding="utf-8") as f:
                settings = json.load(f)
        current = settings.get("statusLine")
        cur_cmd = str(current.get("command", "")) if isinstance(current, dict) else ""
        ours = _ours(cur_cmd)
        if ours and cur_cmd == command:
            return "present"
        # Ours, for a runtime this machine still has → leave it (the other twin owns it).
        if ours and _runtime_of(cur_cmd) != RUNTIME and shutil.which(_runtime_of(cur_cmd)):
            return "present"
        if not ours and os.path.exists(INSTALLED):
            return "kept"
        if not ours and cur_cmd.strip():
            os.makedirs(ROOT, exist_ok=True)
            with open(CHAIN_FILE, "w", encoding="utf-8") as f:
                json.dump({"command": cur_cmd, "recorded_at": int(time.time())}, f)
        settings["statusLine"] = {"type": "command", "command": command, "refreshInterval": 1}
        os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
        tmp = SETTINGS + ".catalyst-tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")
        os.replace(tmp, SETTINGS)
        os.makedirs(ROOT, exist_ok=True)
        with open(INSTALLED, "w") as f:
            f.write(time.strftime("%Y-%m-%dT%H:%M:%S"))
        return "updated" if ours else "installed"
    except Exception:
        return "error"


def touch_state(session_id: str) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        sha = hashlib.sha256(session_id.encode()).hexdigest()
        p = os.path.join(STATE_DIR, f"{sha}.json")
        if not os.path.exists(p):
            now = int(time.time() * 1000)
            st = {"version": SCHEMA, "session_id_sha": sha[:12], "startedAt": now, "updatedAt": now, "user": "",
                  "recovered": 0, "expertise": 0, "memories": 0, "inreach": 0, "wingmen": {}, "owners": {},
                  "inflight": None, "last_from": None, "last_learn": None}
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(st, f)
            os.replace(p + ".tmp", p)
        cutoff = time.time() - 7 * 86400
        for name in os.listdir(STATE_DIR):
            fp = os.path.join(STATE_DIR, name)
            try:
                if os.path.getmtime(fp) < cutoff:
                    os.remove(fp)
            except Exception:
                pass
    except Exception:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
        ev = json.loads(raw) if raw.strip() else {}
    except Exception:
        ev = {}
    outcome = install_setting(refresh_link())
    sid = str(ev.get("session_id") or "").strip()
    if sid:
        touch_state(sid)
    if outcome == "installed":
        sys.stdout.write(json.dumps({"systemMessage": "⚡ Catalyst status line installed — look at the bottom of Claude Code (if it is not there yet, it will be on your next session)."}))
    elif outcome == "error":
        sys.stdout.write(json.dumps({"systemMessage": "⚡ Catalyst could not set up its status line (settings.json unreadable or not writable) — run /catalyst:statusline for the details."}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
