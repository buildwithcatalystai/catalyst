# Catalyst — Claude Code plugin

Build apps via Catalyst from inside Claude Code. The plugin ships the
skill, the MCP-server pointer, and the tool-isolation hook. The
**catalyst backend + MCP server itself you self-host** on your own
machine; this plugin is the lightweight install that wires Claude Code
into them.

## Install

```sh
/plugin install ashwiny66/catalyst
```

Then, in the directory where you'll use Catalyst (or your home),
copy `.env.example` to `.env` and edit it:

```sh
cp .env.example .env
# edit .env to point at your self-hosted catalyst-mcp + catalyst-builder
```

## Configure

`.env` exposes two URLs:

| Variable | Default | What it is |
|---|---|---|
| `CATALYST_MCP_URL` | `http://localhost:9000/mcp` | Where catalyst-mcp listens |

Point this at wherever you ran `start.sh`. The MCP server handles the backend connection internally — no other URLs needed.

## Self-hosting the backend

The plugin assumes you already have catalyst-builder + catalyst-mcp
running. To set those up, see the catalyst-builder repo. The
short version:

```sh
git clone https://github.com/ashwiny66/catalyst-builder.git
cd catalyst-builder && ./start.sh
```

## Use

```sh
$ claude
> /catalyst:build a logistics tracker for last-mile drivers
```

On first call, Claude Code will trigger an OAuth flow against your
backend. A browser opens to your `CATALYST_BACKEND_URL`, you log in
(or sign up if it's the first run), Claude Code stores the JWT, and
the build proceeds.

## What's in the box

```
catalyst/
├── .claude-plugin/
│   └── plugin.json              # CC manifest: name, version, hook bindings
├── skills/catalyst/
│   ├── SKILL.md                 # router + 5-phase playbook + invariants
│   └── references/              # 01-bootstrap … 05-troubleshooting
├── hooks/
│   ├── catalyst-block-native.py # tool-isolation: blocks native Read/Edit/Write
│   │                              while a build is active
│   └── catalyst-event-sink.sh   # event mirror — stubbed in v0.1, see below
├── .mcp.json                    # MCP server pointer (uses CATALYST_MCP_URL)
├── .env.example                 # config template
└── README.md
```

## Known issues / v0.1 limitations

- **Event-sink hook is a no-op.** During a build you won't see live
  ChatPane mirroring in the wizard portal. The build itself runs
  correctly and reload/cold-load history works because catalyst-mcp
  persists everything server-side. Live-mirror returns in v0.2 once
  the backend exposes a `/api/hooks/turn` endpoint and the hook becomes
  a thin curl POST.

- **Single shared org per backend.** The current backend assumes one
  user per deployment. Multi-tenant support (multiple orgs sharing one
  hosted backend) is on the roadmap; for now, each user runs their own
  backend.

- **Mac + Linux only.** Hooks are bash scripts and a Python script.
  Windows isn't supported in v0.1.

## Troubleshooting

If Claude Code says "MCP server unreachable":

1. Check your backend is up: `curl ${CATALYST_BACKEND_URL}/api/healthz`
2. Check the MCP server is up: `curl ${CATALYST_MCP_URL}` (expect 401)
3. Check `.env` URLs match what `start.sh` printed when you launched the backend.

If Claude Code shows "requires re-authorization. Use /mcp.":

- Type `/mcp` in Claude Code's chat input. Pick `catalyst-mcp` and
  re-authorize. This is a Claude Code MCP-client behavior, not a plugin
  bug; the `/mcp` command is the manual escape hatch.

## Development

This plugin is content-only — Markdown, JSON, two short hook scripts.
No build step. To iterate:

```sh
git clone https://github.com/ashwiny66/catalyst.git
# edit files
/plugin reload catalyst   # in your Claude Code session
```

## License

MIT.
