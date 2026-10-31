"""While ask_wingman runs, the status line walks through what it is doing: the PreToolUse capture hook
spawns a watcher that polls /api/events/wingman-progress and copies each step into the tab's in-flight
label — in both twins (python, node). A fake backend serves the steps; the REAL hooks run as
subprocesses against a throwaway $HOME. stdlib only, ~10 s.

    python3 tests/test_wingman_progress_status_line.py
"""
import hashlib
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HOOKS = pathlib.Path(__file__).resolve().parent.parent / "hooks"
STEPS = ["searching the Company Agent Directory", "checking who holds trusted expertise",
         "each Wingman checking itself", "ankit.narayan's Wingman owns this expertise",
         "reaching ankit.narayan's Wingman", "ankit.narayan's Wingman answered"]


class _Backend(http.server.BaseHTTPRequestHandler):
    calls = 0
    auth = []

    def do_GET(self):  # noqa: N802
        _Backend.auth.append(self.headers.get("Authorization"))
        i = min(_Backend.calls, len(STEPS) - 1)
        _Backend.calls += 1
        body = {"active": True, "id": str(int(time.time() * 1000)), "label": STEPS[i], "done": i == len(STEPS) - 1}
        out = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def run(runtime: str) -> list:
    home = tempfile.mkdtemp()
    try:
        state_dir = pathlib.Path(home) / ".claude" / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "catalyst-events-jwt.json").write_text(json.dumps({"events_jwt": "tok-123"}))
        srv = http.server.HTTPServer(("127.0.0.1", 0), _Backend)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _Backend.calls, _Backend.auth = 0, []
        env = {**os.environ, "HOME": home, "CATALYST_BACKEND_URL": f"http://127.0.0.1:{srv.server_port}"}
        env.pop("CLAUDE_PLUGIN_ROOT", None)
        sid = f"cc-progress-{runtime}"
        ev = {"session_id": sid, "hook_event_name": "PreToolUse",
              "tool_name": "mcp__plugin_catalyst_catalyst-mcp__coding_workspace__ask_wingman",
              "tool_input": {"question": "how do we compute ev rent?"}}
        cmd = [sys.executable, str(HOOKS / "statusline_capture.py")] if runtime == "python" else \
              ["node", str(HOOKS / "statusline_capture.js")]
        subprocess.run(cmd, input=json.dumps(ev), text=True, env=env, timeout=10, check=True)
        path = pathlib.Path(home) / ".catalyst-claude" / "statusline" / "state" / (
            hashlib.sha256(sid.encode()).hexdigest() + ".json")
        seen = []
        for _ in range(120):
            time.sleep(0.1)
            try:
                label = (json.loads(path.read_text()).get("inflight") or {}).get("label")
            except Exception:
                continue
            if label and (not seen or seen[-1] != label):
                seen.append(label)
            if label == STEPS[-1]:
                break
        srv.shutdown()
        assert _Backend.auth and _Backend.auth[0] == "Bearer tok-123", _Backend.auth
        return seen
    finally:
        shutil.rmtree(home, ignore_errors=True)


def main() -> None:
    runtimes = ["python"] + (["node"] if shutil.which("node") else [])
    for rt in runtimes:
        seen = run(rt)
        assert seen[0] == STEPS[0], (rt, seen)            # the hook's own first line
        assert seen[-1] == STEPS[-1], (rt, seen)          # walked to the answer
        assert len(seen) >= 4, (rt, seen)                 # and through the steps on the way
        print(f"ok {rt}: {' → '.join(seen)}")


if __name__ == "__main__":
    main()
