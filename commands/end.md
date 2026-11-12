---
description: End the active Catalyst build session and clear the sentinel.
argument-hint: "[reason — optional]"
---

Call `mcp__catalyst-mcp__ensure_auth` then `mcp__catalyst-mcp__end` to cleanly close the active Catalyst session. Pass `$ARGUMENTS` as the reason if provided.

Confirm to the user that the session has ended and native tools are restored.
