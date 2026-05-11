# Plugin packaging

How the plugin is published, installed, and discovered by CC. Source: [.claude-plugin/](../../../codeGen/catalyst-plugin/.claude-plugin/), [.mcp.json](../../../codeGen/catalyst-plugin/.mcp.json), [.env](../../../codeGen/catalyst-plugin/.env), [hooks/hooks.json](../../../codeGen/catalyst-plugin/hooks/hooks.json).

## Distribution

- **Repo**: `github.com/ashwiny66/catalyst` (public).
- **Plugin name**: `catalyst` (in `plugin.json`).
- **Marketplace name**: `catalyst-aibuilder` (in `marketplace.json`) — the namespace user types when installing.
- **Install command**: `/plugin install catalyst@catalyst-aibuilder` inside CC.
- **Resulting tool prefix**: `mcp__plugin_catalyst_catalyst-mcp__<tool>` (CC turns the `:` separator into `_`).

## Manifest files

### `plugin.json` ([.claude-plugin/plugin.json](../../../codeGen/catalyst-plugin/.claude-plugin/plugin.json))

```json
{
  "name": "catalyst",
  "version": "0.1.0",
  "description": "Build apps via Catalyst from inside Claude Code",
  "author": {"name": "ashwiny66", "url": "https://github.com/ashwiny66"},
  "homepage": "https://github.com/ashwiny66/catalyst",
  "repository": "https://github.com/ashwiny66/catalyst"
}
```

Required: `name`. Version is informational; CC pulls latest from git.

### `marketplace.json` ([.claude-plugin/marketplace.json](../../../codeGen/catalyst-plugin/.claude-plugin/marketplace.json))

Points the marketplace name at the git repo:

```json
{
  "name": "catalyst-aibuilder",
  "plugins": [{
    "name": "catalyst",
    "source": {"source": "url", "url": "https://github.com/ashwiny66/catalyst.git"}
  }]
}
```

## MCP registration

### `.mcp.json` ([.mcp.json](../../../codeGen/catalyst-plugin/.mcp.json))

```json
{
  "mcpServers": {
    "catalyst-mcp": {
      "type": "http",
      "url": "http://13.202.117.250:9000/mcp"
    }
  }
}
```

**HTTP, not stdio.** All tool calls go to the EC2-hosted wizard via HTTP. The server-side is `mcp_runner.py` in `catalyst-builder/`.

### Tool naming consequences

| Install path | Tool prefix |
|---|---|
| Direct (user puts `.mcp.json` in their config) | `mcp__catalyst-mcp__<tool>` |
| Plugin install | `mcp__plugin_catalyst_catalyst-mcp__<tool>` |

Plugin install prepends `plugin_<plugin-name>_`. CC mangles the `:` in the original namespace to `_`. The hooks pattern-match `catalyst-mcp__` substring for both.

## Hook registration

### `hooks/hooks.json` ([hooks/hooks.json](../../../codeGen/catalyst-plugin/hooks/hooks.json))

CC reads this on plugin load. Format:

```json
{
  "hooks": {
    "PreToolUse": [{"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/catalyst-block-native.py", "timeout": 5}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/hook_record.py", "timeout": 10}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/hook_record.py", "timeout": 10}]}]
  }
}
```

- `$CLAUDE_PLUGIN_ROOT` — env var CC sets when running the command. Points at the plugin's install dir (where the repo was cloned).
- `timeout` — seconds. If exceeded, CC kills the subprocess and proceeds as if it exited 0.
- The outer `[{"hooks": [...]}]` shape supports per-pattern filters, but the plugin doesn't use them — every fire calls the script.

## Slash commands ([commands/](../../../codeGen/catalyst-plugin/commands/))

Four user-facing commands, all thin wrappers that delegate to the `catalyst` skill:

| Command | Purpose |
|---|---|
| `/build <prompt>` | Build a new app from a one-liner |
| `/list` | List existing projects |
| `/status` | Status of active session |
| `/end` | End the active session |

Each is a markdown file with YAML frontmatter:

```
---
description: ...
argument-hint: "..."
---
Use the Catalyst skill to ...
```

CC surfaces these as `/catalyst:<name>` (registered under the plugin's namespace). They're conveniences — the underlying flow is always the same `mcp__catalyst-mcp__*` tools, driven by the skill.

## Embedded skill ([skills/catalyst/SKILL.md](../../../codeGen/catalyst-plugin/skills/catalyst/SKILL.md))

The plugin bundles its own user-facing skill (`catalyst:catalyst`) — the one users invoke via `/catalyst` or "build me an app". This is what drives the routing: auth → menu → brainstorm → coding. The hooks above are infrastructure; the skill is the agent's playbook.

This skill — `catalyst-plugin` — is a DIFFERENT skill, intended for **plugin developers and Catalyst maintainers**, not end users.

## `.env` discovery

Hooks don't inherit user shell env (CC spawns them fresh). `.env` files are the canonical config source.

### Discovery order ([hook_record.py:962](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L962))

First hit wins for each key:

1. **Process env** — user override (e.g. `export CATALYST_BACKEND_URL=...` before launching CC).
2. **`$CLAUDE_PLUGIN_ROOT/.env`** — plugin-committed defaults. Pointed at the public EC2 deployment.
3. **`~/codeGen/catalyst-plugin/.env`** — dev box working copy.
4. **`~/codeGen/catalyst-builder/backend/.env`** — wizard backend's env (same secret, same Supabase on dev).

### Resolved keys

| Key | Default | Used by |
|---|---|---|
| `CATALYST_BACKEND_URL` | `http://localhost:8000` (literal) / `http://13.202.117.250:8000` (.env) | `_resolve_backend_url`, becomes `{base}/api/events/record/{sid}` |
| `CATALYST_MCP_URL` | — (set in `.env`) | Reference only; `.mcp.json` is the actual MCP URL |
| `CATALYST_MCP_SECRET` | — | `_resolve_mcp_secret` (currently unused — auth is via events_jwt) |
| `CATALYST_HOOK_DEBUG` | unset | Toggles verbose payload dump in `_setup_debug_logger` |

### `_read_env_file` parsing ([hook_record.py:977](../../../codeGen/catalyst-plugin/hooks/hook_record.py#L977))

Naïve KEY=value parser. Strips surrounding quotes. Skips comments (`#`) and blank lines. No interpolation, no escaping.

## Install paths in practice

### On the user's box (after `/plugin install`)

```
~/.claude/plugins/<marketplace>/<plugin>/    ← $CLAUDE_PLUGIN_ROOT
├── hooks/hooks.json
├── hooks/catalyst-block-native.py
├── hooks/hook_record.py
├── commands/*.md
├── skills/catalyst/SKILL.md
├── .mcp.json
└── .env
```

### On the dev box (working copy)

```
~/codeGen/catalyst-plugin/        ← same layout
```

The discovery order means the dev box's `.env` works whether you've installed from marketplace or are running from the working copy.

## When to update this file

- `.mcp.json` URL changes (EC2 redeployed elsewhere).
- New `.env` key resolved.
- Discovery order changes.
- New slash command.
- Marketplace name changes.
