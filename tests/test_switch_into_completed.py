"""switch_mindspace INTO a completed (shipped) Mindspace must bind the tab to it.

The server answers a passive switch with {status: "switched", mode: "menu", session_id,
app_root} and no gen_stream_id (it must not re-enter Build). Before v0.1.80 that response
was not a "full entry" and, with another Mindspace bound (the ScratchPad), the partial
guard dropped it: the tab stayed on the ScratchPad, the next start_app_building was
stamped with the ScratchPad id and the server 500'd (COD, HL, 2026-09-18). Runs the REAL
hooks as subprocesses against a throwaway $HOME. stdlib only, <5s.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
CC = "tab-switch-completed-test"
SCRATCH = "SCRATCHPAD-8cdbc22e"
COD = "COD-a0e45c40"

_home = tempfile.mkdtemp()
_env = {**os.environ, "HOME": _home}
_state = pathlib.Path(_home) / ".claude" / "state"
_state.mkdir(parents=True)


def pre(tool, tool_input=None):
    event = {"session_id": CC, "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}",
             "tool_input": tool_input or {}}
    r = subprocess.run([sys.executable, str(HOOKS / "catalyst-block-native.py")],
                       input=json.dumps(event), capture_output=True, text=True, env=_env)
    try:
        return json.loads(r.stdout)["hookSpecificOutput"].get("updatedInput", {})
    except Exception:
        return {}


def post(tool, response):
    event = {"session_id": CC, "hook_event_name": "PostToolUse",
             "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}", "tool_input": {},
             "tool_response": [{"type": "text", "text": json.dumps(response)}]}
    subprocess.run([sys.executable, str(HOOKS / "hook_record.py")],
                   input=json.dumps(event), capture_output=True, text=True, env=_env)


def row():
    p = _state / "catalyst-active-session.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    for r in data.get("sessions", [data]):
        if r.get("claude_session_id") == CC or r.get("cc_session_id") == CC:
            return r
    return {}


def bound():
    r = row()
    return r.get("catalyst_session_id") or r.get("session_id")


failures = []

# 1. The tab lands on the ScratchPad (Analyst), as every plugin landing does.
pre("health_check")
post("open_scratchpad", {"session_id": SCRATCH, "app_root": "/p/scratch", "gen_stream_id": "g:s:1", "mode": "deep_analysis"})
print(f"[1] bound={bound()} mode={row().get('mode')}")
if bound() != SCRATCH:
    failures.append(f"setup: expected {SCRATCH}, got {bound()}")

# 2. The user asks for COD, a shipped Mindspace: passive switch, mode=menu, no gen_stream_id.
post("switch_mindspace", {"status": "switched", "mode": "menu", "session_id": COD, "session_status": "completed",
                          "app_name": "COD", "app_root": "/p/cod", "project_slug": COD,
                          "paused_previous": {"paused": True}})
print(f"[2] after switch(completed) → bound={bound()} mode={row().get('mode')} gen_stream_id={row().get('gen_stream_id')!r}")
if bound() != COD:
    failures.append(f"switch into a completed Mindspace did NOT bind the tab (still {bound()}) — the bug")
if row().get("mode") != "menu":
    failures.append(f"mode after passive switch should be menu, got {row().get('mode')}")
if row().get("gen_stream_id"):
    failures.append("stale gen_stream_id from the previous Mindspace survived the switch")

# 3. The next Build entry must be stamped with COD, not the ScratchPad.
inj = pre("start_app_building", {"session_id": COD})
print(f"[3] start_app_building stamped session_id={inj.get('session_id')}")
if inj.get("session_id") != COD:
    failures.append(f"start_app_building stamped {inj.get('session_id')} instead of {COD}")

# 4. Entering the edit cycle is a full entry: the tab goes to coding on COD.
post("start_app_building", {"session_id": COD, "app_root": "/p/cod", "gen_stream_id": "g:c:1", "mode": "coding"})
print(f"[4] after start_app_building → bound={bound()} mode={row().get('mode')}")
if bound() != COD or row().get("mode") != "coding":
    failures.append(f"edit cycle did not bind COD in coding (bound={bound()}, mode={row().get('mode')})")

print()
if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("ALL PASS — a passive switch into a shipped Mindspace binds the tab; the edit cycle then lands on it")
