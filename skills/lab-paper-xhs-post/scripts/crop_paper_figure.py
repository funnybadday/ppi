#!/usr/bin/env python3
"""坐标级论文图表裁剪工具（论文版小红书默认流程）。

从论文PDF裁剪表格/图形：以 pdfplumber 的文字坐标定位图表边界（不依赖视觉估计），
pdftoppm 渲染 300dpi 后按坐标裁剪，并做坐标断言验证（区域首行=图表标题、
后续正文不得混入）。本工具不写文案、不核实事实，只负责裁剪与验证。

定位方式（二选一）：
  A. --caption + --next-text ：图表标题起（自动）到后续正文起点止（自动）。
     next-text 填紧跟图表之后的正文开头几个词（如统计段落或下一节标题）。
  B. --caption + --bottom    ：标题起（自动）到指定页面高度百分比止（兜底）。

输出 PNG 并打印验证信息；验证不过则非零退出，不产出半截图。

用法示例：
  python3 crop_paper_figure.py --pdf 素材/论文全文.pdf --page 4 \
    --caption "Table 2" --next-text "Friedman test" \
    --output 公众号/配图/论文Table2_基准设置.png

依赖：pdfplumber、Pillow（Horizon/.venv 已装）、pdftoppm（poppler）。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

CAPTION_MARGIN = 0.0015  # 标题上方留白（页面高度百分比；过大易带入上一段残迹）
DEFAULT_DPI = 300


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--pdf', required=True, help='论文PDF路径')
    parser.add_argument('--page', type=int, required=True, help='1-based 页码')
    parser.add_argument('--caption', required=True, help='图表标题开头词（如 "Table 2"）')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--next-text', help='图表之后正文的开头词（自动定底界）')
    group.add_argument('--bottom', type=float, help='底界（页面高度百分比，0-1，兜底方式）')
    parser.add_argument('--output', required=True, help='输出PNG路径')
    parser.add_argument('--dpi', type=int, default=DEFAULT_DPI)
    parser.add_argument('--left', type=float, default=0.04, help='左边界百分比（默认0.04）')
    parser.add_argument('--right', type=float, default=0.96, help='右边界百分比（默认0.96）')
    return parser.parse_args()


def find_word_top(words, snippet: str):
    """返回匹配 snippet 的词的 top（页面高度百分比），未找到返回 None。

    匹配顺序：①标题式 token（"Table6:" 带冒号开头，避免命中正文句
    "Table 6 gives..."）；②单 token 包含；③同行连续词元拼接的短语级匹配
    （应对 PDF 把 "Table 1." 拆成多个词元的情况）。
    """
    compact = snippet.replace(' ', '')
    with_colon = compact + ':'
    for w in words:  # 第一轮：标题式 token
        text = w['text'].replace(' ', '')
        if text.startswith(with_colon):
            return w['top']
    for w in words:  # 第二轮：单 token 包含
        if compact in w['text'].replace(' ', ''):
            return w['top']
    # 第三轮：按行聚合词元，拼接后做短语匹配。
    # 先匹配"行首即标题"的行（如 "Table3.Tokenusage..."），避免命中
    # 正文中提及该编号的句子（如 "...;Table3）"）。
    rows, current, last = [], [], None
    for w in words:
        if last is not None and abs(w['top'] - last) > 4:
            rows.append(current)
            current = []
        current.append(w)
        last = w['top']
    if current:
        rows.append(current)
    for want_prefix in (True, False):
        for row in rows:
            texts = [w['text'].replace(' ', '') for w in row]
            joined = ''.join(texts)
            idx = joined.find(compact)
            if idx < 0:
                continue
            if want_prefix and idx > 2:  # 行首容差（前置编号/空格）
                continue
            acc = 0
            for w, t in zip(row, texts):
                if acc + len(t) > idx:
                    return w['top']
                acc += len(t)
    return None


def lines_in_region(words, top: float, bottom: float, page_height: float):
    """按行聚合区域内的词（top/bottom 为页面高度百分比），返回行文本列表。"""
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
    import pdfplumber  # 延迟导入，给出清晰报错
    from PIL import Image

    pdf_path = Path(args.pdf).expanduser()
    if not pdf_path.is_file():
        print(f'错误: PDF不存在: {pdf_path}', file=sys.stderr)
        return 2

    with pdfplumber.open(str(pdf_path)) as pdf:
        if not 1 <= args.page <= len(pdf.pages):
            print(f'错误: 页码 {args.page} 超出范围（共{len(pdf.pages)}页）', file=sys.stderr)
            return 2
        page = pdf.pages[args.page - 1]
        page_height = page.height
        words = sorted(page.extract_words(), key=lambda w: w['top'])

        # 顶界：图表标题
        caption_top = find_word_top(words, args.caption)
        if caption_top is None:
            print(f'错误: 第{args.page}页未找到标题 "{args.caption}"', file=sys.stderr)
            return 2
        top = caption_top / page_height - CAPTION_MARGIN

        # 底界
        if args.next_text:
            next_top = find_word_top(words, args.next_text)
            if next_top is None or next_top <= caption_top:
                print(f'错误: 未找到后续正文 "{args.next_text}"（或位于标题之前）', file=sys.stderr)
                return 2
            bottom = next_top / page_height - CAPTION_MARGIN
        else:
            bottom = args.bottom
        if bottom <= top:
            print(f'错误: 底界({bottom:.1%})不高于顶界({top:.1%})', file=sys.stderr)
            return 2

        # 坐标断言验证：首行应为图表标题；后续正文不得混入
        rows = lines_in_region(words, top, bottom, page_height)
        if not rows:
            print('错误: 裁剪区域内无内容', file=sys.stderr)
            return 2
        first_lines = ''.join(rows[:2]).replace(' ', '')
        if args.caption.replace(' ', '') not in first_lines:
            print(f'断言失败: 区域前两行不含标题 "{args.caption}"，实际首行: {rows[0][:80]}', file=sys.stderr)
            return 3
        if args.next_text:
            leaked = [r for r in rows if args.next_text.replace(' ', '') in r.replace(' ', '')]
            if leaked:
                print(f'断言失败: 后续正文混入裁剪区: {leaked[0][:80]}', file=sys.stderr)
                return 3

    # 渲染与裁剪
    with tempfile.TemporaryDirectory() as tmp:
        prefix = str(Path(tmp) / 'page')
        subprocess.run(
            ['pdftoppm', '-png', '-r', str(args.dpi), '-f', str(args.page), '-l', str(args.page), str(pdf_path), prefix],
            check=True, capture_output=True,
        )
        rendered = sorted(Path(tmp).glob('page-*.png'))[0]
        img = Image.open(rendered).convert('RGB')
        w, h = img.size
        crop = img.crop((int(w * args.left), int(h * top), int(w * args.right), int(h * bottom)))

    out = Path(args.output).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    crop.save(out)
    print(f'已裁剪: {out}')
    print(f'  边界: 第{args.page}页 垂直{top:.1%}-{bottom:.1%}, 水平{args.left:.0%}-{args.right:.0%}, {crop.size[0]}x{crop.size[1]}px @{args.dpi}dpi')
    print(f'  首行: {rows[0][:70]}')
    print(f'  末行: {rows[-1][:70]}')
    print(f'  区域共{len(rows)}行（应为表格/图形内容，断言已通过）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
