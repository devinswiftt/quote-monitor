const reload = document.getElementById('ipo-reload');
const status = document.getElementById('ipo-status');
const table = document.getElementById('ipo-table');
const rows = document.getElementById('ipo-rows');
const filters = document.getElementById('ipo-filters');
const dialog = document.getElementById('ipo-chart');
const chartTitle = document.getElementById('ipo-chart-title');
const chartContent = document.getElementById('ipo-chart-content');
const formatter = new Intl.NumberFormat('zh-HK', {maximumFractionDigits: 4});
const date = value => /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : '—';
const labels = {open: '认购中', pending: '待上市', listed: '已上市'};
let stage = 'pending', data, chartRequest = 0;

function price(row) {
  if (row.list_price > 0) return formatter.format(row.list_price);
  const range = [row.ipo_price_min, row.ipo_price_max].filter(value => value > 0);
  return [...new Set(range)].map(value => formatter.format(value)).join('–') || '—';
}

async function showChart(row, listed) {
  const request = ++chartRequest;
  chartTitle.textContent = (row.name || row.code) + ' ' + row.code + ' · 日K';
  chartContent.textContent = listed ? '正在加载富途日K…'
    : '尚未上市，暂无日K。上市日期：' + date(row.list_time);
  dialog.showModal();
  if (!listed) return;
  try {
    const response = await fetch('/api/daily?source=ipo&code=' + encodeURIComponent(row.code));
    const value = await response.json();
    if (!response.ok) throw Error(value.error || '日K加载失败。');
    if (request === chartRequest && dialog.open) chartContent.innerHTML = DailyChart.chartPanel(row.code, value);
  } catch (error) {
    if (request === chartRequest && dialog.open) chartContent.textContent = error.message;
  }
}

function render() {
  if (!data) return;
  const listed = stage === 'listed';
  const source = listed ? data.listed : data.rows;
  const currentIpos = new Map((data.rows || []).map(row => [row.code, row]));
  const listedCodes = new Set((data.listed || []).map(row => row.code));
  const entries = listed
    ? (source || []).map(row => ({...currentIpos.get(row.code), ...row, list_time: row.listing_date}))
      .sort((a, b) => b.list_time.localeCompare(a.list_time) || a.code.localeCompare(b.code))
    : (source || []).filter(row => !listedCodes.has(row.code) && (row.is_subscribe_status === true) === (stage === 'open'))
      .sort((a, b) => String(a.list_time || '9999').localeCompare(String(b.list_time || '9999')));
  rows.replaceChildren(...entries.map(row => {
    const tr = document.createElement('tr');
    const stock = tr.insertCell();
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'secondary';
    button.textContent = row.name || row.code;
    button.addEventListener('click', () => showChart(row, listed));
    const code = document.createElement('small');
    code.textContent = row.code;
    stock.append(button, code);
    for (const value of [labels[stage], date(row.apply_end_time), date(row.list_time), price(row)]) {
      tr.insertCell().textContent = value;
    }
    return tr;
  }));
  table.hidden = !entries.length;
  const summary = source == null ? '富途数据暂不可用，请稍后刷新。'
    : entries.length ? `共 ${entries.length} 只` : `暂无${labels[stage]}股票`;
  if (listed) {
    status.textContent = summary + ' · 富途港股目录，按最近 90 天上市日期筛选，可能含其他上市方式。';
  } else {
    const updated = data.updated_at ? ' · 香港时间 ' + new Date(data.updated_at).toLocaleString('zh-HK', {timeZone: 'Asia/Hong_Kong'}) : '';
    status.textContent = summary + updated + (data.stale && source ? ' · 显示上次结果' : '');
  }
}

async function loadIpos() {
  reload.disabled = true;
  try {
    const response = await fetch('/api/ipo-list');
    if (response.status === 401) {
      location.assign('/');
      return;
    }
    if (!response.ok) throw Error('新股列表读取失败。');
    data = await response.json();
    render();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    reload.disabled = false;
  }
}
filters.addEventListener('click', event => {
  const button = event.target.closest('button[data-stage]');
  if (!button) return;
  stage = button.dataset.stage;
  for (const option of filters.querySelectorAll('button')) option.setAttribute('aria-pressed', String(option === button));
  render();
});
reload.addEventListener('click', loadIpos);
loadIpos();
