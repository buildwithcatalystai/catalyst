"""focus_on_expertise (the new name of switch_mindspace) binds the tab exactly as switch_mindspace did,
and the landing through ensure_auth(home=true) binds the tab to the home Mindspace — while a plain
ensure_auth (what /status, /list and /end call first) never moves it. Runs the REAL hooks as subprocesses
against a throwaway $HOME. stdlib only, <5s.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
CC = "tab-focus-test"
HOME_SID = "HOME-8cdbc22e"
PAYOUTS = "PAYOUTS-a0e45c40"

_home = tempfile.mkdtemp()
_env = {**os.environ, "HOME": _home}
_state = pathlib.Path(_home) / ".claude" / "state"
_state.mkdir(parents=True)


def pre(tool, tool_input=None):
    event = {"session_id": CC, "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}", "tool_input": tool_input or {}}
    r = subprocess.run([sys.executable, str(HOOKS / "catalyst-block-native.py")],
                       input=json.dumps(event), capture_output=True, text=True, env=_env)
    try:
        return json.loads(r.stdout)["hookSpecificOutput"].get("updatedInput", {})
    except Exception:
        return {}


def post(tool, response, tool_input=None):
    event = {"session_id": CC, "hook_event_name": "PostToolUse",
             "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}", "tool_input": tool_input or {},
             "tool_response": [{"type": "text", "text": json.dumps(response)}]}
    subprocess.run([sys.executable, str(HOOKS / "hook_record.py")],
                   input=json.dumps(event), capture_output=True, text=True, env=_env)


def bound():
    p = _state / "catalyst-active-session.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    for r in data.get("sessions", [data]):
        if r.get("claude_session_id") == CC or r.get("cc_session_id") == CC:
            return r.get("catalyst_session_id") or r.get("session_id"), r.get("mode")
    return None


failures = []
LANDING = {"authenticated": True, "session_id": HOME_SID, "app_root": "/p/home", "gen_stream_id": "g:h:1",
           "mode": "deep_analysis", "brief_block": "Today's brief (version 1):\n- [b1] Reply to Vibin — open"}

# 1. The landing is the sign-in call with home: it binds the tab to the home Mindspace.
pre("ensure_auth", {"home": True})
post("ensure_auth", LANDING, {"home": True})
print(f"[1] after ensure_auth(home) → {bound()}")
if (bound() or (None,))[0] != HOME_SID:
    failures.append(f"ensure_auth(home=true) did not bind the tab to home ({bound()})")

# 2. focus_on_expertise into another Mindspace binds the tab there (a passive switch).
post("focus_on_expertise", {"status": "switched", "mode": "menu", "session_id": PAYOUTS, "app_name": "Rider payouts",
                            "app_root": "/p/payouts", "project_slug": PAYOUTS})
print(f"[2] after focus_on_expertise → {bound()}")
if (bound() or (None,))[0] != PAYOUTS:
    failures.append(f"focus_on_expertise did not bind the tab ({bound()})")

# 3. A plain ensure_auth (/status, /list, /end) answers without a Mindspace and never moves the tab.
post("ensure_auth", {"authenticated": True, "user_email": "a@x.in", "org_id": "o"})
print(f"[3] after a plain ensure_auth → {bound()}")
if (bound() or (None,))[0] != PAYOUTS:
    failures.append(f"a plain ensure_auth moved the tab ({bound()})")

# 4. The next tool call is stamped with the Mindspace the tab is focused on.
inj = pre("mindspace_skill", {"mode": "read"})
print(f"[4] mindspace_skill stamped session_id={inj.get('session_id')}")
if inj.get("session_id") != PAYOUTS:
    failures.append(f"a workspace call was stamped {inj.get('session_id')} instead of {PAYOUTS}")

print()
if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("ALL PASS — landing via ensure_auth(home) binds home; focus_on_expertise binds like switch_mindspace; a plain ensure_auth never moves the tab")
