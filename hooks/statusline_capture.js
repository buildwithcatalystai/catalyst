#!/usr/bin/env node
'use strict';
/**
 * PreToolUse + PostToolUse hook: turns each Catalyst tool call into the status
 * line's state (statusline/statusline.js renders it; statusline_install.js wires
 * it into Claude Code). One JSON record per Claude Code session under
 * ~/.catalyst-claude/statusline/state/:
 *
 *   recovered   skills, references, memories and DB Wiki reads brought back this session
 *   wingmen     the colleagues whose Wingmen were reached (name → last time)
 *   expertise   skill writes — the Curator "Learning expertise"
 *   memories    memory saves — the Curator "Recording memories"
 *   inflight    the call running right now (PreToolUse sets it, PostToolUse clears it)
 *   last_from / last_learn   the newest of each, for the rotating panes
 *
 * Whose Wingman a skill belongs to comes from the listings the Wingman already
 * reads (enterprise_trusted_skills and the footer on mindspace_skill reads:
 * "… · from <Name>'s Wingman — read: read_org_skill('<slug>')"), remembered per
 * session as slug → name. Registered in hooks.json with the matcher
 * `mcp__.*catalyst-mcp__.*` so it runs only for Catalyst tools. Node so that it
 * runs on Windows too (python3 is not a command there). Always exits 0.
 */
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOME = os.homedir();
const STATE_DIR = path.join(HOME, '.catalyst-claude', 'statusline', 'state');
const SCHEMA = 1;

