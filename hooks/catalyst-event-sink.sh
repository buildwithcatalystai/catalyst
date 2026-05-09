#!/usr/bin/env bash
# Catalyst event-sink hook (stub for plugin v0.1).
#
# In v0.1 this hook is a no-op — plugin users won't see live ChatPane
# mirroring of Claude Code's turns in the wizard portal during a build.
# The build itself works correctly; only the live mirror is missing.
#
# In v0.2 this hook will POST the turn payload to:
#     ${CATALYST_BACKEND_URL}/api/hooks/turn
# which performs the same translation+persist work that
# `catalyst_mcp.hook_record` does today on the dev's machine.
#
# Always exits 0 so the user's Claude Code turn is never broken.
exit 0
