#!/usr/bin/env python3
"""PreToolUse + PostToolUse hook — the python3 twin of statusline_capture.js, run by
`statusline_hook.sh` where node is absent. Same state record, same rules:

    recovered   skills, references, memories and DB Wiki reads brought back this session
    wingmen     the colleagues whose Wingmen were reached (name → last time)
    expertise   skill writes — the Curator "Learning expertise"
    memories    memory saves — the Curator "Recording memories"
    inflight    the call running right now (PreToolUse sets it, PostToolUse clears it)

Portable: no fcntl (Windows has none) — the record is replaced atomically instead,
as supermemory does. Always exits 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.path.join(HOME, ".catalyst-claude", "statusline", "state")
SCHEMA = 1

READ_SKILL = {"read", "list"}
WRITE_SKILL = {"write_skill", "write", "write_reference", "delete_reference"}
OWNER_LINE = re.compile(
    r"\*\*[^*\n]+\*\*[^\n]*?(?:from ([^\n]+?)'s Wingman|taught by ([^\n·—]+?))\s*[—-]+[^\n]*?read_org_skill\('([^']+)'", re.I)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _path(session_id: str) -> str:
    return os.path.join(STATE_DIR, hashlib.sha256(session_id.strip().encode()).hexdigest() + ".json")


def _bare(tool_name: str) -> str:
    name = tool_name.split("catalyst-mcp__", 1)[1] if "catalyst-mcp__" in tool_name else tool_name
    for ns in ("coding_workspace__", "analysis_workspace__", "union_workspace__"):
        if name.startswith(ns):
            name = name[len(ns):]
    return name


def _text(resp) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(_text(x) for x in resp)
    if isinstance(resp, dict):
        if isinstance(resp.get("content"), list):
            return "\n".join(_text(x) for x in resp["content"])
        for k in ("text", "result", "output", "message"):
            if isinstance(resp.get(k), (str, list, dict)):
                return _text(resp[k])
        try:
            return json.dumps(resp)
        except Exception:
            return str(resp)
    return str(resp)


def _looks_failed(text: str) -> bool:
    t = text.strip()[:160].lower()
    return t.startswith("error") or "has no skill yet" in t or t.startswith("no reference") or t.startswith("no memory")


def _fresh(session_id: str) -> dict:
    return {"version": SCHEMA, "session_id_sha": hashlib.sha256(session_id.encode()).hexdigest()[:12],
            "startedAt": _now_ms(), "updatedAt": _now_ms(), "user": "",
            "recovered": 0, "expertise": 0, "memories": 0, "inreach": 0,
            "wingmen": {}, "owners": {}, "inflight": None, "last_from": None, "last_learn": None}


def _update(session_id: str, fn) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    p = _path(session_id)
    try:
        with open(p, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("version") != SCHEMA:
            st = _fresh(session_id)
    except Exception:
        st = _fresh(session_id)
    fn(st)
    st["updatedAt"] = _now_ms()
    tmp = f"{p}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f)
    os.replace(tmp, p)


def _owner_for(st: dict, slug: str) -> str:
    return (st.get("owners") or {}).get(slug, "")


def _pre_label(st: dict, bare: str, args: dict):
    mode = str(args.get("mode") or "").lower()
    if bare == "enterprise_trusted_skills":
        return "reaching the company's Wingmen"
    if bare == "read_org_skill":
        who = _owner_for(st, str(args.get("mindspace") or ""))
        return f"reaching {who}'s Wingman" if who else "reaching a colleague's Wingman"
    if bare == "mindspace_skill":
        return "Learning expertise" if mode in WRITE_SKILL else "recalling this Mindspace's expertise"
    if bare == "mindspace_memory":
        return {"save": "Recording memories", "forget": "pruning a memory"}.get(mode, "recalling memories")
    if bare == "user_persona":
        return "Learning how you work" if mode.startswith("write") else "reading how you work"
    if bare == "evolve_skill":
        return "Learning expertise" if mode == "apply" else "Curator evolving expertise"
    if bare == "db_skill":
        return "reading the DB Wiki"
    if bare == "db_skill_upgrade":
        return "Learning expertise · DB Wiki"
    if bare in ("run_select_query", "run_python"):
        return "asking the warehouse"
    if bare == "save_prd":
        return "saving the PRD"
    if bare == "todos":
        return "on the ToDos"
    if bare == "external_tools_execute":
        app = str(args.get("toolkit") or args.get("app") or "").strip()
        return f"reaching {app}" if app else "reaching a connected tool"
    if bare in ("open_scratchpad", "start_analysis", "start_app_building", "start_spec", "switch_mindspace"):
        return "opening the Mindspace"
    return None


def _on_pre(st: dict, bare: str, args: dict) -> None:
    label = _pre_label(st, bare, args)
    st["inflight"] = {"label": label, "at": _now_ms(), "tool": bare} if label else None


def _learn(st: dict, counter: str, label: str) -> None:
    if counter:
        st[counter] = int(st.get(counter) or 0) + 1
    st["last_learn"] = {"label": label, "at": _now_ms()}


def _on_post(st: dict, bare: str, args: dict, resp) -> None:
    st["inflight"] = None
    text = _text(resp)
    mode = str(args.get("mode") or "").lower()
    ok = bool(text) and not _looks_failed(text)

    if bare in ("enterprise_trusted_skills", "mindspace_skill", "read_org_skill"):
        owners = st.setdefault("owners", {})
        n = 0
        for m in OWNER_LINE.finditer(text):
            who = (m.group(1) or m.group(2) or "").strip()
            if who and m.group(3):
                owners[m.group(3)] = who
            n += 1
        if bare == "enterprise_trusted_skills":
            st["inreach"] = n

    if bare == "read_org_skill" and ok:
        slug = str(args.get("mindspace") or "")
        who = _owner_for(st, slug)
        st["recovered"] = int(st.get("recovered") or 0) + 1
        st.setdefault("wingmen", {})[who or slug] = _now_ms()
        st["last_from"] = {"label": f"from {who}'s Wingman" if who else "from a colleague's Wingman", "at": _now_ms()}
    elif bare == "mindspace_skill":
        if mode in WRITE_SKILL and ok:
            _learn(st, "expertise", "learned expertise")
        elif mode in READ_SKILL and ok:
            st["recovered"] = int(st.get("recovered") or 0) + 1
    elif bare == "mindspace_memory":
        if mode == "save" and ok:
            _learn(st, "memories", "recorded a memory")
        elif mode == "forget" and ok:
            _learn(st, "", "forgot a memory")
        elif ok:
            n = 1 if args.get("name") else max(1, len(re.findall(r"^\s*- \[", text, re.M)))
            st["recovered"] = int(st.get("recovered") or 0) + n
    elif bare == "user_persona" and mode.startswith("write") and ok:
        _learn(st, "", "learned how you work")
    elif bare == "evolve_skill" and mode == "apply" and ok:
        _learn(st, "expertise", "evolved expertise")
    elif bare == "db_skill" and ok:
        st["recovered"] = int(st.get("recovered") or 0) + 1
        st["last_from"] = {"label": "from the DB Wiki", "at": _now_ms()}
    elif bare == "db_skill_upgrade" and ok:
        _learn(st, "expertise", "learned expertise · DB Wiki")
    elif bare in ("ensure_auth", "open_scratchpad", "current_session") and text:
        m = re.search(r'"display_name"\s*:\s*"([^"]{1,60})"', text) or re.search(r'"email"\s*:\s*"([^"@]{1,40})@', text)
        if m and not st.get("user"):
            st["user"] = m.group(1)


def main() -> int:
    try:
        raw = sys.stdin.read()
        ev = json.loads(raw) if raw.strip() else {}
        sid = str(ev.get("session_id") or "").strip()
        tool = str(ev.get("tool_name") or "")
        if not sid or "catalyst-mcp__" not in tool:
            return 0
        bare = _bare(tool)
        args = ev.get("tool_input") if isinstance(ev.get("tool_input"), dict) else {}
        hook = str(ev.get("hook_event_name") or "")
        if hook == "PreToolUse":
            _update(sid, lambda st: _on_pre(st, bare, args))
        elif hook == "PostToolUse":
            _update(sid, lambda st: _on_post(st, bare, args, ev.get("tool_response")))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
