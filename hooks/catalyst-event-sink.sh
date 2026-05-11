#!/usr/bin/env bash
# Catalyst event-sink hook — PostToolUse + Stop.
#
# Ships every Claude Code coding-mode turn to the wizard backend:
#   • POSTs turn records to /api/events/record/{session_id} authenticated
#     by the events_jwt minted in start_coding/enter_coding_mode.
#   • Writes one structured entry+summary log-line pair per invocation to
#     ~/.claude/state/catalyst-event-sink.log (set CATALYST_HOOK_DEBUG=1
#     in the plugin's .env to also dump full payloads).
#
# Always exits 0 so a hook failure never breaks the user's Claude Code turn.
#
# Zero external dependencies — hook_record.py uses only Python stdlib
# (json, logging, urllib, …). Just point Python at the script and run.

# Prefer python3 from PATH; fall back to /usr/bin/python3 (macOS / most distros).
PYBIN="$(command -v python3 || echo /usr/bin/python3)"

# CLAUDE_PLUGIN_ROOT is set by Claude Code when invoking plugin-registered
# hooks. We use it directly so the script works wherever the plugin lives
# on the user's machine (cache vs marketplace vs custom install root).
exec "$PYBIN" "${CLAUDE_PLUGIN_ROOT}/hooks/hook_record.py" 2>/dev/null
