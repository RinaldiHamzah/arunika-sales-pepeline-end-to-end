import { $, state, pageMetadata, JAKARTA_TIME_ZONE, addOptions, buildQuery, adminHeaders, number, showError, clearError, formatJakartaDateTime } from './core.js';
import { requestJson } from './api.js';
import { renderDashboard, renderTransactions, renderOperationRows, labelTableCells } from './renderers.js';
import { renderCharts } from './charts.js';

function setPage(pageName) {
  const selectedPage = pageMetadata[pageName] ? pageName : 'overview';
  document.querySelectorAll('.dashboard-page').forEach((page) => {
    page.classList.toggle('active', page.dataset.page === selectedPage);
  });
  document.querySelectorAll('[data-page-link]').forEach((link) => {
    link.classList.toggle('active', link.dataset.pageLink === selectedPage);
  });
  document.querySelectorAll('[data-page-link]').forEach(link => {
    if (link.dataset.pageLink === selectedPage) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  if (selectedPage === 'overview' && state.dashboardData) renderCharts(state.dashboardData);
  $('page-title').textContent = pageMetadata[selectedPage].title;
  $('page-subtitle').textContent = pageMetadata[selectedPage].subtitle;
}

function syncPageFromHash() {
  setPage(window.location.hash.replace('#', '') || 'overview');
}


export async function loadDashboard({ apply = false, background = false } = {}) {
  if (background && state.loading) return;
  if (apply) {
    if ($('start-date').value > $('end-date').value && $('end-date').value) {
      showError('Tanggal mulai tidak boleh setelah tanggal akhir.');
      return;
    }
    state.page = 1;
    state.appliedQuery = buildQuery().toString();
  }
  const sequence = ++state.requestSequence;
  state.loading = true;
  const button = $('refresh-button');
  button.disabled = true;
  button.textContent = 'Memuat…';
  try {
    const data = await requestJson('/api/dashboard?' + state.appliedQuery);
    if (sequence !== state.requestSequence) return;
    if (!data.metrics || !data.charts) throw new Error('Data dashboard belum lengkap. Coba muat kembali.');
    if (!state.filtersLoaded) {
      const { start = '', end = '' } = data.filters || {};
      state.defaultFilters = { start, end };
      $('start-date').value = start;
      $('end-date').value = end;
      state.appliedQuery = buildQuery().toString();
      state.filtersLoaded = true;
    }
    const options = data.options || {};
    for (const [id, key] of [['channel', 'channels'], ['status', 'statuses'], ['category', 'categories'], ['brand', 'brands'], ['product', 'products']]) {
      const select = $(id + '-filter');
      const selected = select.value;
      select.length = 1;
      addOptions(id + '-filter', options[key] || []);
      if ([...select.options].some(option => option.value === selected)) select.value = selected;
    }
    if (!background || $('message').dataset.kind === 'connection') clearError();
    renderDashboard(data);
    if (apply) renderTransactions();
    const applied = new URLSearchParams(state.appliedQuery);
    const dates = [applied.get('start'), applied.get('end')].filter(Boolean);
    const activeFilters = [...applied.keys()].filter(key => !['start', 'end'].includes(key)).length;
    $('filter-summary').textContent = dates.join(' → ') + (activeFilters ? ' · ' + activeFilters + ' filter aktif' : ' · Semua channel');
    if (apply && window.matchMedia('(max-width: 640px)').matches) {
      document.querySelector('.filter-disclosure').open = false;
    }
    $('connection-status').textContent = 'Warehouse terhubung';
    $('connection-status').parentElement.dataset.state = 'connected';
  } catch (error) {
    if (sequence !== state.requestSequence) return;
    showError(error.message + (state.dashboardData ? ' Data terakhir tetap ditampilkan.' : ' Gunakan Muat ulang untuk mencoba lagi.'));
    $('message').dataset.kind = 'connection';
    $('connection-status').textContent = 'Koneksi perlu diperiksa';
    $('connection-status').parentElement.dataset.state = 'error';
    if (!state.dashboardData) $('updated-at').textContent = 'Data belum tersedia';
  } finally {
    if (sequence === state.requestSequence) {
      state.loading = false;
      button.disabled = false;
      button.textContent = 'Muat ulang';
    }
  }
}

function setTab(name, focus = false) {
  state.activeTab = name;
  document.querySelectorAll('[data-overview-tab]').forEach(button => {
    const active = button.dataset.overviewTab === name;
    button.setAttribute('aria-selected', String(active));
    button.tabIndex = active ? 0 : -1;
    if (active && focus) button.focus();
  });
  document.querySelectorAll('[data-overview-panel]').forEach(panel => {
    panel.hidden = panel.dataset.overviewPanel !== name;
  });
  if (state.dashboardData) renderCharts(state.dashboardData);
}

function bindTabs() {
  const tabs = [...document.querySelectorAll('[data-overview-tab]')];
  tabs.forEach((button, index) => {
    button.onclick = () => setTab(button.dataset.overviewTab);
    button.onkeydown = event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined) {
        event.preventDefault();
        setTab(tabs[next].dataset.overviewTab, true);
      }
    };
  });
}

