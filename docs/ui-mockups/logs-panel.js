/* Logs panel for the UI mockups (superusers): the API's and every engine run's lines, docked at
 * the bottom of whatever page is open -- no page to go to and come back from.
 *
 *   Open      the log icon in the top bar (this project on a project page, every project on the
 *             Projects page), or a run's "Logs" link (that run). Esc or the close button shuts it.
 *   Showing   one dropdown: a run, this project, or every project. A run with no progress for 10
 *             minutes is amber there -- and the top bar's icon carries an amber dot meanwhile.
 *   Size      drag the top edge; the expand button gives it the whole content area. It stays open,
 *             at its size, from page to page (sessionStorage).
 *
 * Each mockup page includes it (dark pages as ../logs-panel.js). Mockup only: sample lines.
 */
(function () {
  var DARK = /\/dark\/[^\/]*$/.test(location.pathname);
  var KEY = 'mockupLogsPanel';

  // ── Palette: the light and the dark mockups' tokens ─────────────────────────────────────────
  var C = DARK ? {
    card: '#1c1e23', line: '#2c2f37', hair: '#24272e', hover: '#23262d', head: '#23262d', text: '#f2f3f5',
    log: '#d6d9df', sub: '#a3a7b1', muted: '#7c818c', accent: '#1d7bff', accentBg: '#1b2638', accentLine: '#2d4a80',
    ok: '#3ddc84', warn: '#ffc966', warnBg: '#2c2414', err: '#ff7b72', errBg: '#3a1d21', mark: '#3a2e14',
    shadow: '0 -8px 32px rgba(0,0,0,.55)', ui: "'SamsungOne','Roboto',sans-serif", label: "'SamsungOne','Roboto',sans-serif"
  } : {
    card: '#ffffff', line: '#c4c6cd', hair: '#eef1f6', hover: '#f8f9ff', head: '#eff4ff', text: '#0b1c30',
    log: '#0b1c30', sub: '#44474c', muted: '#74777d', accent: '#0058be', accentBg: '#eff4ff', accentLine: '#b9cdf5',
    ok: '#00a572', warn: '#b45309', warnBg: '#fffbeb', err: '#ba1a1a', errBg: '#ffdad6', mark: '#fde68a',
    shadow: '0 -8px 32px rgba(4,22,39,.14)', ui: 'Inter,sans-serif', label: "'JetBrains Mono',monospace"
  };

  var CSS = [
    '#lp{position:fixed;right:0;bottom:0;z-index:250;display:none;flex-direction:column;background:' + C.card + ';border-top:1px solid ' + C.line + ';box-shadow:' + C.shadow + ';font-family:' + C.ui + ';color:' + C.text + '}',
    '#lp.open{display:flex}',
    '#lp .grip{position:absolute;left:0;right:0;top:-4px;height:8px;cursor:ns-resize}',
    '#lp .grip::after{content:"";position:absolute;left:50%;top:3px;width:40px;height:3px;margin-left:-20px;border-radius:3px;background:' + C.line + '}',
    '#lp .bar{display:flex;align-items:center;flex-wrap:wrap;gap:8px 12px;padding:8px 14px;border-bottom:1px solid ' + C.line + '}',
    '#lp .ttl{display:flex;align-items:center;gap:8px;font-weight:600;font-size:14px}',
    '#lp .st{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:500;color:' + C.ok + '}',
    '#lp .st i{width:7px;height:7px;border-radius:50%;background:' + C.ok + '}',
    '#lp .scope{position:relative}',
    '#lp .scopebtn{display:inline-flex;align-items:center;gap:6px;height:30px;max-width:360px;padding:0 10px;border:1px solid ' + C.line + ';border-radius:8px;background:' + C.card + ';font-size:13px;color:' + C.text + ';cursor:pointer;white-space:nowrap}',
    '#lp .scopebtn b{font-weight:500;overflow:hidden;text-overflow:ellipsis}',
    '#lp .scopebtn .k{color:' + C.muted + '}',
    '#lp .menu{position:absolute;left:0;bottom:calc(100% + 6px);min-width:340px;max-height:320px;overflow:auto;background:' + C.card + ';border:1px solid ' + C.line + ';border-radius:10px;box-shadow:' + C.shadow + ';display:none;z-index:5;padding:4px 0}',
    '#lp .menu.open{display:block}',
    '#lp .menu h6{margin:6px 12px 2px;font:600 10px ' + C.label + ';letter-spacing:.06em;text-transform:uppercase;color:' + C.muted + '}',
    '#lp .opt{display:block;width:100%;text-align:left;padding:7px 12px;font-size:13px;color:' + C.text + ';cursor:pointer;background:none;border:0}',
    '#lp .opt:hover{background:' + C.hover + '}',
    '#lp .opt.on{background:' + C.accentBg + ';color:' + C.accent + '}',
    '#lp .opt small{display:flex;align-items:center;gap:6px;font-size:11px;color:' + C.muted + ';margin-top:1px}',
    '#lp .opt small.q{color:' + C.warn + '}',
    '#lp .opt small i{width:6px;height:6px;border-radius:50%;background:' + C.ok + '}',
    '#lp .opt small.q i{background:' + C.warn + '}',
    '#lp .opt small.d i{background:' + C.muted + '}',
    '#lp .seg{display:inline-flex;height:30px;border:1px solid ' + C.line + ';border-radius:8px;overflow:hidden}',
    '#lp .seg button{padding:0 10px;font-size:12px;color:' + C.sub + ';border:0;border-right:1px solid ' + C.line + ';background:' + C.card + ';cursor:pointer;white-space:nowrap}',
    '#lp .seg button:last-child{border-right:0}',
    '#lp .seg button.on{background:' + C.accentBg + ';color:' + C.accent + ';font-weight:600}',
    '#lp label.chk{display:inline-flex;align-items:center;gap:5px;font-size:12px;color:' + C.sub + ';cursor:pointer}',
    '#lp .srch{position:relative}',
    '#lp .srch input{height:30px;width:170px;padding:0 8px 0 28px;border:1px solid ' + C.line + ';border-radius:8px;background:' + C.card + ';font-size:12px;color:' + C.text + '}',
    '#lp .srch span{position:absolute;left:7px;top:7px;font-size:16px;color:' + C.muted + '}',
    '#lp .sw{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:' + C.sub + ';cursor:pointer;user-select:none}',
    '#lp .sw i{position:relative;width:26px;height:16px;border-radius:99px;background:' + C.line + '}',
    '#lp .sw i::after{content:"";position:absolute;top:2px;left:2px;width:12px;height:12px;border-radius:50%;background:#fff;transition:transform .15s}',
    '#lp .sw.on i{background:' + C.accent + '}',
    '#lp .sw.on i::after{transform:translateX(10px)}',
    '#lp .ib{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:8px;border:0;background:none;color:' + C.sub + ';cursor:pointer}',
    '#lp .ib:hover{background:' + C.hover + ';color:' + C.text + '}',
    '#lp .sp{flex:1}',
    '#lp .rows{flex:1;min-height:0;overflow-y:auto}',
    '#lp .r{display:grid;grid-template-columns:92px 68px minmax(0,1fr) auto;column-gap:12px;padding:3px 14px;border-bottom:1px solid ' + C.hair + ';align-items:start}',
    '#lp .r:hover{background:' + C.hover + '}',
    '#lp .t{font:12px/20px "JetBrains Mono",monospace;color:' + C.sub + ';white-space:nowrap;font-variant-ligatures:none}',
    '#lp .lv{justify-self:start;font:600 10px/18px "JetBrains Mono",monospace;padding:0 6px;border-radius:4px;margin-top:1px}',
    '#lp .lv.WARNING{color:' + C.warn + ';background:' + C.warnBg + '}',
    '#lp .lv.ERROR{color:' + C.err + ';background:' + C.errBg + '}',
    '#lp .lv.DEBUG{color:' + C.muted + ';border:1px solid ' + C.line + '}',
    '#lp pre{margin:0;font:12px/20px "JetBrains Mono",monospace;color:' + C.log + ';white-space:pre-wrap;word-break:break-word;font-variant-ligatures:none}',
    '#lp mark{background:' + C.mark + ';color:inherit}',
    '#lp .ctx{max-width:340px;font-size:11px;line-height:20px;color:' + C.muted + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis;text-align:right}',
    '#lp .ctx a{color:' + C.sub + ';cursor:pointer}',
    '#lp .ctx a:hover{color:' + C.accent + ';text-decoration:underline}',
    '#lp .fold{font-size:12px;color:' + C.accent + ';cursor:pointer}',
    '#lp .div{display:flex;align-items:center;gap:8px;padding:8px 14px 2px;font:600 10px ' + C.label + ';letter-spacing:.06em;text-transform:uppercase;color:' + C.accent + '}',
    '#lp .div::after{content:"";flex:1;height:1px;background:' + C.accentLine + '}',
    '#lp .pill{position:absolute;left:50%;bottom:14px;transform:translateX(-50%);display:none;align-items:center;gap:5px;height:28px;padding:0 12px;border-radius:99px;background:' + C.accent + ';color:#fff;font-size:12px;font-weight:600;border:0;cursor:pointer;box-shadow:' + C.shadow + '}',
    '#lp .pill.show{display:inline-flex}',
    '#lp .empty{padding:40px 14px;text-align:center;color:' + C.muted + ';font-size:13px}',
    '#lp-btn{position:relative}',
    '#lp-btn .dot{position:absolute;top:6px;right:6px;width:8px;height:8px;border-radius:50%;background:' + C.warn + ';border:2px solid ' + C.card + ';display:none}',
    '#lp-btn.quiet .dot{display:block}',
    '#lp-btn.on{background:' + C.accentBg + '}',
    '#lp-btn.on .material-symbols-outlined{color:' + C.accent + '!important}'
  ].join('\n');

  // ── Sample lines (the API's record shape, docs/spec/LIVE_LOGS_SPEC.md) ─────────────────────────
  var NAMES = { p76a65b41: 'VCU Engine Firmware', p3147d31b: 'Gateway Core', pfc66bf4b: 'Sample Core' };
  var TAGS = { ver48561e59: 'v1.2.0', ver2b07c9d1: 'v0.4.0', verc81e2a04: 'v2.1' };
  var RUN = { generate: 'Generate', export: 'Export', reexport: 'Word file update', resume: 'Resume', cli: 'Command line' };
  var NOW0 = Date.parse('2026-10-06T10:42:00.000+05:30');
  var ALL = [], jit = 0, seq = 18100;
  function add(minAgo, o) { jit = (jit * 7 + 113) % 997; o.ts = NOW0 - minAgo * 60e3 + jit; o.pid = o.pid || (o.source === 'server' ? 4120 : 7832); ALL.push(o); }
  function x(a, b) { var o = {}; for (var k in a) o[k] = a[k]; for (k in b) o[k] = b[k]; return o; }
  var GW = { project: 'p3147d31b', version: 'ver2b07c9d1', job: 'jobb19c2e07', run: 'export', pid: 6610, step: 'Views', components: ['Layer2.Gateway'] };
  var CLI = { project: 'pfc66bf4b', version: 'verc81e2a04', pid: 9120, step: 'Export SWE.3', components: ['Layer1.Sample Core'] };
  var VCU = { project: 'p76a65b41', version: 'ver48561e59', job: 'jobd46b0548', run: 'generate' };
  var TB = 'Flowchart labels failed for GwRoute_Dispatch: the LLM did not answer\nTraceback (most recent call last):\n  File "engine/flowchart/llm/label_generator.py", line 233, in generate\n    labels = self._batch(nodes)\n  File "engine/flowchart/llm/label_generator.py", line 181, in _batch\n    raise LabelError("no response after 2 attempts")\nLabelError: no response after 2 attempts';
  add(1045, { source: 'server', level: 'INFO', logger: 'api.request', message: 'POST /api/v1/projects/p3147d31b/versions/ver2b07c9d1/export -> 202 (52 ms)', project: GW.project, version: GW.version, job: GW.job });
  add(1044, x(GW, { source: 'engine', level: 'INFO', logger: 'orchestration', message: '[3/4] === Phase 3: Run views ===' }));
  add(1032, x(GW, { source: 'engine', level: 'WARNING', logger: 'llm_client', message: 'LLM (openai/model) HTTP 503: An invalid response was received from the upstream server (attempt 1/2)' }));
  add(1026.9, x(GW, { source: 'engine', level: 'ERROR', logger: 'flowchart.labels', message: TB }));
  add(1026, x(GW, { source: 'engine', level: 'INFO', logger: 'flowchart.labels', message: 'Batch 41/112: 18 nodes, 1 LLM call' }));
  add(42, x(CLI, { source: 'engine', level: 'INFO', logger: 'run', message: 'Command-line export: 1 component (Layer1.Sample Core)' }));
  add(39, x(CLI, { source: 'engine', level: 'INFO', logger: 'docx_exporter', message: 'Wrote software_detailed_design_Sample-Core.docx (212 functions, 4.1 MB)' }));
  add(38.5, x(CLI, { source: 'engine', level: 'INFO', logger: 'run', message: 'Run finished: 1 component, 0 failed (3 min 40 s)' }));
  add(26, { source: 'server', level: 'INFO', logger: 'api.request', message: 'POST /api/v1/projects/p76a65b41/jobs -> 202 (41 ms)', project: VCU.project, version: VCU.version, job: VCU.job });
  add(25.8, x(VCU, { source: 'engine', level: 'INFO', logger: 'orchestration', message: '[1/4] === Phase 1: Parse C++ source ===', step: 'Parse' }));
  add(25.7, x(VCU, { source: 'engine', level: 'INFO', logger: 'parser', message: 'Parsing 214 translation units (Layer1)', step: 'Parse' }));
  add(24, x(VCU, { source: 'engine', level: 'WARNING', logger: 'parser', message: 'Hint: missing include - check --include-path-layer', step: 'Parse' }));
  add(22.5, x(VCU, { source: 'engine', level: 'INFO', logger: 'parser', message: 'Parsed 214 of 214 files in 3 min 12 s', step: 'Parse' }));
  add(22.4, x(VCU, { source: 'engine', level: 'INFO', logger: 'orchestration', message: '[2/4] === Phase 2: Derive model ===', step: 'Derive' }));
  add(22.3, x(VCU, { source: 'engine', level: 'INFO', logger: 'model_deriver', message: 'LLM limited to 2 requested component(s): 38 of 1,284 function(s) to describe', step: 'Derive' }));
  add(15, x(VCU, { source: 'engine', level: 'INFO', logger: 'progress', message: 'LLM-description: 12/38 (31%)', step: 'Derive' }));
  add(6, x(VCU, { source: 'engine', level: 'WARNING', logger: 'llm_client', message: 'LLM (openai/model) HTTP 503: An invalid response was received from the upstream server (attempt 1/2)', step: 'Derive' }));
  add(1, x(VCU, { source: 'engine', level: 'INFO', logger: 'progress', message: 'LLM-description: 20/38 (53%)', step: 'Derive' }));
  ALL.sort(function (a, b) { return a.ts - b.ts; });
  ALL.forEach(function (r) { r.seq = ++seq; });
  var done = 20, clock = NOW0;
  var NEXT = [
    function () { return x(VCU, { source: 'engine', level: 'DEBUG', logger: 'llm_client', message: 'description call 3.1 s (612 tokens in, 74 out)', step: 'Derive' }); },
    function () { done = Math.min(38, done + 1); return x(VCU, { source: 'engine', level: 'INFO', logger: 'progress', message: 'LLM-description: ' + done + '/38 (' + Math.round(done / .38) + '%)', step: 'Derive' }); },
    function () { return { source: 'server', level: 'INFO', logger: 'api.request', message: 'POST /api/v1/projects/p76a65b41/versions/ver48561e59/word-files -> 409 (6 ms)', project: VCU.project, version: VCU.version }; }
  ];

  // Runs at work or cut short (GET /projects/{pid}/runs): the Showing list and the amber dot
  var RUNS = [
    { key: 'jobd46b0548', project: 'p76a65b41', version: 'ver48561e59', command: 'generate', job: 'jobd46b0548', state: 'live', what: 'Derive · writing descriptions, 20 of 38', when: 'just now' },
    { key: 'jobb19c2e07', project: 'p3147d31b', version: 'ver2b07c9d1', command: 'export', job: 'jobb19c2e07', state: 'quiet', what: 'Views · drawing flowcharts, 41 of 112', when: 'Quiet for 17 h' }
  ];

  // ── State ───────────────────────────────────────────────────────────────────────────────────
  var here = (document.title.indexOf('Projects') >= 0 || /projects(-empty)?\.html$/.test(location.pathname)) ? null : 'p76a65b41';
  var S = { open: false, height: 300, max: false, scope: here ? { kind: 'project', project: here } : { kind: 'all' },
            show: 'all', debug: false, source: '', q: '', follow: true, pausedAt: 0, clearedAt: 0 };
  try { var saved = JSON.parse(sessionStorage.getItem(KEY) || 'null'); if (saved) { S.open = saved.open; S.height = saved.height || 300; S.max = !!saved.max; if (saved.scope && saved.scope.kind === 'all') S.scope = saved.scope; if (saved.scope && saved.scope.kind === 'run') S.scope = saved.scope; } } catch (e) {}
  function save() { try { sessionStorage.setItem(KEY, JSON.stringify({ open: S.open, height: S.height, max: S.max, scope: S.scope })); } catch (e) {} }
  var openFolds = {};
  var LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'];
  function level() { return S.show === 'warn' ? 'WARNING' : S.show === 'debug' ? 'DEBUG' : 'INFO'; }
  function pass(r) {
    if (LEVELS.indexOf(r.level) < LEVELS.indexOf(level())) return false;
    if (S.source && r.source !== S.source) return false;
    if (S.scope.kind === 'run') return r.job === S.scope.job;
    if (S.scope.kind === 'project') return r.project === S.scope.project;
    return true;
  }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function hl(t) {
    t = esc(t);
    var q = S.q.trim();
    if (!q) return t;
    return t.replace(new RegExp(esc(q).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), function (m) { return '<mark>' + m + '</mark>'; });
  }
  function clockOf(ms) { return new Date(ms + 5.5 * 3600e3).toISOString().slice(11, 23); }
  function full(ms) { return new Date(ms + 5.5 * 3600e3).toISOString().replace('T', ' ').slice(0, 23) + ' +05:30'; }
  function scopeLabel() {
    if (S.scope.kind === 'all') return ['', 'Every project'];
    if (S.scope.kind === 'project') return ['Project', NAMES[S.scope.project]];
    var r = RUNS.filter(function (x) { return x.key === S.scope.job; })[0] || {};
    return ['Run', (NAMES[r.project] || '') + ' · ' + (TAGS[r.version] || '') + ' · ' + (RUN[r.command] || 'Run')];
  }

  // ── DOM ─────────────────────────────────────────────────────────────────────────────────────
  var el, rowsEl;
  function build() {
    var st = document.createElement('style');
    st.textContent = CSS;
    document.head.appendChild(st);
    el = document.createElement('section');
    el.id = 'lp';
    el.setAttribute('aria-label', 'Logs');
    el.innerHTML =
      '<div class="grip" title="Drag to resize"></div>' +
      '<div class="bar">' +
      '  <span class="ttl"><span class="material-symbols-outlined" style="font-size:18px;">terminal</span>Logs<span class="st"><i></i>Live</span></span>' +
      '  <div class="scope"><button class="scopebtn" data-a="scope"><span class="k"></span><b></b><span class="material-symbols-outlined" style="font-size:16px;">expand_more</span></button><div class="menu"></div></div>' +
      '  <div class="seg" data-g="show" title="Debug: every line, the busiest"><button data-v="all" class="on">All</button><button data-v="warn">Warnings &amp; errors</button><button data-v="debug">Debug</button></div>' +
      '  <div class="seg" data-g="source"><button data-v="" class="on">All</button><button data-v="server">API</button><button data-v="engine">Engine</button></div>' +
      '  <div class="srch"><span class="material-symbols-outlined">search</span><input type="search" placeholder="Search the lines" data-a="q"></div>' +
      '  <span class="sp"></span>' +
      '  <span class="sw on" data-a="follow" role="switch" aria-checked="true"><i></i>Follow</span>' +
      '  <button class="ib" data-a="clear" title="Clear (new lines keep arriving)"><span class="material-symbols-outlined" style="font-size:18px;">clear_all</span></button>' +
      '  <button class="ib" data-a="max" title="Full height"><span class="material-symbols-outlined" style="font-size:18px;">open_in_full</span></button>' +
      '  <button class="ib" data-a="close" title="Close (Esc)"><span class="material-symbols-outlined" style="font-size:18px;">close</span></button>' +
      '</div>' +
      '<div class="rows"></div>' +
      '<button class="pill" data-a="resume"><span class="material-symbols-outlined" style="font-size:15px;">arrow_downward</span><span></span></button>';
    document.body.appendChild(el);
    rowsEl = el.querySelector('.rows');
    el.addEventListener('click', onClick);
    el.querySelector('[data-a=q]').addEventListener('input', function (e) { S.q = e.target.value; render(); });
    rowsEl.addEventListener('scroll', function () {
      var bottom = rowsEl.scrollHeight - rowsEl.scrollTop - rowsEl.clientHeight < 24;
      if (bottom !== S.follow) { S.follow = bottom; if (!bottom) S.pausedAt = seq; paint(); }
    });
    // Resize by the top edge
    el.querySelector('.grip').addEventListener('mousedown', function (e) {
      e.preventDefault();
      var y0 = e.clientY, h0 = el.getBoundingClientRect().height;
      function mv(ev) { S.max = false; S.height = Math.max(160, Math.min(window.innerHeight - 120, h0 + (y0 - ev.clientY))); place(); }
      function up() { document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up); save(); }
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && S.open) setOpen(false); });
    document.addEventListener('click', function (e) {
      var m = el.querySelector('.menu');
      if (m.classList.contains('open') && !el.querySelector('.scope').contains(e.target)) m.classList.remove('open');
    });
    window.addEventListener('resize', place);
  }

  // Over the page's content: right of the sidebar, under the top bar when full height
  function place() {
    var side = document.getElementById('app-sidebar');
    var left = side ? Math.round(side.getBoundingClientRect().right) : 0;
    var header = document.querySelector('header');
    var top = header ? Math.round(header.getBoundingClientRect().bottom) : 56;
    el.style.left = left + 'px';
    el.style.height = (S.max ? window.innerHeight - top : S.height) + 'px';
    el.querySelector('[data-a=max] span').textContent = S.max ? 'close_fullscreen' : 'open_in_full';
    el.querySelector('[data-a=max]').title = S.max ? 'Back to its size' : 'Full height';
  }

  function setOpen(on) {
    S.open = on;
    el.classList.toggle('open', on);
    var b = document.getElementById('lp-btn');
    if (b) b.classList.toggle('on', on);
    save();
    if (on) { place(); render(true); }
  }
  window.openLogs = function (scope) { if (scope) { S.scope = scope; S.clearedAt = 0; } setOpen(true); paintScope(); };

  function onClick(e) {
    var t = e.target.closest('[data-a],[data-v],[data-run],[data-pick]');
    if (!t) return;
    var a = t.getAttribute('data-a');
    if (a === 'close') return setOpen(false);
    if (a === 'max') { S.max = !S.max; place(); save(); return render(); }
    if (a === 'clear') { S.clearedAt = seq; return render(true); }
    if (a === 'follow' || a === 'resume') { S.follow = a === 'resume' ? true : !S.follow; if (!S.follow) S.pausedAt = seq; return render(S.follow); }
    if (a === 'scope') { e.stopPropagation(); return el.querySelector('.menu').classList.toggle('open'); }
    if (t.hasAttribute('data-pick')) {
      var p = JSON.parse(t.getAttribute('data-pick'));
      S.scope = p; S.clearedAt = 0;
      el.querySelector('.menu').classList.remove('open');
      paintScope(); save(); return render(true);
    }
    var g = t.parentNode && t.parentNode.getAttribute && t.parentNode.getAttribute('data-g');
    if (g) { S[g] = t.getAttribute('data-v'); S.clearedAt = 0; paintControls(); return render(true); }
  }

  function paintControls() {
    ['show', 'source'].forEach(function (g) {
      [].forEach.call(el.querySelectorAll('[data-g=' + g + '] button'), function (b) { b.classList.toggle('on', b.getAttribute('data-v') === S[g]); });
    });
  }

  function paintScope() {
    var l = scopeLabel();
    el.querySelector('.scopebtn .k').textContent = l[0] ? l[0] + ':' : 'Showing:';
    el.querySelector('.scopebtn b').textContent = l[1];
    var cur = JSON.stringify(S.scope);
    function opt(pick, title, sub, cls) {
      var on = JSON.stringify(pick) === cur ? ' on' : '';
      return '<button class="opt' + on + '" data-pick=\'' + JSON.stringify(pick) + '\'>' + title + (sub ? '<small class="' + (cls || '') + '"><i></i>' + sub + '</small>' : '') + '</button>';
    }
    var h = '<h6>Runs</h6>';
    RUNS.forEach(function (r) {
      h += opt({ kind: 'run', job: r.job }, NAMES[r.project] + ' · ' + TAGS[r.version] + ' · ' + RUN[r.command],
        r.what + ' · ' + r.when, r.state === 'quiet' ? 'q' : '');
    });
    h += '<h6>Everything</h6>';
    if (here) h += opt({ kind: 'project', project: here }, 'This project · ' + NAMES[here]);
    h += opt({ kind: 'all' }, 'Every project, and the API');
    el.querySelector('.menu').innerHTML = h;
  }

  function row(r, one) {
    var lines = r.message.split('\n'), open = openFolds[r.seq], long = lines.length > 5 && !open;
    var ctx = [(r.source === 'server' ? 'API' : 'Engine') + ' · ' + esc(r.logger)];
    if (!one) {
      if (S.scope.kind === 'all' && r.project) ctx.push('<a data-pick=\'' + JSON.stringify({ kind: 'project', project: r.project }) + '\'>' + NAMES[r.project] + '</a>');
      if (r.version) ctx.push(TAGS[r.version] || r.version);
      if (r.job) ctx.push('<a data-pick=\'' + JSON.stringify({ kind: 'run', job: r.job }) + '\'>' + (RUN[r.run] || 'Run') + '</a>');
      if (r.step) ctx.push(r.step);
    }
    if (r.components) ctx.push(r.components.join(', '));
    return '<div class="r"><span class="t" title="' + full(r.ts) + '">' + clockOf(r.ts) + '</span>' +
      '<span>' + (r.level === 'INFO' ? '' : '<span class="lv ' + r.level + '">' + r.level + '</span>') + '</span>' +
      '<div><pre>' + hl(long ? lines.slice(0, 5).join('\n') : r.message) + '</pre>' +
      (lines.length > 5 ? '<span class="fold" onclick="this.dispatchEvent(new CustomEvent(\'fold\',{bubbles:true,detail:' + r.seq + '}))">' + (open ? 'Show less' : 'Show ' + (lines.length - 5) + ' more lines') + '</span>' : '') +
      '</div><div class="ctx" title="pid ' + r.pid + '">' + ctx.join(' · ') + '</div></div>';
  }

  function render(toBottom) {
    if (!S.open) return paintDot();
    var q = S.q.trim().toLowerCase(), one = S.scope.kind === 'run', step = '', h = '';
    var shown = ALL.filter(function (r) { return pass(r) && r.seq > S.clearedAt && (!q || (r.message + ' ' + r.logger).toLowerCase().indexOf(q) >= 0); }).slice(-500);
    shown.forEach(function (r) {
      if (one && r.source === 'engine' && r.step && r.step !== step) { step = r.step; h += '<div class="div">' + step + '</div>'; }
      h += row(r, one);
    });
    rowsEl.innerHTML = h || '<div class="empty">' + (S.clearedAt && !q ? 'Cleared. New lines appear here as they arrive.' : 'No lines match. New ones appear here as they arrive.') + '</div>';
    if (toBottom || S.follow) rowsEl.scrollTop = rowsEl.scrollHeight;
    var unseen = S.follow ? 0 : shown.filter(function (r) { return r.seq > S.pausedAt; }).length;
    var pill = el.querySelector('.pill');
    pill.classList.toggle('show', unseen > 0);
    pill.lastChild.textContent = unseen + ' new line' + (unseen === 1 ? '' : 's');
    paint();
  }
  function paint() {
    var sw = el.querySelector('[data-a=follow]');
    sw.classList.toggle('on', S.follow); sw.setAttribute('aria-checked', S.follow);
    paintDot();
  }
  function paintDot() {
    var b = document.getElementById('lp-btn');
    if (b) b.classList.toggle('quiet', RUNS.some(function (r) { return r.state === 'quiet'; }));
  }

  // The stream: a line every ~1.5 s from the live run
  var k = 0;
  setInterval(function () {
    clock += 1500;
    var r = NEXT[k++ % NEXT.length]();
    r.ts = clock; r.seq = ++seq; r.pid = r.source === 'server' ? 4120 : 7832;
    ALL.push(r);
    if (S.open) render();
  }, 1500);

  // ── The top bar's button, and the run links that open the panel instead of a page ──────────────
  function mount() {
    build();
    document.addEventListener('fold', function (e) { openFolds[e.detail] = !openFolds[e.detail]; render(); });
    var header = document.querySelector('header');
    var actions = header && header.lastElementChild;
    if (actions && actions !== header.firstElementChild) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'lp-btn';
      btn.title = 'Logs (superusers)';
      btn.setAttribute('aria-label', 'Logs');
      btn.className = 'p-2 hover:bg-surface-container rounded-lg transition-colors';
      btn.innerHTML = '<span class="material-symbols-outlined text-on-surface-variant" style="font-size:22px;">terminal</span><span class="dot" title="A run has reported nothing for 10 minutes"></span>';
      btn.addEventListener('click', function () {
        if (S.open) return setOpen(false);
        window.openLogs(here ? { kind: 'project', project: here } : { kind: 'all' });
      });
      var bell = [].filter.call(actions.querySelectorAll('button'), function (b) { return /notifications/.test(b.textContent); })[0];
      if (bell) bell.parentNode.insertBefore(btn, bell);
      else actions.insertBefore(btn, actions.firstChild);
    }
    document.addEventListener('click', function (e) {
      var a = e.target.closest && e.target.closest('a[href^="live-logs.html"]');
      if (!a) return;
      e.preventDefault();
      var job = new URLSearchParams(a.getAttribute('href').split('?')[1] || '').get('job');
      window.openLogs(job ? { kind: 'run', job: job } : { kind: 'all' });
    });
    paintControls(); paintScope(); paintDot();
    if (location.hash === '#logs' || S.open) window.openLogs();
    if (location.hash === '#logs-max') { S.max = true; window.openLogs(); }
    if (location.hash === '#logs-run') window.openLogs({ kind: 'run', job: 'jobd46b0548' });
    if (location.hash === '#logs-menu') { window.openLogs({ kind: 'run', job: 'jobd46b0548' }); el.querySelector('.menu').classList.add('open'); }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
