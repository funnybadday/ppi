#!/usr/bin/env python3
"""Export completed Horizon stages locally, retaining partial and unscored results."""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def indexed(items, label):
    if not isinstance(items, list):
        raise ValueError(label + ' must be a list')
    result = {}
    for item in items:
        key = item.get('id') if isinstance(item, dict) else None
        if not isinstance(key, str) or not key or key in result:
            raise ValueError(label + ' contains missing or duplicate item IDs')
        result[key] = item
    return result


def analysis(item):
    return (item.get('processing') or {}).get('analysis') or {}


def score(item):
    value = analysis(item).get('score')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) and 0 <= value <= 10 else None


def local_time(value):
    instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('Run timestamps must include their timezone')
    return instant.astimezone(ZoneInfo('Asia/Shanghai'))


def row(item):
    data = analysis(item)
    value = score(item)
    return {'id': item['id'], 'title': item.get('title', ''),
            'url': item.get('url', ''), 'published_at': item.get('published_at'),
            'feed_name': (item.get('metadata') or {}).get('feed_name'),
            'score': value, 'status': 'scored' if value is not None else 'unscored',
            'summary': data.get('summary', ''), 'reason': data.get('reason', ''),
            'tags': data.get('tags') or []}


def render_rows(rows):
    if not rows:
        return '本部分无条目。\n'
    blocks = []
    for n, data in enumerate(rows, 1):
        value = data['score']
        blocks.append('\n'.join([
            f"{n}. {data['title']}",
            f"条目ID：{data['id']}",
            f"订阅记录的发布时间：{data['published_at'] or '不明'}",
            f"评分：{value if value is not None else '未评分'}",
            f"Horizon摘要：{data['summary'] or '未取得摘要'}",
            f"理由：{data['reason'] or '未取得评分理由'}",
            '标签：' + '、'.join(data['tags']),
            f"订阅：{data['feed_name'] or '不明'}",
            f"来源：{data['url']}"]))
    return '\n\n'.join(blocks) + '\n'


def export_run(run_dir, output_dir=None, report_dir=None):
    meta = read_json(run_dir / 'meta.json')
    raw = indexed(read_json(run_dir / 'raw_items.json'), 'raw')
    scored = indexed(read_json(run_dir / 'scored_items.json'), 'scored')
    filtered = indexed(read_json(run_dir / 'filtered_items.json'), 'filtered')
    if not set(scored) <= set(raw) or not set(filtered) <= set(scored):
        raise ValueError('Stage IDs are inconsistent with the fetched items')
    if any(score(item) is None for item in filtered.values()):
        raise ValueError('Filtered items contain invalid or missing scores')
    created = local_time(meta['created_at'])
    since = local_time(meta['since']).isoformat() if meta.get('since') else '未记录'
    all_rows = [row(filtered.get(key, scored.get(key, item))) for key, item in raw.items()]
    selected = [row(item) for item in filtered.values()]
    review = [r for r in all_rows if r['id'] not in filtered and r['score'] is not None and r['score'] >= 3]
    unscored = sum(r['score'] is None for r in all_rows)
    fetch_status = meta.get('fetch_status', 'unknown')
    if fetch_status in ('failure', 'failed', 'error'):
        status = 'failed'
    elif unscored or fetch_status in ('partial_failure', 'partial'):
        status = 'partial'
    elif fetch_status != 'success':
        status = 'unknown'
    else:
        status = 'complete' if raw else 'empty'
    counts = {'raw': len(raw), 'scored': len(raw) - unscored, 'unscored': unscored,
              'filtered': len(filtered), 'review': len(review)}
    manifest = {'run_id': meta.get('run_id', run_dir.name),
                'collection_date': created.date().isoformat(),
                'collected_at': created.isoformat(), 'since': since,
                'status': status, 'fetch_status': fetch_status, 'counts': counts,
                'fetch_report': meta.get('fetch_report'),
                'source_run_directory': str(run_dir.resolve()),
                'editorial_review_performed_by_export': False}
    header = '\n'.join([
        f"Horizon筛选结果与摘要｜{manifest['collection_date']}",
        f"采集时间：{created.isoformat()}（Asia/Shanghai）",
        f"回看起点：{since}；运行ID：{manifest['run_id']}",
        f"抓取状态：{fetch_status}；导出状态：{status}",
        f"原始条目{counts['raw']}；已评分{counts['scored']}；未评分{unscored}；筛选保留{counts['filtered']}。",
        f"阈值：{meta.get('filter_threshold_override') if meta.get('filter_threshold_override') is not None else '以本次配置为准，未记录统一覆盖值'}",
        '数量按链接计，不代表全量已按事件去重。订阅日期不等于原始事件日期。',
        '重叠窗口可能包含往日条目；跨日重复与实质更新在候选复核阶段结合事件台账判断。',
        '以下为Horizon原始评分与摘要，不是OpenAI复筛或全面回源结论。',
        '覆盖以实际fetch_report为准，RSS Feeds汇总成功不证明各订阅均成功。',
        '待复核队列保留未进入简报且不少于3分的条目；全量附件保留全部低分与未评分。',
        '', '筛选保留条目', ''])
    if report_dir is not None:
        report_dir.mkdir(parents=True, exist_ok=True)
        suffix = re.sub(r'[^A-Za-z0-9_-]', '_', manifest['run_id'][-8:])
        report_path = report_dir / (created.strftime('%Y-%m-%d_%H%M%S') + '_' + suffix + '_筛选摘要.txt')
        appendix = '\n待复核队列\n\n' + render_rows(review)
        appendix += '\n全量数据与运行记录（保留在原运行目录）\n'
        for name in ['raw_items.json', 'scored_items.json', 'filtered_items.json', 'meta.json']:
            appendix += str((run_dir / name).resolve()) + '\n'
        with report_path.open('x', encoding='utf-8') as stream:
            stream.write(header + render_rows(selected) + appendix)
        return {**manifest, 'report_path': str(report_path.resolve())}
    # All input validation happens before creating a new delivery directory.
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / 'Horizon筛选与摘要.txt').write_text(header + render_rows(selected), encoding='utf-8')
    (output_dir / 'Horizon待复核队列.txt').write_text(render_rows(review), encoding='utf-8')
    (output_dir / 'Horizon全量评分.json').write_text(json.dumps(all_rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (output_dir / '导出记录.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**manifest, 'output_directory': str(output_dir.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--output-dir', type=Path, help='Create a new structured export directory')
    target.add_argument('--report-dir', type=Path, help='Append one readable report to a daily-report folder')
    args = parser.parse_args()
    try:
        result = export_run(args.run_dir, args.output_dir, args.report_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
