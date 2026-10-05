(() => {
  if (window.__wechatTraffic || navigator.webdriver || navigator.doNotTrack === '1' || /bot|crawler|spider|headless|playwright|puppeteer/i.test(navigator.userAgent)) return;
  window.__wechatTraffic = true;
  const publicPage = /^\/wechat\/?$|^\/wechat\/(discover|rankings|search|categories)(\/\d+)?\/?$|^\/wechat\/(accounts|articles)\/\d+\/?$/;
  let previous = '';
  let timer;
  function collect() {
    if (document.hidden || !publicPage.test(location.pathname)) return;
    const key = location.pathname + location.search;
    if (previous === key) return;
    const referrer = previous ? location.origin + previous : document.referrer;
    previous = key;
    const body = JSON.stringify({path: location.pathname, referrer});
    try {
      if (!navigator.sendBeacon('/traffic/events', new Blob([body], {type: 'application/json'}))) {
        fetch('/traffic/events', {method: 'POST', headers: {'Content-Type': 'application/json'}, body, keepalive: true}).catch(() => {});
      }
    } catch (_) { /* Analytics must not interrupt navigation. */ }
  }
  function schedule() { clearTimeout(timer); timer = setTimeout(collect, 150); }
  for (const method of ['pushState', 'replaceState']) {
    const original = history[method];
    history[method] = function (...args) { const result = original.apply(this, args); schedule(); return result; };
  }
  addEventListener('popstate', schedule);
  document.addEventListener('visibilitychange', schedule);
  schedule();
})();
