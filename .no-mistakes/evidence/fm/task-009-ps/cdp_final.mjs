// Render models.html embedded (host iframe) and assert responsive column hiding + pane width.
import http from 'node:http'; import fs from 'node:fs'; import path from 'node:path';
import { spawn } from 'node:child_process'; import { setTimeout as sleep } from 'node:timers/promises';

const REPO = path.resolve(import.meta.dirname, '..', '..', '..', '..');
const PORTAL = path.join(REPO, 'portal');
const EVID = import.meta.dirname;
const PORT = 8105;
const MIME = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.json':'application/json', '.svg':'image/svg+xml', '.png':'image/png' };
const HIGHLIGHT = 'unsloth/qwen3.6-27b';

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/host') {
    res.writeHead(200, { 'content-type': 'text/html' });
    res.end(`<!doctype html><meta charset=utf-8><style>html,body{margin:0;padding:0;background:#0f1117}iframe{border:0;width:100vw;height:100vh;display:block}</style>` +
      `<iframe src="/models.html?highlight=${encodeURIComponent(HIGHLIGHT)}"></iframe>`);
    return;
  }
  const file = path.join(PORTAL, p === '/' ? '/index.html' : p);
  fs.readFile(file, (err, buf) => {
    if (err) { res.writeHead(404); res.end('nf'); return; }
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' });
    res.end(buf);
  });
});
await new Promise(r => server.listen(PORT, '127.0.0.1', r));

const chrome = spawn('chromium', [
  '--headless=new', '--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage',
  '--hide-scrollbars', '--force-device-scale-factor=2',
  '--remote-debugging-port=9227', `--user-data-dir=/tmp/nm-final-${process.pid}`, 'about:blank',
], { stdio: ['ignore', 'ignore', 'ignore'] });
const cleanup = () => { try { chrome.kill('SIGKILL'); } catch {}; try { server.close(); } catch {}; };
process.on('exit', cleanup); process.on('SIGINT', () => process.exit(1));

let brWs; for (let i = 0; i < 80; i++) { try { brWs = (await (await fetch(`http://127.0.0.1:9227/json/version`)).json()).webSocketDebuggerUrl; break; } catch {} await sleep(150); }
if (!brWs) { console.error('no CDP'); cleanup(); process.exit(2); }

function makeCall(ws) { let id = 0; const pen = new Map(); ws.addEventListener('message', e => { const m = JSON.parse(e.data); if (m.id && pen.has(m.id)) { pen.get(m.id)(m); pen.delete(m.id); } }); return (method, params = {}) => new Promise(r => { const i = ++id; pen.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); }); }
const bws = new WebSocket(brWs); await new Promise(r => bws.addEventListener('open', r, { once: true })); const bcall = makeCall(bws);
const { result: { targetId } } = await bcall('Target.createTarget', { url: `http://127.0.0.1:${PORT}/host` });

let pageWsUrl; for (let i = 0; i < 80; i++) { const list = await (await fetch(`http://127.0.0.1:9227/json`)).json(); const t = list.find(x => x.id === targetId); if (t) { pageWsUrl = t.webSocketDebuggerUrl; break; } await sleep(150); }
const pws = new WebSocket(pageWsUrl); await new Promise(r => pws.addEventListener('open', r, { once: true })); const call = makeCall(pws);
await call('Page.enable'); await call('Runtime.enable');

const COLS = ['model','local','shelf','ctx','params','active','spark','dl','release_date','arch','engine','inf','bench','caps'];
const LABEL = { model:'Model', local:'Local', shelf:'Shelf', ctx:'Max CTX', params:'Params', active:'Active', spark:'Spark', dl:'Download', release_date:'Released', arch:'Arch', engine:'Engine', inf:'Inference', bench:'Bench', caps:'Caps' };

const ev = (ex) => call('Runtime.evaluate', { expression: ex, returnByValue: true, awaitPromise: true });
// wait until the embedded iframe has rendered model rows
let rows = 0;
for (let i = 0; i < 120; i++) {
  const r = await ev(`(function(){try{var f=document.querySelector('iframe');return f&&f.contentDocument?f.contentDocument.querySelectorAll('tbody tr.model-row').length:0;}catch(e){return 0;}}())`);
  rows = r.result?.result?.value ?? 0;
  if (rows > 0) break;
  await sleep(150);
}

