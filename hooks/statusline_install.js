#!/usr/bin/env node
'use strict';
/**
 * SessionStart hook: wire the Catalyst status line into Claude Code.
 *
 * - ~/.catalyst-claude/statusline-current → this plugin version's
 *   statusline/statusline.js (a symlink re-pointed every session, so the setting
 *   survives plugin updates without copying code). Where a symlink cannot be made
 *   (some Windows setups), the setting carries the renderer's absolute path with
 *   forward slashes instead — Claude Code runs status line commands through Git
 *   Bash on Windows, which eats unquoted backslashes — re-pointed every session.
 * - ~/.claude/settings.json `statusLine` → `node <that path>`, once. A status line
 *   that was already there (another plugin's, the user's own) is kept: its command
 *   is recorded in chain.json and the Catalyst renderer prints it after ours, so
 *   nothing the user had disappears. A user who later removes the entry is not
 *   fought — the `installed` sentinel means "install once". An earlier Catalyst
 *   entry (the python3 form) is updated in place.
 * - The session's state record is created, so the line reads "ready" before the
 *   first tool call; records older than 7 days are pruned.
 *
 * On the first install only, prints a systemMessage (shown to the user, adds nothing
 * to the model's context). Node so that it runs on Windows too.
 */
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOME = os.homedir();
const CAT_DIR = path.join(HOME, '.catalyst-claude');
const ROOT = path.join(CAT_DIR, 'statusline');
const STATE_DIR = path.join(ROOT, 'state');
const LINK = path.join(CAT_DIR, 'statusline-current');
const CHAIN_FILE = path.join(ROOT, 'chain.json');
const INSTALLED = path.join(ROOT, 'installed');
const SETTINGS = path.join(HOME, '.claude', 'settings.json');
const LINK_COMMAND = 'node ~/.catalyst-claude/statusline-current';
const SCHEMA = 1;

const rendererPath = () => path.resolve(__dirname, '..', 'statusline', 'statusline.js');
const fwd = (p) => p.replace(/\\/g, '/');

/** Point the stable symlink at this version's renderer; return the command the setting should run. */
function refreshLink() {
  const target = rendererPath();
  try {
    fs.mkdirSync(CAT_DIR, { recursive: true });
    let current = null;
    try { current = fs.readlinkSync(LINK); } catch {}
    if (current !== target) {
      try { fs.unlinkSync(LINK); } catch {}
      fs.symlinkSync(target, LINK, 'file');
    }
    if (fs.readlinkSync(LINK) === target) return LINK_COMMAND;
  } catch {}
  return `node "${fwd(target)}"`;
}

const isOurs = (cmd) => cmd.includes('catalyst-claude') || (cmd.includes('statusline') && cmd.includes('catalyst'));

/** Write the statusLine entry once. Returns installed · updated · present · kept · error. */
function installSetting(command) {
  try {
    let settings = {};
    if (fs.existsSync(SETTINGS)) settings = JSON.parse(fs.readFileSync(SETTINGS, 'utf8'));
    const current = settings.statusLine;
    const curCmd = current && typeof current === 'object' ? String(current.command || '') : '';
    const ours = isOurs(curCmd);
    if (ours && curCmd === command) return 'present';
    if (!ours && fs.existsSync(INSTALLED)) return 'kept';          // installed once before; the user removed it — respect that
    if (!ours && curCmd.trim()) {
      fs.mkdirSync(ROOT, { recursive: true });
      fs.writeFileSync(CHAIN_FILE, JSON.stringify({ command: curCmd, recorded_at: Math.floor(Date.now() / 1000) }), 'utf8');
    }
    settings.statusLine = { type: 'command', command, refreshInterval: 1 };
    fs.mkdirSync(path.dirname(SETTINGS), { recursive: true });
    const tmp = `${SETTINGS}.catalyst-tmp`;
    fs.writeFileSync(tmp, JSON.stringify(settings, null, 2) + '\n', 'utf8');
    fs.renameSync(tmp, SETTINGS);
    fs.mkdirSync(ROOT, { recursive: true });
    fs.writeFileSync(INSTALLED, new Date().toISOString(), 'utf8');
    return ours ? 'updated' : 'installed';
  } catch {
    return 'error';
  }
}

function touchState(sessionId) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    const sha = crypto.createHash('sha256').update(sessionId).digest('hex');
    const p = path.join(STATE_DIR, `${sha}.json`);
    if (!fs.existsSync(p)) {
      const now = Date.now();
      const st = { version: SCHEMA, session_id_sha: sha.slice(0, 12), startedAt: now, updatedAt: now, user: '',
                   recovered: 0, expertise: 0, memories: 0, inreach: 0, wingmen: {}, owners: {}, inflight: null, last_from: null, last_learn: null };
      fs.writeFileSync(`${p}.tmp`, JSON.stringify(st), 'utf8');
      fs.renameSync(`${p}.tmp`, p);
    }
    const cutoff = Date.now() - 7 * 86400 * 1000;
    for (const name of fs.readdirSync(STATE_DIR)) {
      const fp = path.join(STATE_DIR, name);
      try { if (fs.statSync(fp).mtimeMs < cutoff) fs.unlinkSync(fp); } catch {}
    }
  } catch {}
}

function readAll(timeoutMs = 3000) {
  return new Promise((resolve) => {
    let d = '';
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(d); } };
    if (process.stdin.isTTY) return finish();
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { d += c; });
    process.stdin.on('end', finish);
    process.stdin.on('error', finish);
    setTimeout(finish, timeoutMs);
  });
}

async function main() {
  let ev = {};
  try { const raw = await readAll(); ev = raw.trim() ? JSON.parse(raw) : {}; } catch { ev = {}; }
  const outcome = installSetting(refreshLink());
  const sid = String(ev.session_id || '').trim();
  if (sid) touchState(sid);
  // Claude Code re-runs a changed statusLine command right away, so the line usually
  // appears at once; say so once, to the person.
  if (outcome === 'installed') {
    process.stdout.write(JSON.stringify({ systemMessage: '⚡ Catalyst status line installed — look at the bottom of Claude Code (if it is not there yet, it will be on your next session).' }));
  } else if (outcome === 'error') {
    process.stdout.write(JSON.stringify({ systemMessage: '⚡ Catalyst could not set up its status line (settings.json unreadable or not writable) — run /catalyst:statusline for the details.' }));
  }
}

main().then(() => process.exit(0), () => process.exit(0));
