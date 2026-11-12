"""While an ask_wingman runs, copy what it is doing into this tab's status line.

Spawned detached by statusline_capture's PreToolUse for ask_wingman (twin: wingman_progress_watch.js).
Polls the backend's /api/events/wingman-progress with the identity events token, writes each new
step — the Company Agent Directory, each Wingman checking itself, the Wingman being reached, its
answer — as the tab's in-flight label, and exits when the ask is done, the PostToolUse cleared the
in-flight label, or MAX_S passed. Any network or auth trouble: it exits and the label stays as it
was. stdlib only.

    python3 wingman_progress_watch.py <claude-session-id> <inflight-at-ms>
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statusline_capture as cap  # noqa: E402

POLL_S = 0.7
MAX_S = 150
TOKEN_PATH = os.path.join(cap.HOME, ".claude", "state", "catalyst-events-jwt.json")
_ENV_FILES = ([os.path.join(os.environ["CLAUDE_PLUGIN_ROOT"], ".env")] if os.environ.get("CLAUDE_PLUGIN_ROOT") else []) + [
    os.path.join(cap.HOME, "codeGen", "catalyst-plugin", ".env")]


def backend() -> str:
    url = (os.environ.get("CATALYST_BACKEND_URL") or "").strip()
    for path in _ENV_FILES:
        if url:
            break
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    k, _, v = line.strip().partition("=")
                    if k.strip() == "CATALYST_BACKEND_URL" and v.strip():
                        url = v.strip().strip("'\"")
        except Exception:
            pass
    return url.rstrip("/")


def token() -> str:
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            return str(json.load(f).get("events_jwt") or "")
    except Exception:
        return ""


def _inflight(session_id: str):
    try:
        with open(cap._path(session_id), encoding="utf-8") as f:
            return (json.load(f) or {}).get("inflight")
    except Exception:
        return None


def main(session_id: str, at: int) -> None:
    base, tok = backend(), token()
    if not base or not tok:
        return
    started, last = time.time(), None
    while time.time() - started < MAX_S:
        time.sleep(POLL_S)
        cur = _inflight(session_id)
        if not cur or cur.get("tool") != "ask_wingman" or int(cur.get("at") or 0) != at:
            return                                       # the call is over (or another one began)
        try:
            req = urllib.request.Request(f"{base}/api/events/wingman-progress",
                                         headers={"Authorization": f"Bearer {tok}"})
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8") or "{}")
        except Exception:
            continue
        if not data.get("id") or int(data["id"]) < at - 5000:
            continue                                     # an earlier ask — this one has not reported yet
        label = str(data.get("label") or "")
        if label and label != last:
            last = label

            def put(st, label=label):
                f = st.get("inflight") or {}
                if f.get("tool") == "ask_wingman" and int(f.get("at") or 0) == at:
                    f["label"] = label
            cap._update(session_id, put)
        if data.get("done"):
            return


if __name__ == "__main__":
    try:
        main(sys.argv[1], int(sys.argv[2]))
    except Exception:
        pass
