// BOSS 直聘 JD 采集器（CDP 驱动，跟随已登录会话）
// node harvest.js <搜索词> <采集份数上限>
// 输出：out\_boss\jds.jsonl（一行一份：title/salary/company/tags/desc）
const http = require('http');
const fs = require('fs');

const OUT = __dirname + '\\jds.jsonl';
const SEARCH = process.argv[2] || '上位机';
const LIMIT = parseInt(process.argv[3] || '15', 10);
const sleep = ms => new Promise(r => setTimeout(r, ms));

function getTargets() {
  return new Promise((resolve, reject) => {
    http.get('http://127.0.0.1:9222/json/list', res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    }).on('error', reject);
  });
}

class Tab {
  constructor(ws) { this.ws = ws; this.id = 0; this.pending = new Map(); }
  static async attach(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
    const t = new Tab(ws);
    ws.onmessage = ev => {
      const m = JSON.parse(ev.data);
      if (m.id && t.pending.has(m.id)) { t.pending.get(m.id)(m); t.pending.delete(m.id); }
    };
    return t;
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((ok, bad) => {
      this.pending.set(id, m => m.error ? bad(new Error(m.error.message)) : ok(m.result));
      this.ws.send(JSON.stringify({ id, method, params }));
      setTimeout(() => { if (this.pending.has(id)) { this.pending.delete(id); bad(new Error('timeout ' + method)); } }, 25000);
    });
  }
  async nav(url) { await this.send('Page.navigate', { url }); }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, returnByValue: true });
    return r.result.value;
  }
  async waitExpr(expr, tries = 20, gap = 500) {
    for (let i = 0; i < tries; i++) {
      const v = await this.eval(expr);
      if (v) return v;
      await sleep(gap);
    }
    return null;
  }
}

(async () => {
  const targets = await getTargets();
  const t = targets.find(x => x.type === 'page' && x.url.includes('zhipin.com'));
  if (!t) { console.error('zhipin 标签页不存在'); process.exit(2); }
  const tab = await Tab.attach(t.webSocketDebuggerUrl);

  // 1) 搜索列表页
  const q = encodeURIComponent(SEARCH);
  await tab.nav(`https://www.zhipin.com/web/geek/jobs?query=${q}`);
  await sleep(4500);
  const list = await tab.waitExpr(`(() => {
    const cards = [...document.querySelectorAll('.job-card-wrapper, li.job-card-box')];
    if (!cards.length) return null;
    const total = (document.querySelector('.job-count span, .search-job-result .job-count')?.innerText || '').trim();
    const items = cards.map(c => {
      const a = c.querySelector('a[href*="/job_detail/"]');
      return a ? {
        title: c.querySelector('.job-name')?.innerText?.trim() || '',
        salary: c.querySelector('.salary')?.innerText?.trim() || '',
        company: c.querySelector('.company-name a')?.innerText?.trim() || '',
        tags: [...c.querySelectorAll('.tag-list li')].map(x => x.innerText.trim()).join('|'),
        href: a.href
      } : null;
    }).filter(Boolean);
    return JSON.stringify({ total, items });
  })()`);
  if (!list) { console.error('列表页没抓到卡片（可能要登录/验证码）'); process.exit(3); }
  const { total, items } = JSON.parse(list);
  console.log(`搜索"${SEARCH}" 共 ${total || '?'} 个在招职位，本页 ${items.length} 张卡`);

  // 2) 逐份详情（人性节奏）
  const picks = items.slice(0, LIMIT);
  const done = [];
  for (let i = 0; i < picks.length; i++) {
    const it = picks[i];
    try {
      await tab.nav(it.href);
      await sleep(3500 + Math.floor(Math.random() * 1500));
      const desc = await tab.waitExpr(`(() => {
        const el = document.querySelector('.job-sec .job-sec-text, .detail-content, .job-detail-section');
        if (!el) return null;
        const clean = el.innerText.replace(/\n{3,}/g, '\n\n').trim();
        return clean.length > 60 ? clean : null;
      })()`, 10, 600);
      done.push({ ...it, desc: desc || '(详情未取到)' });
      console.log(`[${i + 1}/${picks.length}] ${it.title} @${it.company} — ${desc ? desc.length + ' 字' : '未取到'}`);
    } catch (e) {
      console.log(`[${i + 1}/${picks.length}] ${it.title} — 出错 ${e.message}`);
      done.push({ ...it, desc: '(出错: ' + e.message + ')' });
    }
    await sleep(1200);
  }
  fs.writeFileSync(OUT, done.map(x => JSON.stringify(x)).join('\n'), 'utf8');
  console.log(`完成：${done.length} 份 → ${OUT}`);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
