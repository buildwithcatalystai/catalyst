---
description: Your ToDos — what's waiting on you, what you asked others for.
argument-hint: "[mine | asked | mindspace | all]"
---

Show the user's ToDos from the shared ToDo list. If no Catalyst session is bound in this tab yet, call `mcp__catalyst-mcp__open_scratchpad` first (silently). Then call the `todos` workspace tool with `mode='list'` and `scope=$ARGUMENTS` (default `mine`; `all` = the whole company). Render one line per row, grouped by Mindspace — `title · kind · status (Pending / In Progress / Completed / Cancelled) · whose move it is · to/from · due` — never a number: a ToDo is named by its title and who it's with. End with the one thing you'd do next (answer the oldest clarification, close what came back, or nothing).
