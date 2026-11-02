---
description: Check the Catalyst status line (the "⚡ catalyst …" line at the bottom of the terminal) and explain why it is or is not showing.
---

The user wants to know about the Catalyst status line — the `⚡ catalyst · …` line under the prompt that shows what their Wingman is doing (reaching a colleague's Wingman, learning expertise, recording memories).

Run this ONE shell command with the native Bash tool (it is read-only) and read its output:

```
sh "$(ls -d ~/.claude/plugins/cache/catalyst-aibuilder/catalyst/*/ 2>/dev/null | sort -V | tail -1)hooks/statusline_hook.sh" doctor; echo "--- claude $(claude --version 2>/dev/null | head -1) · plugin $(ls ~/.claude/plugins/cache/catalyst-aibuilder/catalyst/ 2>/dev/null | sort -V | tail -1)"
```

Then tell the user, in plain words and at most five lines, which of these it is:

1. **No `statusLine` anywhere** → the plugin's start-up hook has not run in a session on this machine yet. Start a new Claude Code session (or run `/clear`); the line appears from then on. If the plugin version printed is below 0.1.87, run `/plugin install catalyst@catalyst-aibuilder` first, then `/reload-plugins`.
2. **The winning `statusLine` is not Catalyst's** (another tool's, or a project-level entry) → that entry shadows ours. Catalyst keeps other lines: remove the shadowing entry from that file and start a new session; the other line is then shown after ours.
3. **"no runtime on this machine"** → the line needs `node` or `python3` with the developer tools. On a Mac: `xcode-select --install` (or install Node); on Windows: install Node. Then a new session.
4. **Everything present but the terminal shows nothing** → the status line is a terminal feature: it does not exist in the VS Code extension panel or the Desktop app; in a terminal, make sure the folder's trust dialog was accepted, then run `claude --debug` once and look for "Status line" in the debug log.
5. **The doctor renders a sample line** → the machinery works; the line is simply resting on this session's state. It updates as the Wingman reads skills and memories.

Do not change any settings yourself — describe the fix and let the user do it.
