---
description: Your ToDos — what's waiting on you, what you asked others for.
argument-hint: "[mine | asked | mindspace | open]"
---

Show the user's ToDos from the shared ToDo list. If no Catalyst session is bound in this tab yet, call `mcp__catalyst-mcp__open_scratchpad` first (silently). Then call the `todos` workspace tool with `mode='list'` and `scope=$ARGUMENTS` (default `mine`). Render one line per row — `#number · kind · title · to/from · Mindspace · whose move it is` — and end with the one thing you'd do next (answer the oldest clarification, close what came back, or nothing).
