import {
  $, state, money, number, escapeHtml, formatJakartaDateTime, JAKARTA_TIME_ZONE,
} from './core.js';
import { renderCharts } from './charts.js';

const percent = value => Number(value || 0).toFixed(1) + '%';
const statusBadge = status => `<span class="status" data-status="${escapeHtml(status)}">${escapeHtml(status)}</span>`;

function renderRankList(id, items = [], mode) {
  const value = item => mode === 'quantity'
    ? `${number(item.quantity)}<small>${money(item.net_sales)}</small>`
    : money(item.value);
  $(id).innerHTML = items.length ? items.slice(0, 6).map((item, index) => `
    <div class="rank-row">
      <span class="rank">${String(index + 1).padStart(2, '0')}</span>
      <span class="rank-name">${escapeHtml(item.label)}</span>
      <span class="rank-value">${value(item)}</span>
    </div>
  `).join('') : '<p class="empty">Tidak ada data untuk filter ini.</p>';
}

export function renderTransactions() {
  const totalPages = Math.max(1, Math.ceil(state.rows.length / state.pageSize));
  state.page = Math.max(1, Math.min(state.page, totalPages));
  const start = (state.page - 1) * state.pageSize;
  const rows = state.rows.slice(start, start + state.pageSize);
  $('transaction-rows').innerHTML = rows.length ? rows.map(row => `
    <tr>
      <td>${escapeHtml(row.order_date)}</td>
      <td>${escapeHtml(row.order_id)}</td>
      <td>${escapeHtml(row.channel_name)}</td>
      <td>${escapeHtml(row.product_name)}</td>
      <td>${escapeHtml(row.category)}</td>
      <td>${statusBadge(row.status)}</td>
      <td>${number(row.quantity)}</td>
      <td>${money(row.net_amount)}</td>
    </tr>
  `).join('') : '<tr><td colspan="8" class="empty">Tidak ada transaksi. Coba ubah periode atau reset filter di Overview.</td></tr>';
  labelTableCells();
  $('row-count').textContent = `${number(state.rows.length)} transaksi`;
  $('page-info').textContent = `Halaman ${state.page} / ${totalPages}`;
  $('prev-page').disabled = state.page === 1;
  $('next-page').disabled = state.page === totalPages;
}

function renderMetrics(metrics) {
  const values = {
    'metric-sales': money(metrics.net_sales),
    'metric-gross': money(metrics.gross_sales),
    'metric-orders': number(metrics.orders),
    'metric-units': number(metrics.units),
    'metric-aov': money(metrics.average_order_value),
    'metric-return-rate': percent(metrics.return_rate),
  };
  Object.entries(values).forEach(([id, value]) => { $(id).textContent = value; });
  const change = metrics.net_change_percent;
  $('metric-sales-change').textContent = change == null
    ? 'Belum ada periode pembanding'
    : `${change >= 0 ? '▲' : '▼'} ${percent(Math.abs(change))} dibanding periode sebelumnya`;
}

function renderObservability(observability) {
  const run = observability.latest_run;
  $('pipeline-status').textContent = run?.status || 'BELUM ADA RUN';
  $('pipeline-run').textContent = run
    ? `Run ${String(run.run_id).slice(0, 8)} · ${formatJakartaDateTime(run.started_at)} WIB`
    : 'Belum ada pipeline run';
  $('pipeline-volume').textContent = run
    ? `${number(run.loaded_records ?? run.fact_inserted_records)} fakta berhasil dimuat`
    : 'Belum ada data dimuat';
  $('pipeline-success-rate').textContent = percent(observability.pipeline_success_rate);
  $('pipeline-duration').textContent = observability.pipeline_duration == null
    ? '—' : `${Number(observability.pipeline_duration).toFixed(1)}s`;
  $('pipeline-rejected-rate').textContent = percent(observability.rejected_record_rate);
  $('source-freshness').innerHTML = (observability.source_freshness || []).map(source =>
    `<span>${escapeHtml(source.source_name)}</span>`,
  ).join('') || 'Belum ada data ingestion';
  $('city-coverage').textContent = percent(observability.known_city_coverage_rate) + ' lokasi diketahui';
}

