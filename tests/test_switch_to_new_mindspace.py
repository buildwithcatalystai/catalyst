"""Regression guard: "start a new Mindspace" must actually start a new one.

The bug (fixed 2026-08-23): the PreToolUse hook stamps the CURRENT session_id
from the local registry into every Catalyst call — deliberately, so that on a
shared MCP host an agent can never wander into a Mindspace the user didn't
pick. The stage transitions (start_analysis / start_spec / start_app_building)
may fall back to an agent-supplied session_id ONLY when that local binding is
empty. So while a tab held a session, every "fresh Mindspace" attempt silently
CONTINUED the old one, and `switch_mindspace`'s own `next_step` ("call
start_app_building with NO session_id") was unfollowable — the hook re-stamped
it right after the agent omitted it. Observed in the wild as three attempts
across all three transitions, all reattaching to the same session_id
immediately after the switch reported `ready_for_new`.

The contract this locks down spans BOTH repos:
  server (catalyst_mcp/mcp_client.switch_project) returns `pause_after_complete`
  on the ready_for_new branch  →  plugin (hook_record._maybe_clear_local_state)
  clears this tab's session_id  →  the next transition is free to mint fresh.

Runs the REAL hook scripts as subprocesses against a throwaway $HOME, so it
never touches the developer's own registry. stdlib only, no network, <5s:
    ~/.pyenv/versions/mcp-env/bin/python tests/test_switch_to_new_mindspace.py
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
CC = "tab-switch-test"
OLD = "OLD-SESSION-b2f7cc3e"

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


def bound_session():
    """The session_id currently bound to this tab, or None."""
    p = _state / "catalyst-active-session.json"
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    for row in data.get("sessions", [data]):
        if row.get("claude_session_id") == CC or row.get("cc_session_id") == CC:
            return row.get("catalyst_session_id") or row.get("session_id")
    return None


failures = []

pre("health_check")                                    # tab claims its row
post("start_app_building", {"session_id": OLD, "app_root": "/p/old",
                            "gen_stream_id": "g:1:2", "mode": "coding"})
if bound_session() != OLD:
    failures.append(f"setup: expected bound to {OLD}, got {bound_session()}")
print(f"[1] bound to {bound_session()}")

# While bound, the sentinel MUST win — this is the multi-tenant guarantee, not
# the bug. The bug was that nothing ever released it.
if pre("start_analysis").get("session_id") != OLD:
    failures.append("while bound, the local session must be stamped (tenant safety)")
print("[2] transition while bound → old session stamped (correct: sentinel wins)")

# The switch's ready_for_new must RELEASE the binding.
post("switch_mindspace", {"status": "ready_for_new", "paused": {"paused": True},
                          "pause_after_complete": True})
released = bound_session()
print(f"[3] after switch(ready_for_new) → binding = {released}")
if released is not None:
    failures.append(f"switch did NOT release the binding (still {released}) — the bug")

# …so the next transition mints a NEW Mindspace instead of reattaching.
injected = pre("start_analysis")
print(f"[4] transition after switch → session_id {injected.get('session_id', '(omitted)')}")
if injected.get("session_id"):
    failures.append(f"transition reattached to {injected['session_id']} instead of minting fresh")

# The legitimate resume path must survive: with the binding empty, a transition
# may still honor an agent-named session (e.g. resuming from list_mindspaces).
if pre("start_analysis", {"session_id": "RESUME-ME"}).get("session_id") != "RESUME-ME":
    failures.append("agent-named resume broke (post-end resume would fork a new Mindspace)")
print("[5] agent-named resume still honored")

print()
if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("ALL PASS — switch releases the binding, fresh mints fresh, resume intact")
