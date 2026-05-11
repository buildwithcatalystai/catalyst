#!/usr/bin/env bash
# Catalyst event-sink hook — PostToolUse + Stop.
#
# Ships every Claude Code coding-mode turn to the wizard backend:
#   • POSTs turn records to /api/events/record/{session_id} authenticated
#     by the events_jwt minted in start_coding/enter_coding_mode.
#   • Writes one structured entry+summary log-line pair per invocation to
#     ~/.claude/state/catalyst-event-sink.log (see hook_record.py for the
#     full log schema and CATALYST_HOOK_DEBUG=1 dump option).
#
# Always exits 0 so a hook failure never breaks the user's Claude Code turn.
#
# DEV NOTE: this hook depends on the catalyst_mcp Python package living
# in the developer's local codeGen tree at $HOME/codeGen/catalyst_mcp/.
# Plugin users without that tree get a no-op (the python -m fails fast
# with no log noise). Packaging catalyst_mcp into the plugin payload is
# tracked as follow-up work; until then, only the developer's box runs
# the hook meaningfully.

PYBIN="$HOME/.pyenv/versions/mcp-env/bin/python"
if [ ! -x "$PYBIN" ]; then
    PYBIN="$(command -v python3)"
fi

# catalyst_mcp + its deps (pi_agent_core_deep_v2, enterprise_ai_developer_v2,
# the wizard backend) all live in the user's codeGen tree. Mirror the same
# PYTHONPATH catalyst-mcp's mcp_server.py uses so the import works whether
# or not the user's shell has these set.
export PYTHONPATH="$HOME/codeGen/catalyst_mcp:$HOME/codeGen:$HOME/codeGen/pi_agent_core_deep_v2:$HOME/codeGen/catalyst-builder/backend${PYTHONPATH:+:$PYTHONPATH}"

# Pass stdin straight through; hook_record reads from stdin and resolves
# the active session via ~/.claude/state/catalyst-active-session.json.
# Suppress any import-time stderr so plugin users without the codegen tree
# don't see noise — the hook becomes a silent no-op for them.
exec "$PYBIN" -m catalyst_mcp.hook_record 2>/dev/null