const READ_SKILL = new Set(['read', 'list']);
const WRITE_SKILL = new Set(['write_skill', 'write', 'write_reference', 'delete_reference']);
// "**Name** · trust 0.91 · from Devin's Wingman — read: `read_org_skill('slug')`"  (legacy: "taught by Devin")
const OWNER_LINE = /\*\*[^*\n]+\*\*[^\n]*?(?:from ([^\n]+?)'s Wingman|taught by ([^\n·—]+?))\s*[—-]+[^\n]*?read_org_skill\('([^']+)'/gi;

const nowMs = () => Date.now();
const statePath = (sid) => path.join(STATE_DIR, crypto.createHash('sha256').update(sid.trim()).digest('hex') + '.json');

function bare(toolName) {
  let name = toolName.includes('catalyst-mcp__') ? toolName.split('catalyst-mcp__')[1] : toolName;
  for (const ns of ['coding_workspace__', 'analysis_workspace__', 'union_workspace__']) {
    if (name.startsWith(ns)) name = name.slice(ns.length);
  }
  return name;
}

/** The tool result as one string, whatever shape Claude Code hands us. */
function textOf(resp) {
  if (resp == null) return '';
  if (typeof resp === 'string') return resp;
  if (Array.isArray(resp)) return resp.map(textOf).join('\n');
  if (typeof resp === 'object') {
    if (Array.isArray(resp.content)) return resp.content.map(textOf).join('\n');
    for (const k of ['text', 'result', 'output', 'message']) {
      if (resp[k] != null && (typeof resp[k] === 'string' || typeof resp[k] === 'object')) return textOf(resp[k]);
    }
    try { return JSON.stringify(resp); } catch { return String(resp); }
  }
  return String(resp);
}

function looksFailed(text) {
  const t = text.trim().slice(0, 160).toLowerCase();
  return t.startsWith('error') || t.includes('has no skill yet') || t.startsWith('no reference') || t.startsWith('no memory');
}

function fresh(sid) {
  const t = nowMs();
  return { version: SCHEMA, session_id_sha: crypto.createHash('sha256').update(sid).digest('hex').slice(0, 12),
           startedAt: t, updatedAt: t, user: '', recovered: 0, expertise: 0, memories: 0, inreach: 0,
           wingmen: {}, owners: {}, inflight: null, last_from: null, last_learn: null };
}

/** Read-modify-write with an atomic replace (tmp + rename), as supermemory does. */
function update(sid, fn) {
  fs.mkdirSync(STATE_DIR, { recursive: true });
  const p = statePath(sid);
  let st;
  try { st = JSON.parse(fs.readFileSync(p, 'utf8')); if (!st || st.version !== SCHEMA) st = fresh(sid); } catch { st = fresh(sid); }
  fn(st);
  st.updatedAt = nowMs();
  const tmp = `${p}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(st), 'utf8');
  fs.renameSync(tmp, p);
}

const ownerFor = (st, slug) => (st.owners || {})[slug] || '';

function preLabel(st, name, args) {
  const mode = String(args.mode || '').toLowerCase();
  switch (name) {
    case 'enterprise_trusted_skills': return "reaching the company's Wingmen";
    case 'read_org_skill': { const who = ownerFor(st, String(args.mindspace || '')); return who ? `reaching ${who}'s Wingman` : "reaching a colleague's Wingman"; }
    case 'mindspace_skill': return WRITE_SKILL.has(mode) ? 'Learning expertise' : "recalling this Mindspace's expertise";
    case 'mindspace_memory': return mode === 'save' ? 'Recording memories' : mode === 'forget' ? 'pruning a memory' : 'recalling memories';
    case 'user_persona': return mode.startsWith('write') ? 'Learning how you work' : 'reading how you work';
    case 'evolve_skill': return mode === 'apply' ? 'Learning expertise' : 'Curator evolving expertise';
    case 'db_skill': return 'reading the DB Wiki';
    case 'db_skill_upgrade': return 'Learning expertise · DB Wiki';
    case 'run_select_query': case 'run_python': return 'asking the warehouse';
    case 'save_prd': return 'saving the PRD';
    case 'todos': return 'on the ToDos';
    case 'external_tools_execute': { const app = String(args.toolkit || args.app || '').trim(); return app ? `reaching ${app}` : 'reaching a connected tool'; }
    case 'open_scratchpad': case 'start_analysis': case 'start_app_building': case 'start_spec': case 'switch_mindspace': return 'opening the Mindspace';
    default: return null;
  }
}

function onPre(st, name, args) {
  const label = preLabel(st, name, args);
  st.inflight = label ? { label, at: nowMs(), tool: name } : null;
}

function learn(st, counter, label) {
  if (counter) st[counter] = (Number(st[counter]) || 0) + 1;
  st.last_learn = { label, at: nowMs() };
}

function onPost(st, name, args, resp) {
  st.inflight = null;
  const text = textOf(resp);
  const mode = String(args.mode || '').toLowerCase();
  const ok = Boolean(text) && !looksFailed(text);

  // Whose Wingman each skill is — from any listing that names them.
  if (name === 'enterprise_trusted_skills' || name === 'mindspace_skill' || name === 'read_org_skill') {
    st.owners = st.owners || {};
    let n = 0;
    for (const m of text.matchAll(OWNER_LINE)) {
      const who = (m[1] || m[2] || '').trim();
      if (who && m[3]) st.owners[m[3]] = who;
      n++;
    }
    if (name === 'enterprise_trusted_skills') st.inreach = n;
  }

  if (name === 'read_org_skill' && ok) {
    const slug = String(args.mindspace || '');
    const who = ownerFor(st, slug);
    st.recovered = (Number(st.recovered) || 0) + 1;
    st.wingmen = st.wingmen || {};
    st.wingmen[who || slug] = nowMs();
    st.last_from = { label: who ? `from ${who}'s Wingman` : "from a colleague's Wingman", at: nowMs() };
  } else if (name === 'mindspace_skill') {
    if (WRITE_SKILL.has(mode) && ok) learn(st, 'expertise', 'learned expertise');
    else if (READ_SKILL.has(mode) && ok) st.recovered = (Number(st.recovered) || 0) + 1;
  } else if (name === 'mindspace_memory') {
    if (mode === 'save' && ok) learn(st, 'memories', 'recorded a memory');
    else if (mode === 'forget' && ok) learn(st, '', 'forgot a memory');
    else if (ok) {
      const n = args.name ? 1 : Math.max(1, (text.match(/^\s*- \[/gm) || []).length);
      st.recovered = (Number(st.recovered) || 0) + n;
    }
  } else if (name === 'user_persona' && mode.startsWith('write') && ok) {
    learn(st, '', 'learned how you work');
  } else if (name === 'evolve_skill' && mode === 'apply' && ok) {
    learn(st, 'expertise', 'evolved expertise');
  } else if (name === 'db_skill' && ok) {
    st.recovered = (Number(st.recovered) || 0) + 1;
    st.last_from = { label: 'from the DB Wiki', at: nowMs() };
  } else if (name === 'db_skill_upgrade' && ok) {
    learn(st, 'expertise', 'learned expertise · DB Wiki');
  } else if ((name === 'ensure_auth' || name === 'open_scratchpad' || name === 'current_session') && text) {
    const m = text.match(/"display_name"\s*:\s*"([^"]{1,60})"/) || text.match(/"email"\s*:\s*"([^"@]{1,40})@/);
    if (m && !st.user) st.user = m[1];
  }
}

function readAll(timeoutMs = 3000) {
  return new Promise((resolve) => {
    let d = '';
    let done = false;
    const finish = () => { if (!done) { done = true; resolve(d); } };
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (c) => { d += c; });
    process.stdin.on('end', finish);
    process.stdin.on('error', finish);
    setTimeout(finish, timeoutMs);
  });
}

async function main() {
  try {
    const raw = await readAll();
    const ev = raw.trim() ? JSON.parse(raw) : {};
    const sid = String(ev.session_id || '').trim();
    const tool = String(ev.tool_name || '');
    if (!sid || !tool.includes('catalyst-mcp__')) return;
    const name = bare(tool);
    const args = ev.tool_input && typeof ev.tool_input === 'object' ? ev.tool_input : {};
    const hook = String(ev.hook_event_name || '');
    if (hook === 'PreToolUse') update(sid, (st) => onPre(st, name, args));
    else if (hook === 'PostToolUse') update(sid, (st) => onPost(st, name, args, ev.tool_response));
  } catch {
    // never disturb the tool call
  }
}

main().then(() => process.exit(0), () => process.exit(0));
