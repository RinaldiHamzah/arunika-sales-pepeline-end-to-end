import { $, state, money, number, escapeHtml } from './core.js';

/** The table is always available, including offline and to assistive technology. */
function accessibleChart(canvas, config) {
  const panel = canvas.closest('.panel');
  let details = panel.querySelector('.chart-data');
  if (!details) {
    details = document.createElement('details');
    details.className = 'chart-data';
    details.innerHTML = '<summary>Lihat data tabel</summary><div class="chart-table"></div>';
    panel.append(details);
  }
  const { labels, datasets } = config.data;
  const isCount = canvas.id === 'status-chart';
  const format = isCount ? number : money;
  const title = panel.querySelector('h3').textContent;
  canvas.setAttribute('role', 'img');
  canvas.setAttribute('aria-label', title + '. Angka lengkap tersedia pada Lihat data tabel.');
  details.querySelector('.chart-table').innerHTML = labels.length
    ? `<table><caption>${escapeHtml(title)}</caption><thead><tr><th scope="col">Nama</th>${datasets.map(d => `<th scope="col">${escapeHtml(d.label || (isCount ? 'Pesanan' : 'Net sales'))}</th>`).join('')}</tr></thead><tbody>${labels.map((label, index) => `<tr><th scope="row">${escapeHtml(label)}</th>${datasets.map(d => `<td>${format(d.data[index])}</td>`).join('')}</tr>`).join('')}</tbody></table>`
    : '<p class="empty">Tidak ada data pada periode ini. Coba rentang tanggal lain.</p>';
  canvas.hidden = !labels.length || !window.Chart;
  let notice = panel.querySelector('.chart-notice');
  if (!notice) {
    notice = document.createElement('p');
    notice.className = 'chart-notice';
    canvas.parentElement.after(notice);
  }
  notice.hidden = !canvas.hidden;
  notice.textContent = labels.length
    ? 'Grafik tidak tersedia. Angka lengkap tetap dapat dibaca di tabel.'
    : 'Tidak ada data untuk filter ini.';
  canvas.parentElement.hidden = canvas.hidden;
  if (!window.Chart) details.open = true;
}

function drawChart(id, config) {
  const canvas = $(id + '-chart');
  if (!canvas) return;
  accessibleChart(canvas, config);
  if (canvas.hidden || !canvas.getClientRects().length) return;
  config.options.animation = false;
  if (state.charts[id]) {
    state.charts[id].data = config.data;
    state.charts[id].options = config.options;
    state.charts[id].update('none');
    state.charts[id].resize();
  } else {
    state.charts[id] = new window.Chart(canvas, config);
  }
}

const compactMoney = value => 'Rp ' + new Intl.NumberFormat('id-ID', {
  notation: 'compact', maximumFractionDigits: 1,
}).format(value);

function horizontalChart(items, color, formatter = money) {
  return {
    type: 'bar',
    data: {
      labels: items.map(item => item.label),
      datasets: [{ data: items.map(item => item.value), backgroundColor: color, borderRadius: 5 }],
    },
    options: {
      indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: context => formatter(context.raw) } },
      },
      scales: {
        x: { ticks: { maxTicksLimit: 3, callback: formatter === money ? compactMoney : number } },
        y: { grid: { display: false }, ticks: { callback(value) {
          const label = this.getLabelForValue(value);
          return label.length > 23 ? label.slice(0, 22) + '…' : label;
        } } },
      },
    },
  };
}

export function renderCharts(data) {
  const charts = data.charts || {};
  const month = charts.month || [];
  const channel = charts.channel || [];
  drawChart('month', {
    type: 'line',
    data: {
      labels: month.map(item => item.label),
      datasets: [
        { label: 'Net sales', data: month.map(item => item.net), borderColor: '#176b61', backgroundColor: '#176b6115', fill: true, tension: .25 },
        { label: 'Gross sales', data: month.map(item => item.gross), borderColor: '#ed8b65', tension: .25 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: { callbacks: { label: ctx => ctx.dataset.label + ': ' + money(ctx.raw) } },
      },
      scales: {
        y: { ticks: { maxTicksLimit: 4, callback: compactMoney } },
        x: { grid: { display: false }, ticks: { maxTicksLimit: 5, maxRotation: 0 } },
      },
    },
  });
  drawChart('channel', {
    type: 'doughnut',
    data: {
      labels: channel.map(item => item.label),
      datasets: [{ data: channel.map(item => item.value), backgroundColor: ['#176b61', '#ed8b65', '#75b9a7', '#d4ac50', '#668aaa', '#99799d', '#a6a99b'], borderWidth: 2 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '65%',
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 10, padding: 14 } },
        tooltip: { callbacks: { label: ctx => ctx.label + ': ' + money(ctx.raw) } },
      },
    },
  });
  drawChart('brand', horizontalChart(charts.brand || [], '#176b61'));
  drawChart('category', horizontalChart(charts.category || [], '#75b9a7'));
  drawChart('sku', horizontalChart(charts.sku || [], '#ed8b65'));
  drawChart('status', horizontalChart((charts.status || []).map(item => ({ ...item, value: item.orders })), '#6f8d84', number));
}