const stateExpr = `(function(){
  var f=document.querySelector('iframe'); var w=f.contentWindow; var d=f.contentDocument; var g=w.getComputedStyle.bind(w);
  function vis(sel){var e=d.querySelector(sel);return e?g(e).display:'absent';}
  var cols=${JSON.stringify(COLS)};
  var out={cols:{}};
  cols.forEach(function(k){ out.cols[k]={th:vis('thead th[data-col="'+k+'"]'), td:vis('tbody td[data-col="'+k+'"]')}; });
  var pane=d.getElementById('model-detail-pane'); var st=g(pane);
  out.pane={open:!!d.body.dataset.pane, width:st.width, minWidth:st.minWidth, maxWidth:st.maxWidth, position:st.position, transform:st.transform};
  out.iw=w.innerWidth; out.rows=d.querySelectorAll('tbody tr.model-row').length;
  out.url=w.location.href;
  return JSON.stringify(out);
})()`;

const WIDTHS = [
  { w: 1600, name: 'w1600_all-columns', expectHidden: [] },
  { w: 1350, name: 'w1350_spark-hidden', expectHidden: ['spark'] },
  { w: 1200, name: 'w1200_spark-dl-hidden', expectHidden: ['spark','dl'] },
  { w: 1000, name: 'w1000_shelf-hidden', expectHidden: ['spark','dl','shelf'] },
  { w: 850,  name: 'w850_below-900', expectHidden: ['spark','dl','shelf','arch','engine','bench','release_date','ctx'] },
  { w: 600,  name: 'w600_mobile', expectHidden: ['spark','dl','shelf','arch','engine','bench','release_date','ctx'] },
];
const ALWAYS_VISIBLE = ['model','local','params','active','inf','caps'];

const results = [];
let failures = 0;
for (const { w, name, expectHidden } of WIDTHS) {
  await call('Emulation.setDeviceMetricsOverride', { width: w, height: 1200, deviceScaleFactor: 2, mobile: false });
  await ev('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');
  const raw = (await ev(stateExpr)).result.result.value;
  const st = JSON.parse(raw);
  const hidden = COLS.filter(c => st.cols[c].th === 'none');
  const missing = expectHidden.filter(c => !hidden.includes(c));
  const extra = hidden.filter(c => !expectHidden.includes(c));
  const brokenAlways = ALWAYS_VISIBLE.filter(c => st.cols[c].th === 'none');
  // pane expectations
  let paneNote = `open=${st.pane.open} width=${st.pane.width} min=${st.pane.minWidth} pos=${st.pane.position}`;
  let paneOk = true;
  if (w >= 900) { paneOk = st.pane.position === 'sticky' && st.pane.open; }
  else { paneOk = st.pane.position === 'fixed' && st.pane.open; }
  const ok = !missing.length && !extra.length && !brokenAlways.length && paneOk;
  if (!ok) failures++;
  console.log(`w=${w} iw=${st.iw} rows=${st.rows} ${ok?'OK':'FAIL'} | hidden=[${hidden.join(',')}] | ${paneNote}` +
    (missing.length?` | MISS=[${missing.join(',')}]`:'') + (extra.length?` | EXTRA=[${extra.join(',')}]`:'') + (brokenAlways.length?` | HIDDEN-BUT-SHOULD-SHOW=[${brokenAlways.join(',')}]`:'') + (!paneOk?` | PANE-FAIL`:''));
  // screenshot
  const shot = await call('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(path.join(EVID, `models_${name}.png`), Buffer.from(shot.result.data, 'base64'));
  results.push({ width: w, name, hidden, missing, extra, brokenAlways, pane: st.pane, ok, iw: st.iw, rows: st.rows });
}

// Also capture a wide standalone-style shot with pane open at exactly 1400 boundary check + 30vw math
const w1600pane = results[0].pane;
console.log(`\nrows_rendered=${rows} | pane@1600 width=${w1600pane.width} (30vw of 1600=${1600*0.3}, floor min 520) pos=${w1600pane.position}`);
fs.writeFileSync(path.join(EVID, 'responsive_report.json'), JSON.stringify({ rows, results, note: '30vw with min-width 520; at w=1600 30vw=480 so min-width 520 binds' }, null, 2));
console.log('FAILURES=' + failures);
cleanup();
process.exit(failures ? 3 : 0);
