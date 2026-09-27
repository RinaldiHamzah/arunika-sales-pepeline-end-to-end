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

export function filteredTransactionRows() {
  const query = state.transactionSearch.trim().toLocaleLowerCase('id-ID');
  if (!query) return state.rows;
  return state.rows.filter(row => [
    row.order_id,
    row.product_name,
    row.product_id,
    row.channel_name,
    row.category,
    row.status,
  ].some(value => String(value ?? '').toLocaleLowerCase('id-ID').includes(query)));
}

export function renderTransactions() {
  const filteredRows = filteredTransactionRows();
  const totalPages = Math.max(1, Math.ceil(filteredRows.length / state.pageSize));
  state.page = Math.max(1, Math.min(state.page, totalPages));
  const start = (state.page - 1) * state.pageSize;
  const rows = filteredRows.slice(start, start + state.pageSize);
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
  `).join('') : `<tr><td colspan="8" class="empty">${state.transactionSearch ? 'Tidak ada transaksi yang sesuai pencarian.' : 'Tidak ada transaksi. Coba ubah periode atau reset filter di Overview.'}</td></tr>`;
  labelTableCells();
  $('row-count').textContent = state.transactionSearch
    ? `${number(filteredRows.length)} dari ${number(state.rows.length)} Transaksi`
    : `${number(filteredRows.length)} Transaksi`;
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
  $('metric-sales-note').textContent = 'Total order COMPLETED';
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
  if (rowsChanged) {
    state.transactionSearch = '';
    if ($('transaction-search')) $('transaction-search').value = '';
  }
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
  const metric = value => value == null ? '—' : number(value);
  const message = run.status === 'FAILED'
    ? 'Pipeline gagal. Lihat alasan di bawah.'
    : (run.outcome_message || 'Run lama: metrik sebelum validasi belum direkam.');
  const summary = run.report_summary;
  const raw = summary?.raw || {};
  const productMaster = raw.product_master || {};
  const quality = summary?.quality_staging;
  const warehouse = summary?.warehouse || {};
  const newOrChanged = raw.new_or_changed ?? run.extracted_records ?? 0;
  const hasWork = Number(newOrChanged) > 0;
  const issueLabels = {
    missing_value: 'Nilai kosong',
    duplicate_business_key: 'Duplikat unique key',
    invalid_quantity: 'Kuantitas tidak valid',
    invalid_price: 'Harga transaksi tidak valid',
    invalid_status: 'Status tidak valid',
    invalid_date: 'Tanggal tidak valid',
    unmapped_product: 'Produk tidak termapping',
    type_cast_failure: 'Konversi tipe gagal',
  };
  const sourceLabels = {
    SHOPEE: 'Shopee', TOKOPEDIA: 'Tokopedia', WEBSITE: 'Website', OFFLINE_STORE: 'Offline Store', PRODUCT_MASTER: 'Master Produk',
  };
  const findingsFor = sections => Object.entries(issueLabels).flatMap(([key, label]) => {
    const finding = sections?.[key] || {};
    if (!finding.total) return [];
    const fields = Object.entries(finding.by_field || {}).map(([field, count]) => `${escapeHtml(field)}: ${number(count)}`).join(' · ');
    return [`<li><strong>${label}</strong>: ${number(finding.total)}${fields ? `<br><small>${fields}</small>` : ''}</li>`];
  }).join('');
  const findings = quality ? findingsFor(quality) : '';
  const sourceQualityFor = target => (target?.by_source || []).map(source => {
    const sourceFindings = findingsFor(source.issues);
    return `<details class="quality-source-detail">
      <summary><strong>${escapeHtml(sourceLabels[source.source_name] || source.source_name)}</strong><span>${number(source.processed)} diproses · ${number(source.valid)} valid</span></summary>
      <dl class="quality-source-stats">
        <dt>Data diproses</dt><dd>${number(source.processed)}</dd>
        <dt>Data valid</dt><dd>${number(source.valid)}</dd>
        <dt>Data ditolak</dt><dd>${number(source.rejected)}</dd>
        <dt>Duplikat validasi</dt><dd>${number(source.duplicate)}</dd>
      </dl>
      ${sourceFindings ? `<ul class="run-findings">${sourceFindings}</ul>` : '<p>Tidak ada masalah kualitas data pada sumber ini.</p>'}
    </details>`;
  }).join('');
  const sourceQuality = sourceQualityFor(quality);
  const detail = !summary ? `
    <dl>
      <dt>Data diproses</dt><dd>${metric(run.extracted_records)}</dd>
      <dt>Data valid</dt><dd>${metric(run.validated_records)}</dd>
      <dt>Data ditolak</dt><dd>${metric(run.rejected_records)}</dd>
      <dt>Duplikat validasi</dt><dd>${metric(run.duplicate_records)}</dd>
      <dt>Fact ditulis</dt><dd>${metric(run.loaded_records)}</dd>
    </dl>` : `
    <h4>Raw Layer</h4>
    <dl>
      <dt>Total transaksi Raw Layer</dt><dd>${metric(raw.total_transactions_in_raw)}</dd>
      <dt>Transaksi baru atau berubah</dt><dd>${metric(newOrChanged)}</dd>
      <dt>Transaksi dimuat ke Raw Layer</dt><dd>${metric(raw.inserted_to_raw)}</dd>
      <dt>Total Master Produk Raw Layer</dt><dd>${metric(productMaster.total_in_raw)}</dd>
      <dt>Master Produk diproses</dt><dd>${metric(productMaster.new_or_changed)}</dd>
      <dt>Master Produk dimuat ke Raw Layer</dt><dd>${metric(productMaster.inserted_to_raw)}</dd>
    </dl>
    ${!hasWork ? '<p>Tidak ada data baru dan perubahan pada runing ini sehingga tahap Data Quality Check, Transformasi, Staging, dan Warehouse tidak dijalankan.</p>' : `
      <h4>Data Quality Check &amp; Staging</h4>
      ${findings ? `<ul class="run-findings">${findings}</ul>` : '<p>Tidak ada temuan data quality check yang memblokir data.</p>'}
      <dl>
        <dt>Data lolos ke Staging</dt><dd>${metric(quality?.passed_to_staging)}</dd>
        <dt>Data diload ke Staging</dt><dd>${metric(quality?.written_to_staging)}</dd>
      </dl>
      ${sourceQuality ? `<h4>Rincian per sumber</h4><div class="quality-source-list">${sourceQuality}</div>` : ''}
      <h4>Warehouse</h4>
      <dl>
        <dt>Fact siap dimuat</dt><dd>${metric(warehouse.eligible_facts)}</dd>
        <dt>Fact baru</dt><dd>${metric(warehouse.inserted_facts)}</dd>
        <dt>Total fact ditulis</dt><dd>${metric(warehouse.facts_written)}</dd>
      </dl>`}`;
  return `<details class="run-explanation">
    <summary>Rincian proses</summary>
    <p>${escapeHtml(message)}</p>
    ${detail}
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
