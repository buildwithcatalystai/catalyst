---
description: Check the status of the current or most recent Catalyst build session.
argument-hint: "[session_id — optional, defaults to active session]"
---

Call `mcp__catalyst-mcp__ensure_auth` then `mcp__catalyst-mcp__current_session` to report the status of the active Catalyst build. If `$ARGUMENTS` contains a session ID, use that. Otherwise use the active sentinel session.

Report: session ID, phase, status, app name, and any pending question.
