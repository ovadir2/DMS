// The KPI Builder: it makes the two files the DMS expects, and nothing else. There is no publishing API in
// the DMS yet (docs/12 §5), so the package is downloaded and dropped on the department's KPIs folder - which
// the DMS turns into the KPI's own folder, page at its root, definition released into Current_ReadOnly.
const $ = s => document.querySelector(s);
const here = new URLSearchParams(location.search);
const ARG = {
  mode: here.get('mode') || 'create',
  folder: here.get('folder') || '',          // the KPIs folder in the DMS
  owner: here.get('owner') || '',            // the department or customer it belongs to
  kpi: here.get('kpi') || '',
  user: here.get('user') || '',
  dms: (here.get('dms') || '').replace(/\/+$/, ''),
  api: here.get('api') || '/api/kpi',
};

$('#where').textContent = ARG.folder ? `${ARG.owner || ''} - ${ARG.folder}` : 'opened on its own';
if (ARG.kpi) { $('#id').value = ARG.kpi; $('#title').value = ARG.kpi.replace(/_/g, ' '); }
const say = (text, bad) => { const p = $('#say'); p.textContent = text || ''; p.className = bad ? 'err' : 'muted'; };

// What is already in that folder. The DMS answers a page it served with a key of its own; opened from the
// DMS menu the Builder is a site of its own, so it asks with the sign-in instead (DMS_ALLOWED_ORIGINS).
async function look() {
  if (!ARG.dms || !ARG.folder) return;
  const url = `${ARG.dms}/api/browse?path=${encodeURIComponent(ARG.folder + '\\Current_ReadOnly')}`;
  try {
    const r = await fetch(url, { credentials: 'include' });
    if (!r.ok) throw new Error(r.status === 403 ? 'not allowed to read that folder' : `the DMS answered ${r.status}`);
    const d = await r.json();
    const rows = (d.files || []).map(f => `<tr><td>${f.name}</td><td class="muted">${(f.size / 1024 | 0)} KB</td></tr>`);
    $('#list').innerHTML = `<tbody>${rows.join('') || '<tr><td class="muted">Nothing there yet.</td></tr>'}</tbody>`;
  } catch (e) {
    $('#list').innerHTML = `<tbody><tr><td class="err">The DMS was not read (${e.message}).
      The package can still be made; drop it into the DMS when it is ready.</td></tr></tbody>`;
  }
}
look();

const definition = () => ({
  kpi: ($('#id').value || '').trim(),
  title: ($('#title').value || '').trim(),
  owner: ARG.owner,
  source: $('#source').value,
  match: ($('#match').value || '*.md').trim(),
  column: ($('#column').value || '').trim(),
  kind: $('#kind').value,
  goal: $('#goal').value === '' ? null : Number($('#goal').value),
  madeBy: ARG.user,
  madeUtc: new Date().toISOString(),
  version: 1,
});

// A drawing of its own: the server has no way out to a chart library, and a KPI page must open anywhere.
function draw(svg, points, kind, goal) {
  const w = 640, h = 320, pad = 34;
  const values = points.map(p => p.value).filter(v => typeof v === 'number' && !isNaN(v));
  if (!values.length) { svg.innerHTML = '<text x="20" y="30" fill="#6b7280">Nothing to draw yet</text>'; return; }
  const top = Math.max(...values, goal || 0) * 1.1 || 1, step = (w - pad * 2) / Math.max(points.length - 1, 1);
  const y = v => h - pad - (v / top) * (h - pad * 2);
  const bits = [`<line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="#e5e7eb"/>`,
                `<line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h - pad}" stroke="#e5e7eb"/>`];
  if (goal != null) bits.push(`<line x1="${pad}" y1="${y(goal)}" x2="${w - pad}" y2="${y(goal)}" stroke="#b91c1c" stroke-dasharray="5 4"/>`);
  if (kind === 'number') {
    bits.push(`<text x="${w / 2}" y="${h / 2}" font-size="64" text-anchor="middle" fill="#0ea5a4">${values[values.length - 1]}</text>`);
  } else if (kind === 'bar') {
    points.forEach((p, i) => bits.push(`<rect x="${pad + i * step - step / 3}" y="${y(p.value)}" width="${Math.max(step / 1.6, 6)}" height="${h - pad - y(p.value)}" fill="#0ea5a4"/>`));
  } else {
    bits.push(`<polyline fill="none" stroke="#0ea5a4" stroke-width="2" points="${points.map((p, i) => `${pad + i * step},${y(p.value)}`).join(' ')}"/>`);
    points.forEach((p, i) => bits.push(`<circle cx="${pad + i * step}" cy="${y(p.value)}" r="3" fill="#0ea5a4"/>`));
  }
  points.forEach((p, i) => { if (points.length < 14 || i % Math.ceil(points.length / 12) === 0)
    bits.push(`<text x="${pad + i * step}" y="${h - pad + 16}" font-size="11" text-anchor="middle" fill="#6b7280">${p.label}</text>`); });
  svg.innerHTML = bits.join('');
}

