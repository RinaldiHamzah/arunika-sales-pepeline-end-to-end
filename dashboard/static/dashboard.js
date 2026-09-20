/* Dashboard client: API access, state, rendering, and event wiring. */
const state = {
  charts: {},
  rows: [],
  page: 1,
  pageSize: 25,
  defaultFilters: { start: '', end: '' },
  pipelineProgressTimer: null,
  pipelineProgressAttempts: 0,
};
const JAKARTA_TIME_ZONE = 'Asia/Jakarta';
const pageMetadata = {
  overview: {
    title: 'Sales intelligence',
    subtitle: 'Ringkasan penjualan terintegrasi dari marketplace, website, dan toko offline.',
  },
  transactions: {
    title: 'Transactions',
    subtitle: 'Telusuri transaksi warehouse yang telah melewati proses data quality.',
  },
  settings: {
    title: 'Settings',
    subtitle: 'Kelola batch data, jalankan pipeline, dan pantau riwayat eksekusi.',
  },
};

const $ = (id) => document.getElementById(id);
const money = (value) => new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(value || 0);
const number = (value) => new Intl.NumberFormat('id-ID').format(value || 0);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' })[char]);

function formatJakartaDateTime(value) {
  return value
    ? new Date(value).toLocaleString('id-ID', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: JAKARTA_TIME_ZONE,
    })
    : '—';
}

function selectedValues(id) {
  return [...$(id).selectedOptions].map((option) => option.value).filter(Boolean);
}

function addOptions(id, items) {
  const select = $(id);
  if (select.options.length > 1) return;
  [...new Set(items.filter(Boolean))].forEach((item) => select.add(new Option(item, item)));
}

function buildQuery() {
  const query = new URLSearchParams({ start: $('start-date').value, end: $('end-date').value });
  [['channel-filter', 'channel'], ['status-filter', 'status'], ['category-filter', 'category'], ['brand-filter', 'brand'], ['product-filter', 'product']]
    .forEach(([elementId, parameter]) => selectedValues(elementId).forEach((value) => query.append(parameter, value)));
  return query;
}

function adminHeaders() {
  const token = $('admin-token')?.value.trim();
  if (!token) throw new Error('Masukkan admin token sebelum menjalankan operasi admin.');
  return { 'X-Admin-Token': token };
}

function showError(message) { $('message').textContent = message; $('message').classList.remove('hidden'); }
function clearError() { $('message').classList.add('hidden'); }

function setPage(pageName) {
  const selectedPage = pageMetadata[pageName] ? pageName : 'overview';
  document.querySelectorAll('.dashboard-page').forEach((page) => {
    page.classList.toggle('active', page.dataset.page === selectedPage);
  });
  document.querySelectorAll('[data-page-link]').forEach((link) => {
    link.classList.toggle('active', link.dataset.pageLink === selectedPage);
  });
  $('page-title').textContent = pageMetadata[selectedPage].title;
  $('page-subtitle').textContent = pageMetadata[selectedPage].subtitle;
}

function syncPageFromHash() {
  setPage(window.location.hash.replace('#', '') || 'overview');
}

async function requestJson(url, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  let response;
  try {
    response = await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Dashboard tidak menerima respons data dalam 20 detik. Silakan refresh atau periksa koneksi database.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || 'Request dashboard gagal.');
  return data;
}

function fallbackChartItems(config) {
  const labels = config.data.labels || [];
  const datasets = config.data.datasets || [];
  if (config.type === 'line') {
    return labels.map((label, index) => ({
      label,
      value: Number(datasets[0]?.data[index] || 0),
      secondary: Number(datasets[1]?.data[index] || 0),
    }));
  }
  return labels.map((label, index) => ({
    label,
    value: Number(datasets[0]?.data[index] || 0),
    secondary: null,
  }));
}

function drawFallbackChart(canvas, config) {
  const container = canvas.parentElement;
  container.querySelector('.fallback-chart')?.remove();
  canvas.hidden = true;
  const items = fallbackChartItems(config);
  const maximum = Math.max(...items.map((item) => item.value), 1);
  const fallback = document.createElement('div');
  fallback.className = 'fallback-chart';
  fallback.setAttribute('role', 'img');
  fallback.setAttribute('aria-label', `Ringkasan ${config.type} chart`);
  fallback.innerHTML = items.slice(0, 8).map((item) => {
    const width = Math.max((item.value / maximum) * 100, 2);
    const secondary = item.secondary == null ? '' : `<small>Gross ${money(item.secondary)}</small>`;
    return `
      <div class="fallback-chart-row">
        <div class="fallback-chart-label" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</div>
        <div class="fallback-chart-bar"><span style="width: ${width}%"></span></div>
        <div class="fallback-chart-value">${money(item.value)}${secondary}</div>
      </div>
    `;
  }).join('') || '<p class="empty">Tidak ada data untuk chart ini.</p>';
  container.append(fallback);
}

