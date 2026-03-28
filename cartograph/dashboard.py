"""
Local dashboard server for Cartograph.

Spins up a background HTTP server, serves a single-page registry browser,
and writes a PID file so it can be stopped later.
"""

import json
import os
import signal
import sys
import threading
import webbrowser
import http.server
import urllib.parse

_PID_DIR = os.path.join(os.path.expanduser("~"), ".cartograph")
_PID_FILE = os.path.join(_PID_DIR, "dashboard.pid")


_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cartograph</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/nim.min.js"></script>
<script>hljs.configure({ignoreUnescapedHTML: true});</script>
<style>
  /* Override hljs background to match our theme */
  .hljs { background: var(--surface) !important; padding: 0 !important; }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:        #0d1117;
    --surface:   #161b22;
    --surface2:  #1c2128;
    --border:    #30363d;
    --text:      #e6edf3;
    --muted:     #8b949e;
    --blue:      #58a6ff;
    --green:     #3fb950;
    --orange:    #d29922;
    --red:       #f85149;
    --purple:    #bc8cff;
  }

  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 14px; }

  /* ── Nav ── */
  nav {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 24px;
    height: 54px;
    display: flex;
    align-items: center;
    gap: 16px;
    position: sticky;
    top: 0;
    z-index: 100;
  }
  .nav-logo { font-weight: 700; font-size: 18px; color: var(--text); letter-spacing: -0.5px; cursor: pointer; flex-shrink: 0; }
  .nav-logo em { color: var(--blue); font-style: normal; }


  .nav-tabs { display: flex; gap: 0; margin-left: 24px; height: 100%; }
  .nav-tab {
    padding: 0 16px; height: 100%; display: flex; align-items: center; gap: 6px;
    font-size: 14px; color: var(--muted); cursor: pointer;
    border: none; background: none; border-bottom: 2px solid transparent;
    transition: color 0.1s;
  }
  .nav-tab:hover { color: var(--text); }
  .nav-tab.active { color: var(--text); border-bottom-color: var(--orange); font-weight: 500; }

  .nav-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; margin-left: auto; }

  .btn {
    background: var(--surface2);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--muted);
    padding: 5px 12px;
    font-size: 13px;
    cursor: pointer;
    display: flex; align-items: center; gap: 5px;
    transition: color 0.1s, border-color 0.1s;
  }
  .btn:hover { color: var(--text); border-color: var(--muted); }
  .btn.refreshing { animation: spin 0.6s linear infinite; }


  .tab-badge {
    background: var(--border);
    color: var(--muted);
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 10px;
  }
  .nav-tab.active .tab-badge { background: #1f6feb44; color: var(--blue); }

  /* ── Content ── */
  .content { max-width: 960px; margin: 0 auto; padding: 24px; }

  /* ── Search view ── */
  .search-bar {
    max-width: 520px;
    position: relative;
    margin-bottom: 24px;
  }
  .search-bar input {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px 12px 40px;
    color: var(--text);
    font-size: 16px;
    outline: none;
    transition: border-color 0.15s;
  }
  .search-bar input:focus { border-color: var(--blue); }
  .search-bar input::placeholder { color: var(--muted); }
  .search-bar-icon {
    position: absolute; left: 14px; top: 50%; transform: translateY(-50%);
    color: var(--muted); font-size: 16px; pointer-events: none;
  }

  /* ── Filters ── */
  .filters {
    display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center;
  }
  .filter-chip {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 4px 12px;
    font-size: 12px;
    color: var(--muted);
    cursor: pointer;
    transition: all 0.1s;
  }
  .filter-chip:hover { color: var(--text); border-color: var(--muted); }
  .filter-chip.active { color: var(--blue); border-color: var(--blue); background: #58a6ff11; }
  .filter-label { font-size: 12px; color: var(--muted); margin-right: 4px; }

  /* ── Widget list ── */
  .widget-list { display: flex; flex-direction: column; }
  .widget-card {
    padding: 16px 0;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background 0.1s;
  }
  .widget-card:first-child { border-top: 1px solid var(--border); }
  .widget-card:hover { background: var(--surface); margin: 0 -12px; padding: 16px 12px; border-radius: 6px; border-color: transparent; }
  .widget-card:hover + .widget-card { border-top-color: transparent; }
  .widget-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
  .widget-name { font-size: 15px; font-weight: 600; color: var(--blue); }
  .widget-owner { font-size: 13px; color: var(--muted); }
  .widget-version { font-size: 12px; color: var(--muted); background: var(--surface2); padding: 1px 6px; border-radius: 4px; }
  .widget-desc { font-size: 13px; color: var(--muted); line-height: 1.5; margin-bottom: 8px; max-width: 700px; }
  .widget-meta { display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--muted); flex-wrap: wrap; }

  .lang-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
  .lang-python     { background: #3572A5; }
  .lang-javascript { background: #f1e05a; }
  .lang-typescript { background: #2b7489; }
  .lang-nim        { background: #ffc200; }
  .lang-unknown    { background: var(--muted); }

  .domain-tag {
    font-size: 11px;
    padding: 1px 7px;
    border-radius: 10px;
    border: 1px solid var(--border);
    color: var(--muted);
  }

  .sync-badge {
    font-size: 11px; padding: 2px 8px; border-radius: 10px;
    border: 1px solid; font-weight: 500; white-space: nowrap;
  }
  .sync-local    { color: var(--blue);   border-color: #58a6ff55; background: #58a6ff11; }
  .sync-cloud    { color: var(--purple); border-color: #bc8cff55; background: #bc8cff11; }
  .sync-published   { color: var(--green);  border-color: #3fb95055; background: #3fb95011; }
  .sync-mismatch { color: var(--orange); border-color: #d2992255; background: #d2992211; }

  .vis-badge {
    font-size: 11px; padding: 1px 6px; border-radius: 4px;
  }
  .vis-public  { color: var(--green); background: #3fb95015; }
  .vis-private { color: var(--orange); background: #d2992215; }
  .vis-local   { color: var(--blue); background: #4a9eff15; }
  .vis-cloud   { color: var(--purple); background: #bc8cff15; }
  .vis-mismatch { color: var(--orange); background: #d2992215; }

  /* ── Detail view ── */
  .detail-back {
    font-size: 13px; color: var(--blue); cursor: pointer; margin-bottom: 16px;
    display: inline-flex; align-items: center; gap: 4px;
  }
  .detail-back:hover { text-decoration: underline; }
  .detail-title { font-size: 24px; font-weight: 600; margin-bottom: 4px; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .detail-owner { font-size: 15px; color: var(--muted); margin-bottom: 16px; }
  .detail-desc { font-size: 15px; color: var(--text); line-height: 1.6; margin-bottom: 24px; max-width: 700px; }

  .detail-grid {
    display: grid;
    grid-template-columns: 1fr 280px;
    gap: 24px;
    align-items: start;
  }
  @media (max-width: 768px) { .detail-grid { grid-template-columns: 1fr; } }

  .detail-main { min-width: 0; }
  .detail-sidebar {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }
  .detail-sidebar h3 { font-size: 12px; text-transform: uppercase; color: var(--muted); letter-spacing: 0.5px; margin-bottom: 10px; }
  .detail-meta-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
  .detail-meta-row:last-child { border-bottom: none; }
  .detail-meta-label { color: var(--muted); }
  .detail-meta-value { color: var(--text); font-weight: 500; }

  .install-cmd {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px 14px;
    font-family: monospace;
    font-size: 13px;
    color: var(--green);
    margin-top: 12px;
    cursor: pointer;
    position: relative;
    transition: border-color 0.1s;
  }
  .install-cmd:hover { border-color: var(--green); }
  .install-cmd .copy-hint {
    position: absolute; right: 10px; top: 50%; transform: translateY(-50%);
    font-size: 11px; color: var(--muted); font-family: -apple-system, sans-serif;
  }

  .tags-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
  .tag { background: #1f6feb22; color: var(--blue); font-size: 12px; padding: 2px 8px; border-radius: 12px; }

  .detail-section { margin-bottom: 24px; }
  .detail-section h3 { font-size: 14px; font-weight: 600; margin-bottom: 10px; color: var(--text); }

  .review-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    margin-bottom: 8px;
  }
  .review-score { color: var(--orange); font-weight: 600; margin-bottom: 4px; }
  .review-comment { font-size: 13px; color: var(--muted); }

  /* ── Empty / loading ── */
  .empty { text-align: center; padding: 60px 0; color: var(--muted); }
  .empty-title { font-size: 16px; margin-bottom: 6px; color: var(--text); }
  .empty-sub { font-size: 13px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { width: 20px; height: 20px; border: 2px solid var(--border); border-top-color: var(--blue); border-radius: 50%; animation: spin 0.7s linear infinite; margin: 0 auto 12px; }

  .results-count { font-size: 13px; color: var(--muted); margin-bottom: 12px; }

  /* ── Code viewer (stacked) ── */
  .file-block { margin-bottom: 16px; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  .file-header {
    background: var(--surface2);
    border-bottom: 1px solid var(--border);
    padding: 6px 12px;
    font-size: 13px;
    font-family: "SF Mono", "Fira Code", monospace;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .file-header-name { color: var(--text); font-weight: 500; }
  .file-header-dir { color: var(--muted); }
  pre.code-block {
    background: var(--surface);
    padding: 12px 16px;
    margin: 0;
    overflow-x: auto;
    font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace;
    font-size: 13px;
    line-height: 1.55;
    color: var(--text);
    tab-size: 4;
  }
  pre.code-block code { background: none !important; padding: 0 !important; font-size: inherit; line-height: inherit; font-family: inherit; }

  /* Files section full-width below the grid */
  .detail-files-full {
    margin-top: 24px;
  }

  /* ── Profile header ── */
  .profile-header {
    display: flex;
    align-items: center;
    gap: 16px;
    margin-bottom: 24px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }
  .profile-avatar {
    width: 56px; height: 56px;
    border-radius: 50%;
    background: var(--surface2);
    border: 2px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    font-size: 24px; font-weight: 600; color: var(--blue);
    flex-shrink: 0;
  }
  .profile-info { flex: 1; min-width: 0; }
  .profile-name { font-size: 20px; font-weight: 600; margin-bottom: 2px; }
  .profile-handle { font-size: 14px; color: var(--muted); }
  .profile-stats {
    display: flex; gap: 20px; margin-top: 6px;
    font-size: 13px; color: var(--muted);
  }
  .profile-stat strong { color: var(--text); font-weight: 600; }

  /* ── Responsive ── */
  @media (max-width: 640px) {
    .content { padding: 16px; }
    .nav-tabs { margin-left: 12px; }
    .profile-header { flex-direction: column; text-align: center; }
    .profile-stats { justify-content: center; }
  }
</style>
</head>
<body>

<nav>
  <span class="nav-logo" onclick="navigate('profile')"><em>&#9674;</em> Cartograph</span>
  <div class="nav-tabs">
    <button class="nav-tab active" data-view="profile">Profile <span class="tab-badge" id="badge-my">0</span></button>
    <button class="nav-tab" data-view="search">Search</button>
  </div>
  <div class="nav-right">
    <button class="btn" id="refresh-btn" title="Refresh data">&#8635; Refresh</button>
  </div>
</nav>

<div class="content" id="content">
  <div class="empty"><div class="spinner"></div>Loading...</div>
</div>

<script>
// ── State ──
let currentView = 'profile';
let searchQuery = '';
let searchResults = [];
let searchDomain = '';
let searchLang = '';
let myWidgets = [];
let whoamiData = {};
let detailWidget = null;
let isSearching = false;
let viewingProfile = null;  // null = own profile, string = other user's handle

// ── Language helpers ──
function langClass(lang) {
  const l = (lang||'unknown').toLowerCase();
  if (l === 'python') return 'lang-python';
  if (l === 'javascript' || l === 'js') return 'lang-javascript';
  if (l === 'typescript' || l === 'ts') return 'lang-typescript';
  if (l === 'nim') return 'lang-nim';
  return 'lang-unknown';
}

function stars(n) {
  if (!n) return '';
  const full = Math.floor(n);
  let s = '';
  for (let i = 0; i < full; i++) s += '&#9733;';
  if (n - full >= 0.5) s += '&#9734;';
  return s;
}

// ── Navigation ──
function navigate(view, data) {
  if (view === 'detail') {
    detailWidget = data;
    detailFiles = null;
    const wid = data.id || data.name;
    if (wid) loadDetailFiles(wid, data.owner || '');
  } else if (view === 'user') {
    // Viewing another user's profile
    viewingProfile = data;
    detailWidget = null;
    detailFiles = null;
    loadUserWidgets(data);
    currentView = 'profile';
  } else {
    if (view === 'profile') viewingProfile = null;
    detailWidget = null;
    detailFiles = null;
  }
  if (view !== 'user') currentView = view;

  // Update nav tabs
  const src = detailWidget ? (detailWidget._source || 'profile') : 'profile';
  const tabView = currentView === 'detail' ? src : currentView;
  document.querySelectorAll('.nav-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.view === tabView);
  });

  render();
}

// Load another user's public widgets
let userWidgets = [];
async function loadUserWidgets(owner) {
  userWidgets = [];
  render();
  try {
    const res = await fetch(`/api/search?q=*&owner=${encodeURIComponent(owner)}`);
    const data = await res.json();
    userWidgets = (data.widgets || []).map(w => ({
      ...w,
      id: w.id || (w.namespaced_id || '').replace(/^@[^/]+\//, ''),
    }));
  } catch {
    userWidgets = [];
  }
  render();
}

function viewUserProfile(owner) {
  navigate('user', owner);
}

// ── Tab clicks ──
document.querySelectorAll('.nav-tab').forEach(btn => {
  btn.addEventListener('click', () => navigate(btn.dataset.view));
});

// ── Refresh ──
document.getElementById('refresh-btn').addEventListener('click', async () => {
  const btn = document.getElementById('refresh-btn');
  btn.style.pointerEvents = 'none';
  btn.textContent = '... Refreshing';
  await loadMyWidgets();
  if (searchQuery) await doSearch();
  btn.innerHTML = '&#8635; Refresh';
  btn.style.pointerEvents = '';
  render();
});

// ── Search ──
async function doSearch() {
  isSearching = true;
  render();
  const params = new URLSearchParams({ q: searchQuery });
  if (searchDomain) params.set('domain', searchDomain);
  if (searchLang) params.set('language', searchLang);
  try {
    const [cloudRes, localRes] = await Promise.all([
      fetch('/api/search?' + params).then(r => r.json()).catch(() => ({widgets:[]})),
      fetch('/api/search-local?' + params).then(r => r.json()).catch(() => ({widgets:[]})),
    ]);
    const seen = new Set();
    const merged = [];
    for (const w of (localRes.widgets || [])) {
      if (!seen.has(w.id)) { seen.add(w.id); merged.push(w); }
    }
    for (const w of (cloudRes.widgets || [])) {
      const baseId = w.id || (w.namespaced_id || '').replace(/^@[^/]+\//, '');
      if (!seen.has(baseId)) { seen.add(baseId); merged.push({...w, id: baseId}); }
    }
    searchResults = merged;
  } catch {
    searchResults = [];
  }
  isSearching = false;
  render();
}

// ── Widget card HTML ──
function widgetCard(w, opts = {}) {
  const lang = (w.language || 'unknown').toLowerCase();
  const owner = w.owner || '';
  const ver = w.version || w._localVersion || w._cloudVersion || '';
  const installs = w.install_count || 0;
  const vis = w.visibility || 'public';

  let badges = '';
  if (opts.showSync && w._sync) {
    const syncLabels = {
      local: 'Local only', cloud: 'Cloud only', published: 'Published',
      mismatch: `v${w._localVersion||'?'} &#8594; v${w._cloudVersion||'?'}`
    };
    const syncClasses = { local: 'sync-local', cloud: 'sync-cloud', published: 'sync-published', mismatch: 'sync-mismatch' };
    badges += `<span class="sync-badge ${syncClasses[w._sync]}">${syncLabels[w._sync]}</span>`;
  }
  if (vis === 'private') badges += `<span class="vis-badge vis-private">private</span>`;

  return `<div class="widget-card" onclick="viewDetail(${JSON.stringify(w).replace(/"/g,'&quot;').replace(/'/g,'&#39;')}, '${opts.source||'library'}')">
    <div class="widget-header">
      <span class="widget-name">${esc(w.id || w.name || '?')}</span>
      ${owner ? `<span class="widget-owner" onclick="event.stopPropagation();viewUserProfile('${esc(owner)}')" style="cursor:pointer">@${esc(owner)}</span>` : ''}
      ${ver ? `<span class="widget-version">v${esc(ver)}</span>` : ''}
      ${badges}
    </div>
    ${w.description ? `<div class="widget-desc">${esc(w.description)}</div>` : ''}
    <div class="widget-meta">
      <span><span class="lang-dot ${langClass(lang)}"></span> ${esc(lang)}</span>
      ${w.domain ? `<span class="domain-tag">${esc(w.domain)}</span>` : ''}
      ${installs ? `<span>${installs} install${installs!==1?'s':''}</span>` : ''}
      ${w.rating ? `<span>${stars(w.rating)} ${w.rating.toFixed(1)}</span>` : ''}
    </div>
  </div>`;
}

function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function viewDetail(w, source) {
  w._source = source;
  navigate('detail', w);
}

// ── Render ──
function render() {
  const el = document.getElementById('content');

  if (currentView === 'detail' && detailWidget) {
    el.innerHTML = renderDetail(detailWidget);
    if (typeof hljs !== 'undefined') hljs.highlightAll();
    return;
  }

  if (currentView === 'profile') {
    el.innerHTML = renderProfile();
    bindProfileEvents();
    return;
  }

  if (currentView === 'search') {
    el.innerHTML = renderSearch();
    bindSearchEvents();
    return;
  }
}

// ── Profile view (home) ──
function renderProfile() {
  const isOwnProfile = !viewingProfile;
  const widgets = isOwnProfile ? myWidgets : userWidgets;
  const handle = isOwnProfile
    ? (whoamiData.owner || whoamiData.email || '')
    : viewingProfile;

  let html = '';

  // Profile header
  html += `<div class="profile-header">`;
  const initial = (handle || '?')[0].toUpperCase();
  html += `<div class="profile-avatar">${esc(initial)}</div>`;
  html += `<div class="profile-info">`;

  if (isOwnProfile && !whoamiData.authenticated) {
    html += `<div class="profile-name">Local Library</div>`;
    html += `<div class="profile-handle">Not signed in</div>`;
  } else if (isOwnProfile) {
    html += `<div class="profile-name">@${esc(handle)}</div>`;
    html += `<div class="profile-handle">Your widgets</div>`;
  } else {
    html += `<div class="profile-name">@${esc(handle)}</div>`;
    html += `<div class="profile-handle" style="cursor:pointer;color:var(--blue)" onclick="navigate('profile')">&#8592; Back to your profile</div>`;
  }

  // Stats
  const localCount = widgets.filter(w => w._sync === 'local').length;
  const pubCount = widgets.filter(w => w._sync === 'published' || w._sync === 'mismatch' || w._sync === 'cloud').length;
  const domains = [...new Set(widgets.map(w => w.domain).filter(Boolean))];

  html += `<div class="profile-stats">`;
  html += `<span><strong>${widgets.length}</strong> widget${widgets.length!==1?'s':''}</span>`;
  if (isOwnProfile && localCount) html += `<span><strong>${localCount}</strong> local</span>`;
  if (pubCount) html += `<span><strong>${pubCount}</strong> published</span>`;
  html += `<span><strong>${domains.length}</strong> domain${domains.length!==1?'s':''}</span>`;
  html += `</div>`;

  html += `</div>`; // profile-info
  html += `</div>`; // profile-header

  if (!widgets.length) {
    if (isOwnProfile) {
      html += `<div class="empty">
        <div class="empty-title">No widgets yet</div>
        <div class="empty-sub">Create one with <code>cartograph create</code> or search the registry to install one</div>
      </div>`;
    } else {
      html += `<div class="empty">
        <div class="empty-title">No public widgets</div>
        <div class="empty-sub">@${esc(handle)} hasn't published any widgets yet</div>
      </div>`;
    }
    return html;
  }

  const allDomains = [...new Set(widgets.map(w => w.domain).filter(Boolean))].sort();
  const allLangs = [...new Set(widgets.map(w => (w.language||'').toLowerCase()).filter(Boolean))].sort();

  // Filter bar
  html += `<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap">`;
  html += `<input type="search" id="profile-search" placeholder="Filter widgets..." style="
    background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;
    color:var(--text);font-size:13px;width:240px;outline:none;
  " />`;
  if (isOwnProfile) {
    const counts = { all: widgets.length, local: localCount, published: pubCount };
    html += `<div class="filters" style="margin-bottom:0">
      <span class="filter-chip active" data-statusfilter="all">All <strong>${counts.all}</strong></span>
      <span class="filter-chip" data-statusfilter="local">Local <strong>${counts.local}</strong></span>
      <span class="filter-chip" data-statusfilter="published">Published <strong>${counts.published}</strong></span>
    </div>`;
  }
  html += `</div>`;

  if (allDomains.length > 1 || allLangs.length > 1) {
    html += `<div class="filters">`;
    if (allDomains.length > 1) {
      html += `<span class="filter-label">Domain:</span>`;
      html += `<span class="filter-chip active" data-domainfilter="">All</span>`;
      allDomains.forEach(d => { html += `<span class="filter-chip" data-domainfilter="${esc(d)}">${esc(d)}</span>`; });
    }
    if (allLangs.length > 1) {
      html += `<span class="filter-label" style="margin-left:12px">Language:</span>`;
      html += `<span class="filter-chip active" data-langfilter="">All</span>`;
      allLangs.forEach(l => { html += `<span class="filter-chip" data-langfilter="${esc(l)}">${esc(l)}</span>`; });
    }
    html += `</div>`;
  }

  const showSync = isOwnProfile;
  html += `<div id="profile-list" class="widget-list">${widgets.map(w => widgetCard(w, {showSync, source:'profile'})).join('')}</div>`;

  return html;
}

function bindProfileEvents() {
  const search = document.getElementById('profile-search');
  if (search) {
    search.addEventListener('input', () => filterProfile());
  }
  document.querySelectorAll('[data-statusfilter]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('[data-statusfilter]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      filterProfile();
    });
  });
  document.querySelectorAll('[data-domainfilter]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('[data-domainfilter]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      filterProfile();
    });
  });
  document.querySelectorAll('[data-langfilter]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('[data-langfilter]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      filterProfile();
    });
  });
}

function filterProfile() {
  const isOwnProfile = !viewingProfile;
  const widgets = isOwnProfile ? myWidgets : userWidgets;
  const q = (document.getElementById('profile-search')?.value || '').toLowerCase();
  const statusFilter = document.querySelector('[data-statusfilter].active')?.dataset.statusfilter || 'all';
  const domainFilter = document.querySelector('[data-domainfilter].active')?.dataset.domainfilter || '';
  const langFilter = document.querySelector('[data-langfilter].active')?.dataset.langfilter || '';

  let filtered = widgets;
  if (isOwnProfile) {
    if (statusFilter === 'local') filtered = filtered.filter(w => w._sync === 'local');
    else if (statusFilter === 'published') filtered = filtered.filter(w => w._sync === 'published' || w._sync === 'mismatch' || w._sync === 'cloud');
  }

  if (domainFilter) filtered = filtered.filter(w => w.domain === domainFilter);
  if (langFilter) filtered = filtered.filter(w => (w.language||'').toLowerCase() === langFilter);

  if (q) {
    filtered = filtered.filter(w =>
      (w.id||'').toLowerCase().includes(q) ||
      (w.description||'').toLowerCase().includes(q) ||
      (w.domain||'').toLowerCase().includes(q)
    );
  }

  const listEl = document.getElementById('profile-list');
  if (listEl) {
    const showSync = isOwnProfile;
    listEl.innerHTML = filtered.length
      ? filtered.map(w => widgetCard(w, {showSync, source:'profile'})).join('')
      : `<div class="empty"><div class="empty-title">No matches</div></div>`;
  }
}

// ── Search view ──
function renderSearch() {
  let html = '';

  html += `<div class="search-bar">
    <span class="search-bar-icon">&#128269;</span>
    <input type="search" id="search-input" placeholder="Search widgets... (e.g. retry, auth, sorting)" value="${esc(searchQuery)}" />
  </div>`;

  if (!searchQuery) {
    html += `<div class="empty">
      <div class="empty-sub">Search the local library and cloud registry</div>
    </div>`;
    return html;
  }

  html += `<div class="results-count">${isSearching ? 'Searching...' : `${searchResults.length} result${searchResults.length!==1?'s':''} for "${esc(searchQuery)}"`}</div>`;

  if (isSearching) {
    html += `<div class="empty"><div class="spinner"></div></div>`;
  } else if (!searchResults.length) {
    html += `<div class="empty"><div class="empty-title">No results</div><div class="empty-sub">Try different keywords or check your spelling</div></div>`;
  } else {
    // Filters on results
    const domains = [...new Set(searchResults.map(w => w.domain).filter(Boolean))];
    const langs = [...new Set(searchResults.map(w => w.language).filter(Boolean))];
    if (domains.length > 1 || langs.length > 1) {
      html += `<div class="filters">`;
      if (domains.length > 1) {
        html += `<span class="filter-label">Domain:</span>`;
        html += `<span class="filter-chip ${!searchDomain?'active':''}" onclick="setSearchFilter('domain','')">All</span>`;
        domains.forEach(d => {
          html += `<span class="filter-chip ${searchDomain===d?'active':''}" onclick="setSearchFilter('domain','${esc(d)}')">${esc(d)}</span>`;
        });
      }
      if (langs.length > 1) {
        html += `<span class="filter-label" style="margin-left:12px">Language:</span>`;
        html += `<span class="filter-chip ${!searchLang?'active':''}" onclick="setSearchFilter('lang','')">All</span>`;
        langs.forEach(l => {
          html += `<span class="filter-chip ${searchLang===l?'active':''}" onclick="setSearchFilter('lang','${esc(l)}')">${esc(l)}</span>`;
        });
      }
      html += `</div>`;
    }

    let filtered = searchResults;
    if (searchDomain) filtered = filtered.filter(w => w.domain === searchDomain);
    if (searchLang) filtered = filtered.filter(w => w.language === searchLang);
    html += `<div class="widget-list">${filtered.map(w => widgetCard(w, {source:'search'})).join('')}</div>`;
  }

  return html;
}

function setSearchFilter(type, val) {
  if (type === 'domain') searchDomain = val;
  if (type === 'lang') searchLang = val;
  render();
}

function bindSearchEvents() {
  const input = document.getElementById('search-input');
  if (input) {
    input.addEventListener('keydown', e => {
      if (e.key === 'Enter' && e.target.value.trim()) {
        searchQuery = e.target.value.trim();
        doSearch();
      }
    });
    input.focus();
  }
}

// ── Detail view ──
let detailFiles = null;

function renderDetail(w) {
  const lang = (w.language || 'unknown').toLowerCase();
  const owner = w.owner || '';
  const ver = w.version || w._localVersion || w._cloudVersion || '';
  const installs = w.install_count || 0;
  const vis = w.visibility || '';
  const sync = w._sync || '';
  const tags = w.tags || [];
  const deps = (w.dependencies || (w.tech_stack && w.tech_stack.dependencies) || []);
  const reviews = w.reviews || [];
  const nsid = w.namespaced_id || (owner ? `@${owner}/${w.id}` : w.id);
  const notes = w.library_notes || {};

  // Status badge: local, published, cloud-only, or visibility from cloud
  let statusBadge = '';
  if (sync === 'local') statusBadge = '<span class="vis-badge vis-local">local</span>';
  else if (sync === 'published') statusBadge = '<span class="vis-badge vis-public">published</span>';
  else if (sync === 'mismatch') statusBadge = '<span class="vis-badge vis-mismatch">out of sync</span>';
  else if (sync === 'cloud') statusBadge = '<span class="vis-badge vis-cloud">cloud</span>';
  else if (vis === 'private') statusBadge = '<span class="vis-badge vis-private">private</span>';
  else if (vis) statusBadge = `<span class="vis-badge vis-public">${esc(vis)}</span>`;

  let html = `<div class="detail-back" onclick="navigate('${w._source||'profile'}')">&#8592; Back</div>`;

  html += `<div class="detail-title">
    ${esc(w.id || w.name)}
    ${statusBadge}
  </div>`;
  if (owner) html += `<div class="detail-owner">by <span style="cursor:pointer;color:var(--blue)" onclick="viewUserProfile('${esc(owner)}')">@${esc(owner)}</span></div>`;

  html += `<div class="detail-grid">`;

  // Main content
  html += `<div class="detail-main">`;
  if (w.description) html += `<div class="detail-desc">${esc(w.description)}</div>`;

  // Install command
  html += `<div class="detail-section">
    <h3>Install</h3>
    <div class="install-cmd" onclick="copyInstall(this)" title="Click to copy">
      cartograph install ${esc(nsid)}
      <span class="copy-hint">click to copy</span>
    </div>
  </div>`;

  // Tags
  if (tags.length) {
    html += `<div class="detail-section">
      <h3>Tags</h3>
      <div class="tags-list">${tags.map(t => `<span class="tag">${esc(t)}</span>`).join('')}</div>
    </div>`;
  }

  // Reviews
  if (reviews.length) {
    html += `<div class="detail-section">
      <h3>Reviews (${reviews.length})</h3>
      ${reviews.map(r => `<div class="review-card">
        <div class="review-score">${stars(r.score)} ${r.score}/5</div>
        ${r.comment ? `<div class="review-comment">${esc(r.comment)}</div>` : ''}
      </div>`).join('')}
    </div>`;
  }

  html += `</div>`; // detail-main

  // Sidebar
  html += `<div class="detail-sidebar">
    <h3>Details</h3>
    <div class="detail-meta-row"><span class="detail-meta-label">Version</span><span class="detail-meta-value">${esc(ver) || '—'}</span></div>
    <div class="detail-meta-row"><span class="detail-meta-label">Language</span><span class="detail-meta-value"><span class="lang-dot ${langClass(lang)}"></span> ${esc(lang)}</span></div>
    <div class="detail-meta-row"><span class="detail-meta-label">Domain</span><span class="detail-meta-value">${esc(w.domain || 'universal')}</span></div>
    <div class="detail-meta-row"><span class="detail-meta-label">Installs</span><span class="detail-meta-value">${installs}</span></div>
    ${w.rating ? `<div class="detail-meta-row"><span class="detail-meta-label">Rating</span><span class="detail-meta-value">${stars(w.rating)} ${w.rating.toFixed(1)}</span></div>` : ''}
    <div class="detail-meta-row"><span class="detail-meta-label">Status</span><span class="detail-meta-value">${sync === 'local' ? 'Local only' : sync === 'published' ? 'Published' : sync === 'mismatch' ? 'Out of sync' : sync === 'cloud' ? 'Cloud only' : vis || 'Local only'}</span></div>
    ${owner ? `<div class="detail-meta-row"><span class="detail-meta-label">Owner</span><span class="detail-meta-value">@${esc(owner)}</span></div>` : ''}
    ${deps.length ? `<div class="detail-meta-row"><span class="detail-meta-label">Dependencies</span><span class="detail-meta-value">${deps.map(esc).join(', ')}</span></div>` : `<div class="detail-meta-row"><span class="detail-meta-label">Dependencies</span><span class="detail-meta-value">None</span></div>`}
    ${notes.general ? `<div style="margin-top:14px"><h3>Notes</h3><div style="font-size:12px;color:var(--muted);line-height:1.5;margin-top:6px">${esc(notes.general)}</div></div>` : ''}
  </div>`;

  html += `</div>`; // detail-grid

  // Source files — full width below the grid
  html += `<div class="detail-files-full" id="files-section">`;
  if (detailFiles && Object.keys(detailFiles).length) {
    const fileNames = Object.keys(detailFiles).sort((a, b) => {
      const order = f => f.startsWith('src/') ? 0 : f.startsWith('tests/') ? 1 : f.startsWith('examples/') ? 2 : f === 'widget.json' ? 3 : 4;
      return order(a) - order(b) || a.localeCompare(b);
    });

    html += `<h3 style="margin-bottom:12px">Files (${fileNames.length})</h3>`;
    fileNames.forEach(f => {
      const parts = f.split('/');
      const name = parts.pop();
      const dir = parts.length ? parts.join('/') + '/' : '';
      const hljsLang = fileToLang(f);
      html += `<div class="file-block">
        <div class="file-header">${dir ? `<span class="file-header-dir">${esc(dir)}</span>` : ''}<span class="file-header-name">${esc(name)}</span></div>
        <pre class="code-block"><code class="language-${hljsLang}">${esc(detailFiles[f] || '')}</code></pre>
      </div>`;
    });
  } else if (detailFiles === null) {
    html += `<h3>Files</h3><div class="empty" style="padding:24px 0"><div class="spinner"></div>Loading source...</div>`;
  } else {
    html += `<h3>Files</h3><div style="color:var(--muted);font-size:13px;padding:12px 0">No source files available</div>`;
  }
  html += `</div>`;

  return html;
}

function fileToLang(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  const map = {
    py: 'python', js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
    json: 'json', nim: 'nim', rs: 'rust', go: 'go', rb: 'ruby', sh: 'bash',
    md: 'markdown', yml: 'yaml', yaml: 'yaml', toml: 'ini',
    txt: 'plaintext', cfg: 'ini', ini: 'ini', html: 'xml', css: 'css',
  };
  return map[ext] || 'plaintext';
}

async function loadDetailFiles(widgetId, owner) {
  detailFiles = null;
  render();
  try {
    let url = `/api/files/${encodeURIComponent(widgetId)}`;
    if (owner) url += `?owner=${encodeURIComponent(owner)}`;
    const res = await fetch(url);
    const data = await res.json();
    detailFiles = data.files || {};
  } catch {
    detailFiles = {};
  }
  render();
}

function copyInstall(el) {
  const text = el.textContent.replace('click to copy', '').trim();
  navigator.clipboard.writeText(text).then(() => {
    const hint = el.querySelector('.copy-hint');
    if (hint) { hint.textContent = 'copied!'; setTimeout(() => hint.textContent = 'click to copy', 1500); }
  });
}

// ── Data loading ──
async function loadMyWidgets() {
  const [whoami, localRes, cloudRes] = await Promise.all([
    fetch('/api/whoami').then(r => r.json()).catch(() => ({})),
    fetch('/api/local').then(r => r.json()).catch(() => ({widgets:[]})),
    fetch('/api/cloud').then(r => r.json()).catch(() => ({widgets:[]})),
  ]);

  whoamiData = whoami;

  // Merge local + cloud
  const map = {};
  (localRes.widgets || []).forEach(w => {
    map[w.id] = { ...w, _sync: 'local', _localVersion: w.version };
  });
  (cloudRes.widgets || []).forEach(w => {
    const baseId = w.id || (w.namespaced_id || '').replace(/^@[^/]+\//, '');
    if (map[baseId]) {
      const lv = map[baseId]._localVersion;
      const cv = w.version;
      map[baseId] = { ...map[baseId], ...w, id: baseId };
      map[baseId]._cloudVersion = cv;
      map[baseId]._localVersion = lv;
      map[baseId]._sync = lv === cv ? 'published' : 'mismatch';
    } else {
      map[baseId] = { ...w, id: baseId, _sync: 'cloud', _cloudVersion: w.version };
    }
  });

  myWidgets = Object.values(map).sort((a,b) => (a.id||'').localeCompare(b.id||''));
  document.getElementById('badge-my').textContent = myWidgets.length;
}

async function init() {
  await loadMyWidgets();
  render();
}

init();
</script>
</body>
</html>"""


def _make_handler(engine):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = dict(urllib.parse.parse_qsl(parsed.query))

            if path == "/":
                self._send(200, "text/html", _HTML.encode())
            elif path == "/api/whoami":
                self._send_json(self._whoami())
            elif path == "/api/local":
                self._send_json(self._local())
            elif path == "/api/cloud":
                self._send_json(self._cloud())
            elif path == "/api/search":
                self._send_json(self._search(qs))
            elif path.startswith("/api/inspect/"):
                parts = path.removeprefix("/api/inspect/").split("/", 1)
                if len(parts) == 2:
                    self._send_json(self._inspect(parts[0], parts[1]))
                else:
                    self._send_json({"error": "Use /api/inspect/{owner}/{widget_id}"})
            elif path == "/api/search-local":
                self._send_json(self._search_local(qs))
            elif path.startswith("/api/files/"):
                widget_id = path.removeprefix("/api/files/")
                self._send_json(self._files(widget_id, qs.get("owner", "")))
            else:
                self._send(404, "text/plain", b"Not found")

        def _whoami(self):
            from .auth import is_authenticated
            if not is_authenticated():
                return {"authenticated": False}
            from .cloud import whoami
            result = whoami()
            if "error" in result:
                return {"authenticated": False}
            return {"authenticated": True, **result}

        def _local(self):
            widgets = [
                {k: v for k, v in w.items() if k not in ("path", "reviews", "implementation_hash")}
                for w in engine.widgets
            ]
            return {"widgets": widgets}

        def _cloud(self):
            from .auth import is_authenticated
            if not is_authenticated():
                return {"widgets": [], "skipped": "not authenticated"}
            from .cloud import list_widgets
            result = list_widgets()
            if "error" in result:
                return {"widgets": [], "error": result["error"]}
            return {"widgets": result.get("widgets", [])}

        def _search_local(self, qs):
            q = qs.get("q", "").strip()
            if not q:
                return {"widgets": [], "total": 0}
            domain = qs.get("domain")
            language = qs.get("language")
            result = engine._search_backend.query(q, domain_filter=domain, language_filter=language, top_k=20)
            widgets = result.get("results", [])
            return {"widgets": widgets, "total": len(widgets)}

        def _search(self, qs):
            q = qs.get("q", "").strip()
            if not q:
                return {"widgets": [], "total": 0}
            from .auth import is_authenticated, load_token
            from .cloud import _get
            params = {"q": q}
            if qs.get("domain"): params["domain"] = qs["domain"]
            if qs.get("language"): params["language"] = qs["language"]
            query_string = urllib.parse.urlencode(params)
            try:
                result = _get(f"/v1/widgets/search?{query_string}")
                return result
            except Exception as e:
                return {"widgets": [], "error": str(e)}

        def _inspect(self, owner, widget_id):
            from .cloud import _get
            try:
                return _get(f"/v1/widgets/{owner}/{widget_id}")
            except Exception as e:
                return {"error": str(e)}

        def _files(self, widget_id, owner=""):
            import os
            # Find the widget in local library
            widget = None
            for w in engine.widgets:
                if w.get("id") == widget_id or w.get("name") == widget_id:
                    widget = w
                    break

            if widget and "path" in widget:
                return self._local_files(widget_id, widget["path"])

            # Not local — try fetching from cloud
            return self._cloud_files(widget_id, owner)

        def _local_files(self, widget_id, base):
            import os
            files = {}
            skip_dirs = {"__pycache__", ".pytest_cache", "history", ".git", "node_modules"}
            skip_files = {".coverage", ".validation_stamp.json"}
            max_size = 50_000

            for root, dirs, filenames in os.walk(base):
                dirs[:] = [d for d in dirs if d not in skip_dirs]
                for fname in filenames:
                    if fname in skip_files:
                        continue
                    fpath = os.path.join(root, fname)
                    relpath = os.path.relpath(fpath, base)
                    try:
                        size = os.path.getsize(fpath)
                        if size > max_size:
                            files[relpath] = f"[File too large: {size} bytes]"
                            continue
                        with open(fpath, "r", errors="replace") as f:
                            files[relpath] = f.read()
                    except Exception:
                        files[relpath] = "[Could not read file]"

            return {"widget_id": widget_id, "files": files}

        def _cloud_files(self, widget_id, owner=""):
            if not owner:
                return {"widget_id": widget_id, "files": {}, "error": "No owner specified"}

            from .cloud import _get
            result = _get(f"/v1/widgets/{owner}/{widget_id}/files")
            if "error" in result:
                return {"widget_id": widget_id, "files": {}, "error": result["error"]}
            return {"widget_id": widget_id, "files": result.get("files", {})}

        def _send_json(self, data):
            body = json.dumps(data).encode()
            self._send(200, "application/json", body)

        def _send(self, code, content_type, body):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler


def _write_pid(pid, port):
    os.makedirs(_PID_DIR, exist_ok=True)
    with open(_PID_FILE, "w") as f:
        f.write(f"{pid}\n{port}\n")


def _read_pid():
    """Returns (pid, port) or (None, None)."""
    if not os.path.exists(_PID_FILE):
        return None, None
    try:
        lines = open(_PID_FILE).read().strip().splitlines()
        pid = int(lines[0])
        port = int(lines[1]) if len(lines) > 1 else 0
        # Check if process is still alive
        os.kill(pid, 0)
        return pid, port
    except (ValueError, IndexError, ProcessLookupError, PermissionError):
        os.remove(_PID_FILE)
        return None, None


def stop():
    """Stop a running dashboard. Returns True if one was stopped."""
    pid, _ = _read_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if os.path.exists(_PID_FILE):
        os.remove(_PID_FILE)
    return True


def serve(engine, port=0, open_browser=True):
    # Restart if already running
    existing_pid, _ = _read_pid()
    if existing_pid is not None:
        print("  Restarting dashboard...")
        stop()

    handler = _make_handler(engine)
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"

    # Fork to background
    pid = os.fork()
    if pid > 0:
        # Parent - wait briefly for child to bind, then report
        _write_pid(pid, actual_port)
        print(f"\n  Cartograph Dashboard -> {url}  (pid {pid})")
        print(f"  Run 'cartograph dashboard --stop' to stop it.\n")
        if open_browser:
            threading.Timer(0.3, lambda: webbrowser.open(url)).start()
        return

    # Child - detach and serve
    os.setsid()
    sys.stdin.close()
    devnull = open(os.devnull, "w")
    sys.stdout = devnull
    sys.stderr = devnull

    signal.signal(signal.SIGTERM, lambda *_: (server.server_close(), sys.exit(0)))

    try:
        server.serve_forever()
    finally:
        server.server_close()
        if os.path.exists(_PID_FILE):
            os.remove(_PID_FILE)
