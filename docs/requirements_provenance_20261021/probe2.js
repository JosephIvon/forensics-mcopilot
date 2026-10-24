// 诊断版：node probe2.js <url> — 打印 CDP 原始响应 + 页面结构
const http = require('http');
const sleep = ms => new Promise(r => setTimeout(r, ms));
function getTargets() {
  return new Promise((res, rej) => {
    http.get('http://127.0.0.1:9222/json/list', r => {
      let d = '';
      r.on('data', c => d += c);
      r.on('end', () => res(JSON.parse(d)));
    }).on('error', rej);
  });
}
(async () => {
  const url = process.argv[2];
  const ts = await getTargets();
  const t = ts.find(x => x.type === 'page' && x.url.includes('zhipin.com'));
  if (!t) { console.error('无 zhipin 标签页'); process.exit(2); }
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
  let id = 0;
  const pend = new Map();
  ws.onmessage = ev => {
    const m = JSON.parse(ev.data);
    if (pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise(ok => {
    const i = ++id;
    pend.set(i, ok);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evRaw = async e => await send('Runtime.evaluate', { expression: e, returnByValue: true, awaitPromise: true });

  // 管道自检
  const ping = await evRaw('1+1');
  console.log('管道自检:', JSON.stringify(ping.result));

  await send('Page.navigate', { url });
  await sleep(8000);
  const expr = `(() => {
    const pick = sel => { const el = document.querySelector(sel); return el ? el.innerText.replace(/\\s+/g,' ').slice(0,120) : null; };
    return JSON.stringify({
      url: location.href.slice(0,110),
      title: document.title.slice(0,60),
      bodyLen: document.body.innerText.length,
      jobSec: pick('.job-sec'),
      secText: pick('.job-sec-text'),
      detail: pick('.detail-content'),
      jobDetail: pick('.job-detail-section'),
      banner: pick('.job-banner'),
      head: document.body.innerText.replace(/\\s+/g,' ').slice(0,300)
    });
  })()`;
  const r = await evRaw(expr);
  if (r.result && r.result.value !== undefined) {
    console.log('页面状态:', r.result.value);
  } else {
    console.log('CDP 原始响应:', JSON.stringify(r).slice(0, 800));
  }
  ws.close();
  process.exit(0);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