function drawChart(id, config) {
  const canvas = $(`${id}-chart`);
  if (!canvas) return;
  if (!window.Chart) {
    drawFallbackChart(canvas, config);
    return;
  }
  canvas.hidden = false;
  canvas.parentElement.querySelector('.fallback-chart')?.remove();
  state.charts[id]?.destroy();
  state.charts[id] = new Chart(canvas, config);
}

function horizontalChart(items, color) {
  return { type: 'bar', data: { labels: items.map((item) => item.label), datasets: [{ data: items.map((item) => item.value), backgroundColor: color, borderRadius: 6 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => money(context.raw) } } }, scales: { x: { ticks: { callback: (value) => money(value) } }, y: { grid: { display: false } } } } };
}

function renderRankList(id, items, mode) {
  $(id).innerHTML = items.length ? items.map((item, index) => `<div class="rank-row"><span class="rank">${String(index + 1).padStart(2, '0')}</span><span class="rank-name">${escapeHtml(item.label)}</span><span class="rank-value">${mode === 'quantity' ? number(item.quantity) : number(item.orders)}<small>${money(item.net_sales)}</small></span></div>`).join('') : '<p class="empty">Tidak ada data untuk filter ini.</p>';
}

function renderTransactions() {
  const totalPages = Math.max(1, Math.ceil(state.rows.length / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const start = (state.page - 1) * state.pageSize;
  const rows = state.rows.slice(start, start + state.pageSize);
  $('transaction-rows').innerHTML = rows.length ? rows.map((row) => `<tr><td>${row.order_date}</td><td>${escapeHtml(row.order_id)}</td><td>${escapeHtml(row.channel_name)}</td><td>${escapeHtml(row.product_name)}</td><td>${escapeHtml(row.category)}</td><td><span class="status">${escapeHtml(row.status)}</span></td><td>${number(row.quantity)}</td><td>${money(row.net_amount)}</td></tr>`).join('') : '<tr><td colspan="8" class="empty">Tidak ada transaksi pada periode ini.</td></tr>';
  $('row-count').textContent = `${number(state.rows.length)} rows`;
  $('page-info').textContent = `Page ${state.page} / ${totalPages}`;
  $('prev-page').disabled = state.page === 1;
  $('next-page').disabled = state.page === totalPages;
}

function renderCharts(data) {
  drawChart('month', { type: 'line', data: { labels: data.charts.month.map((item) => item.label), datasets: [{ label: 'Net sales', data: data.charts.month.map((item) => item.net), borderColor: '#126b63', backgroundColor: 'rgba(18,107,99,.12)', fill: true, tension: .35 }, { label: 'Gross sales', data: data.charts.month.map((item) => item.gross), borderColor: '#f28a61', tension: .35 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'bottom' } }, scales: { y: { ticks: { callback: (value) => money(value) } }, x: { grid: { display: false } } } } });
  drawChart('channel', { type: 'doughnut', data: { labels: data.charts.channel.map((item) => item.label), datasets: [{ data: data.charts.channel.map((item) => item.value), backgroundColor: ['#126b63', '#f28a61', '#75b9a7', '#e4bd65'], borderWidth: 0 }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '65%', plugins: { legend: { position: 'bottom' } } } });
  drawChart('brand', horizontalChart(data.charts.brand, '#126b63'));
  drawChart('category', horizontalChart(data.charts.category, '#75b9a7'));
  drawChart('sku', horizontalChart(data.charts.sku, '#f28a61'));
}

function renderDashboard(data) {
  const metrics = data.metrics;
  const observability = data.observability || {};
  const run = observability.latest_run;
  state.rows = data.rows || [];
  [['metric-sales', money(metrics.net_sales)], ['metric-gross', money(metrics.gross_sales)], ['metric-orders', number(metrics.orders)], ['metric-units', number(metrics.units)], ['metric-aov', money(metrics.average_order_value)], ['metric-return-rate', `${(metrics.return_rate || 0).toFixed(1)}%`]].forEach(([id, value]) => { $(id).textContent = value; });
  $('metric-sales-change').textContent = metrics.net_change_percent == null ? 'No prior-period comparison' : `${metrics.net_change_percent >= 0 ? '▲' : '▼'} ${Math.abs(metrics.net_change_percent).toFixed(1)}% vs prior period`;
  $('pipeline-status').textContent = run?.status || 'NO RUN';
  if (run) {
    const startedAt = formatJakartaDateTime(run.started_at);
    $('pipeline-run').textContent = `Run ${String(run.run_id).slice(0, 8)} · ${startedAt}`;
    $('pipeline-volume').textContent = `${number(run.fact_inserted_records)} fakta berhasil dimuat`;
  } else {
    $('pipeline-run').textContent = 'Belum ada pipeline run';
    $('pipeline-volume').textContent = 'Belum ada data dimuat';
  }
  $('pipeline-success-rate').textContent = `${(observability.pipeline_success_rate || 0).toFixed(1)}%`;
  $('pipeline-duration').textContent = observability.pipeline_duration == null ? '—' : `${Number(observability.pipeline_duration).toFixed(1)}s`;
  $('pipeline-rejected-rate').textContent = `${(observability.rejected_record_rate || 0).toFixed(1)}%`;
  $('source-freshness').innerHTML = (observability.source_freshness || []).map((source) => `<span>${escapeHtml(source.source_name)}</span>`).join('') || 'No ingestion data';
  renderCharts(data); renderRankList('product-list', data.charts.product, 'quantity'); renderRankList('status-list', data.charts.status, 'orders'); renderTransactions();
  $('updated-at').textContent = `Diperbarui ${new Date().toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', timeZone: JAKARTA_TIME_ZONE })} WIB`;
}

async function loadDashboard() {
  const refreshButton = $('refresh-button');
  refreshButton.disabled = true;
  refreshButton.textContent = 'Memuat…';
  $('updated-at').textContent = 'Memuat data warehouse…';
  try {
    const data = await requestJson(`/api/dashboard?${buildQuery()}`);
    clearError();
    state.page = 1;
    renderDashboard(data);
  } catch (error) {
    showError(error.message);
  } finally {
    refreshButton.disabled = false;
    refreshButton.textContent = 'Refresh data';
  }
}

function formatInputDate(value) {
  return [
    value.getFullYear(),
    String(value.getMonth() + 1).padStart(2, '0'),
    String(value.getDate()).padStart(2, '0'),
  ].join('-');
}

function setActivePreset(activePreset = '') {
  document.querySelectorAll('[data-preset]').forEach((button) => {
    button.classList.toggle('active', button.dataset.preset === activePreset);
  });
}

function setPreset(preset) {
  const end = new Date();
  const start = new Date(end);
  if (preset === 'ytd') start.setMonth(0, 1);
  else if (preset !== 'today') start.setDate(end.getDate() - Number(preset) + 1);
  $('start-date').value = formatInputDate(start);
  $('end-date').value = formatInputDate(end);
  setActivePreset(preset);
  loadDashboard();
}

function resetFilters() {
  document.querySelectorAll('.filter-card select').forEach((select) => {
    select.selectedIndex = 0;
  });
  $('start-date').value = state.defaultFilters.start;
  $('end-date').value = state.defaultFilters.end;
  document.querySelector('.advanced-filters').open = false;
  setActivePreset();
  state.page = 1;
  loadDashboard();
}

function downloadTransactions() {
  window.location = `/api/dashboard/export?${buildQuery()}`;
}

function stopPipelinePolling() {
  if (state.pipelineProgressTimer) window.clearTimeout(state.pipelineProgressTimer);
  state.pipelineProgressTimer = null;
}

function setPipelineProgress(message, stateName = 'idle') {
  const progress = $('pipeline-progress');
  progress.textContent = message;
  progress.dataset.state = stateName;
}

async function pollPipelineProgress() {
  try {
    const data = await requestJson('/api/pipeline/progress', { headers: adminHeaders() });
    const run = data.run;
    const button = $('run-pipeline');
    if (!run || (run.status !== 'RUNNING' && state.pipelineProgressAttempts < 10)) {
      state.pipelineProgressAttempts += 1;
      setPipelineProgress('Menunggu pipeline dimulai…', 'running');
      state.pipelineProgressTimer = window.setTimeout(pollPipelineProgress, 1000);
      return;
    }
    if (run.status === 'RUNNING') {
      state.pipelineProgressAttempts = 0;
      setPipelineProgress(`Tahap aktif: ${run.current_stage || 'menyiapkan'}`, 'running');
      state.pipelineProgressTimer = window.setTimeout(pollPipelineProgress, 1000);
      return;
    }
    stopPipelinePolling();
    button.disabled = false;
    button.textContent = 'Jalankan sekarang';
    if (run.status === 'SUCCESS') {
      setPipelineProgress(`Selesai · ${formatJakartaDateTime(run.ended_at)} WIB`, 'success');
      loadDashboard();
    } else {
      setPipelineProgress('Pipeline gagal. Lihat riwayat eksekusi.', 'failed');
    }
  } catch (error) {
    stopPipelinePolling();
    $('run-pipeline').disabled = false;
    $('run-pipeline').textContent = 'Jalankan sekarang';
    setPipelineProgress('Status pipeline tidak dapat dimuat.', 'failed');
    showError(error.message);
  }
}

async function runPipeline() {
  const button = $('run-pipeline');
  button.disabled = true;
  button.textContent = 'Memulai…';
  try {
    const data = await requestJson('/api/pipeline/run', { method: 'POST', headers: adminHeaders() });
    stopPipelinePolling();
    state.pipelineProgressAttempts = 0;
    if (data.status === 'already_running') {
      button.textContent = 'Pipeline berjalan';
      setPipelineProgress('Pipeline sudah berjalan. Memuat tahap aktif…', 'running');
    } else {
      button.textContent = 'Pipeline berjalan';
      setPipelineProgress('Pipeline dimulai. Memuat tahap aktif…', 'running');
    }
    state.pipelineProgressTimer = window.setTimeout(pollPipelineProgress, 500);
  } catch (error) {
    button.disabled = false;
    button.textContent = 'Jalankan sekarang';
    setPipelineProgress('Pipeline belum dijalankan.', 'failed');
    showError(error.message);
  }
}

function updateFileName() {
  const file = $('upload-file').files[0];
  $('upload-file-name').textContent = file ? file.name : 'Belum ada file';
}

async function uploadBatch() { const file = $('upload-file').files[0]; if (!file) return showError('Pilih file CSV terlebih dahulu.'); const button = $('upload-button'); button.disabled = true; button.textContent = 'Uploading…'; try { const body = new FormData(); body.append('source', $('upload-source').value); body.append('file', file); const data = await requestJson('/api/ingestion/upload', { method: 'POST', headers: adminHeaders(), body }); $('message').textContent = `${data.rows_appended} rows ditambahkan ke ${data.source}. ${data.next_step}`; $('message').classList.remove('hidden'); $('upload-file').value = ''; updateFileName(); button.textContent = 'Uploaded'; } catch (error) { showError(error.message); button.textContent = 'Upload batch'; } finally { button.disabled = false; } }

function formatDateTime(value) { return formatJakartaDateTime(value); }

function renderOperationRows(runs) {
  if (!runs.length) {
    return '<tr><td class="empty" colspan="10">Belum ada pipeline run.</td></tr>';
  }
  return runs.map((run) => `
    <tr>
      <td>${escapeHtml(String(run.run_id).slice(0, 8))}</td>
      <td><span class="status">${escapeHtml(run.status)}</span></td>
      <td>${formatDateTime(run.started_at)}</td>
      <td>${run.duration_seconds == null ? '—' : `${Number(run.duration_seconds).toFixed(1)}s`}</td>
      <td>${number(run.extracted_records)}</td>
      <td>${number(run.validated_records)}</td>
      <td>${number(run.rejected_records)}</td>
      <td>${number(run.duplicate_records)}</td>
      <td>${number(run.incremental_records)}</td>
      <td>${number(run.fact_inserted_records)}</td>
    </tr>
  `).join('');
}

async function loadOperations() {
  const button = $('operations-button');
  button.disabled = true;
  button.textContent = 'Memuat…';
  try {
    const data = await requestJson('/api/admin/operations', { headers: adminHeaders() });
    const latest = data.recent_runs[0];
    $('operations-empty').classList.add('hidden');
    $('operations-content').classList.remove('hidden');
    $('operation-latest-status').textContent = latest?.status || 'NO RUN';
    $('operation-latest-facts').textContent = number(latest?.fact_inserted_records);
    $('failed-runs').textContent = number(data.failed_runs_last_7_days);
    $('operation-run-rows').innerHTML = renderOperationRows(data.recent_runs);
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Check status';
  }
}

function bindEvents() {
  $('apply-button').onclick = loadDashboard;
  $('refresh-button').onclick = loadDashboard;
  $('reset-button').onclick = resetFilters;
  $('download-transactions').onclick = downloadTransactions;
  $('run-pipeline').onclick = runPipeline;
  $('upload-button').onclick = uploadBatch;
  $('upload-file').onchange = updateFileName;
  $('operations-button').onclick = loadOperations;
  $('prev-page').onclick = () => { state.page -= 1; renderTransactions(); };
  $('next-page').onclick = () => { state.page += 1; renderTransactions(); };
  document.querySelectorAll('[data-preset]').forEach((button) => {
    button.onclick = () => setPreset(button.dataset.preset);
  });
  window.addEventListener('hashchange', syncPageFromHash);
}

async function initialise() {
  const data = await requestJson('/api/dashboard');
  $('start-date').value = data.filters.start;
  $('end-date').value = data.filters.end;
  state.defaultFilters = { start: data.filters.start, end: data.filters.end };
  addOptions('channel-filter', data.options.channels);
  addOptions('status-filter', data.options.statuses);
  addOptions('category-filter', data.options.categories);
  addOptions('brand-filter', data.options.brands);
  addOptions('product-filter', data.options.products);
  renderDashboard(data);
  bindEvents();
  syncPageFromHash();
  setInterval(loadDashboard, 30000);
}

initialise().catch((error) => showError(error.message));
