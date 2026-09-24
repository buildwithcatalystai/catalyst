"""External MCPs (any ``mcp__*`` that is not catalyst-mcp) follow the SAME switch as the
native FS/shell tools: denied only while the tab is in a Build mode (coding/vibe_code with a
Mindspace bound); open in menu, Analyst, PM and in a tab with no Mindspace bound.
v0.1.78 (user decision 2026-09-18: "even in PM mode all native tools open, only Engineering not").

History: 0.1.75/0.1.76 denied on the registry row alone and stranded a teammate on
2026-09-17 (Notion after ``switch_mindspace`` with no target); 0.1.77 keyed on the binding.
Runs the REAL hook as a subprocess against a throwaway $HOME (never touches the developer's
registry). stdlib only, <5s.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
CC = "tab-external-mcp-test"
SID = "MINDSPACE-10160a14"
EXTERNAL = "mcp__claude_ai_Notion__notion-fetch"

_home = tempfile.mkdtemp()
_env = {**os.environ, "HOME": _home}
(pathlib.Path(_home) / ".claude" / "state").mkdir(parents=True)


def pre(tool_name, tool_input=None):
    """Fire PreToolUse for an arbitrary tool; return 'allow' | 'deny'."""
    event = {"session_id": CC, "tool_name": tool_name, "tool_input": tool_input or {}}
    r = subprocess.run([sys.executable, str(HOOKS / "catalyst-block-native.py")],
                       input=json.dumps(event), capture_output=True, text=True, env=_env)
    if r.returncode == 2:
        return "deny"
    try:
        out = json.loads(r.stdout or "{}")
        if (out.get("hookSpecificOutput") or {}).get("permissionDecision") == "deny":
            return "deny"
    except Exception:
        pass
    return "allow"


def post(tool, response):
    event = {"session_id": CC, "hook_event_name": "PostToolUse",
             "tool_name": f"mcp__plugin_catalyst_catalyst-mcp__{tool}", "tool_input": {},
             "tool_response": [{"type": "text", "text": json.dumps(response)}]}
    subprocess.run([sys.executable, str(HOOKS / "hook_record.py")],
                   input=json.dumps(event), capture_output=True, text=True, env=_env)


def cat(tool):
    return f"mcp__plugin_catalyst_catalyst-mcp__{tool}"


failures = []
def check(step, got, want):
    print(f"[{step}] {got}  (want {want})")
    if got != want:
        failures.append(f"{step}: got {got}, want {want}")

# 0. No row at all: nothing to guard.
check("0 no row → external MCP", pre(EXTERNAL), "allow")

# 1. Row claimed by a lone health_check, nothing bound: still nothing to guard.
pre(cat("health_check"))
check("1 registered, unbound → external MCP", pre(EXTERNAL), "allow")
check("1 registered, unbound → native Read", pre("Read", {"file_path": "/x"}), "allow")

# 2. Bind a Mindspace in Build: external MCPs denied, native FS redirected.
post("start_app_building", {"session_id": SID, "app_root": "/p/x", "gen_stream_id": "g:1:2", "mode": "coding"})
check("2 bound (coding) → external MCP", pre(EXTERNAL), "deny")
check("2 bound (coding) → native Read", pre("Read", {"file_path": "/x"}), "deny")

# 3. The teammate's flow: switch_mindspace with no target clears the binding but keeps the row.
post("switch_mindspace", {"status": "ready_for_new", "paused": {"paused": True}, "pause_after_complete": True})
check("3 cleared via switch → external MCP", pre(EXTERNAL), "allow")
check("3 cleared via switch → native Read", pre("Read", {"file_path": "/x"}), "allow")

# 4. Bound in Analyst mode: natives AND external MCPs open (not a Build).
post("start_analysis", {"session_id": SID, "app_root": "/p/x", "gen_stream_id": "g:1:3", "mode": "deep_analysis"})
check("4 bound (deep_analysis) → native Read", pre("Read", {"file_path": "/x"}), "allow")
check("4 bound (deep_analysis) → external MCP", pre(EXTERNAL), "allow")

# 5. Bound in PM (Spec) mode: same — open.
post("start_spec", {"session_id": SID, "app_root": "/p/x", "gen_stream_id": "g:1:4", "mode": "spec"})
check("5 bound (spec) → native Read", pre("Read", {"file_path": "/x"}), "allow")
check("5 bound (spec) → external MCP", pre(EXTERNAL), "allow")

# 6. Back into a Build: both denied again; finishing the build (binding KEPT, mode=menu) reopens them.
post("start_app_building", {"session_id": SID, "app_root": "/p/x", "gen_stream_id": "g:1:5", "mode": "coding"})
check("6 bound (coding) → external MCP", pre(EXTERNAL), "deny")
post("complete_build", {"status": "completed", "already_completed": False, "pause_after_complete": True})
check("6 after complete_build → external MCP", pre(EXTERNAL), "allow")

# 7. `end` drops this tab's row: everything passes.
pre(cat("end"))
check("7 after end → external MCP", pre(EXTERNAL), "allow")

print()
if failures:
    for f in failures:
        print("FAIL:", f)
    sys.exit(1)
print("ALL PASS — external MCPs follow the Build switch: denied only in coding/vibe_code, open everywhere else")
