"""
Local dashboard server for Cartograph.

Spins up a temporary HTTP server, serves a single-page dashboard,
and shuts down when the user closes the terminal (Ctrl-C).
"""

import json
import threading
import webbrowser
import http.server
import urllib.parse


_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cartograph Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:       #0d1117;
    --surface:  #161b22;
    --border:   #30363d;
    --text:     #e6edf3;
    --muted:    #8b949e;
    --blue:     #58a6ff;
    --green:    #3fb950;
    --orange:   #d29922;
    --red:      #f85149;
    --purple:   #bc8cff;
    --teal:     #39d353;
    --cyan:     #79c0ff;
  }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    min-height: 100vh;
  }

  /* ── Header ── */
  header {
    border-bottom: 1px solid var(--border);
    padding: 16px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    background: var(--bg);
    z-index: 10;
  }
  .logo { font-size: 18px; font-weight: 600; color: var(--blue); letter-spacing: -0.3px; }
  .logo span { color: var(--muted); font-weight: 400; font-size: 13px; margin-left: 10px; }
  #user-badge {
    font-size: 12px;
    color: var(--muted);
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 4px 12px;
  }
  #user-badge.authed { color: var(--green); border-color: #238636; }

  /* ── Main ── */
  main { max-width: 1200px; margin: 0 auto; padding: 32px; }

  /* ── Stats row ── */
  .stats {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 12px;
    margin-bottom: 28px;
  }
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }
  .stat-num { font-size: 28px; font-weight: 700; line-height: 1; }
  .stat-label { font-size: 11px; color: var(--muted); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-num.blue   { color: var(--blue); }
  .stat-num.green  { color: var(--green); }
  .stat-num.orange { color: var(--orange); }
  .stat-num.purple { color: var(--purple); }
  .stat-num.muted  { color: var(--muted); }

  /* ── Toolbar ── */
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }
  .tabs { display: flex; gap: 4px; }
  .tab {
    padding: 6px 14px;
    border-radius: 6px;
    border: 1px solid transparent;
    background: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 13px;
    transition: all 0.15s;
  }
  .tab:hover { color: var(--text); background: var(--surface); }
  .tab.active {
    background: var(--surface);
    border-color: var(--border);
    color: var(--text);
    font-weight: 500;
  }
  .tab .count {
    display: inline-block;
    background: var(--border);
    border-radius: 10px;
    padding: 0 6px;
    font-size: 11px;
    margin-left: 4px;
    color: var(--muted);
  }
  .tab.active .count { background: #1f6feb33; color: var(--blue); }

  #search {
    margin-left: auto;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    color: var(--text);
    font-size: 13px;
    width: 220px;
    outline: none;
  }
  #search:focus { border-color: var(--blue); }
  #search::placeholder { color: var(--muted); }

  .filter-row {
    display: flex;
    gap: 8px;
    margin-bottom: 20px;
    flex-wrap: wrap;
  }
  .filter-btn {
    padding: 3px 10px;
    border-radius: 20px;
    border: 1px solid var(--border);
    background: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 12px;
    transition: all 0.15s;
  }
  .filter-btn:hover { border-color: var(--blue); color: var(--blue); }
  .filter-btn.active { border-color: var(--blue); color: var(--blue); background: #1f6feb22; }

  /* ── Grid ── */
  #grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 14px;
  }

  /* ── Card ── */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    transition: border-color 0.15s;
    position: relative;
  }
  .card:hover { border-color: #58a6ff55; }

  .card-top {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 8px;
  }
  .card-name {
    font-weight: 600;
    font-size: 13px;
    color: var(--text);
    word-break: break-word;
  }
  .card-id {
    font-size: 11px;
    color: var(--muted);
    font-family: monospace;
  }

  .badges { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 2px; }
  .badge {
    font-size: 10px;
    padding: 2px 7px;
    border-radius: 10px;
    font-weight: 500;
    border: 1px solid;
    white-space: nowrap;
  }
  .badge-frontend  { color: #bc8cff; border-color: #bc8cff44; background: #bc8cff11; }
  .badge-backend   { color: #58a6ff; border-color: #58a6ff44; background: #58a6ff11; }
  .badge-data      { color: #39d353; border-color: #39d35344; background: #39d35311; }
  .badge-ml        { color: #d29922; border-color: #d2992244; background: #d2992211; }
  .badge-security  { color: #f85149; border-color: #f8514944; background: #f8514911; }
  .badge-infra     { color: #8b949e; border-color: #8b949e44; background: #8b949e11; }
  .badge-logic     { color: #3fb950; border-color: #3fb95044; background: #3fb95011; }
  .badge-search    { color: #79c0ff; border-color: #79c0ff44; background: #79c0ff11; }
  .badge-ui        { color: #e879f9; border-color: #e879f944; background: #e879f911; }
  .badge-algo      { color: #fbbf24; border-color: #fbbf2444; background: #fbbf2411; }
  .badge-math      { color: #a78bfa; border-color: #a78bfa44; background: #a78bfa11; }
  .badge-sim       { color: #34d399; border-color: #34d39944; background: #34d39911; }
  .badge-networking{ color: #60a5fa; border-color: #60a5fa44; background: #60a5fa11; }
  .badge-universal { color: #8b949e; border-color: #8b949e44; background: #8b949e11; }
  .badge-lang {
    color: var(--muted);
    border-color: var(--border);
    background: transparent;
  }

  .card-desc {
    font-size: 12px;
    color: var(--muted);
    line-height: 1.5;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: auto;
    padding-top: 8px;
    border-top: 1px solid var(--border);
  }
  .card-meta { font-size: 11px; color: var(--muted); display: flex; gap: 10px; }
  .rating { color: var(--orange); }

  /* Sync status pill */
  .sync-pill {
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 600;
    border: 1px solid;
  }
  .sync-local    { color: var(--blue);   border-color: #58a6ff44; background: #58a6ff11; }
  .sync-cloud    { color: var(--purple); border-color: #bc8cff44; background: #bc8cff11; }
  .sync-synced   { color: var(--green);  border-color: #3fb95044; background: #3fb95011; }
  .sync-mismatch { color: var(--orange); border-color: #d2992244; background: #d2992211; }

  /* ── Empty / loading states ── */
  .state {
    grid-column: 1 / -1;
    text-align: center;
    padding: 60px 0;
    color: var(--muted);
  }
  .state-title { font-size: 16px; margin-bottom: 6px; }
  .state-sub   { font-size: 13px; }

  /* ── Spinner ── */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 24px; height: 24px;
    border: 2px solid var(--border);
    border-top-color: var(--blue);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    margin: 0 auto 12px;
  }

  @media (max-width: 600px) {
    main { padding: 16px; }
    .stats { grid-template-columns: repeat(2, 1fr); }
    header { padding: 12px 16px; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">Cartograph <span>Local Dashboard</span></div>
  <div id="user-badge">Not logged in</div>
</header>

<main>
  <div class="stats">
    <div class="stat"><div class="stat-num blue"  id="s-total">—</div><div class="stat-label">Total</div></div>
    <div class="stat"><div class="stat-num blue"  id="s-local">—</div><div class="stat-label">Local</div></div>
    <div class="stat"><div class="stat-num purple" id="s-cloud">—</div><div class="stat-label">Cloud</div></div>
    <div class="stat"><div class="stat-num green"  id="s-synced">—</div><div class="stat-label">Synced</div></div>
    <div class="stat"><div class="stat-num orange" id="s-mismatch">—</div><div class="stat-label">Version Gap</div></div>
  </div>

  <div class="toolbar">
    <div class="tabs">
      <button class="tab active" data-tab="all">All <span class="count" id="c-all">0</span></button>
      <button class="tab" data-tab="local">Local only <span class="count" id="c-local">0</span></button>
      <button class="tab" data-tab="cloud">Cloud only <span class="count" id="c-cloud">0</span></button>
      <button class="tab" data-tab="synced">Synced <span class="count" id="c-synced">0</span></button>
    </div>
    <input id="search" type="search" placeholder="Search widgets…">
  </div>

  <div class="filter-row" id="domain-filters"></div>

  <div id="grid">
    <div class="state"><div class="spinner"></div><div class="state-title">Loading…</div></div>
  </div>
</main>

<script>
let allWidgets = [];
let activeTab = 'all';
let activeDomain = null;
let searchQuery = '';

function stars(rating) {
  if (!rating) return '';
  const full = Math.round(rating);
  return '★'.repeat(full) + '☆'.repeat(5 - full) + ' ' + rating.toFixed(1);
}

function domainClass(domain) {
  const d = (domain || 'universal').toLowerCase();
  const known = ['frontend','backend','data','ml','security','infra','logic',
                 'search','ui','algo','math','sim','networking','universal'];
  return known.includes(d) ? 'badge-' + d : 'badge-universal';
}

function renderCard(w) {
  const sync = w._sync;
  let syncLabel, syncClass;
  if (sync === 'local')    { syncLabel = 'Local only'; syncClass = 'sync-local'; }
  else if (sync === 'cloud') { syncLabel = 'Cloud only'; syncClass = 'sync-cloud'; }
  else if (sync === 'mismatch') { syncLabel = `v${w._localVersion} → v${w._cloudVersion}`; syncClass = 'sync-mismatch'; }
  else                     { syncLabel = 'Synced';     syncClass = 'sync-synced'; }

  const rating = w.rating ? `<span class="rating">${stars(w.rating)}</span>` : '';
  const installs = w.install_count ? `${w.install_count} installs` : '';
  const ver = w._localVersion || w._cloudVersion || w.version || '';

  return `<div class="card">
    <div class="card-top">
      <div>
        <div class="card-name">${w.name || w.id}</div>
        <div class="card-id">${w.id}</div>
      </div>
      <span class="sync-pill ${syncClass}">${syncLabel}</span>
    </div>
    <div class="badges">
      <span class="badge ${domainClass(w.domain)}">${w.domain || 'universal'}</span>
      <span class="badge badge-lang">${w.language || '?'}</span>
      ${ver ? `<span class="badge badge-lang">v${ver}</span>` : ''}
    </div>
    ${w.description ? `<div class="card-desc">${w.description}</div>` : ''}
    <div class="card-footer">
      <div class="card-meta">
        ${rating}
        ${installs}
      </div>
    </div>
  </div>`;
}

function render() {
  const q = searchQuery.toLowerCase();
  const filtered = allWidgets.filter(w => {
    if (activeTab === 'local'  && w._sync !== 'local')    return false;
    if (activeTab === 'cloud'  && w._sync !== 'cloud')    return false;
    if (activeTab === 'synced' && w._sync !== 'synced' && w._sync !== 'mismatch') return false;
    if (activeDomain && w.domain !== activeDomain) return false;
    if (q && !(
      (w.id||'').toLowerCase().includes(q) ||
      (w.name||'').toLowerCase().includes(q) ||
      (w.description||'').toLowerCase().includes(q) ||
      (w.domain||'').toLowerCase().includes(q)
    )) return false;
    return true;
  });

  const grid = document.getElementById('grid');
  if (filtered.length === 0) {
    grid.innerHTML = `<div class="state"><div class="state-title">No widgets found</div><div class="state-sub">Try a different filter or search term.</div></div>`;
  } else {
    grid.innerHTML = filtered.map(renderCard).join('');
  }
}

function buildDomainFilters(widgets) {
  const counts = {};
  widgets.forEach(w => { counts[w.domain || 'universal'] = (counts[w.domain || 'universal'] || 0) + 1; });
  const sorted = Object.entries(counts).sort((a,b) => b[1]-a[1]);
  const row = document.getElementById('domain-filters');
  row.innerHTML = sorted.map(([d, n]) =>
    `<button class="filter-btn" data-domain="${d}">${d} <span style="opacity:.5">${n}</span></button>`
  ).join('');
  row.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const d = btn.dataset.domain;
      if (activeDomain === d) {
        activeDomain = null;
        btn.classList.remove('active');
      } else {
        activeDomain = d;
        row.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      }
      render();
    });
  });
}

function updateStats(widgets) {
  const local   = widgets.filter(w => w._sync === 'local').length;
  const cloud   = widgets.filter(w => w._sync === 'cloud').length;
  const synced  = widgets.filter(w => w._sync === 'synced').length;
  const mm      = widgets.filter(w => w._sync === 'mismatch').length;
  document.getElementById('s-total').textContent    = widgets.length;
  document.getElementById('s-local').textContent    = local + synced + mm;
  document.getElementById('s-cloud').textContent    = cloud + synced + mm;
  document.getElementById('s-synced').textContent   = synced;
  document.getElementById('s-mismatch').textContent = mm;

  document.getElementById('c-all').textContent    = widgets.length;
  document.getElementById('c-local').textContent  = local;
  document.getElementById('c-cloud').textContent  = cloud;
  document.getElementById('c-synced').textContent = synced + mm;
}

async function load() {
  const [whoamiRes, localRes, cloudRes] = await Promise.all([
    fetch('/api/whoami').then(r => r.json()).catch(() => ({})),
    fetch('/api/local').then(r => r.json()).catch(() => ({widgets:[]})),
    fetch('/api/cloud').then(r => r.json()).catch(() => ({widgets:[]})),
  ]);

  // User badge
  const badge = document.getElementById('user-badge');
  if (whoamiRes.authenticated) {
    badge.textContent = whoamiRes.owner || whoamiRes.email || 'logged in';
    badge.classList.add('authed');
  }

  const localWidgets = localRes.widgets || [];
  const cloudWidgets = cloudRes.widgets || [];

  // Build merged map by base widget ID (strip @owner/ prefix from cloud)
  const map = {};
  localWidgets.forEach(w => {
    map[w.id] = { ...w, _sync: 'local', _localVersion: w.version };
  });
  cloudWidgets.forEach(w => {
    const baseId = w.id || (w.namespaced_id || '').replace(/^@[^/]+\//, '');
    if (map[baseId]) {
      const lv = map[baseId]._localVersion;
      const cv = w.version;
      map[baseId]._cloudVersion = cv;
      map[baseId]._sync = lv === cv ? 'synced' : 'mismatch';
      // Prefer cloud description/rating if richer
      if (!map[baseId].description && w.description) map[baseId].description = w.description;
      if (w.rating) map[baseId].rating = w.rating;
      if (w.install_count) map[baseId].install_count = w.install_count;
    } else {
      map[baseId] = { ...w, id: baseId, _sync: 'cloud', _cloudVersion: w.version };
    }
  });

  allWidgets = Object.values(map).sort((a,b) => (a.id||'').localeCompare(b.id||''));
  updateStats(allWidgets);
  buildDomainFilters(allWidgets);
  render();
}

// Tabs
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    activeTab = tab.dataset.tab;
    render();
  });
});

// Search
document.getElementById('search').addEventListener('input', e => {
  searchQuery = e.target.value;
  render();
});

load();
</script>
</body>
</html>"""


def _make_handler(engine):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            if path == "/":
                self._send(200, "text/html", _HTML.encode())
            elif path == "/api/whoami":
                self._send_json(self._whoami())
            elif path == "/api/local":
                self._send_json(self._local())
            elif path == "/api/cloud":
                self._send_json(self._cloud())
            else:
                self._send(404, "text/plain", b"Not found")

        def _whoami(self):
            from .auth import is_authenticated, get_token
            if not is_authenticated():
                return {"authenticated": False}
            from .cloud import _get
            result = _get("/v1/auth/me")
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
            from .cloud import _get
            result = _get("/v1/widgets?top_k=500")
            if "error" in result:
                return {"widgets": [], "error": result["error"]}
            return {"widgets": result.get("widgets", [])}

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


def serve(engine, port=0, open_browser=True):
    handler = _make_handler(engine)
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}"

    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()

    print(f"\n  Cartograph Dashboard → {url}")
    print("  Press Ctrl-C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
