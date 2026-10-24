const http = require('http');
const sleep = ms => new Promise(r => setTimeout(r, ms));
function getTargets() { return new Promise((res, rej) => { http.get('http://127.0.0.1:9222/json/list', r => { let d=''; r.on('data',c=>d+=c); r.on('end',()=>res(JSON.parse(d))); }).on('error', rej); }); }
(async () => {
  const ts = await getTargets();
  const t = ts.find(x => x.type === 'page' && x.url.includes('zhipin.com'));
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((ok,bad) => { ws.onopen=ok; ws.onerror=bad; });
  let id = 0; const pend = new Map();
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
  const send = (method, params={}) => new Promise((ok) => { const i=++id; pend.set(i, m=>ok(m.result)); ws.send(JSON.stringify({id:i, method, params})); });
  const ev = async (e) => (await send('Runtime.evaluate', {expression: e, returnByValue: true})).result?.result?.value;
  await send('Page.navigate', { url: process.argv[2] });
  await sleep(7000);
  const out = await ev(`(() => {
    const secs = [...document.querySelectorAll('div[class], section[class]')].slice(0, 40)
      .map(d => d.className + ' | len=' + d.innerText.length + ' | ' + d.innerText.replace(/\\s+/g,' ').slice(0, 50));
    return JSON.stringify({ url: location.href.slice(0,100), title: document.title.slice(0,50),
      hasJobSec: !!document.querySelector('.job-sec'), bodyLen: document.body.innerText.length,
      head: document.body.innerText.replace(/\\s+/g,' ').slice(0, 260), secs });
  })()`);
  console.log(out);
  ws.close();
  process.exit(0);
})();
