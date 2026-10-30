#!/usr/bin/env node
'use strict';

// Render already edited copy; this helper neither writes news nor retrieves assets.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');

function args(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--help') { result.help = true; continue; }
    if (!['--input', '--output-dir', '--node-module-dir', '--browser-executable'].includes(key)) throw Error(`Unknown argument: ${key}`);
    if (!argv[i + 1] || argv[i + 1].startsWith('--')) throw Error(`Missing value for ${key}`);
    result[key.slice(2)] = argv[++i];
  }
  return result;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function localImage(file, root) {
  if (typeof file !== 'string' || !file.trim()) throw Error('Image file must be a nonempty local path');
  if (/^[a-z]+:\/\//i.test(file) || file.startsWith('data:')) throw Error('Provide a local image file; remote image retrieval is not part of rendering');
  const resolved = path.resolve(root, file);
  const types = {'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp','.gif':'image/gif','.svg':'image/svg+xml'};
  const mime = types[path.extname(resolved).toLowerCase()];
  if (!mime) throw Error(`Unsupported image extension: ${file}`);
  const data = fs.readFileSync(resolved);
  return {file: resolved, sha256: crypto.createHash('sha256').update(data).digest('hex'), data: `data:${mime};base64,${data.toString('base64')}`};
}

function normalize(input, root) {
  if (input.schema_version !== 1) throw Error('Expected schema_version: 1');
  if (!input.source || typeof input.source.path !== 'string' || !/^[0-9a-f]{64}$/i.test(input.source.sha256 || '')) throw Error('source.path and source.sha256 are required');
  const sourcePath = path.resolve(root, input.source.path);
  if (!['.docx','.txt','.md','.html','.htm','.json'].includes(path.extname(sourcePath).toLowerCase()) || path.basename(sourcePath).startsWith('.env')) throw Error('source.path must refer to an article document');
  const sourceHash = crypto.createHash('sha256').update(fs.readFileSync(sourcePath)).digest('hex');
  if (sourceHash !== input.source.sha256.toLowerCase()) throw Error('Source SHA-256 mismatch; re-extract the current approved article before rendering');
  if (!input.article || !Array.isArray(input.article.blocks)) throw Error('article.blocks must be an array');
  const article = input.article;
  const blocks = article.blocks.map((block, index) => {
    if (!['paragraph', 'heading', 'image'].includes(block.type)) throw Error(`Unsupported block type at ${index}`);
    if (block.type === 'image') return {...block, index, image: localImage(block.file, root)};
    if (typeof block.text !== 'string' || !block.text.trim()) throw Error(`Text block ${index} must contain text`);
    return {...block, index};
  });
  if (!blocks.length) throw Error('The article has no blocks to render');
  const sources = article.sources || [];
  if (!Array.isArray(sources)) throw Error('article.sources must be an array');
  for (const [index, source] of sources.entries()) {
    if (!source || typeof source !== 'object') throw Error(`Invalid source ${index}`);
    if (source.url && !/^https?:\/\//i.test(source.url)) throw Error(`Source ${index} URL must use HTTP or HTTPS`);
    if (![source.label, source.publisher, source.date, source.url].some(v => typeof v === 'string' && v.trim())) throw Error(`Empty source ${index}`);
  }
  const copy = input.copy || {};
  if (!sources.length && !(typeof copy.source_line === 'string' && copy.source_line.trim())) throw Error('News pages require source attribution: provide article.sources or a nonempty copy.source_line');
  const cover = input.cover || {};
  const coverMode = cover.mode || 'image';
  if (!['image','text'].includes(coverMode)) throw Error('cover.mode must be image or text');
  if (coverMode === 'image' && !cover.image) throw Error('Cover image is missing. Supply a local cover.image, or use cover.mode: "text" only when the user explicitly requested a text cover');
  const coverTitle = copy.cover_title ?? article.title ?? '';
  const coverSummary = copy.cover_summary ?? '';
  for (const [key, value] of Object.entries({cover_title:coverTitle, cover_summary:coverSummary, source_line:copy.source_line || ''})) {
    if (typeof value !== 'string') throw Error(`${key} must be a string`);
  }
  const defaults = {width:1080,height:1440,margin:64,font_size:42,line_height:68,paragraph_gap:24,heading_size:42,heading_line_height:64,column_gap:128,highlight:'#EAE3F4',underline:'#8064A8',background:'#FFFFFF',text:'#161616',font_family:'Songti SC',cover_title_size:96,cover_summary_size:40,source_size:22,source_line_height:36};
  const theme = {...defaults};
  for (const [key, value] of Object.entries(input.theme || {})) {
    if (!(key in defaults)) throw Error(`Unknown theme field: ${key}`);
    if (typeof defaults[key] === 'number') {
      if (!Number.isFinite(value) || value <= 0) throw Error(`theme.${key} must be a positive number`);
    } else if (key === 'font_family') {
      if (typeof value !== 'string' || !/^[\p{L}\p{N} ._-]+$/u.test(value)) throw Error('Invalid font_family');
    } else if (!/^#[0-9a-f]{6}$/i.test(value)) throw Error(`theme.${key} must be a six-digit hex color`);
    theme[key] = value;
  }
  if (!Number.isInteger(theme.width) || !Number.isInteger(theme.height) || theme.width * 4 !== theme.height * 3) throw Error('Page dimensions must be integer pixels in a 3:4 ratio');
  if (theme.margin * 2 >= Math.min(theme.width, theme.height)) throw Error('Page margins leave no content area');
  if (theme.line_height < theme.font_size || theme.heading_line_height < theme.heading_size || theme.source_line_height < theme.source_size) throw Error('Line heights must accommodate their font sizes');
  const coverImage = cover.image ? localImage(cover.image, root) : null;
  if (!coverImage && !coverTitle && !coverSummary) throw Error('The text cover has no supplied title or summary');
  return {blocks, sources, copy, theme, coverTitle, coverSummary, coverImage, coverCaption:cover.caption || '', hasCover:true, verifiedSource:{path:sourcePath,sha256:sourceHash}};
}

function createHtml(model) {
  const t = model.theme, W = t.width - 2 * t.margin, H = t.height - 2 * t.margin;
  const e = escapeHtml;
  const body = model.blocks.map(b => b.type === 'image'
    ? `<figure data-source-block="${b.index}" data-block-type="image"><img src="${b.image.data}" alt="${e(b.caption || '')}">${b.caption ? `<figcaption>${e(b.caption)}</figcaption>` : ''}</figure>`
    : b.type === 'heading' ? `<h2 data-source-block="${b.index}" data-block-type="heading"><span>${e(b.text)}</span></h2>` : `<p data-source-block="${b.index}" data-block-type="paragraph">${e(b.text)}</p>`).join('');
  const sourceLines = [];
  if (model.copy.source_line) sourceLines.push(`<div>${e(model.copy.source_line)}</div>`);
  model.sources.forEach(s => {
    const description = [s.label, s.publisher, s.date].filter(Boolean).join(' · ') || (s.url ? new URL(s.url).hostname : '');
    sourceLines.push(`<div>${e(description)}</div>`);
  });
  const cover = model.hasCover ? `<section class="sheet cover" data-page="1">${model.coverImage ? `<div class="hero-wrap"><img class="hero" src="${model.coverImage.data}" alt="${e(model.coverCaption)}"></div>` : ''}<div class="cover-main">${model.coverCaption ? `<div class="photo-caption">${e(model.coverCaption)}</div>` : ''}${model.coverTitle ? `<h1 class="cover-title">${e(model.coverTitle)}</h1>` : ''}${model.coverSummary ? `<div class="cover-summary">${e(model.coverSummary)}</div>` : ''}</div></section>` : '';
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>${e(model.coverTitle || '小红书分页稿')}</title><style>
*{box-sizing:border-box}html,body{margin:0;padding:0}body{background:#e9e9e7;color:${t.text};font-family:"${t.font_family}","STSong",serif;-webkit-font-smoothing:antialiased}
.sheet{width:${t.width}px;height:${t.height}px;background:${t.background};position:relative;margin:32px auto;overflow:hidden}
.cover{display:flex;flex-direction:column}.hero-wrap{flex:1;min-height:0;overflow:hidden}.hero{width:100%;height:100%;object-fit:cover;display:block}.cover-main{flex:none;padding:36px ${t.margin}px ${t.margin}px;display:flex;flex-direction:column;gap:28px}.cover:not(:has(.hero)){justify-content:center}.photo-caption{font:22px/30px "PingFang SC",sans-serif;color:#777}.cover-title{margin:0;font-size:${t.cover_title_size}px;line-height:1.22;letter-spacing:-1px;font-weight:900;white-space:pre-wrap;overflow-wrap:anywhere}.cover-summary{margin:0;padding-left:24px;border-left:7px solid #222;font-size:${t.cover_summary_size}px;line-height:1.6;font-weight:600;white-space:pre-wrap;overflow-wrap:anywhere}
.content-viewport{position:absolute;top:${t.margin}px;left:${t.margin}px;width:${W}px;height:${H}px;overflow:hidden}.article-flow{width:${W}px;height:${H}px;column-gap:${t.column_gap}px;column-width:${W}px;column-count:1;column-fill:auto;font-size:${t.font_size}px;line-height:${t.line_height}px;font-weight:400;letter-spacing:0;text-align:justify;line-break:strict;overflow:visible;overflow-wrap:anywhere}
.article-flow p{margin:0 0 ${t.paragraph_gap}px;break-inside:auto;orphans:2;widows:2;text-wrap:pretty;word-break:normal;white-space:pre-wrap}.article-flow h2{font-size:${t.heading_size}px;line-height:${t.heading_line_height}px;font-weight:900;margin:32px 0 20px;break-after:avoid;break-inside:avoid;text-align:left;letter-spacing:0;white-space:pre-wrap;overflow-wrap:anywhere}.article-flow h2:first-child{margin-top:0}.article-flow h2 span{background:linear-gradient(to bottom,transparent 16%,${t.highlight} 16%,${t.highlight} 93%,transparent 93%);padding:3px 4px;box-decoration-break:clone;-webkit-box-decoration-break:clone;border-bottom:2px solid ${t.underline}}
.article-flow figure{margin:20px 0 28px;break-inside:avoid;text-align:left;max-height:${H - 12}px}.article-flow figure img{display:block;width:100%;height:auto;max-height:${Math.floor(H * .64)}px;object-fit:contain}.article-flow figcaption{font-size:${t.source_size}px;line-height:${t.source_line_height}px;color:#727272;margin-top:12px;white-space:pre-wrap;overflow-wrap:anywhere}
.source-footer{font-size:${t.source_size}px;line-height:${t.source_line_height}px;color:#727272;margin-top:24px;padding-top:16px;border-top:1px solid #deded9;text-align:left;break-inside:avoid;overflow-wrap:anywhere}.source-footer>div+div{margin-top:12px}.source-url{font-family:"${t.font_family}",serif}.layout-stage{position:absolute;left:0;top:0;visibility:hidden;pointer-events:none}
@media print{body{background:#fff}.sheet{margin:0;page-break-after:always}.layout-stage{display:none}}
</style></head><body>${cover}<div class="layout-stage"><div class="article-flow" id="master-flow">${body}${sourceLines.length ? `<div class="source-footer">${sourceLines.join('')}</div>` : ''}</div></div></body></html>`;
}

function loadPlaywright(directory) {
  const attempts = [];
  const candidates = directory ? [path.resolve(directory, 'playwright'), path.resolve(directory)] : ['playwright', path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright')];
  for (const candidate of candidates) {
    try { const found = require(candidate); if (found.chromium) return found; attempts.push(`${candidate}: chromium unavailable`); }
    catch (error) { attempts.push(`${candidate}: ${error.code || error.message}`); }
  }
  throw Error(`Installed Playwright was not found. Supply --node-module-dir with an existing node_modules directory. No package was downloaded. ${attempts.join('; ')}`);
}

function pngSize(file) {
  const bytes = fs.readFileSync(file);
  if (bytes.length < 24 || bytes.subarray(0, 8).toString('hex') !== '89504e470d0a1a0a') throw Error(`Invalid PNG output: ${file}`);
  return {width:bytes.readUInt32BE(16),height:bytes.readUInt32BE(20)};
}

async function main() {
  const options = args(process.argv.slice(2));
  if (options.help) { console.log('Usage: node render_pages.cjs --input manifest.json --output-dir NEW_DIRECTORY [--node-module-dir EXISTING_NODE_MODULES] [--browser-executable CHROME_PATH]'); return; }
  if (!options.input || !options['output-dir']) throw Error('--input and --output-dir are required');
  const inputFile = path.resolve(options.input), output = path.resolve(options['output-dir']);
  if (fs.existsSync(output)) throw Error(`Output directory already exists; choose a new path: ${output}`);
  const inputBytes = fs.readFileSync(inputFile);
  const input = JSON.parse(inputBytes.toString('utf8'));
  const model = normalize(input, path.dirname(inputFile));
  const {chromium} = loadPlaywright(options['node-module-dir']);
  fs.mkdirSync(path.dirname(output), {recursive:true});
  // Exclusive creation also protects against two renderers choosing the same path.
  fs.mkdirSync(output);
  fs.mkdirSync(path.join(output, '图片'));
  let browser;
  try {
    const launch = {headless:true};
    if (options['browser-executable']) launch.executablePath = path.resolve(options['browser-executable']);
    else launch.channel = 'chrome';
    try { browser = await chromium.launch(launch); }
    catch (error) { throw Error(`Could not launch installed Chrome. Supply --browser-executable with an existing compatible browser. No browser was downloaded. ${error.message}`); }
    const context = await browser.newContext({viewport:{width:model.theme.width + 160,height:model.theme.height + 100},deviceScaleFactor:1});
    await context.setOffline(true);
    const page = await context.newPage();
    await page.setContent(createHtml(model), {waitUntil:'load'});
    await page.evaluate(async () => { await document.fonts.ready; await Promise.all([...document.images].map(img => img.decode())); });
    const expected = model.blocks.filter(b => b.type !== 'image').map(b => ({index:b.index,type:b.type,text:b.text}));
    const result = await page.evaluate(({expected,theme,hasCover}) => {
      const W = theme.width - 2 * theme.margin, H = theme.height - 2 * theme.margin, G = theme.column_gap, step = W + G, pageOffset = hasCover ? 2 : 1;
      const master = document.getElementById('master-flow');
      const original = [...master.querySelectorAll('[data-source-block]')].filter(n=>n.dataset.blockType !== 'image').map(n=>({index:Number(n.dataset.sourceBlock),type:n.dataset.blockType,text:n.textContent}));
      if (JSON.stringify(original) !== JSON.stringify(expected)) throw Error('Source body mismatch');
      let columns = Math.max(1, Math.ceil((master.scrollWidth + G) / step));
      if (columns > 100) throw Error('Article exceeds 100 body pages; check input or split editorially');
      function balance(n) { master.style.width = `${n * W + (n - 1) * G}px`; master.style.columnCount = n; master.style.columnWidth = 'auto'; master.style.columnFill = 'balance'; }
      const maximum = columns;
      for (let n = 1; n <= maximum; n++) { balance(n); if (Math.ceil((master.scrollWidth + G) / step) <= n) { columns = n; break; } }
      balance(columns);
      if (Math.ceil((master.scrollWidth + G) / step) > columns) throw Error('Unexpected extra column');
      const origin = master.getBoundingClientRect(), fragments = [], blocks = [], bottoms = Array(columns).fill(0), tops = Array(columns).fill(Infinity);
      function charRows(element) {
        const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT); let node; const chars = [];
        while (node = walker.nextNode()) {
          let offset = 0;
          for (const ch of node.textContent) {
            const range = document.createRange(); range.setStart(node, offset); offset += ch.length; range.setEnd(node, offset);
            const rects = [...range.getClientRects()].filter(r=>r.height > .1);
            if (!rects.length) { if (ch.trim()) throw Error('Unpainted character'); if (!chars.length) throw Error('Unlocatable leading whitespace; normalize block boundaries'); chars.push({...chars.at(-1), ch}); continue; }
            const r = rects[0], x = r.left - origin.left, y = r.top - origin.top, col = Math.floor((x + .1) / step), localX = x - col * step;
            // Justified lines can paint an invisible trailing space exactly at (or a hair past)
            // the column's right edge; that is not clipped content, so clamp it onto the line
            // instead of failing the render. Everything else must stay inside the column.
            const eolSpace = ch === ' ' && col >= 0 && col < columns && localX >= W - 1 && localX <= W + 60 && y > -.8 && r.bottom - origin.top <= H + .8;
            if (!eolSpace && (col < 0 || col >= columns || localX < -.8 || localX + r.width > W + .8 || y < -.8 || r.bottom - origin.top > H + .8)) throw Error('Text outside column: '+JSON.stringify({ch,col,x:localX,y,bottom:r.bottom-origin.top}));
            chars.push({ch,col,y,bottom:r.bottom-origin.top}); bottoms[col] = Math.max(bottoms[col], r.bottom-origin.top); tops[col] = Math.min(tops[col], y);
          }
        }
        return chars;
      }
      for (const node of master.querySelectorAll('[data-source-block]')) {
        const index = Number(node.dataset.sourceBlock), type = node.dataset.blockType;
        if (type === 'image') {
          const rects = [...node.getClientRects()].filter(r=>r.width > .1 && r.height > .1);
          if (rects.length !== 1) throw Error(`Image block ${index} was split across pages`);
          const r = rects[0], col = Math.floor((r.left-origin.left+.1)/step), localX=r.left-origin.left-col*step, top=r.top-origin.top, bottom=r.bottom-origin.top;
          if (col < 0 || col >= columns || localX < -.8 || localX+r.width > W+.8 || top < -.8 || bottom > H+.8) throw Error(`Image block ${index} is clipped`);
          const img=node.querySelector('img'); if (!img.complete || !img.naturalWidth) throw Error(`Image block ${index} failed to load`);
          if (node.querySelector('figcaption')) charRows(node.querySelector('figcaption'));
          bottoms[col]=Math.max(bottoms[col],bottom);tops[col]=Math.min(tops[col],top);
          blocks.push({index,type,pages:[col+pageOffset],caption:node.querySelector('figcaption')?.textContent||'',image_bounds:{x:localX,top,bottom,width:r.width}});
          continue;
        }
        const chars = charRows(node);
        if (chars.map(c=>c.ch).join('') !== node.textContent) throw Error(`Character coverage mismatch at block ${index}`);
        let start=0;
        for(let i=1;i<=chars.length;i++) {
          if (i<chars.length && chars[i].col===chars[start].col) continue;
          const piece=chars.slice(start,i), fragment={source_block_index:index,type,start,end:i,page:piece[0].col+pageOffset,text:piece.map(c=>c.ch).join(''),line_tops:[...new Set(piece.map(c=>Math.round(c.y*100)/100))]};
          if(fragments.length && fragment.page<fragments.at(-1).page) throw Error('Non-sequential column text');
          fragments.push(fragment);start=i;
        }
        blocks.push({index,type,text:node.textContent,pages:[...new Set(chars.map(c=>c.col+pageOffset))]});
      }
      const headingChecks=[];
      for(const heading of blocks.filter(b=>b.type==='heading')) {
        const position=blocks.findIndex(b=>b.index===heading.index), following=blocks[position+1];
        if(!following) throw Error(`Heading block ${heading.index} has no following content`);
        const pageNumber=heading.pages[0];
        if(heading.pages.length!==1) throw Error(`Heading block ${heading.index} crosses pages`);
        if(following.type==='image') {
          if(!following.pages.includes(pageNumber)) throw Error(`Heading block ${heading.index} is isolated from its following image`);
          headingChecks.push({source_block_index:heading.index,page:pageNumber,following_image:true});continue;
        }
        const allLines=new Set(fragments.filter(f=>f.source_block_index===following.index).flatMap(f=>f.line_tops.map(y=>`${f.page}:${y}`))).size;
        const samePageLines=new Set(fragments.filter(f=>f.source_block_index===following.index&&f.page===pageNumber).flatMap(f=>f.line_tops)).size;
        const required=Math.min(2,allLines);
        if(!samePageLines || samePageLines<required) throw Error(`Orphan heading at block ${heading.index}: ${samePageLines} following lines, ${required} required`);
        headingChecks.push({source_block_index:heading.index,page:pageNumber,following_text_lines:samePageLines,required_lines:required});
      }
      const source = master.querySelector('.source-footer'); let sourcePages=[];
      if(source) {
        const sourceChars=charRows(source);sourcePages=[...new Set(sourceChars.map(c=>c.col+pageOffset))];
        if(sourcePages.length!==1 || sourcePages[0]!==columns-1+pageOffset) throw Error('Sources do not fit entirely on the final body page');
      }
      const full=expected.map(b=>b.text).join('');if(fragments.map(f=>f.text).join('')!==full) throw Error('Fragment reconstruction mismatch');
      const palette=[...master.querySelectorAll('h2 span')].map(node=>({background:getComputedStyle(node).backgroundImage,underline:getComputedStyle(node).borderBottomColor}));
      const pages=[];
      for(let col=0;col<columns;col++) {
        if(!Number.isFinite(tops[col])) throw Error('Unexpected blank body page');
        const sheet=document.createElement('section');sheet.className='sheet article';sheet.dataset.page=col+pageOffset;
        const viewport=document.createElement('div');viewport.className='content-viewport';const clone=master.cloneNode(true);clone.removeAttribute('id');clone.style.transform=`translateX(${-col*step}px)`;viewport.appendChild(clone);sheet.appendChild(viewport);document.body.appendChild(sheet);
        pages.push({page:col+pageOffset,column:col,content_top:tops[col],content_bottom:bottoms[col],bottom_whitespace:H-bottoms[col],fragments:fragments.filter(f=>f.page===col+pageOffset),image_blocks:blocks.filter(b=>b.type==='image'&&b.pages.includes(col+pageOffset)).map(b=>b.index),source_visible:sourcePages.includes(col+pageOffset)});
      }
      document.querySelector('.layout-stage').remove();
      let coverCheck=null;
      if(hasCover) {
        const cover=document.querySelector('.cover'), cr=cover.getBoundingClientRect(), content=cover.querySelector('.cover-main'), hero=cover.querySelector('.hero-wrap');
        for(const child of content.children) { const r=child.getBoundingClientRect();if(r.left<cr.left-.5||r.right>cr.right+.5||r.top<cr.top-.5||r.bottom>cr.bottom-theme.margin+.5) throw Error('Cover text is clipped'); }
        if(hero) { const r=hero.getBoundingClientRect(),img=hero.querySelector('img');if(r.height<180||r.bottom>content.getBoundingClientRect().top+.5||!img.naturalWidth) throw Error('Cover image is clipped or crowded by copy'); }
        const last=content.lastElementChild?.getBoundingClientRect();coverCheck={image_height:hero?.getBoundingClientRect().height||0,bottom_whitespace:last?cr.bottom-last.bottom:cr.height};
      }
      const dimensions=[...document.querySelectorAll('.sheet')].map(sheet=>{const r=sheet.getBoundingClientRect();if(r.width!==theme.width||r.height!==theme.height) throw Error('Wrong page dimensions');return {width:r.width,height:r.height};});
      const headerFooterCount=document.querySelectorAll('header,footer,[data-page-number],.article-top,.article-footer,.cover-tag,.cover-date,.cover-rule').length;
      if(headerFooterCount) throw Error('Unexpected page header, footer or page number');
      return {text_exact_match:true,text_blocks:expected.length,text_characters:[...full].length,body_columns:columns,image_count:columns+(hasCover?1:0),dimensions,pages,fragments,split_paragraphs:blocks.filter(b=>b.type==='paragraph'&&b.pages.length>1),heading_checks:headingChecks,palette,cover:coverCheck,header_footer_count:headerFooterCount,source_present:!!source,source_only_final_visible_page:!!source,source_pages:sourcePages,blocks};
    }, {expected,theme:model.theme,hasCover:model.hasCover});
    const images=[];
    for(let i=0;i<result.image_count;i++) {
      const name=String(i+1).padStart(2,'0')+(model.hasCover&&i===0?'_封面':'_正文')+'.png', file=path.join(output,'图片',name);
      await page.locator('.sheet').nth(i).screenshot({path:file,animations:'disabled'});
      const dimensions=pngSize(file);
      if(dimensions.width!==model.theme.width||dimensions.height!==model.theme.height) throw Error(`Screenshot has wrong dimensions: ${name}`);
      images.push({file:`图片/${name}`,...dimensions,sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
    }
    fs.writeFileSync(path.join(output,'分页排版.html'),'<!doctype html>\n'+await page.locator('html').evaluate(node=>node.outerHTML));
    fs.writeFileSync(path.join(output,'逐页内容.json'),JSON.stringify([...(model.hasCover?[{page:1,type:'cover',title:model.coverTitle,summary:model.coverSummary}]:[]),...result.pages.map(p=>({page:p.page,type:'article',fragments:p.fragments,image_blocks:p.image_blocks,source_visible:p.source_visible}))],null,2)+'\n');
    fs.writeFileSync(path.join(output,'来源链接.txt'),model.sources.map(s=>[s.label,s.publisher,s.date,s.url].filter(Boolean).join('\n')).join('\n\n')+'\n');
    const report={status:'passed',checked_at:new Date().toISOString(),input:{path:inputFile,sha256:crypto.createHash('sha256').update(inputBytes).digest('hex'),source:model.verifiedSource},theme:model.theme,...result,images,visual_review:'PNG files still require actual visual inspection before delivery.'};
    fs.writeFileSync(path.join(output,'排版检查.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify({status:'passed',output_dir:output,image_count:images.length,dimensions:[model.theme.width,model.theme.height],text_exact_match:true,split_paragraphs:result.split_paragraphs.map(b=>({block:b.index,pages:b.pages})),source_pages:result.source_pages}));
  } catch(error) {
    fs.writeFileSync(path.join(output,'failure-report.json'),JSON.stringify({status:'failed',checked_at:new Date().toISOString(),input:inputFile,message:error.message,stack:error.stack,retained_outputs:fs.readdirSync(output)},null,2)+'\n');
    throw error;
  } finally { if(browser) await browser.close(); }
}

main().catch(error=>{console.error(error.stack||error.message);process.exitCode=1;});
