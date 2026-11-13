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
    row.promo_code,
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
      <td>${number(row.returned_units)}</td>
      <td>${money(row.processed_refund_amount)}</td>
      <td>${money(row.discount_amount)}</td>
      <td>${escapeHtml(row.promo_code || '—')}</td>
      <td>${money(row.net_amount)}</td>
    </tr>
  `).join('') : `<tr><td colspan="12" class="empty">${state.transactionSearch ? 'Tidak ada transaksi yang sesuai pencarian.' : 'Tidak ada transaksi. Coba ubah periode atau reset filter di Overview.'}</td></tr>`;
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
    'metric-discount': money(metrics.discount_total),
    'metric-orders': number(metrics.orders),
    'metric-units': number(metrics.units),
    'metric-aov': money(metrics.average_order_value),
    'metric-returned-units': number(metrics.returned_units),
    'metric-return-rate': percent(metrics.return_rate),
    'metric-refunds': money(metrics.processed_refund_amount),
  };
  Object.entries(values).forEach(([id, value]) => { $(id).textContent = value; });
  $('metric-sales-note').textContent = 'COMPLETED/RETURNED order setelah diskon dan refund diproses';
  const change = metrics.net_change_percent;
  $('metric-sales-change').textContent = change == null
    ? ''
    : `${change >= 0 ? '▲' : '▼'} ${percent(Math.abs(change))} dibanding periode sebelumnya`;
}

function renderReturnTable(id, rows, renderRow, colspan) {
  const body = $(id);
  if (!body) return;
  body.innerHTML = rows?.length
    ? rows.map(renderRow).join('')
    : `<tr><td colspan="${colspan}" class="empty">Tidak ada data return pada filter ini.</td></tr>`;
}

function renderReturnEvents(rows) {
  const totalPages = Math.max(1, Math.ceil(rows.length / state.returnPageSize));
  state.returnPage = Math.max(1, Math.min(state.returnPage, totalPages));
  const start = (state.returnPage - 1) * state.returnPageSize;
  const pageRows = rows.slice(start, start + state.returnPageSize);
  renderReturnTable('return-event-rows', pageRows, row => `
    <tr><td>${escapeHtml(row.return_date)}</td><td>${escapeHtml(row.return_id)}${Number(row.return_line_number) > 1 ? ` · ${number(row.return_line_number)}` : ''}</td>
    <td>${escapeHtml(row.channel_name)}</td><td>${escapeHtml(row.order_id)} · ${number(row.source_line_number)}</td>
    <td>${escapeHtml(row.product_name)} <small>${escapeHtml(row.product_id)}</small></td>
    <td>${statusBadge(row.return_status)}</td><td>${escapeHtml(row.return_reason)}</td>
    <td>${number(row.quantity_returned)}</td><td>${statusBadge(row.refund_status)}</td><td>${money(row.refund_amount)}</td></tr>
  `, 10);
  const pageInfo = $('return-page-info');
  if (pageInfo) {
    pageInfo.textContent = `Halaman ${state.returnPage} / ${totalPages}`;
  }
  const previous = $('return-prev-page');
  const next = $('return-next-page');
  if (previous) {
    previous.disabled = state.returnPage === 1;
    previous.onclick = () => { state.returnPage -= 1; renderReturnEvents(state.returnRows); };
  }
  if (next) {
    next.disabled = state.returnPage === totalPages;
    next.onclick = () => { state.returnPage += 1; renderReturnEvents(state.returnRows); };
  }
}

function renderReturnAnalytics(data = {}) {
  const statuses = Object.fromEntries((data.by_status || []).map(row => [row.label, row]));
  const refunds = Object.fromEntries((data.by_refund_status || []).map(row => [row.label, row]));
  const total = (data.by_status || []).reduce((sum, row) => sum + Number(row.events || 0), 0);
  const setText = (id, value) => { if ($(id)) $(id).textContent = value; };
  setText('return-total', `${number(total)} event`);
  setText('return-pending', number(statuses.PENDING?.events));
  setText('return-approved', number(statuses.APPROVED?.events));
  setText('return-rejected', number(statuses.REJECTED?.events));
  setText('return-processed', number(statuses.PROCESSED?.events));
  setText('return-refund-total', money(refunds.PROCESSED?.processed_refund_amount));
  const returnRows = data.rows || [];
  if (JSON.stringify(returnRows) !== JSON.stringify(state.returnRows)) state.returnPage = 1;
  state.returnRows = returnRows;
  setText('return-event-count', `${number(returnRows.length)} event`);

  renderReturnTable('return-status-rows', data.by_status, row => `
    <tr><td data-label="Status return">${statusBadge(row.label)}</td><td data-label="Event">${number(row.events)}</td><td data-label="Unit">${number(row.units)}</td>
    <td data-label="Event refund diproses">${number(row.refunded_events)}</td><td data-label="Nilai refund diproses">${money(row.processed_refund_amount)}</td></tr>
  `, 5);
  renderReturnTable('refund-status-rows', data.by_refund_status, row => `
    <tr><td data-label="Status refund">${statusBadge(row.label)}</td><td data-label="Event">${number(row.events)}</td>
    <td data-label="Nilai refund diproses">${money(row.processed_refund_amount)}</td></tr>
  `, 3);
  renderReturnTable('return-channel-rows', data.by_channel, row => `
    <tr><td data-label="Channel">${escapeHtml(row.label)}</td><td data-label="Event">${number(row.events)}</td><td data-label="Unit">${number(row.units)}</td>
    <td data-label="Pending">${number(row.pending_events)}</td><td data-label="Ditolak">${number(row.rejected_events)}</td>
    <td data-label="Refund diproses">${money(row.processed_refund_amount)}</td></tr>
  `, 6);
  renderReturnTable('return-reason-rows', data.by_reason, row => `
    <tr><td data-label="Alasan">${escapeHtml(row.label)}</td><td data-label="Event">${number(row.events)}</td><td data-label="Unit">${number(row.units)}</td>
    <td data-label="Refund diproses">${money(row.processed_refund_amount)}</td></tr>
  `, 4);
  renderReturnEvents(returnRows);
}

function renderObservability(observability) {
  const run = observability.latest_run;
  $('pipeline-status').textContent = run?.status || 'BELUM ADA RUN';
  $('pipeline-run').textContent = run
    ? `Run ${String(run.run_id).slice(0, 8)} · ${formatJakartaDateTime(run.started_at)} WIB`
    : 'Belum ada pipeline run';
  const returnFacts = run?.report_summary?.return_warehouse?.facts_written
    ?? run?.report_summary?.auxiliary_sources?.find(source => source.source_name === 'RETURN_EVENTS')?.warehouse_written;
  $('pipeline-volume').textContent = run
    ? `${number(run.loaded_records ?? run.fact_inserted_records)} fact sales · ${returnFacts == null ? 'fact return —' : `${number(returnFacts)} fact return`} dimuat`
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
  renderReturnAnalytics(data.returns || {});
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
  const returns = (summary?.auxiliary_sources || []).find(source => source.source_name === 'RETURN_EVENTS') || {};
  const promo = (summary?.auxiliary_sources || []).find(source => source.source_name === 'PROMO_MASTER') || {};
  const returnWarehouse = summary?.return_warehouse || {};
  const dimensions = summary?.dimensions || {};
  const sourceMetrics = Array.isArray(run.source_metrics) ? run.source_metrics : [];
  const sourceByName = Object.fromEntries(sourceMetrics.map(source => [source.source_name, source]));
  const channels = ['SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE'];
  const valueOf = (source, key) => Number(source?.[key] || 0);
  const channelCandidates = channels.reduce((sum, name) => sum + valueOf(sourceByName[name], 'extracted_records'), 0);
  const productCandidate = valueOf(sourceByName.PRODUCT_MASTER, 'extracted_records');
  const promoCandidate = valueOf(promo, 'processed');
  const returnCandidate = valueOf(returns, 'processed');
  const totalCandidates = channelCandidates + productCandidate + promoCandidate + returnCandidate;
  const salesValid = channels.reduce((sum, name) => sum + valueOf(sourceByName[name], 'validated_records'), 0);
  const productValid = valueOf(sourceByName.PRODUCT_MASTER, 'validated_records');
  const totalValid = salesValid + productValid + valueOf(promo, 'validated') + valueOf(returns, 'validated');
  const totalRejected = [...channels, 'PRODUCT_MASTER'].reduce((sum, name) => sum + valueOf(sourceByName[name], 'rejected_records'), 0)
    + valueOf(promo, 'rejected') + valueOf(returns, 'rejected');
  const totalDuplicates = [...channels, 'PRODUCT_MASTER'].reduce((sum, name) => sum + valueOf(sourceByName[name], 'duplicate_records'), 0)
    + valueOf(promo, 'duplicates') + valueOf(returns, 'duplicates');
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
  const listSection = (title, items) => `<h4>${escapeHtml(title)}</h4><ul class="run-findings">${items.map(item => `<li>${item}</li>`).join('')}</ul>`;
  const summarySection = listSection('Ringkasan Record', [
    `Kandidat Transaksi kanal: ${number(channelCandidates)}`,
    `Kandidat Master Produk: ${number(productCandidate)}`,
    `Kandidat Promo baru: ${number(promoCandidate)}`,
    `Kandidat Return baru: ${number(returnCandidate)}`,
    `Total baris semua sumber: ${number(totalCandidates)}`,
    `Total valid: ${number(totalValid)}`,
    `Total ditolak: ${number(totalRejected)}`,
    `Total duplikat: ${number(totalDuplicates)}`,
    `Fact Sales ditulis: ${number(warehouse.facts_written ?? run.loaded_records)}`,
    `Fact Return ditulis: ${number(returnWarehouse.facts_written ?? returns.warehouse_written)}`,
  ]);
  const sourceDetails = [];
  const sourceQualityByName = Object.fromEntries((quality?.by_source || []).map(source => [source.source_name, source]));
  const sourceIssueList = source => {
    const items = findingsFor(source?.issues);
    return items ? `<ul class="run-findings">${items}</ul>` : '';
  };
  const renderSourceDetail = (title, summaryText, ledgerLine, metrics, sourceFindings = '') => {
    const metricRows = metrics.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${value}</dd>`).join('');
    sourceDetails.push(`<details class="quality-source-detail">
      <summary><strong>${escapeHtml(title)}</strong><span>${escapeHtml(summaryText)}</span></summary>
      <p class="quality-source-ledger">${ledgerLine}</p>
      <dl class="quality-source-stats">${metricRows}</dl>
      ${sourceFindings || '<p class="quality-source-empty">Tidak ada temuan validasi pada sumber ini.</p>'}
    </details>`);
  };
  const product = sourceByName.PRODUCT_MASTER || {};
  const productExtra = [
    valueOf(productMaster, 'inserted_to_raw') ? `Raw ditambah ${number(productMaster.inserted_to_raw)}` : '',
    valueOf(dimensions, 'products_processed') ? `Dimensi Produk diproses ${number(dimensions.products_processed)}` : '',
  ].filter(Boolean);
  const productLine = `Master Produk: sumber ${number(product.source_records)} | kandidat ${number(product.extracted_records)} | valid ${number(product.validated_records)} | ditolak ${number(product.rejected_records)} | duplikat dilewati ${number(product.duplicate_records)}${productExtra.length ? ` | ${productExtra.join(' | ')}` : ''}`;
  renderSourceDetail('Master Produk', `${number(product.extracted_records)} kandidat · ${number(product.validated_records)} valid`, productLine,
    [['Baris sumber', number(product.source_records)], ['Kandidat diproses', number(product.extracted_records)], ['Valid', number(product.validated_records)], ['Ditolak', number(product.rejected_records)], ['Duplikat dilewati', number(product.duplicate_records)], ['Raw ditambahkan', number(productMaster.inserted_to_raw)], ['Dimensi Produk diproses', number(dimensions.products_processed)]], sourceIssueList(sourceQualityByName.PRODUCT_MASTER));
  const promoExtra = [
    valueOf(promo, 'raw_inserted') ? `Raw ditambah ${number(promo.raw_inserted)}` : '',
    valueOf(promo, 'warehouse_written') ? `Dimensi Promo diproses ${number(promo.warehouse_written)}` : '',
    valueOf(promo, 'promo_codes_checked') ? `Kode promo cocok ${number(promo.promo_codes_matched)}/${number(promo.promo_codes_checked)}` : '',
  ].filter(Boolean);
  const promoLine = `Master Promo: katalog ${number(promo.source_records)} | valid katalog ${number(promo.catalog_validated ?? promo.validated)} | baru/berubah ${number(promo.processed)} | ditolak ${number(promo.rejected)} | duplikat ${number(promo.duplicates)}${promoExtra.length ? ` | ${promoExtra.join(' | ')}` : ''}`;
  renderSourceDetail('Master Promo', `${number(promo.processed)} baru/berubah · ${number(promo.catalog_validated ?? promo.validated)} valid`, promoLine,
    [['Baris katalog', number(promo.source_records)], ['Katalog diperiksa', number(promo.catalog_checked ?? promo.source_records)], ['Katalog valid', number(promo.catalog_validated ?? promo.validated)], ['Baru/berubah', number(promo.processed)], ['Ditolak', number(promo.rejected)], ['Duplikat identik', number(promo.duplicates)], ['Raw ditambahkan', number(promo.raw_inserted)], ['Dimensi Promo dimuat', number(promo.warehouse_written)], ['Kode promo cocok', `${number(promo.promo_codes_matched)}/${number(promo.promo_codes_checked)}`]]);
  channels.forEach(name => {
    const source = sourceByName[name] || {};
    const line = `${sourceLabels[name]}: sumber ${number(source.source_records)} | kandidat ${number(source.extracted_records)} | valid ${number(source.validated_records)} | ditolak ${number(source.rejected_records)} | duplikat dilewati ${number(source.duplicate_records)}`;
    renderSourceDetail(sourceLabels[name], `${number(source.extracted_records)} kandidat · ${number(source.validated_records)} valid`, line,
      [['Baris sumber', number(source.source_records)], ['Kandidat diproses', number(source.extracted_records)], ['Valid', number(source.validated_records)], ['Ditolak', number(source.rejected_records)], ['Duplikat dilewati', number(source.duplicate_records)]], sourceIssueList(sourceQualityByName[name]));
  });
  const returnExtra = [
    valueOf(returns, 'raw_inserted') ? `Raw ditambah ${number(returns.raw_inserted)}` : '',
    valueOf(returns, 'staging_written') ? `Staging dimuat ${number(returns.staging_written)}` : '',
    valueOf(returns, 'warehouse_written') ? `Fact ditulis ${number(returns.warehouse_written)}` : '',
  ].filter(Boolean);
  const returnLine = `Return: sumber ${number(returns.source_records)} | berubah ${number(returns.processed)} | valid ${number(returns.validated)} | ditolak ${number(returns.rejected)} | duplikat ${number(returns.duplicates)}${returnExtra.length ? ` | ${returnExtra.join(' | ')}` : ''}`;
  const returnReasons = Object.entries(returns.rejection_reasons || {}).map(([reason, count]) => `<li>${escapeHtml(reason)}: ${number(count)}</li>`).join('');
  renderSourceDetail('Return', `${number(returns.processed)} berubah · ${number(returns.validated)} valid`, returnLine,
    [['Baris sumber', number(returns.source_records)], ['Berubah/diperiksa', number(returns.processed)], ['Tidak berubah', number(returns.unchanged)], ['Valid', number(returns.validated)], ['Ditolak', number(returns.rejected)], ['Duplikat', number(returns.duplicates)], ['Raw ditambahkan', number(returns.raw_inserted)], ['Dimuat ke Staging', number(returns.staging_written)], ['Fact Return ditulis', number(returns.warehouse_written)]], returnReasons ? `<ul class="run-findings">${returnReasons}</ul>` : '');

  const rawSection = listSection('Raw Layer', [
    `Transaksi kanal baru/berubah: ${number(raw.new_or_changed)} | Raw ditambah ${number(raw.inserted_to_raw)} | total Raw: ${metric(raw.total_transactions_in_raw)}`,
    `Master Produk baru/berubah: ${number(productMaster.new_or_changed)} | Raw ditambah ${number(productMaster.inserted_to_raw)} | total Raw: ${metric(productMaster.total_in_raw)}`,
    `Master Promo baru/berubah: ${number(promo.processed)} | Raw ditambah ${number(promo.raw_inserted)} | total Raw: ${metric((summary?.database_table_counts || {})['raw.promo_master'])}`,
    `Return baru/berubah: ${number(returns.processed)} | Raw ditambah ${number(returns.raw_inserted)} | total Raw: ${metric((summary?.database_table_counts || {})['raw.return_events'])}`,
  ]);
  const qualitySection = quality
    ? `<h4>Quality Check — Sales</h4>${findings
      ? `<ul class="run-findings">${findings}</ul>`
      : '<p>Tidak ada temuan data quality check.</p>'}`
    : listSection('Quality Check — Sales', ['Tidak dijalankan karena tidak ada data baru atau perubahan.']);
  const returnReasonLabels = {
    required: 'Nilai wajib kosong/tidak valid', duplicate: 'Business key duplikat', date: 'Tanggal tidak valid',
    status: 'Status return/refund tidak valid', quantity: 'Jumlah return tidak valid/melebihi penjualan',
    refund: 'Nilai refund tidak valid/melebihi penjualan', reference: 'Referensi transaksi tidak valid',
  };
  const returnRejectionSummary = Object.entries(returns.rejection_reasons || {}).reduce((result, [reason, count]) => {
    const value = Number(count || 0);
    const text = String(reason).toLowerCase();
    const category = text.includes('duplikat') || text.includes('business key') ? 'duplicate'
      : (text.includes('date') || text.includes('tanggal') || text.includes('yyyy-mm-dd')) ? 'date'
        : text.includes('status') ? 'status'
          : (text.includes('quantity') || text.includes('jumlah retur')) ? 'quantity'
            : (text.includes('refund') || text.includes('net amount')) ? 'refund'
              : (text.includes('tidak ditemukan') || text.includes('cancelled') || text.includes('merujuk')) ? 'reference' : 'required';
    result[category] = (result[category] || 0) + value;
    return result;
  }, {});
  const returnQualityItems = !returnCandidate
    ? ['Tidak dijalankan karena tidak ada data baru atau perubahan.']
    : [
      `Baris sumber: ${number(returns.source_records)} | berubah: ${number(returns.processed)} | tidak berubah: ${number(returns.unchanged)}`,
      `Diperiksa: ${number(returns.processed)}`,
      `Valid: ${number(returns.validated)}`,
      `Ditolak: ${number(returns.rejected)}`,
      `Duplikat: ${number(returns.duplicates)}`,
      ...Object.entries(returnRejectionSummary).map(([key, count]) => `${returnReasonLabels[key]}: ${number(count)}`),
      ...Object.keys(returns.rejection_reasons || {}).map(reason => `Alasan: ${escapeHtml(reason)} (${number(returns.rejection_reasons[reason])})`),
    ];
  const stageSection = listSection('Staging Layer', [
    `Sales lolos ke Staging: ${number(quality?.passed_to_staging)}`,
    `Sales dimuat ke Staging: ${number(quality?.written_to_staging)}`,
    `Return lolos ke Staging: ${number(returns.validated)}`,
    `Return dimuat ke Staging: ${number(returns.staging_written)}`,
  ]);
  const warehouseSection = listSection('Warehouse Layer', [
    `Fact Sales siap dimuat: ${number(warehouse.eligible_facts)}`,
    `Fact Sales baru: ${number(warehouse.inserted_facts)}`,
    `Fact Sales diperbarui: ${number(warehouse.updated_facts)}`,
    `Total Fact Sales ditulis: ${number(warehouse.facts_written ?? run.loaded_records)}`,
    `Fact Return siap dimuat: ${number(returnWarehouse.eligible_facts ?? returns.validated)}`,
    `Fact Return baru: ${number(returnWarehouse.inserted_facts)}`,
    `Fact Return diperbarui: ${number(returnWarehouse.updated_facts)}`,
    `Total Fact Return ditulis: ${number(returnWarehouse.facts_written ?? returns.warehouse_written)}`,
  ]);
  const summaryDetail = summary ? `
    ${summarySection}
    <h4>Rincian per Sumber</h4><div class="quality-source-list">${sourceDetails.join('')}</div>
    ${rawSection}
    ${qualitySection}
    ${listSection('Quality Check — Return', returnQualityItems)}
    ${stageSection}
    ${warehouseSection}` : `
    <dl>
      <dt>Data diproses</dt><dd>${metric(run.extracted_records)}</dd>
      <dt>Data valid</dt><dd>${metric(run.validated_records)}</dd>
      <dt>Data ditolak</dt><dd>${metric(run.rejected_records)}</dd>
      <dt>Duplikat validasi</dt><dd>${metric(run.duplicate_records)}</dd>
      <dt>Fact ditulis</dt><dd>${metric(run.loaded_records)}</dd>
    </dl>`;
  return `<details class="run-explanation">
    <summary>Detail Proses</summary>
    <p>${escapeHtml(message)}</p>
    ${summaryDetail}
    ${run.error_message ? `<p class="run-error">Alasan gagal: ${escapeHtml(run.error_message)}</p>` : ''}
  </details>`;
}