$('#preview').onclick = () => {
  const made = definition();
  const points = [['Week 1', 62], ['Week 2', 68], ['Week 3', 71], ['Week 4', 66], ['Week 5', 74]]
    .map(([label, value]) => ({ label, value }));
  draw($('#chart'), points, made.kind, made.goal);
  say('A drawing of made-up numbers, to see the shape. The page reads the real ones from the DMS.');
};

const save = (name, text, type) => {
  const a = Object.assign(document.createElement('a'),
    { href: URL.createObjectURL(new Blob([text], { type })), download: name });
  a.click();
  URL.revokeObjectURL(a.href);
};

$('#make').onclick = () => {
  const made = definition();
  if (!made.kpi) return say('The KPI needs a name: its folder and its files are named after it.', true);
  if (!/^[\w\- ]{1,60}$/.test(made.kpi)) return say('A name of letters, numbers, spaces, - and _ only.', true);
  if (made.kind !== 'number' && !made.column) return say('Say which table heading holds the value.', true);
  save(`${made.kpi}.json`, JSON.stringify(made, null, 2), 'application/json');
  save(`${made.kpi}.html`, page(made), 'text/html');
  say(`${made.kpi}.html and ${made.kpi}.json were saved. Drop both on ${ARG.folder || 'the department’s KPIs folder'} in the DMS.`);
};

// The KPI's own page: it reads its definition and the exports beside it through the key the DMS gives it,
// and draws the same way this page draws. Nothing is fetched from anywhere else, so it opens on any PC.
function page(made) {
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${made.title || made.kpi}</title><link rel="icon" href="/dms/icon.png">
<style>body{margin:0;font:15px/1.5 "Segoe UI",system-ui,sans-serif;color:#1f2a37;background:#eef2f7}
header{display:flex;align-items:center;gap:12px;padding:12px 20px;background:#fff;border-bottom:1px solid #e5e7eb}
header img{height:26px}main{max-width:900px;margin:18px auto;padding:0 16px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px}
.muted{color:#6b7280;font-size:13px}.err{color:#b91c1c}svg{width:100%;height:340px}</style></head>
<body><header><img src="/dms/logo.png" alt="rh" onerror="this.remove()"><b>${made.title || made.kpi}</b>
<span class="muted">${made.owner || ''}</span></header>
<main><div class="card"><svg id="c" viewBox="0 0 640 320" preserveAspectRatio="none"></svg>
<p class="muted" id="s">Reading the DMS…</p></div></main>
<script>
const KPI = ${JSON.stringify(made)};
${draw.toString()}
const say = t => document.getElementById('s').innerHTML = t;
const rx = new RegExp('^' + KPI.match.replace(/[.+^\${}()|[\\]\\\\]/g, '\\\\$&').replace(/\\*/g, '.*') + '$', 'i');
const when = name => (name.match(/(\\d{2})[.\\-](\\d{2})[.\\-](\\d{4})/) || []).slice(1).reverse().join('-') || name;
// A table of the Markdown export: the row's first cell names it, the column we want holds the number.
function fromMarkdown(text, column) {
  const rows = text.split('\\n').filter(l => l.trim().startsWith('|'));
  if (rows.length < 2) return null;
  const head = rows[0].split('|').map(c => c.trim());
  const at = head.findIndex(c => c.toLowerCase() === column.toLowerCase());
  if (at < 0) return null;
  for (const row of rows.slice(2)) {
    const cells = row.split('|').map(c => c.trim());
    const n = parseFloat((cells[at] || '').replace(/[^\\d.\\-]/g, ''));
    if (!isNaN(n)) return n;
  }
  return null;
}
(async () => {
  const key = (window.DMS && window.DMS.key) || new URLSearchParams(location.search).get('t');
  const folder = (window.DMS && window.DMS.folder) || '';
  if (!key) return say('<span class="err">Open this page from the DMS: it is what gives it the key to read the folder.</span>');
  const where = folder + '\\\\Current_ReadOnly';
  const listed = await (await fetch('/api/kpi/files?t=' + encodeURIComponent(key) + '&path=' + encodeURIComponent(where))).json();
  const files = (listed.files || []).filter(f => rx.test(f.name)).sort((a, b) => a.name.localeCompare(b.name));
  const points = [];
  for (const f of files) {
    const text = await (await fetch('/api/kpi/file?t=' + encodeURIComponent(key) + '&path=' + encodeURIComponent(f.path))).text();
    const value = KPI.source === 'json' ? (JSON.parse(text)[KPI.column] ?? null) : fromMarkdown(text, KPI.column);
    if (value != null) points.push({ label: when(f.name), value: Number(value) });
  }
  draw(document.getElementById('c'), points, KPI.kind, KPI.goal);
  say(points.length ? points.length + ' report(s) read from ' + where
    : '<span class="err">Nothing matching ' + KPI.match + ' with a ' + KPI.column + ' column in ' + where + '</span>');
})();
<\/script></body></html>`;
}
