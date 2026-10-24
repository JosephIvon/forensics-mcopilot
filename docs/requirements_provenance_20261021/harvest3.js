// BOSS JD 批量采集 v3：node harvest3.js
// 批次矩阵：5 城市 × 3 搜索词；去重（按 job_detail id）；追加写 jds.jsonl；每份即落盘
const http = require('http');
const fs = require('fs');
const OUT = __dirname + '\\jds.jsonl';
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 城市: BOSS city 代码
const CITY = { '深圳': '101280600', '苏州': '101190400', '佛山': '101281000', '上海': '101020100', '东莞': '101281600' };
// 批次: [城市, 搜索词, 份数]
const BATCHES = [
  ['深圳', '上位机', 10],
  ['深圳', '运动控制', 6],
  ['苏州', '上位机', 10],
  ['苏州', '运动控制', 6],
  ['佛山', '上位机', 8],
  ['上海', '自动化软件工程师', 8],
  ['东莞', '运动控制', 6],
];

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
  // 已有记录 → 去重集
  const seen = new Set();
  if (fs.existsSync(OUT)) {
    for (const line of fs.readFileSync(OUT, 'utf8').split('\n').filter(Boolean)) {
      try { seen.add((JSON.parse(line).href || '').split('?')[0]); } catch {}
    }
  }
  console.log(`已存在 ${seen.size} 份，开始增量采集`);

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
    for (let i = 0; i < tries; i++) { const v = await ev(expr); if (v) return v; await sleep(gap); }
    return null;
  };
  const append = rec => fs.appendFileSync(OUT, JSON.stringify(rec) + '\n', 'utf8');

  const pageReady = `(() => {
    if (/安全验证|security_check/i.test(document.title + location.href)) return null;
    const el = document.querySelector('.job-detail-section');
    return el && el.innerText.replace(/\\s+/g, '').length > 80 ? 'ok' : null;
  })()`;
  const grab = `(() => {
    const clean = s => (s || '').replace(/[\\t ]+/g, ' ').replace(/\\n{3,}/g, '\\n\\n').trim();
    return JSON.stringify({
      banner: clean(document.querySelector('.job-banner')?.innerText),
      desc: clean(document.querySelector('.job-detail-section')?.innerText),
      pageTitle: (document.title.match(/「(.+?)招聘」/) || [])[1] || ''
    });
  })()`;

  let added = 0, skipped = 0, failed = 0;
  for (const [city, term, want] of BATCHES) {
    const url = `https://www.zhipin.com/web/geek/jobs?query=${encodeURIComponent(term)}&city=${CITY[city]}`;
    try {
      await send('Page.navigate', { url });
    } catch { await sleep(3000); await send('Page.navigate', { url }).catch(() => {}); }
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
    })()`, 14, 800);
    if (!listRaw) { console.log(`[${city}/${term}] 列表失败，跳过`); continue; }
    const items = JSON.parse(listRaw);
    console.log(`[${city}/${term}] ${items.length} 张卡`);
    let got = 0;
    for (const it of items) {
      if (got >= want) break;
      const key = it.href.split('?')[0];
      if (seen.has(key)) { skipped++; continue; }
      try {
        await send('Page.navigate', { url: it.href });
        await sleep(5000);
        const ok = await waitExpr(pageReady, 12, 900);
        if (!ok) { console.log(`  ! 未就绪: ${it.title.slice(0, 24)}`); failed++; continue; }
        const d = JSON.parse(await ev(grab));
        append({ city, term, ...it, banner: d.banner, desc: d.desc, pageTitle: d.pageTitle });
        seen.add(key); got++; added++;
        console.log(`  + ${it.title.slice(0, 26)} ${it.salary} (${d.desc.length}字)`);
      } catch (e) {
        console.log(`  ! ERR ${it.title.slice(0, 24)}: ${e.message}`);
        failed++;
      }
      await sleep(1800 + Math.floor(Math.random() * 1600));
    }
    await sleep(2500);
  }
  console.log(`\n完成：新增 ${added}，重复跳过 ${skipped}，失败 ${failed}`);
  console.log(`总计文件记录数：${fs.readFileSync(OUT, 'utf8').split('\n').filter(Boolean).length}`);
  ws.close();
  process.exit(0);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
