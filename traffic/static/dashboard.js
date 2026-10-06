'use strict';
const number = (value) => new Intl.NumberFormat('zh-CN').format(value);
let days = 1;
let loading = false;
function rows(id, data, label, count, subtitle, link) {
  const container = document.querySelector('#' + id);
  container.replaceChildren();
  if (!data.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = '当前时段暂无记录，新的访问会在一分钟内更新。';
    container.append(empty);
  }
  for (const item of data.slice(0, 20)) {
    const row = document.createElement('div');
    row.className = 'row';
    const text = document.createElement('div');
    const name = document.createElement(link ? 'a' : 'span');
    name.textContent = label(item);
    if (link) name.href = link(item);
    text.append(name);
    if (subtitle) {
      const sub = document.createElement('small');
      sub.textContent = subtitle(item);
      text.append(sub);
    }
    const value = document.createElement('strong');
    value.textContent = number(count(item));
    row.append(text, value);
    container.append(row);
  }
}
function trend(data, start) {
  const container = document.querySelector('#trend');
  container.replaceChildren();
  const max = Math.max(1, ...data.map((item) => item.views));
  const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const anchor = new Date(today + 'T00:00:00+08:00');
  for (let offset = days - 1; offset >= 0; offset--) {
    const day = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(anchor.getTime() - offset * 86400000));
    const item = data.find((row) => row.date.replaceAll('-', '') === day.replaceAll('-', ''));
    const available = day >= start.slice(0, 10);
    const value = item ? item.views : 0;
    const column = document.createElement('div');
    column.className = 'day';
    column.title = day + (available ? '：' + number(value) + ' 次' : '：监控尚未启用');
    column.setAttribute('aria-label', column.title);
    const count = document.createElement('small');
    count.textContent = available ? number(value) : '—';
    const bar = document.createElement('div');
    bar.className = 'bar';
    bar.style.height = Math.max(2, value / max * 130) + 'px';
    const label = document.createElement('small');
    label.textContent = day.slice(5);
    column.append(count, bar, label);
    container.append(column);
  }
}
const countryNames = new Intl.DisplayNames(['zh-CN'], {type: 'region'});
function countryName(code) {
  if (code === '-') return '未知国家／地区';
  if (code === 'T1') return 'Tor 网络';
  try { return countryNames.of(code) || code; } catch { return code; }
}
function geographyRows(id, data, level) {
  const container = document.querySelector('#' + id);
  container.replaceChildren();
  if (!data.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = '当前时段暂无位置记录。';
    container.append(empty);
    return;
  }
  const heading = document.createElement('div');
  heading.className = 'geo-row geo-heading';
  for (const label of ['地区', '浏览器 PV', 'HTTP 请求']) {
    const text = document.createElement('span');
    text.textContent = label;
    heading.append(text);
  }
  container.append(heading);
  for (const item of data.slice(0, 20)) {
    const row = document.createElement('div');
    row.className = 'geo-row';
    const place = document.createElement('div');
    const name = document.createElement('span');
    name.textContent = level === 'country' ? countryName(item.country)
      : item[level] === '-' ? (level === 'city' ? '未知城市' : '未知省／州') : item[level];
    place.append(name);
    if (level !== 'country') {
      const parent = document.createElement('small');
      parent.textContent = countryName(item.country) + (level === 'city' && item.region !== '-' ? ' · ' + item.region : '');
      place.append(parent);
    }
    row.append(place);
    for (const metric of ['browser_pv', 'http_requests']) {
      const count = document.createElement('strong');
      count.textContent = number(item[metric]);
      row.append(count);
    }
    container.append(row);
  }
}
async function update() {
  if (loading) return;
  loading = true;
  const controls = document.querySelectorAll('.toolbar button');
  controls.forEach((button) => { button.disabled = true; });
  const message = document.querySelector('#message');
  try {
    const response = await fetch('/traffic/api/summary?days=' + days, {cache: 'no-store'});
    if (response.status === 401) { location.replace('/traffic'); return; }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || '统计读取失败，请稍后刷新。');
    document.querySelector('#pv').textContent = number(data.browser_pv);
    document.querySelector('#uv').textContent = number(data.browser_uv);
    document.querySelector('#requests').textContent = number(data.http_requests);
    document.querySelector('#ai-count').textContent = number(data.types['AI 爬虫 / 助手']);
    document.querySelector('#updated').textContent = '最近更新 ' + new Date(data.updated_at).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai'}) + ' · 采集始于 ' + data.collection_started_at.slice(0, 10);
    rows('types', Object.entries(data.types), (row) => row[0], (row) => row[1]);
    rows('sources', data.sources, (row) => row.host, (row) => row.views, (row) => row.kind);
    rows('ai', data.ai, (row) => row.name, (row) => row.requests);
    rows('pages', data.pages, (row) => row.path, (row) => row.views, null, (row) => row.path.startsWith('/wechat') ? row.path : '/wechat');
    const geography = data.geography || {countries: [], regions: [], cities: [], located: {browser_pv: 0}};
    geographyRows('countries', geography.countries, 'country');
    geographyRows('regions', geography.regions, 'region');
    geographyRows('cities', geography.cities, 'city');
    document.querySelector('#geo-info').textContent = 'IP 归属估算 · 浏览器已识别 ' + number(geography.located.browser_pv)
      + ' / ' + number(data.browser_pv) + ' PV · 位置采集始于 ' + (data.location_started_at || data.updated_at).slice(0, 10)
      + ' · 历史无位置记录保留为未知';
    trend(data.daily, data.collection_started_at);
    message.hidden = true;
  } catch (error) {
    message.textContent = error.message === 'Failed to fetch' ? '网络连接失败，保留上次统计；请稍后刷新。' : error.message;
    message.hidden = false;
  } finally {
    controls.forEach((button) => { button.disabled = false; });
    loading = false;
  }
}
document.querySelectorAll('[data-days]').forEach((button) => button.addEventListener('click', () => {
  days = Number(button.dataset.days);
  document.querySelectorAll('[data-days]').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
  update();
}));
document.querySelector('#refresh').addEventListener('click', update);
document.querySelector('#logout').addEventListener('click', async () => {
  const response = await fetch('/traffic/logout', {method: 'POST'});
  if (response.ok) location.replace('/traffic');
});
update();
setInterval(() => { if (!document.hidden) update(); }, 60000);
