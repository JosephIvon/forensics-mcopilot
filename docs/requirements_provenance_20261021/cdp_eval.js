// CDP 驱动：node cdp_eval.js <url匹配串|"*"> <js表达式>
// 找到 URL 匹配的标签页，连 WebSocket 执行 Runtime.evaluate，打印返回值(JSON)
const http = require('http');

function getTargets() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json/list', res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

(async () => {
  const [, , matcher, expr] = process.argv;
  const targets = await getTargets();
  const t = targets.find(x => x.type === 'page' &&
    (matcher === '*' || x.url.includes(matcher)));
  if (!t) { console.error(JSON.stringify({ error: 'no tab', urls: targets.filter(x => x.type === 'page').map(x => x.url.slice(0, 80)) })); process.exit(2); }
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
  const result = await new Promise((ok, bad) => {
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id === 1) ok(m.result);
    };
    ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true, awaitPromise: true } }));
    setTimeout(() => bad(new Error('evaluate timeout')), 20000);
  });
  ws.close();
  console.log(JSON.stringify(result, null, 1));
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
