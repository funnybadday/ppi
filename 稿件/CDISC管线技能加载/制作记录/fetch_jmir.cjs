#!/usr/bin/env node
// 一次性抓取脚本：用本机Chrome过AWS WAF，保存JMIR文章页HTML与PDF
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('/Users/xulei/项目/搜索/蓝图论文/node_modules/playwright');

(async () => {
  const outDir = '/Users/xulei/项目/搜索/蓝图论文/稿件/CDISC管线技能加载/素材';
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--disable-blink-features=AutomationControlled']
  });
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    locale: 'en-US',
    viewport: { width: 1280, height: 900 }
  });
  const page = await ctx.newPage();
  const url = process.argv[2] || 'https://formative.jmir.org/2026/1/e100769';
  console.log('goto', url);
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  // WAF质询：等待若干秒让其完成并自动跳转
  for (let i = 0; i < 6; i++) {
    await page.waitForTimeout(5000);
    const title = await page.title();
    const len = (await page.content()).length;
    console.log(`t+${(i + 1) * 5}s title="${title}" len=${len} url=${page.url()}`);
    if (title && !/Just a moment|challenge|WAF/i.test(title) && len > 20000) break;
  }
  const html = await page.content();
  fs.writeFileSync(path.join(outDir, 'jmir_article.html'), html);
  console.log('saved jmir_article.html', html.length);
  // 找PDF链接
  const links = await page.$$eval('a', as => as.map(a => ({ href: a.href, text: (a.textContent || '').trim().slice(0, 60) }))
    .filter(l => /pdf|download/i.test(l.href + l.text)));
  console.log('pdf-ish links:', JSON.stringify(links.slice(0, 20), null, 1));
  // 尝试用页面上下文直接下载PDF
  const pdfUrl = (links.find(l => /\/PDF/i.test(l.href)) || {}).href;
  if (pdfUrl) {
    const resp = await ctx.request.get(pdfUrl, { timeout: 120000 });
    const buf = await resp.body();
    console.log('pdf status', resp.status(), 'bytes', buf.length, 'type', resp.headers()['content-type']);
    if (resp.status() === 200 && buf.length > 10000) {
      fs.writeFileSync(path.join(outDir, '论文全文.pdf'), buf);
      console.log('saved 论文全文.pdf');
    } else {
      fs.writeFileSync(path.join(outDir, 'jmir_pdf_try.pdf'), buf);
    }
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
