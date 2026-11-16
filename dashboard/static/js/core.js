export const state = {
  charts: {},
  rows: [],
  dashboardData: null,
  requestSequence: 0,
  appliedQuery: '',
  filtersLoaded: false,
  loading: false,
  activeTab: 'summary',
  page: 1,
  pageSize: 25,
  returnPage: 1,
  returnPageSize: 10,
  returnRows: [],
  transactionSearch: '',
  defaultFilters: { start: '', end: '' },
  pipelineProgressTimer: null,
  pipelineProgressAttempts: 0,
  pipelineProgressFailures: 0,
  pipelineExpectedRunId: null,
  pendingUploadSummary: [],
};
export const JAKARTA_TIME_ZONE = 'Asia/Jakarta';
export const pageMetadata = {
  overview: {
    title: 'Dashboard ',
    subtitle: 'Ringkasan penjualan terintegrasi dari marketplace, website, dan toko offline.',
  },
  transactions: {
    title: 'Transaksi',
    subtitle: 'Data transaksi yang telah tervalidasi proses data quality.',
  },
  returns: {
    title: 'Return & Refund',
    subtitle: 'Pantau proses return, status refund, dan riwayat event berdasarkan tanggal return.',
  },
  settings: {
    title: 'Pengaturan',
    subtitle: 'Kelola batch data, jalankan pipeline, dan pantau riwayat eksekusi.',
  },
};
export const $ = (id) => document.getElementById(id);
const missingSentinels = new Set(['nan', 'none', 'null', 'n/a', 'na']);
const numericValue = (value) => {
  if (value == null || value === '') return 0;
  if (typeof value === 'string' && missingSentinels.has(value.trim().toLowerCase())) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
export const money = (value) => {
  const parsed = numericValue(value);
  return parsed == null
    ? '—'
    : new Intl.NumberFormat('id-ID', { style: 'currency', currency: 'IDR', maximumFractionDigits: 0 }).format(parsed);
};
export const number = (value) => {
  const parsed = numericValue(value);
  return parsed == null ? '—' : new Intl.NumberFormat('id-ID').format(parsed);
};
export const escapeHtml = (value) => {
  const text = String(value ?? '');
  const normalized = missingSentinels.has(text.trim().toLowerCase()) ? '—' : text;
  return normalized.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' })[char]);
};

export function formatJakartaDateTime(value) {
  return value
    ? new Date(value).toLocaleString('id-ID', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: JAKARTA_TIME_ZONE,
    })
    : '—';
}

export function selectedValues(id) {
  return [...$(id).selectedOptions].map((option) => option.value).filter(Boolean);
}

export function addOptions(id, items) {
  const select = $(id);
  if (select.options.length > 1) return;
  [...new Set(items.filter(Boolean))].forEach((item) => select.add(new Option(item, item)));
}

export function buildQuery() {
  const query = new URLSearchParams({ start: $('start-date').value, end: $('end-date').value });
  [['channel-filter', 'channel'], ['status-filter', 'status'], ['category-filter', 'category'], ['brand-filter', 'brand'], ['product-filter', 'product']]
    .forEach(([elementId, parameter]) => selectedValues(elementId).forEach((value) => query.append(parameter, value)));
  return query;
}

export function adminHeaders() {
  const token = $('admin-token')?.value.trim();
  if (!token) throw new Error('Masukkan admin token sebelum menjalankan operasi admin.');
  return { 'X-Admin-Token': token };
}

export function showError(message) {
  $('message').textContent = message;
  $('message').dataset.kind = 'error';
  $('message').classList.remove('hidden');
}
export function clearError() { $('message').classList.add('hidden'); }
