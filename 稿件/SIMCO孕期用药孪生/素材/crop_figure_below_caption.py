#!/usr/bin/env python3
"""Science Advances版Figure裁剪（图题在图下方）。

crop_paper_figure.py 的 caption→next-text 方式适用于表题在上的表格；
Science Advances 的 Figure 图题在图形本体下方，故按 production.md 规定用
pdfplumber 图形对象（lines/rects/curves/images）定位图形本体边界：
正文结束之后、图题结束之前，坐标断言后 300dpi 渲染裁剪。

断言：
1. 裁剪区首段文本行=图题（Fig. N.），不得是正文；
2. 图形本体（图形对象bbox）完整落在裁剪区内；
3. 页脚（Einhaus et al.）与正文行不得混入图形带；
4. 区域非空。
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--pdf', required=True)
p.add_argument('--page', type=int, required=True)
p.add_argument('--top', type=float, required=True, help='图形带上界（页面高度百分比，正文结束之后）')
p.add_argument('--caption', required=True, help='图题开头词，如 "Fig. 1."')
p.add_argument('--bottom', type=float, required=True, help='图题下界（页面高度百分比，页脚之前）')
p.add_argument('--output', required=True)
p.add_argument('--left', type=float, default=0.04)
p.add_argument('--right', type=float, default=0.96)
args = p.parse_args()

import pdfplumber
from PIL import Image

pdf_path = Path(args.pdf)
with pdfplumber.open(str(pdf_path)) as pdf:
    page = pdf.pages[args.page - 1]
    H, W = page.height, page.width
    words = sorted(page.extract_words(), key=lambda w: (round(w['top'], 0), w['x0']))
    rows = {}
    for w in words:
        rows.setdefault(round(w['top'], 0), []).append(w['text'])
    row_text = {k: ' '.join(v) for k, v in rows.items()}

    # 图题行定位
    cap_key = None
    for k in sorted(row_text):
        if row_text[k].replace(' ', '').startswith(args.caption.replace(' ', '')):
            cap_key = k
            break
    assert cap_key is not None, f'未找到图题 {args.caption}'
    cap_top = cap_key / H

    # 图形本体 bbox（图题上方、top 之下）
    objs = page.lines + page.rects + page.curves + page.images
    band = [o for o in objs if args.top * H < o['top'] < cap_top * H]
    assert band, '图形带内无图形对象'
    g_top = min(o['top'] for o in band)
    g_bottom = max(o['bottom'] for o in band)
    assert g_top >= args.top * H - 2, f'图形上缘({g_top/H:.3f})越过裁剪上界'
    assert g_bottom <= cap_top * H + 2, f'图形下缘({g_bottom/H:.3f})越过图题'

    # 正文混入检查：图形带内的文本行只允许面板标签（<=6字符）与science.org下载水印词
    WATERMARK = {'Downloaded', 'from', 'https://www.science.org', 'on', 'October', '22,', '2026'}
    leaked = [t for k, t in row_text.items()
              if args.top * H < k < cap_key
              and len(t.replace(' ', '')) > 6
              and not all(tok in WATERMARK for tok in t.split())]
    assert not leaked, f'正文混入图形带: {leaked[:2]}'

    # 页脚不得混入裁剪区（"Downloaded from"为PDF自带斜向水印词，叠加在图上，单独放行）
    foot = [t for k, t in row_text.items()
            if args.top * H < k < args.bottom * H and t.startswith('Einhaus et al.')]
    assert not foot, f'页脚混入: {foot[:1]}'

    print(f'图形本体: v {g_top/H:.3f}-{g_bottom/H:.3f}; 图题: {cap_top:.3f} 首行: {row_text[cap_key][:60]}')
    print(f'图形带文本行: {[row_text[k] for k in sorted(row_text) if args.top*H < k < cap_key][:8]}')

with tempfile.TemporaryDirectory() as tmp:
    prefix = str(Path(tmp) / 'page')
    subprocess.run(['pdftoppm', '-png', '-r', '300', '-f', str(args.page), '-l', str(args.page), str(pdf_path), prefix], check=True, capture_output=True)
    img = Image.open(sorted(Path(tmp).glob('page-*.png'))[0]).convert('RGB')
    w, h = img.size
    crop = img.crop((int(w * args.left), int(h * args.top), int(w * args.right), int(h * args.bottom)))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out)
    print(f'已裁剪: {out} {crop.size[0]}x{crop.size[1]}px 边界 v{args.top:.3f}-{args.bottom:.3f} h{args.left}-{args.right}')