export function renderDashboard(data) {
  state.dashboardData = data;
  const nextRows = data.rows || [];
  const rowsChanged = JSON.stringify(state.rows) !== JSON.stringify(nextRows);
  state.rows = nextRows;
  renderMetrics(data.metrics || {});
  renderObservability(data.observability || {});
  renderCharts(data);
  renderRankList('product-list', data.charts.product, 'quantity');
  renderRankList('city-list', data.charts.city, 'sales');
  if (rowsChanged || !$('transaction-rows').children.length) renderTransactions();
  const updated = new Date().toLocaleTimeString('id-ID', {
    hour: '2-digit', minute: '2-digit', timeZone: JAKARTA_TIME_ZONE,
  });
  $('updated-at').textContent = `Update ${updated} WIB`;
}

function renderRunExplanation(run) {
  const metric = value => value == null ? 'Belum direkam' : number(value);
  const message = run.status === 'FAILED'
    ? 'Pipeline gagal. Lihat alasan di bawah.'
    : (run.outcome_message || 'Run lama: metrik sebelum validasi belum direkam.');
  return `<details class="run-explanation">
    <summary>Rincian proses</summary>
    <p>${escapeHtml(message)}</p>
    <dl>
      <dt>Total baris source transaksi</dt><dd>${metric(run.source_records)}</dd>
      <dt>Identik sebelum validasi</dt><dd>${metric(run.skipped_unchanged_records)}</dd>
      <dt>Kandidat baru/berubah</dt><dd>${metric(run.extracted_records)}</dd>
      <dt>Identik dengan warehouse</dt><dd>${metric(run.fact_skipped_records)}</dd>
      <dt>Fact baru</dt><dd>${metric(run.fact_inserted_records)}</dd>
      <dt>Fact ditulis (insert/koreksi)</dt><dd>${metric(run.loaded_records)}</dd>
    </dl>
    <p>Total source bukan jumlah upload terakhir; tidak termasuk Product Master. Identik dilewati, bukan divalidasi ulang.</p>
    ${(run.source_metrics || []).map(source => `<p><strong>${escapeHtml(source.source_name)}</strong><br>
      Total ${metric(source.source_records)} · Identik ${metric(source.skipped_unchanged_records)} · Kandidat ${metric(source.extracted_records)}
      <br>Valid ${metric(source.validated_records)} · Ditolak ${metric(source.rejected_records)} · Duplikat validasi ${metric(source.duplicate_records)}
    </p>`).join('')}
    ${run.error_message ? `<p class="run-error">Alasan gagal: ${escapeHtml(run.error_message)}</p>` : ''}
  </details>`;
}

export function renderOperationRows(runs = []) {
  if (!runs.length) {
    return '<tr><td class="empty" colspan="11">Belum ada pipeline run.</td></tr>';
  }
  return runs.map(run => `
    <tr>
      <td title="${escapeHtml(run.run_id)}">${escapeHtml(String(run.run_id).slice(0, 8))}${renderRunExplanation(run)}</td>
      <td>${statusBadge(run.status)}</td>
      <td>${formatJakartaDateTime(run.started_at)}</td>
      <td>${formatJakartaDateTime(run.ended_at)}</td>
      <td>${run.duration_seconds == null ? '—' : Number(run.duration_seconds).toFixed(1) + 's'}</td>
      <td>${number(run.extracted_records)}</td>
      <td>${number(run.validated_records)}</td>
      <td>${number(run.rejected_records)}</td>
      <td>${number(run.duplicate_records)}</td>
      <td>${number(run.incremental_records)}</td>
      <td>${number(run.loaded_records)}</td>
    </tr>
  `).join('');
}

/** Same table data becomes labelled cards on mobile; no duplicate controls or markup. */
export function labelTableCells() {
  document.querySelectorAll('.table-container table').forEach(table => {
    const labels = [...table.querySelectorAll('thead th')].map(cell => cell.textContent.trim());
    table.querySelectorAll('tbody tr').forEach(row => {
      [...row.cells].forEach((cell, index) => {
        if (cell.colSpan === 1) cell.dataset.label = labels[index] || '';
      });
    });
  });
}
