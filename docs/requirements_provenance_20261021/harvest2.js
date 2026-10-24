// BOSS JD 采集器 v2（CDP）：node harvest2.js <搜索词> <份数>
// 修复：安全验证页等待、.job-detail-section 选择器、进程退出
const http = require('http');
const fs = require('fs');
const OUT = __dirname + '\\jds.jsonl';
const SEARCH = process.argv[2] || '上位机';
const LIMIT = parseInt(process.argv[3] || '15', 10);
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
  const ts = await getTargets();
  const t = ts.find(x => x.type === 'page' && x.url.includes('zhipin.com'));
  if (!t) { console.error('无 zhipin 标签页'); process.exit(2); }
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
  let id = 0;
  const pend = new Map();
  ws.onmessage = ev => { const m = JSON.parse(ev.data); if (pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); } };
  const send = (method, params = {}) => new Promise((ok, bad) => {
    const i = ++id;
    pend.set(i, m => m.error ? bad(new Error(m.error.message)) : ok(m.result));
    ws.send(JSON.stringify({ id: i, method, params }));
    setTimeout(() => { if (pend.has(i)) { pend.delete(i); bad(new Error('timeout ' + method)); } }, 30000);
  });
  const ev = async e => {
    const r = await send('Runtime.evaluate', { expression: e, returnByValue: true });
    return r.result && r.result.value;
  };
  const waitExpr = async (expr, tries, gap) => {
    for (let i = 0; i < tries; i++) {
      const v = await ev(expr);
      if (v) return v;
      await sleep(gap);
    }
    return null;
  };

  // 1) 列表
  await send('Page.navigate', { url: `https://www.zhipin.com/web/geek/jobs?query=${encodeURIComponent(SEARCH)}` });
  await sleep(5000);
  const listRaw = await waitExpr(`(() => {
    const cards = [...document.querySelectorAll('.job-card-wrapper, li.job-card-box')];
    if (cards.length < 3) return null;
    const items = cards.map(c => {
      const a = c.querySelector('a[href*="/job_detail/"]');
      return a ? { title: c.querySelector('.job-name')?.innerText?.trim() || '',
        salary: c.querySelector('.salary')?.innerText?.trim() || '',
        company: c.querySelector('.company-name a')?.innerText?.trim() || '',
        tags: [...c.querySelectorAll('.tag-list li')].map(x => x.innerText.trim()).join('|'),
        href: a.href } : null;
    }).filter(Boolean);
    return JSON.stringify(items);
  })()`, 16, 800);
  if (!listRaw) { console.error('列表抓取失败'); process.exit(3); }
  const items = JSON.parse(listRaw);
  console.log(`本页 ${items.length} 张卡，采前 ${Math.min(LIMIT, items.length)} 份`);

  // 2) 详情
  const pageReady = `(() => {
    if (/安全验证|security_check/i.test(document.title + location.href)) return null;
    const el = document.querySelector('.job-detail-section');
    return el && el.innerText.replace(/\\s+/g, '').length > 80 ? 'ok' : null;
  })()`;
  const grab = `(() => {
    const clean = s => (s || '').replace(/[\\t ]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim();
    return JSON.stringify({
      banner: clean(document.querySelector('.job-banner')?.innerText),
      desc: clean(document.querySelector('.job-detail-section')?.innerText)
    });
  })()`;
  const done = [];
  for (let i = 0; i < Math.min(LIMIT, items.length); i++) {
    const it = items[i];
    try {
      await send('Page.navigate', { url: it.href });
      await sleep(5000);
      const ok = await waitExpr(pageReady, 14, 900);
      if (!ok) { console.log(`[${i + 1}] ${it.title} — 页面未就绪(验证码?)`); done.push({ ...it, desc: '(未就绪)' }); continue; }
      const d = JSON.parse(await ev(grab));
      done.push({ ...it, banner: d.banner, desc: d.desc });
      console.log(`[${i + 1}] ${it.title} @${it.company} — ${d.desc.length} 字`);
    } catch (e) {
      console.log(`[${i + 1}] ${it.title} — ERR ${e.message}`);
      done.push({ ...it, desc: '(ERR ' + e.message + ')' });
    }
    await sleep(1500 + Math.floor(Math.random() * 1500));
  }
  fs.writeFileSync(OUT, done.map(x => JSON.stringify(x)).join('\n'), 'utf8');
  console.log(`完成 ${done.length} 份 -> ${OUT}`);
  ws.close();
  process.exit(0);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
