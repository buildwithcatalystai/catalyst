#!/usr/bin/env python3
"""The Catalyst status line for Claude Code — the python3 renderer.

Twin of statusline.js (same state files, same line, same panes); the launcher
`hooks/statusline_hook.sh` and the install hook pick node where it exists and
python3 otherwise, so a Mac without Node still gets the line. Portable on purpose:
stdin is read on a daemon thread with a deadline (no `select`, which only works on
sockets on Windows), the state is plain JSON, nothing here needs a POSIX-only module.
`--doctor` explains a blank line. Fails silent, always.

    ⚡ catalyst ⠹ reaching Devin's Wingman          ← a tool call in flight
    ⚡ catalyst · 4 recovered · 2 Wingmen · 1 expertise learned · 3 memories recorded
    ⚡ catalyst · from Devin's Wingman 2m ago       ← panes rotate every 4 s
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time

HOME = os.path.expanduser("~")
ROOT = os.path.join(HOME, ".catalyst-claude", "statusline")
STATE_DIR = os.path.join(ROOT, "state")
CHAIN_FILE = os.path.join(ROOT, "chain.json")
LINK = os.path.join(HOME, ".catalyst-claude", "statusline-current")
SCHEMA = 1

INFLIGHT_TTL_S = 120
PANE_TICKS = 4
EMPHASIS_TICKS = 2
CREST_STRIDE = 3
STDIN_TIMEOUT_S = 0.5
CHAIN_TIMEOUT_S = 0.8
SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

BASE = "\x1b[38;2;140;116;245m"
MID = "\x1b[38;2;201;191;251m"
HI = "\x1b[38;2;241;238;254m"
WHITE = "\x1b[97m"
GRAY = "\x1b[38;5;245m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"


def _read_stdin(timeout_s: float = STDIN_TIMEOUT_S) -> tuple:
    """Claude Code writes one JSON object and closes the pipe (its own doc examples
    read to EOF). A daemon thread bounds the wait anyway, portably."""
    if sys.stdin.isatty():
        return {}, b""
    box: dict = {}

    def _r():
        try:
            box["raw"] = sys.stdin.buffer.read()
        except Exception:
            box["raw"] = b""

    t = threading.Thread(target=_r, daemon=True)
    t.start()
    t.join(timeout_s)
    raw = box.get("raw", b"") or b""
    try:
        return json.loads(raw.decode("utf-8") or "{}"), raw
    except Exception:
        return {}, raw


def state_path(session_id: str) -> str:
    return os.path.join(STATE_DIR, hashlib.sha256(session_id.strip().encode()).hexdigest() + ".json")


def read_state(session_id: str):
    try:
        with open(state_path(session_id), encoding="utf-8") as f:
            st = json.load(f)
        return st if st.get("version") == SCHEMA else None
    except Exception:
        return None


def age(ms: float, now_ms: float) -> str:
    s = max(1, int((now_ms - float(ms)) / 1000))
    if s < 60:
        return f"{s}s"
    m = s // 60
    return f"{m}m" if m < 60 else f"{m // 60}h"


def shimmer(word: str, tick: int) -> str:
    crest = (tick * CREST_STRIDE) % len(word)
    out = []
    for i, ch in enumerate(word):
        d = abs(i - crest)
        out.append((HI if d == 0 else MID if d <= 2 else BASE) + ch)
    return "".join(out) + RESET


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def render(st, now_ms: float) -> str:
    tick = int(now_ms // 1000)
    brand = f"{BASE}{BOLD}⚡{RESET} {BOLD}{shimmer('catalyst', tick)}{RESET}"
    # A tab opened before the plugin (or its update) never ran the start-up hook and
    # has no record: still show the brand, resting — every tab carries the line, and
    # the tally fills in where the hooks run. Only a payload without a session id is blank.
    if not st:
        return f"{brand} {WHITE}· ready{RESET}"

    inflight = st.get("inflight") or None
    if inflight and inflight.get("at") is not None and 0 <= now_ms - float(inflight["at"]) < INFLIGHT_TTL_S * 1000:
        spin = SPINNER[(tick * 3) % len(SPINNER)]
        return f"{brand} {BASE}{spin}{RESET} {WHITE}{inflight.get('label') or 'working'}{RESET}"

    parts = []
    if int(st.get("recovered") or 0) > 0:
        parts.append(f"{st['recovered']} recovered")
    wingmen = st.get("wingmen") or {}
    if wingmen:
        parts.append(plural(len(wingmen), "Wingman", "Wingmen"))
    if int(st.get("expertise") or 0) > 0:
        parts.append(f"{st['expertise']} expertise learned")
    if int(st.get("memories") or 0) > 0:
        parts.append(plural(int(st["memories"]), "memory recorded", "memories recorded"))
    if not parts:
        return f"{brand} {WHITE}· ready{RESET}"

    panes = [None]
    lf = st.get("last_from") or {}
    if lf.get("at"):
        panes.append(f"{lf.get('label') or 'from a colleague'} {age(lf['at'], now_ms)} ago")
    ll = st.get("last_learn") or {}
    if ll.get("at"):
        panes.append(f"{ll.get('label') or 'learned'} {age(ll['at'], now_ms)} ago")
    pane = panes[(tick // PANE_TICKS) % len(panes)]
    if pane:
        return f"{brand} {WHITE}·{RESET} {WHITE}{pane}{RESET}"

    emph = (tick // EMPHASIS_TICKS) % len(parts)
    styled = [f"{WHITE}{BOLD}{p}{RESET}" if i == emph else f"{GRAY}{p}{RESET}" for i, p in enumerate(parts)]
    return f"{brand} {WHITE}·{RESET} " + f"{GRAY} · {RESET}".join(styled)


def chained(raw: bytes) -> str:
    """The status line that was there before Catalyst — still rendered, after ours."""
    try:
        with open(CHAIN_FILE, encoding="utf-8") as f:
            cmd = (json.load(f).get("command") or "").strip()
        if not cmd or "catalyst-claude" in cmd:
            return ""
        out = subprocess.run(cmd, shell=True, input=raw, capture_output=True, timeout=CHAIN_TIMEOUT_S)
        return out.stdout.decode("utf-8", "replace").splitlines()[0].strip() if out.stdout else ""
    except Exception:
        return ""


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def doctor() -> str:
    import glob
    import platform
    lines = [f"catalyst status line doctor · python {platform.python_version()} · {platform.system()}"]
    managed = {"Darwin": "/Library/Application Support/ClaudeCode/managed-settings.json",
               "Linux": "/etc/claude-code/managed-settings.json",
               "Windows": "C:/Program Files/ClaudeCode/managed-settings.json"}.get(platform.system(), "")
    cwd = os.getcwd()
    files = [("managed", managed), ("project local", os.path.join(cwd, ".claude", "settings.local.json")),
             ("project", os.path.join(cwd, ".claude", "settings.json")), ("user", os.path.join(HOME, ".claude", "settings.json"))]
    winner = None
    for label, p in files:
        if not p or not os.path.exists(p):
            lines.append(f"  {label:<14} {p or '-'}: absent")
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            lines.append(f"  {label:<14} {p}: UNREADABLE ({e})")
            continue
        sl = d.get("statusLine")
        cmd = str(sl.get("command", "")) if isinstance(sl, dict) else ""
        mark = "catalyst" if "catalyst" in cmd else ("OTHER" if cmd else "none")
        lines.append(f"  {label:<14} {p}: statusLine={mark}{' → ' + cmd if cmd else ''}{' · disableAllHooks=true !' if d.get('disableAllHooks') else ''}")
        if sl and winner is None:
            winner = (label, cmd)
    if winner:
        lines.append(f"  → Claude Code runs the {winner[0]} entry: {winner[1]}" + ("" if "catalyst" in winner[1] else "   ← this shadows Catalyst's user-level entry"))
    else:
        lines.append("  → no statusLine anywhere: the plugin's SessionStart hook has not run in a session yet (start a new session)")
    link = f"  link           {LINK if os.path.lexists(LINK) else 'MISSING ' + LINK}"
    if os.path.islink(LINK):
        tgt = os.readlink(LINK)
        link += f" → {tgt}"
        if not os.path.exists(tgt):
            lines.append("  ! the link's target does not exist (plugin dir moved?) — a new session re-points it")
    lines.append(link)
    states = sorted(glob.glob(os.path.join(STATE_DIR, "*.json")), key=os.path.getmtime, reverse=True)
    lines.append(f"  state records  {len(states)} in {STATE_DIR}")
    if states:
        try:
            with open(states[0], encoding="utf-8") as f:
                st = json.load(f)
            lines.append(f"  newest record  updated {age(st.get('updatedAt', 0), time.time() * 1000)} ago · recovered={st.get('recovered')} expertise={st.get('expertise')} memories={st.get('memories')}")
            lines.append("  sample render  " + strip_ansi(render(st, time.time() * 1000)))
        except Exception as e:
            lines.append(f"  newest record  unreadable ({e})")
    lines.append("  chain          " + (open(CHAIN_FILE, encoding="utf-8").read().strip()[:120] if os.path.exists(CHAIN_FILE) else "none"))
    lines.append("  if all of this looks right and the line is still blank: run `claude --debug` and look for 'Status line' in the debug log — it logs the exit code and stderr of the first invocation.")
    return "\n".join(lines)


def main() -> None:
    if "--doctor" in sys.argv[1:]:
        try:
            sys.stdout.write(doctor() + "\n")
        except Exception as e:
            sys.stdout.write(f"doctor failed: {type(e).__name__}: {e}\n")
        return
    try:
        payload, raw = _read_stdin()
        sid = payload.get("session_id") if isinstance(payload, dict) else None
        ours = render(read_state(sid), time.time() * 1000) if isinstance(sid, str) and sid.strip() else ""
        other = chained(raw)
        line = ours if not other else (f"{ours} {GRAY}│{RESET} {other}" if ours else other)
        if line:
            sys.stdout.write(line)
            sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)      # the stdin thread may still be parked on an open pipe


if __name__ == "__main__":
    main()
