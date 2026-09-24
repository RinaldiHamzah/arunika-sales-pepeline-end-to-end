/**
 * Dashboard-only regression test. Uses Node 22+ and installed Chrome/Edge.
 * No database, credentials, Python imports, or production API calls.
 * Run: node dashboard/tests/browser_smoke.mjs
 */
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { spawn } from 'node:child_process';
import { readFile, mkdtemp, rm, access, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const profile = await mkdtemp(path.join(tmpdir(), 'arunika-ui-test-'));
const examples = [{ label: 'Wardah', value: 31383000, orders: 40 }];
const fixture = {
  filters: { start: '2026-01-01', end: '2026-09-20' },
  options: { channels: ['Shopee', 'Tokopedia'], statuses: ['COMPLETED'], categories: ['Skincare'], brands: ['Wardah'], products: ['WRD-SKC-001'] },
  metrics: { net_sales: 31383000, gross_sales: 32383000, orders: 241, units: 374, average_order_value: 130220, return_rate: 17.4 },
  charts: {
    month: [{ label: '2026-08', net: 1000000, gross: 1200000 }, { label: '2026-09', net: 2000000, gross: 2500000 }],
    channel: examples, brand: examples, category: examples, sku: examples, status: examples,
    product: [{ label: 'Wardah UV Shield Aqua Fresh Essence SPF 50 PA++++ 30ml', quantity: 30, net_sales: 1000000 }],
    city: [{ label: 'Yogyakarta', value: 1000000 }],
  },
  observability: {},
  rows: Array.from({ length: 61 }, (_, i) => ({
    order_id: 'ORDER-' + i, order_date: '2026-09-20', channel_name: 'Shopee',
    product_name: 'Wardah UV Shield Aqua Fresh Essence SPF 50 PA++++ 30ml',
    category: 'Skincare', status: 'COMPLETED', quantity: 2, net_amount: 137800,
  })),
};
let fail = false;
let blockChart = false;
let dashboardRequests = 0;
const requests = [];
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.startsWith('/api/')) {
    requests.push(url.pathname);
    res.setHeader('Content-Type', 'application/json');
    if (url.pathname === '/api/dashboard') {
      dashboardRequests++;
      res.statusCode = fail ? 503 : 200;
      res.end(JSON.stringify(fail ? { error: 'Fixture: database unavailable' } : fixture));
    } else if (url.pathname === '/api/admin/operations') {
      res.end(JSON.stringify({ failed_runs_last_7_days: 1, recent_runs: [{
        run_id: 'test-run-001', status: 'SUCCESS', started_at: '2026-09-20T10:00:00+07:00',
        ended_at: '2026-09-20T10:00:02+07:00', duration_seconds: 2,
        extracted_records: 20, validated_records: 18, rejected_records: 2,
        duplicate_records: 0, incremental_records: 18, loaded_records: 18,
        source_records: 120, skipped_unchanged_records: 100, fact_skipped_records: 0,
        outcome_message: '18 fact ditulis; 100 baris identik dilewati.',
        source_metrics: [{ source_name: 'SHOPEE', source_records: 120, skipped_unchanged_records: 100,
          extracted_records: 20, validated_records: 18, rejected_records: 2, duplicate_records: 0 }],
      }] }));
    } else if (url.pathname === '/api/pipeline/run') {
      res.end(JSON.stringify({ status: 'started' }));
    } else if (url.pathname === '/api/pipeline/progress') {
      res.end(JSON.stringify({ run: { status: 'RUNNING', current_stage: 'staging_load' } }));
    } else if (url.pathname === '/api/ingestion/upload') {
      res.end(JSON.stringify({ rows_appended: 20, source: 'shopee', next_step: 'Jalankan pipeline.' }));
    } else res.end('{}');
    return;
  }
  try {
    if (url.pathname === '/') {
      const child = await readFile(path.join(root, 'templates/dashboard.html'), 'utf8');
      const content = child.match(/\{% block page_content %\}([\s\S]*?)\{% endblock %\}/)?.[1];
      if (content === undefined) throw new Error('Dashboard content block was not found');
      let template = await readFile(path.join(root, 'templates/base.html'), 'utf8');
      template = template.replace('{% block page_content %}{% endblock %}', content);
      for (const partial of ['transactions', 'settings']) {
        const include = `{% include "${partial}.html" %}`;
        const markup = await readFile(path.join(root, `templates/${partial}.html`), 'utf8');
        template = template.replace(include, markup);
      }
      res.setHeader('Content-Type', 'text/html; charset=utf-8');
      res.end(template.replace(/\{\{ url_for\('static', filename='([^']+)'[^}]*\}\}/g, (_, file) => '/static/' + file));
      return;
    }
    if (blockChart && url.pathname.includes('chart.umd')) throw new Error('Offline chart test');
    const target = path.resolve(root, '.' + url.pathname);
    if (!target.startsWith(path.join(root, 'static') + path.sep)) throw new Error('Not a static file');
    const types = { '.js': 'text/javascript', '.css': 'text/css' };
    res.setHeader('Content-Type', (types[path.extname(target)] || 'application/octet-stream') + '; charset=utf-8');
    res.end(await readFile(target));
  } catch {
    res.statusCode = 404;
    res.end('Not found');
  }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = 'http://127.0.0.1:' + server.address().port;
console.log('Test server ready');
let browser;
let socket;
try {
  const candidates = [
    process.env.BROWSER_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  ].filter(Boolean);
  let executable;
  for (const candidate of candidates) {
    try { await access(candidate); executable = candidate; break; } catch { /* Try next browser. */ }
  }
  assert.ok(executable, 'Set BROWSER_PATH to a Chromium browser executable.');
  browser = spawn(executable, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
    '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
    '--user-data-dir=' + profile, 'about:blank',
  ], { windowsHide: true, stdio: 'ignore' });
  browser.on('error', error => console.error(error.message));
  let port;
  for (let i = 0; i < 100; i++) {
    try { port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; } catch { await wait(100); }
  }
  assert.ok(port, 'Browser remote debugging did not start.');
  console.log('Browser ready');
  const pages = await (await fetch('http://127.0.0.1:' + port + '/json')).json();
  socket = new WebSocket(pages.find(page => page.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Browser WebSocket timeout')), 10000);
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Browser WebSocket error')); }, { once: true });
  });
  console.log('Browser connected');
  let id = 0;
  const pending = new Map();
  const errors = [];
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params.exceptionDetails);
    if (message.id) {
      const callback = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) callback.reject(new Error(JSON.stringify(message.error)));
      else callback.resolve(message.result);
    }
  });
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const requestId = ++id;
    const timeout = setTimeout(() => reject(new Error('CDP timeout: ' + method)), 10000);
    pending.set(requestId, {
      resolve: value => { clearTimeout(timeout); resolve(value); },
      reject: error => { clearTimeout(timeout); reject(error); },
    });
    socket.send(JSON.stringify({ id: requestId, method, params }));
  });
  const evaluate = async expression => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  const until = async expression => {
    for (let i = 0; i < 100; i++) { if (await evaluate(expression)) return; await wait(50); }
    throw new Error('Timed out: ' + expression);
  };
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.addScriptToEvaluateOnNewDocument', {
    source: 'window.__intervals=[]; const originalInterval=window.setInterval; window.setInterval=(fn, ms)=>{ if(ms===30000) window.__intervals.push(fn); return originalInterval(fn,ms); };',
  });
  await send('Page.navigate', { url: origin });
  await until("document.getElementById('metric-orders')?.textContent === '241'");
  console.log('Initial render ready');
  assert.equal(await evaluate("document.querySelectorAll('.chart-data').length"), 6);
  for (const width of [320, 375, 640, 768, 1024, 1440]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false });
    for (const tab of ['summary', 'sales', 'products']) {
      await evaluate("location.hash='overview'; document.querySelector('[data-overview-tab=" + tab + "]').click()");
      await wait(100);
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'Overflow at ' + width + '/' + tab);
      assert.equal(await evaluate("document.querySelectorAll('[data-overview-panel]:not([hidden])').length"), 1);
    }
    for (const page of ['transactions', 'settings']) {
      await evaluate("location.hash='" + page + "'");
      await wait(100);
      assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'Overflow at ' + width + '/' + page);
    }
    if (width <= 640) {
      assert.equal(await evaluate("getComputedStyle(document.querySelector('#transaction-rows tr')).display"), 'block');
      assert.equal(await evaluate("document.querySelector('#transaction-rows td').dataset.label"), 'Tanggal');
    }
  }
  await evaluate("location.hash='overview'; document.getElementById('tab-summary').focus(); document.getElementById('tab-summary').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowRight', bubbles:true}))");
  assert.equal(await evaluate("document.getElementById('tab-sales').getAttribute('aria-selected')"), 'true');
  await evaluate("location.hash='transactions'");
  await wait(100);
  await evaluate("document.getElementById('next-page').click(); document.activeElement.blur()");
  assert.equal(await evaluate("document.getElementById('page-info').textContent"), 'Halaman 2 / 3');
  const previousRequests = dashboardRequests;
  await evaluate('window.__intervals[0]()');
  await until("!document.getElementById('refresh-button').disabled");
  assert.ok(dashboardRequests > previousRequests, 'Auto refresh requested dashboard');
  assert.equal(await evaluate("document.getElementById('page-info').textContent"), 'Halaman 2 / 3');
  await evaluate("location.hash='overview'; document.getElementById('reset-button').click()");
  await until("!document.getElementById('refresh-button').disabled");
  assert.equal(await evaluate("document.getElementById('page-info').textContent"), 'Halaman 1 / 3');
  await evaluate("location.hash='settings'; document.getElementById('admin-token').value='fixture-only'; document.getElementById('operations-button').click()");
  await until("document.querySelectorAll('#operation-run-rows td').length===11");
  assert.equal(await evaluate("document.querySelector('#operation-run-rows td:last-child').textContent"), '18');
  await evaluate("document.querySelector('.run-explanation').open=true");
  assert.equal(await evaluate("document.querySelector('.run-explanation').textContent.includes('100')"), true);
  for (const width of [320, 375, 640, 1440]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await wait(100);
    assert.equal(await evaluate('document.documentElement.scrollWidth <= innerWidth'), true, 'Run explanation overflow at ' + width);
  }
  await evaluate("document.getElementById('run-pipeline').click()");
  await until("document.getElementById('pipeline-progress').textContent.includes('staging_load')");
  assert.ok(requests.includes('/api/pipeline/run'));
  await evaluate("const input=document.getElementById('upload-file'); const dt=new DataTransfer(); dt.items.add(new File(['order_id\\n1'], 'new-batch.csv', {type:'text/csv'})); input.files=dt.files; input.dispatchEvent(new Event('change')); document.getElementById('upload-button').click()");
  await until("document.getElementById('message').textContent.includes('20 baris')");
  fail = true;
  await send('Page.navigate', { url: origin + '/?case=initial-failure#settings' });
  await until("document.getElementById('message')?.textContent.includes('unavailable')");
  assert.equal(await evaluate("document.getElementById('settings').classList.contains('active')"), true);
  fail = false;
  await evaluate("document.getElementById('refresh-button').click()");
  await until("document.getElementById('metric-orders').textContent==='241'");
  blockChart = true;
  await send('Page.navigate', { url: origin + '/?case=offline-chart' });
  await until("document.getElementById('metric-orders')?.textContent==='241'");
  assert.equal(await evaluate("document.querySelector('.chart-data').open"), true);
  assert.equal(await evaluate("document.querySelectorAll('.chart-table tbody tr').length>0"), true);
  blockChart = false;
  await send('Page.navigate', { url: origin + '/?case=screenshots' });
  await until("document.getElementById('metric-orders')?.textContent==='241'");
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  for (const [page, name] of [['overview', 'dashboard-overview'], ['transactions', 'dashboard-transactions'], ['settings', 'dashboard-settings']]) {
    await evaluate(`location.hash='${page}'`);
    await wait(200);
    const screenshot = await send('Page.captureScreenshot', { format: 'png' });
    const target = path.join(tmpdir(), 'arunika-' + name + '.png');
    await writeFile(target, Buffer.from(screenshot.data, 'base64'));
    console.log('SCREENSHOT ' + target);
  }
  assert.deepEqual(errors, [], 'No uncaught JavaScript errors');
  console.log('PASS: 6 widths × 6 views; tabs; mobile cards; pagination; refresh; reset; upload; run; history; API recovery; chart fallback.');
} finally {
  socket?.close();
  browser?.kill();
  server.closeAllConnections();
  server.close();
  await wait(1000);
  // Only remove the dedicated temporary browser profile created by this test.
  if (path.dirname(profile) === path.resolve(tmpdir()) && path.basename(profile).startsWith('arunika-ui-test-')) {
    await rm(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 500 }).catch(() => {});
  }
}
