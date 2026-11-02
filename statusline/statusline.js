#!/usr/bin/env node
'use strict';
/**
 * The Catalyst status line for Claude Code — what your Wingman is doing behind the prompt.
 *
 * Claude Code runs this on every activity tick (and once a second when idle) with a
 * JSON object on stdin that carries the `session_id`. There is no running process:
 * the plugin's hooks write one small JSON record per session under
 * ~/.catalyst-claude/statusline/state/ (hooks/statusline_capture.js) and this script
 * prints one line from it — a pure function of (state, now), so the shimmer and the
 * pane rotation are choreographed by the clock, not by memory.
 *
 *   ⚡ catalyst ⠹ reaching Devin's Wingman          ← a tool call in flight
 *   ⚡ catalyst · 4 recovered · 2 Wingmen · 1 expertise learned · 3 memories recorded
 *   ⚡ catalyst · from Devin's Wingman 2m ago       ← panes rotate every 4 s
 *   ⚡ catalyst · learned expertise 5m ago
 *
 * Node, like supermemory's renderer and for the same reason: it is the one runtime a
 * Claude Code user reliably has on macOS, Linux AND Windows (python3 is not a command
 * on Windows). Reads stdin the way supermemory does — returns the moment the JSON
 * parses, never waits for EOF. If another status line was configured before Catalyst
 * installed itself (chain.json, written by hooks/statusline_install.js), its output is
 * appended after a divider. `--doctor` explains a blank line. Fails silent, always.
 */
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const HOME = os.homedir();
const ROOT = path.join(HOME, '.catalyst-claude', 'statusline');
const STATE_DIR = path.join(ROOT, 'state');
const CHAIN_FILE = path.join(ROOT, 'chain.json');
const LINK = path.join(HOME, '.catalyst-claude', 'statusline-current');
const SCHEMA = 1;

const INFLIGHT_TTL_MS = 120 * 1000;   // a PreToolUse with no PostToolUse (denied / crashed) stops spinning here
const PANE_TICKS = 4;                 // seconds a pane stays before the next
const EMPHASIS_TICKS = 2;             // seconds each tally part stays bold
const CREST_STRIDE = 3;               // letters the shimmer crest jumps per tick (coprime with "catalyst".length)
const STDIN_TIMEOUT_MS = 500;
const CHAIN_TIMEOUT_MS = 800;
const SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'];

// The site's violet (#6C4CF1, --primary) lifted to a mid tint so it clears both
// dark and light terminals; the crest of the shimmer runs to near-white.
const BASE = '\x1b[38;2;140;116;245m';
const MID = '\x1b[38;2;201;191;251m';
const HI = '\x1b[38;2;241;238;254m';
const WHITE = '\x1b[97m';
const GRAY = '\x1b[38;5;245m';
const BOLD = '\x1b[1m';
const RESET = '\x1b[0m';

function statePath(sessionId) {
  return path.join(STATE_DIR, crypto.createHash('sha256').update(sessionId.trim()).digest('hex') + '.json');
}

function readState(sessionId) {
  try {
    const st = JSON.parse(fs.readFileSync(statePath(sessionId), 'utf8'));
    return st && st.version === SCHEMA ? st : null;
  } catch {
    return null;
  }
}

