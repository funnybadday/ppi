#!/usr/bin/env python3
"""短语级坐标裁剪（crop_paper_figure.py 的本案例适配版，不改skills/）。

本PDF（JMIR XSL-FO排版）中图表标题被pdfplumber拆为多个词（"Table" "1."），
原脚本的单词包含匹配无法命中。本脚本沿用原脚本的坐标定位思路与断言
（首行=标题、后续正文零混入、区域非空），把匹配单位从单词改为连续词短语。

用法:
  python3 crop_with_phrase.py --pdf 素材/论文全文.pdf --page 3 \
    --caption-phrase "Table 1. Sequential" --next-phrase "and Define-XML" \
    --output 公众号/配图/论文Table1_证据阶段.png
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CAPTION_MARGIN = 0.0015  # 与 crop_paper_figure.py 一致
DEFAULT_DPI = 300


def parse_args():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--pdf', required=True)
    p.add_argument('--page', type=int, required=True)
    p.add_argument('--caption-phrase', required=True, help='图表标题开头连续词（如 "Table 1. Sequential"）')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--next-phrase', help='图表之后正文开头连续词')
    g.add_argument('--bottom', type=float, help='底界（页面高度百分比，兜底）')
    p.add_argument('--output', required=True)
    p.add_argument('--dpi', type=int, default=DEFAULT_DPI)
    p.add_argument('--left', type=float, default=0.04)
    p.add_argument('--right', type=float, default=0.96)
    return p.parse_args()


def norm(s: str) -> str:
    return re.sub(r'\s+', '', s)


def find_phrase_top(words, phrase: str):
    """返回连续词短语首次出现的 top（页面pt）与x0；词须同行（top差<3pt）且升序。"""
    tokens = phrase.split()
    n = len(tokens)
    for i in range(len(words) - n + 1):
        seq = words[i:i + n]
        if any(seq[j]['text'] != tokens[j] for j in range(n)):
            continue
        if max(w['top'] for w in seq) - min(w['top'] for w in seq) > 3:
            continue
        if all(seq[j + 1]['x0'] > seq[j]['x0'] for j in range(n - 1)):
            return seq[0]['top'], seq[0]['x0']
    return None, None


def lines_in_region(words, top: float, bottom: float, page_height: float):
    in_region = [w for w in words if top * page_height <= (w['top'] + w['bottom']) / 2 <= bottom * page_height]
    in_region.sort(key=lambda w: (round(w['top'], 1), w['x0']))
    rows, current, last = [], [], None
    for w in in_region:
        if last is not None and abs(w['top'] - last) > 4:
            rows.append(' '.join(current))
            current = []
        current.append(w['text'])
        last = w['top']
    if current:
        rows.append(' '.join(current))
    return rows


def main() -> int:
    args = parse_args()
    import pdfplumber
    from PIL import Image

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.is_file():
        print(f'错误: PDF不存在: {pdf_path}', file=sys.stderr)
        return 2

    with pdfplumber.open(str(pdf_path)) as pdf:
        if not 1 <= args.page <= len(pdf.pages):
            print(f'错误: 页码超出范围（共{len(pdf.pages)}页）', file=sys.stderr)
            return 2
        page = pdf.pages[args.page - 1]
        page_height = page.height
        words = sorted(page.extract_words(), key=lambda w: (round(w['top'], 1), w['x0']))

        cap_top, _ = find_phrase_top(words, args.caption_phrase)
        if cap_top is None:
            print(f'错误: 第{args.page}页未找到标题短语 "{args.caption_phrase}"', file=sys.stderr)
            return 2
        top = cap_top / page_height - CAPTION_MARGIN

        if args.next_phrase:
            nxt_top, _ = find_phrase_top(words, args.next_phrase)
            if nxt_top is None or nxt_top <= cap_top:
                print(f'错误: 未找到后续正文短语 "{args.next_phrase}"（或位于标题之前）', file=sys.stderr)
                return 2
            bottom = nxt_top / page_height - CAPTION_MARGIN
        else:
            bottom = args.bottom
        if bottom <= top:
            print(f'错误: 底界({bottom:.1%})不高于顶界({top:.1%})', file=sys.stderr)
            return 2

        rows = lines_in_region(words, top, bottom, page_height)
        if not rows:
            print('错误: 裁剪区域内无内容', file=sys.stderr)
            return 2
        first_lines = ''.join(rows[:2]).replace(' ', '')
        if norm(args.caption_phrase)[:12] not in first_lines:
            print(f'断言失败: 区域前两行不含标题 "{args.caption_phrase}"，实际首行: {rows[0][:80]}', file=sys.stderr)
            return 3
        if args.next_phrase:
            np_compact = norm(args.next_phrase)
            leaked = [r for r in rows if np_compact in r.replace(' ', '')]
            if leaked:
                print(f'断言失败: 后续正文混入裁剪区: {leaked[0][:80]}', file=sys.stderr)
                return 3

    with tempfile.TemporaryDirectory() as tmp:
        prefix = str(Path(tmp) / 'page')
        subprocess.run(['pdftoppm', '-png', '-r', str(args.dpi), '-f', str(args.page), '-l', str(args.page),
                        str(pdf_path), prefix], check=True, capture_output=True)
        rendered = sorted(Path(tmp).glob('page-*.png'))[0]
        img = Image.open(rendered).convert('RGB')
        w, h = img.size
        crop = img.crop((int(w * args.left), int(h * top), int(w * args.right), int(h * bottom)))

    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out)
    print(f'已裁剪: {out}')
    print(f'  边界: 第{args.page}页 垂直{top:.2%}-{bottom:.2%}, 水平{args.left:.0%}-{args.right:.0%}, {crop.size[0]}x{crop.size[1]}px @{args.dpi}dpi')
    print(f'  首行: {rows[0][:70]}')
    print(f'  末行: {rows[-1][:70]}')
    print(f'  区域共{len(rows)}行（断言已通过）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