function formatInputDate(value) {
  return value.toISOString().slice(0, 10);
}

function setActivePreset(activePreset = '') {
  document.querySelectorAll('[data-preset]').forEach((button) => {
    button.classList.toggle('active', button.dataset.preset === activePreset);
  });
}

function setPreset(preset) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: JAKARTA_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  const part = type => parts.find(item => item.type === type).value;
  const end = new Date(part('year') + '-' + part('month') + '-' + part('day') + 'T00:00:00Z');
  const start = new Date(end);
  if (preset === 'ytd') start.setUTCMonth(0, 1);
  else if (preset !== 'today') start.setUTCDate(end.getUTCDate() - Number(preset) + 1);
  $('start-date').value = formatInputDate(start);
  $('end-date').value = formatInputDate(end);
  setActivePreset(preset);
  loadDashboard({ apply: true });
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
  loadDashboard({ apply: true });
}

function downloadTransactions() {
  window.location = `/api/dashboard/export?${state.appliedQuery}`;
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
    if (!run && state.pipelineProgressAttempts >= 10) {
      throw new Error('Belum ada status pipeline. Coba periksa riwayat eksekusi.');
    }
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
    loadOperations();
    button.disabled = false;
    button.textContent = 'Jalankan sekarang';
    if (run.status === 'SUCCESS') {
      setPipelineProgress(`Selesai · ${formatJakartaDateTime(run.ended_at)} WIB. ${run.outcome_message || 'Lihat rincian proses untuk hasilnya.'}`, 'success');
      loadDashboard();
    } else {
      setPipelineProgress('Pipeline gagal. ' + (run.error_message || 'Lihat rincian riwayat eksekusi.'), 'failed');
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

async function uploadBatch() {
  const file = $('upload-file').files[0];
  if (!file) return showError('Pilih file CSV terlebih dahulu.');
  const button = $('upload-button');
  button.disabled = true;
  button.textContent = 'Mengunggah…';
  try {
    const body = new FormData();
    body.append('source', $('upload-source').value);
    body.append('file', file);
    const data = await requestJson('/api/ingestion/upload', {
      method: 'POST', headers: adminHeaders(), body,
    });
    $('message').textContent = `${data.rows_appended} baris ditambahkan ke ${data.source}. ${data.next_step}`;
    $('message').dataset.kind = 'success';
    $('message').classList.remove('hidden');
    $('upload-file').value = '';
    updateFileName();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Upload CSV';
  }
}

async function loadOperations() {
  const button = $('operations-button');
  button.disabled = true;
  button.textContent = 'Memuat…';
  try {
    const data = await requestJson('/api/admin/operations', { headers: adminHeaders() });
    const latest = data.recent_runs[0];
    $('operation-outcome').textContent = latest?.status === 'FAILED'
      ? 'Pipeline terakhir gagal. Buka Rincian proses untuk melihat alasannya.'
      : (latest?.outcome_message || 'Pilih Rincian proses untuk melihat metrik. Run lama belum memiliki metrik skip awal.');
    $('operations-empty').classList.add('hidden');
    $('operations-content').classList.remove('hidden');
    $('operation-latest-status').textContent = latest?.status || 'NO RUN';
    $('operation-latest-facts').textContent = number(latest?.loaded_records);
    $('failed-runs').textContent = number(data.failed_runs_last_7_days);
    $('operation-run-rows').innerHTML = renderOperationRows(data.recent_runs);
    labelTableCells();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = 'Check status';
  }
}


export function bindEvents() {
  const mobile = window.matchMedia('(max-width: 640px)');
  const disclosure = document.querySelector('.filter-disclosure');
  disclosure.open = !mobile.matches;
  mobile.addEventListener('change', event => { disclosure.open = !event.matches; });
  $('apply-button').onclick = () => loadDashboard({ apply: true });
  $('refresh-button').onclick = () => loadDashboard();
  $('reset-button').onclick = resetFilters;
  $('download-transactions').onclick = downloadTransactions;
  $('run-pipeline').onclick = runPipeline;
  $('upload-button').onclick = uploadBatch;
  $('upload-file').onchange = updateFileName;
  $('operations-button').onclick = loadOperations;
  $('prev-page').onclick = () => { state.page -= 1; renderTransactions(); };
  $('next-page').onclick = () => { state.page += 1; renderTransactions(); };
  document.querySelectorAll('[data-preset]').forEach(button => {
    button.onclick = () => setPreset(button.dataset.preset);
  });
  document.querySelectorAll('.filter-card input, .filter-card select').forEach(control => {
    control.addEventListener('change', () => setActivePreset());
  });
  bindTabs();
  syncPageFromHash();
  window.addEventListener('hashchange', syncPageFromHash);
  window.setInterval(() => {
    // Do not replace content under a reader, a focused control, or a draft filter.
    const interacting = document.activeElement?.closest('input, select, button, summary, a');
    const readingChart = [...document.querySelectorAll('.chart-data[open]')]
      .some(details => details.getClientRects().length);
    if (!document.hidden && !interacting && !readingChart && buildQuery().toString() === state.appliedQuery) {
      loadDashboard({ background: true });
    }
  }, 30000);
}