function age(ms, now) {
  const s = Math.max(1, Math.floor((now - Number(ms)) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h`;
}

function shimmer(word, tick) {
  const crest = (tick * CREST_STRIDE) % word.length;
  let out = '';
  for (let i = 0; i < word.length; i++) {
    const d = Math.abs(i - crest);
    out += (d === 0 ? HI : d <= 2 ? MID : BASE) + word[i];
  }
  return out + RESET;
}

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function render(st, now) {
  const tick = Math.floor(now / 1000);
  const brand = `${BASE}${BOLD}⚡${RESET} ${BOLD}${shimmer('catalyst', tick)}${RESET}`;
  // A tab opened before the plugin (or its update) never ran the start-up hook and has
  // no record: still show the brand, resting — every tab carries the line, and the
  // tally fills in where the hooks run. Only a payload without a session id is blank.
  if (!st) return `${brand} ${WHITE}· ready${RESET}`;

  const inflight = st.inflight;
  if (inflight && inflight.at != null) {
    const dt = now - Number(inflight.at);
    if (dt >= 0 && dt < INFLIGHT_TTL_MS) {
      const spin = SPINNER[(tick * 3) % SPINNER.length];
      return `${brand} ${BASE}${spin}${RESET} ${WHITE}${inflight.label || 'working'}${RESET}`;
    }
  }

  const parts = [];
  if (Number(st.recovered) > 0) parts.push(`${st.recovered} recovered`);
  const wingmen = Object.keys(st.wingmen || {}).length;
  if (wingmen > 0) parts.push(plural(wingmen, 'Wingman', 'Wingmen'));
  if (Number(st.expertise) > 0) parts.push(`${st.expertise} expertise learned`);
  if (Number(st.memories) > 0) parts.push(plural(Number(st.memories), 'memory recorded', 'memories recorded'));
  if (parts.length === 0) return `${brand} ${WHITE}· ready${RESET}`;

  // Rotate real content: the tally, then live relative ages that tick upward.
  const panes = [null];
  if (st.last_from && st.last_from.at) panes.push(`${st.last_from.label || 'from a colleague'} ${age(st.last_from.at, now)} ago`);
  if (st.last_learn && st.last_learn.at) panes.push(`${st.last_learn.label || 'learned'} ${age(st.last_learn.at, now)} ago`);
  const pane = panes[Math.floor(tick / PANE_TICKS) % panes.length];
  if (pane) return `${brand} ${WHITE}·${RESET} ${WHITE}${pane}${RESET}`;

  const emph = Math.floor(tick / EMPHASIS_TICKS) % parts.length;
  const styled = parts.map((p, i) => (i === emph ? `${WHITE}${BOLD}${p}${RESET}` : `${GRAY}${p}${RESET}`));
  return `${brand} ${WHITE}·${RESET} ` + styled.join(`${GRAY} · ${RESET}`);
}

/** The status line that was there before Catalyst — still rendered, after ours. */
function chained(raw) {
  try {
    const cmd = String(JSON.parse(fs.readFileSync(CHAIN_FILE, 'utf8')).command || '').trim();
    if (!cmd || cmd.includes('catalyst-claude')) return '';
    const r = spawnSync(cmd, { shell: true, input: raw, timeout: CHAIN_TIMEOUT_MS, encoding: 'utf8' });
    return String(r.stdout || '').split('\n')[0].trim();
  } catch {
    return '';
  }
}

/** Resolve the moment the JSON parses — the pipe may stay open, and a renderer that
 *  waits for EOF idles to its deadline and can be cut off (a blank status line). */
function readStdin(timeoutMs = STDIN_TIMEOUT_MS) {
  return new Promise((resolve) => {
    if (process.stdin.isTTY) return resolve({ payload: {}, raw: '' });
    let data = '';
    let settled = false;
    let timer = null;
    const finish = (payload) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { process.stdin.pause(); if (typeof process.stdin.unref === 'function') process.stdin.unref(); } catch {}
      resolve({ payload, raw: data });
    };
    const tryParse = (final) => {
      const v = data.trim();
      if (!v) { if (final) finish({}); return; }
      try { finish(JSON.parse(v)); } catch { if (final) finish({}); }
    };
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { data += c; tryParse(false); });
    process.stdin.on('end', () => tryParse(true));
    process.stdin.on('error', () => finish({}));
    timer = setTimeout(() => tryParse(true), timeoutMs);
  });
}

const stripAnsi = (s) => s.replace(/\x1b\[[0-9;]*m/g, '');

/** `--doctor`: why is the line not showing? The four settings files in precedence
 *  order (managed › project local › project › user), the link, the state records,
 *  a sample render, the chain. Plain text, for a person to read. */
function doctor() {
  const lines = [`catalyst status line doctor · node ${process.version} · ${process.platform}`];
  const managed = { darwin: '/Library/Application Support/ClaudeCode/managed-settings.json',
                    linux: '/etc/claude-code/managed-settings.json',
                    win32: 'C:/Program Files/ClaudeCode/managed-settings.json' }[process.platform] || '';
  const cwd = process.cwd();
  const files = [['managed', managed], ['project local', path.join(cwd, '.claude', 'settings.local.json')],
                 ['project', path.join(cwd, '.claude', 'settings.json')], ['user', path.join(HOME, '.claude', 'settings.json')]];
  let winner = null;
  for (const [label, p] of files) {
    if (!p || !fs.existsSync(p)) { lines.push(`  ${label.padEnd(14)} ${p || '-'}: absent`); continue; }
    let d;
    try { d = JSON.parse(fs.readFileSync(p, 'utf8')); } catch (e) { lines.push(`  ${label.padEnd(14)} ${p}: UNREADABLE (${e.message})`); continue; }
    const sl = d.statusLine;
    const cmd = sl && typeof sl === 'object' ? String(sl.command || '') : '';
    const mark = cmd.includes('catalyst') ? 'catalyst' : cmd ? 'OTHER' : 'none';
    lines.push(`  ${label.padEnd(14)} ${p}: statusLine=${mark}${cmd ? ' → ' + cmd : ''}${d.disableAllHooks ? ' · disableAllHooks=true !' : ''}`);
    if (sl && winner === null) winner = [label, cmd];
  }
  if (winner) lines.push(`  → Claude Code runs the ${winner[0]} entry: ${winner[1]}${winner[1].includes('catalyst') ? '' : '   ← this shadows Catalyst\'s user-level entry'}`);
  else lines.push('  → no statusLine anywhere: the plugin\'s SessionStart hook has not run in a session yet (start a new session)');
  let linkLine = `  link           ${fs.existsSync(LINK) || isLink(LINK) ? LINK : 'MISSING ' + LINK}`;
  try { const t = fs.readlinkSync(LINK); linkLine += ` → ${t}`; if (!fs.existsSync(t)) lines.push('  ! the link\'s target does not exist (plugin dir moved?) — a new session re-points it'); } catch {}
  lines.push(linkLine);
  let states = [];
  try { states = fs.readdirSync(STATE_DIR).filter((n) => n.endsWith('.json')).map((n) => path.join(STATE_DIR, n)).sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs); } catch {}
  lines.push(`  state records  ${states.length} in ${STATE_DIR}`);
  if (states.length) {
    try {
      const st = JSON.parse(fs.readFileSync(states[0], 'utf8'));
      lines.push(`  newest record  updated ${age(st.updatedAt || 0, Date.now())} ago · recovered=${st.recovered} expertise=${st.expertise} memories=${st.memories}`);
      lines.push('  sample render  ' + stripAnsi(render(st, Date.now())));
    } catch (e) { lines.push(`  newest record  unreadable (${e.message})`); }
  }
  lines.push('  chain          ' + (fs.existsSync(CHAIN_FILE) ? fs.readFileSync(CHAIN_FILE, 'utf8').trim().slice(0, 120) : 'none'));
  lines.push("  if all of this looks right and the line is still blank: run `claude --debug` and look for 'Status line' in the debug log — it logs the exit code and stderr of the first invocation.");
  return lines.join('\n');
}

function isLink(p) { try { return fs.lstatSync(p).isSymbolicLink(); } catch { return false; } }

async function main() {
  if (process.argv.slice(2).includes('--doctor')) {
    try { process.stdout.write(doctor() + '\n'); } catch (e) { process.stdout.write(`doctor failed: ${e && e.message}\n`); }
    return;
  }
  try {
    const { payload, raw } = await readStdin();
    const sid = payload && typeof payload.session_id === 'string' ? payload.session_id : '';
    const ours = sid.trim() ? render(readState(sid), Date.now()) : '';
    const other = chained(raw);
    const line = !other ? ours : ours ? `${ours} ${GRAY}│${RESET} ${other}` : other;
    if (line) process.stdout.write(line, () => process.exit(0));
    else process.exit(0);
  } catch {
    process.exit(0);   // a status line must never disturb Claude Code
  }
}

if (require.main === module) main();

module.exports = { render, readState, age, shimmer, stripAnsi, SCHEMA };
