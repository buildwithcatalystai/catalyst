#!/usr/bin/env node
'use strict';
/**
 * While an ask_wingman runs, copy what it is doing into this tab's status line.
 *
 * Spawned detached by statusline_capture's PreToolUse for ask_wingman (twin:
 * wingman_progress_watch.py). Polls the backend's /api/events/wingman-progress with
 * the identity events token, writes each new step — the Company Agent Directory,
 * each Wingman checking itself, the Wingman being reached, its answer — as the
 * tab's in-flight label, and exits when the ask is done, the PostToolUse cleared
 * the in-flight label, or MAX_MS passed. Any network or auth trouble: it exits and
 * the label stays as it was.
 *
 *   node wingman_progress_watch.js <claude-session-id> <inflight-at-ms>
 */
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const POLL_MS = 700;
const MAX_MS = 150000;
const HOME = os.homedir();
const STATE_DIR = path.join(HOME, '.catalyst-claude', 'statusline', 'state');
const TOKEN_PATH = path.join(HOME, '.claude', 'state', 'catalyst-events-jwt.json');
const ENV_FILES = [
  ...(process.env.CLAUDE_PLUGIN_ROOT ? [path.join(process.env.CLAUDE_PLUGIN_ROOT, '.env')] : []),
  path.join(HOME, 'codeGen', 'catalyst-plugin', '.env'),
];

const statePath = (sid) => path.join(STATE_DIR, crypto.createHash('sha256').update(sid.trim()).digest('hex') + '.json');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function backend() {
  let url = String(process.env.CATALYST_BACKEND_URL || '').trim();
  for (const f of ENV_FILES) {
    if (url) break;
    try {
      for (const line of fs.readFileSync(f, 'utf8').split(/\r?\n/)) {
        const i = line.indexOf('=');
        if (i > 0 && line.slice(0, i).trim() === 'CATALYST_BACKEND_URL' && line.slice(i + 1).trim()) {
          url = line.slice(i + 1).trim().replace(/^['"]|['"]$/g, '');
        }
      }
    } catch { /* next */ }
  }
  return url.replace(/\/+$/, '');
}

function token() {
  try { return String(JSON.parse(fs.readFileSync(TOKEN_PATH, 'utf8')).events_jwt || ''); } catch { return ''; }
}

function readState(sid) {
  try { return JSON.parse(fs.readFileSync(statePath(sid), 'utf8')) || {}; } catch { return null; }
}

function putLabel(sid, at, label) {
  const p = statePath(sid);
  const st = readState(sid);
  const f = st && st.inflight;
  if (!f || f.tool !== 'ask_wingman' || Number(f.at || 0) !== at) return;
  f.label = label;
  st.updatedAt = Date.now();
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(st), 'utf8');
  fs.renameSync(tmp, p);
}

async function main(sid, at) {
  const base = backend();
  const tok = token();
  if (!base || !tok || typeof fetch !== 'function') return;
  const started = Date.now();
  let last = null;
  while (Date.now() - started < MAX_MS) {
    await sleep(POLL_MS);
    const st = readState(sid);
    const cur = st && st.inflight;
    if (!cur || cur.tool !== 'ask_wingman' || Number(cur.at || 0) !== at) return;   // the call is over
    let data;
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 3000);
      const r = await fetch(`${base}/api/events/wingman-progress`, { headers: { Authorization: `Bearer ${tok}` }, signal: ctl.signal });
      clearTimeout(timer);
      data = await r.json();
    } catch { continue; }
    if (!data || !data.id || Number(data.id) < at - 5000) continue;   // an earlier ask
    const label = String(data.label || '');
    if (label && label !== last) {
      last = label;
      try { putLabel(sid, at, label); } catch { /* the next poll */ }
    }
    if (data.done) return;
  }
}

main(String(process.argv[2] || ''), Number(process.argv[3] || 0)).then(() => process.exit(0), () => process.exit(0));
