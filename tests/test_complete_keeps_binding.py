"""Regression guard: finishing a build must NOT unbind the tab.

The bug (fixed 2026-09-14): `complete_build` returns `pause_after_complete`
— the same flag `switch_mindspace` uses to say "release this tab, the user
wants a fresh Mindspace" — and the PostToolUse hook treated both alike:
mode=menu AND session_id cleared. But completion is immediately followed by
the Curator's reflect (mindspace_skill / mindspace_memory / user_persona
writes) and often a "resume after completion to bank the lessons". With the
binding gone those calls left the tab unbound: the writes landed nowhere (a
completed Journal Entries app with NO skill) and `start_app_building`, seeing
no session_id, minted a stray greenfield Mindspace.

The contract this locks down:
  complete_build  → mode=menu, session_id KEPT   (reflect + resume stay bound)
  switch_mindspace(ready_for_new) → session_id cleared  (unchanged — see
                                     tests/test_switch_to_new_mindspace.py)

Runs the REAL hook scripts as subprocesses against a throwaway $HOME. stdlib
only, no network, <5s:
    ~/.pyenv/versions/mcp-env/bin/python tests/test_complete_keeps_binding.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
CC = "tab-complete-test"
DONE = "DONE-SESSION-727e817c"

_home = tempfile.mkdtemp()
_env = {**os.environ, "HOME": _home}
_state = pathlib.Path(_home) / ".claude" / "state"
_state.mkdir(parents=True)


def pre(tool, tool_input=None):
    """Fire PreToolUse; return the args the hook would hand the server."""
    event = {
        "session_id": CC,
        "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}",
        "tool_input": tool_input or {},
    }
    r = subprocess.run([sys.executable, str(HOOKS / "catalyst-block-native.py")],
                       input=json.dumps(event), capture_output=True, text=True, env=_env)
    try:
        return json.loads(r.stdout)["hookSpecificOutput"].get("updatedInput", {})
    except Exception:
        return {}


def post(tool, response):
    """Fire PostToolUse with a synthetic server response."""
    event = {
        "session_id": CC,
        "hook_event_name": "PostToolUse",
        "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}",
        "tool_input": {},
        "tool_response": [{"type": "text", "text": json.dumps(response)}],
    }
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


def bound_session():
    r = row()
    return r.get("catalyst_session_id") or r.get("session_id")


failures = []

pre("health_check")                                    # tab claims its row
post("start_app_building", {"session_id": DONE, "app_root": "/p/done",
                            "gen_stream_id": "g:1:2", "mode": "coding"})
if bound_session() != DONE:
    failures.append(f"setup: expected bound to {DONE}, got {bound_session()}")
print(f"[1] building in {bound_session()} (mode={row().get('mode')})")

# Completion flips the tab to menu but MUST keep the Mindspace bound.
post("complete_build", {"status": "completed", "already_completed": False,
                        "pause_after_complete": True})
print(f"[2] after complete_build → binding={bound_session()} mode={row().get('mode')}")
if bound_session() != DONE:
    failures.append(f"complete_build unbound the tab (binding={bound_session()}) — the bug")
if row().get("mode") != "menu":
    failures.append(f"complete_build should flip mode to menu, got {row().get('mode')!r}")

# The Curator's reflect right after completion stays in the finished Mindspace.
skill = pre("coding_workspace__mindspace_skill", {"mode": "write", "content": "lessons"})
print(f"[3] reflect write routes to session_id={skill.get('session_id', '(omitted)')}")
if skill.get("session_id") != DONE:
    failures.append(f"reflect after completion went to {skill.get('session_id')!r}, not the finished Mindspace")

# "Resume after completion" CONTINUES the finished Mindspace — never a greenfield mint.
resume = pre("start_app_building")
print(f"[4] start_app_building after completion → session_id={resume.get('session_id', '(omitted)')}")
if resume.get("session_id") != DONE:
    failures.append(f"post-completion start_app_building would mint a stray (session_id={resume.get('session_id')!r})")

# A NEW Mindspace is still one deliberate step away — switch releases the binding.
post("switch_mindspace", {"status": "ready_for_new", "paused": {"paused": True},
                          "pause_after_complete": True})
print(f"[5] after switch(ready_for_new) → binding={bound_session()}")
if bound_session() is not None:
    failures.append(f"switch did NOT release the binding (still {bound_session()})")

print()
if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("OK — completion keeps the tab bound; switch is the one release.")