export function renderOperationRows(runs = []) {
  if (!runs.length) {
    return '<tr><td class="empty" colspan="9">Belum ada pipeline run.</td></tr>';
  }
  return runs.map(run => {
    const returnFacts = run.report_summary?.return_warehouse?.facts_written
      ?? run.report_summary?.auxiliary_sources?.find(source => source.source_name === 'RETURN_EVENTS')?.warehouse_written;
    return `
      <tr>
        <td class="operation-run-cell" title="${escapeHtml(run.run_id)}">${escapeHtml(String(run.run_id).slice(0, 8))}${renderRunExplanation(run)}</td>
        <td>${statusBadge(run.status)}</td>
        <td>${formatJakartaDateTime(run.started_at)}</td>
        <td>${run.duration_seconds == null ? '—' : Number(run.duration_seconds).toFixed(1) + 's'}</td>
        <td>${number(run.extracted_records)}</td>
        <td>${number(run.validated_records)}</td>
        <td>${number(run.rejected_records)}</td>
        <td>${number(run.loaded_records)}</td>
        <td>${returnFacts == null ? '—' : number(returnFacts)}</td>
      </tr>
    `;
  }).join('');
}

/** Data tabel yang sama ditampilkan sebagai kartu berlabel di ponsel tanpa kontrol atau markup duplikat. */
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
