#!/usr/bin/env python3
"""Offline cross-run context and editorial event ledger; never fetches or scores."""
import argparse
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import unquote_plus, urlsplit, urlunsplit
from zoneinfo import ZoneInfo


STATUSES = {'recommended', 'drafted', 'published', 'deferred', 'dismissed', 'pending'}
CHANGES = {'new', 'update', 'repeat', 'pending'}


def validate_platform_outputs(value):
    """A format conversion is metadata on the same event, not a recommendation."""
    if not isinstance(value, dict) or set(value) - {'wechat', 'xiaohongshu'}:
        raise ValueError('platform_outputs must map wechat/xiaohongshu to objects')
    for platform, output in value.items():
        if not isinstance(output, dict):
            raise ValueError('Invalid platform output: ' + platform)
        if 'review_status' in output and output['review_status'] not in (
                'awaiting_user_review', 'approved'):
            raise ValueError('Invalid platform review_status')
        if 'published' in output and not isinstance(output['published'], bool):
            raise ValueError('Platform published must be boolean')
        if 'directory' in output and (not isinstance(output['directory'], str)
                                      or not output['directory'].strip()):
            raise ValueError('Platform directory must be a nonempty string')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamps must include a timezone')
    return result


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def normalized_url(url):
    """Remove known tracking only; preserve query order, case and page identity."""
    if not isinstance(url, str):
        raise ValueError('URL must be a string')
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in ('http', 'https') or not parsed.hostname:
        raise ValueError('Expected an absolute HTTP(S) URL')
    if parsed.username or parsed.password:
        raise ValueError('URLs containing credentials are unsupported')
    host = parsed.hostname.lower()
    if ':' in host:
        host = '[' + host + ']'
    port = parsed.port
    if port and (parsed.scheme.lower(), port) not in (('http', 80), ('https', 443)):
        host += ':' + str(port)
    query = []
    for part in parsed.query.split('&') if parsed.query else []:
        name = unquote_plus(part.partition('=')[0]).lower()
        if not name.startswith('utm_') and name not in ('fbclid', 'gclid'):
            query.append(part)
    return urlunsplit((parsed.scheme.lower(), host, parsed.path or '/', '&'.join(query), ''))


def fingerprint(item):
    # Changes in fetched_at, feed metadata or an AI score are not article changes.
    return digest([item.get('title') or '', item.get('content') or ''])


def items_at(path):
    rows = read_json(path)
    if not isinstance(rows, list):
        raise ValueError(str(path) + ' must contain an array')
    ids = set()
    for item in rows:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
            raise ValueError(str(path) + ' contains an invalid item ID')
        if item['id'] in ids:
            raise ValueError(str(path) + ' contains duplicate item IDs')
        ids.add(item['id'])
        normalized_url(item.get('url'))
    return rows


def ledger_path(root):
    return root / '选题池/事件台账.json'


def load_ledger(path):
    if not path.exists():
        return {'schema_version': 1, 'events': [], 'processed_reviews': {}}
    value = read_json(path)
    if (not isinstance(value, dict) or value.get('schema_version') != 1
            or not isinstance(value.get('events'), list)
            or not isinstance(value.get('processed_reviews'), dict)):
        raise ValueError('Invalid event ledger schema: ' + str(path))
    keys = set()
    for event in value['events']:
        if not isinstance(event, dict) or not isinstance(event.get('event_key'), str) or not event['event_key']:
            raise ValueError('Invalid event key in ledger')
        if event['event_key'] in keys or event.get('status') not in STATUSES:
            raise ValueError('Duplicate key or invalid status in ledger')
        keys.add(event['event_key'])
        for field in ('sources', 'discovery_items', 'recommendation_history'):
            if not isinstance(event.get(field), list):
                raise ValueError('Invalid ledger event field: ' + field)
        if 'platform_outputs' in event:
            validate_platform_outputs(event['platform_outputs'])
    return value


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def ledger_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the lock inode stable: unlinking after release can split concurrent locks.
    with path.with_suffix(path.suffix + '.lock').open('a', encoding='utf-8') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Event ledger is busy; retry after the active writer finishes') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def historical_runs(root):
    directory = root / 'Horizon/data/mcp-runs'
    if not directory.exists():
        return []
    result = []
    for path in directory.iterdir():
        if path.is_dir() and (path / 'meta.json').exists():
            meta = read_json(path / 'meta.json')
            result.append((instant(meta['created_at']), path, meta))
    return sorted(result, key=lambda row: (row[0], row[1].name))


def event_urls(event):
    urls = [source.get('url') for source in event.get('sources', []) if isinstance(source, dict)]
    urls.extend(item.get('discovery_url') or item.get('url')
                for item in event.get('discovery_items', []) if isinstance(item, dict))
    return {normalized_url(url) for url in urls if url}


def compare(root, run_dir, output):
    meta = read_json(run_dir / 'meta.json')
    cutoff = instant(meta['created_at'])
    raw = items_at(run_dir / 'raw_items.json')
    ledger = load_ledger(ledger_path(root))
    history = {}
    count = 0
    runs = historical_runs(root)
    for when, path, prior in runs:
        if when >= cutoff or path.resolve() == run_dir.resolve() or not (path / 'raw_items.json').exists():
            continue
        count += 1
        for item in items_at(path / 'raw_items.json'):
            history.setdefault(normalized_url(item['url']), []).append({
                'run_id': prior.get('run_id', path.name), 'item_id': item['id'],
                'collected_at': when.isoformat(), 'content_fingerprint': fingerprint(item)})
    event_index = {}
    for event in ledger['events']:
        for url in event_urls(event):
            event_index.setdefault(url, []).append(event['event_key'])
    rows = []
    for item in raw:
        url, content_hash = normalized_url(item['url']), fingerprint(item)
        prior = history.get(url, [])
        status = 'new_url'
        if prior:
            status = ('same_url_same_content' if prior[-1]['content_fingerprint'] == content_hash
                      else 'same_url_changed')
        rows.append({'item_id': item['id'], 'title': item.get('title', ''), 'url': item['url'],
                     'normalized_url': url, 'content_fingerprint': content_hash,
                     'history_status': status, 'previous_matches': prior,
                     'matched_event_keys': event_index.get(url, [])})
    result = {'schema_version': 1, 'run_id': meta.get('run_id', run_dir.name),
              'generated_at': now_iso(), 'source_run_directory': str(run_dir.resolve()),
              'history_run_count': count, 'raw_items_count': len(raw),
              'counts': dict(Counter(row['history_status'] for row in rows)),
              'ledger_path': str(ledger_path(root).resolve()), 'known_events': ledger['events'],
              'items': rows, 'scope': 'Exact URL/content context only; editorial event decisions remain required.'}
    protected = {ledger_path(root).resolve(), (run_dir / 'meta.json').resolve()}
    protected.update(p.resolve() for p in run_dir.glob('*_items.json'))
    for _, path, _ in runs:
        protected.add((path / 'meta.json').resolve())
        protected.update(p.resolve() for p in path.glob('*_items.json'))
    if output.resolve() in protected:
        raise ValueError('Context output cannot overwrite the ledger or run inputs')
    atomic_json(output, result)
    return {'output': str(output.resolve()), 'raw_items_count': len(raw),
            'history_run_count': count, 'counts': result['counts']}


def merge_unique(existing, additional):
    seen = {digest(row) for row in existing}
    for row in additional:
        if digest(row) not in seen:
            existing.append(deepcopy(row))
            seen.add(digest(row))


def source_rows(entry):
    rows = []
    for field in ('sources', 'additional_sources'):
        value = entry.get(field, [])
        if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
            raise ValueError(field + ' must contain source objects')
        rows.extend(value)
    source = entry.get('source')
    if source is not None:
        if not isinstance(source, dict):
            raise ValueError('source must be an object')
        rows.insert(0, source)
    if entry.get('source_url'):
        rows.append({'url': entry['source_url']})
    for row in rows:
        normalized_url(row.get('url'))
    return rows


def apply_review(ledger, review, review_hash, review_file):
    if not isinstance(review, dict):
        raise ValueError('Review must be a JSON object')
    events = review.get('events', [])
    history_rows = review.get('history_review', [])
    if not isinstance(events, list) or not isinstance(history_rows, list):
        raise ValueError('events and history_review must be arrays')
    if not events and not history_rows and not (
            isinstance(review.get('source_run'), str) and review['source_run'].strip()
            and 'events' in review and 'history_review' in review):
        raise ValueError('Empty review requires a source_run and both decision arrays')
    index = {event['event_key']: event for event in ledger['events']}
    timestamp = now_iso()
    observed = review.get('observed_at', timestamp)
    observed_time = instant(observed)
    for entry, recommended in [(x, True) for x in events] + [(x, False) for x in history_rows]:
        if not isinstance(entry, dict):
            raise ValueError('Each review decision must be an object')
        change = entry.get('change_type', 'new' if recommended else 'pending')
        if change not in CHANGES:
            raise ValueError('Invalid change_type')
        if not recommended and change not in ('repeat', 'pending', 'update'):
            raise ValueError('history_review accepts repeat, pending, or non-recommended update decisions')
        sources = source_rows(entry)
        discoveries = entry.get('discovery_items', [])
        if not isinstance(discoveries, list) or any(not isinstance(x, dict) for x in discoveries):
            raise ValueError('discovery_items must contain objects')
        key = entry.get('event_key')
        if key is not None and (not isinstance(key, str) or not key.strip()):
            raise ValueError('event_key must be a nonempty string')
        if not key:
            if change in ('update', 'repeat'):
                raise ValueError('update/repeat requires an existing event_key')
            if not sources:
                raise ValueError('A new event needs a source URL or an explicit event_key')
            key = 'evt-' + digest([normalized_url(sources[0]['url']), entry.get('source_date') or 'unknown'])[:20]
        previous = index.get(key)
        if previous and change == 'new':
            raise ValueError('Existing event_key cannot be recorded as new: ' + key)
        if previous is None and change in ('update', 'repeat'):
            raise ValueError('Unknown event_key for update/repeat: ' + key)
        if change == 'update' and not str(entry.get('change_note') or '').strip():
            raise ValueError('update requires a concrete change_note')
        status = entry.get('status')
        if status == 'awaiting_user_selection':
            status = 'recommended'
        if status is not None and status not in STATUSES:
            raise ValueError('Invalid event status')
        if previous is None:
            if not entry.get('topic'):
                raise ValueError('New event requires a topic')
            previous = {'event_key': key, 'first_seen': observed, 'sources': [],
                        'discovery_items': [], 'recommendation_history': [], 'review_history': []}
            ledger['events'].append(previous)
            index[key] = previous
        if change != 'repeat':
            for field in ('topic', 'source_date', 'source_date_note', 'verified_facts',
                          'fact_summary', 'new_information', 'category'):
                if field in entry:
                    previous[field] = deepcopy(entry[field])
        if 'article_directory' in entry:
            previous['article_directory'] = deepcopy(entry['article_directory'])
        if 'platform_outputs' in entry:
            validate_platform_outputs(entry['platform_outputs'])
            outputs = previous.setdefault('platform_outputs', {})
            for platform, output in entry['platform_outputs'].items():
                outputs.setdefault(platform, {}).update(deepcopy(output))
        default_status = 'pending' if change == 'pending' or not recommended else 'recommended'
        old_status = previous.get('status')
        if old_status in ('drafted', 'published') and status in (None, 'recommended'):
            status = old_status
        elif status is None and change == 'update' and recommended and old_status == 'pending':
            status = 'recommended'
        previous['status'] = status or old_status or default_status
        if observed_time < instant(previous['first_seen']):
            previous['first_seen'] = observed
        if observed_time >= instant(previous.get('last_seen', previous['first_seen'])):
            previous['last_seen'] = observed
        merge_unique(previous['sources'], sources)
        merge_unique(previous['discovery_items'], discoveries)
        decision = deepcopy(entry)
        decision.update({'event_key': key, 'change_type': change, 'recorded_at': timestamp,
                         'observed_at': observed,
                         'source_run': review.get('source_run'), 'review_file': str(review_file.resolve()),
                         'review_hash': review_hash})
        previous.setdefault('review_history', []).append(decision)
        if recommended and change in ('new', 'update'):
            previous['recommendation_history'].append(deepcopy(decision))
    ledger['processed_reviews'][review_hash] = {'review_file': str(review_file.resolve()),
        'source_run': review.get('source_run'), 'recorded_at': timestamp}
    ledger['updated_at'] = timestamp


def record(root, review_file):
    review = read_json(review_file)
    review_hash = digest(review)
    path = ledger_path(root)
    with ledger_lock(path):
        ledger = load_ledger(path)
        if review_hash in ledger['processed_reviews']:
            return {'ledger_path': str(path.resolve()), 'already_recorded': True,
                    'event_count': len(ledger['events']), 'review_hash': review_hash}
        # All validation and updates finish in memory before replacing the file.
        apply_review(ledger, review, review_hash, review_file)
        atomic_json(path, ledger)
    return {'ledger_path': str(path.resolve()), 'already_recorded': False,
            'event_count': len(ledger['events']), 'review_hash': review_hash}


def valid_score(item):
    value = ((item.get('processing') or {}).get('analysis') or {}).get('score')
    return not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) and 0 <= value <= 10


def window(root, now=None):
    current = instant(now) if now else datetime.now(timezone.utc)
    candidates, excluded = [], []
    for when, path, meta in historical_runs(root):
        if when > current:
            continue
        if meta.get('fetch_status') != 'success' or any(
                not (path / (stage + '_items.json')).exists() for stage in ('raw', 'scored', 'filtered')):
            excluded.append(path.name)
            continue
        raw, scored, filtered = [items_at(path / (stage + '_items.json'))
                                 for stage in ('raw', 'scored', 'filtered')]
        ids = lambda rows: {row['id'] for row in rows}
        # RSS can swallow individual feed errors and still report aggregate success.
        # An empty run alone is therefore insufficient to advance the checkpoint.
        if (not raw or ids(raw) != ids(scored) or not ids(filtered) <= ids(scored)
                or not all(valid_score(x) for x in scored + filtered)):
            excluded.append(path.name)
            continue
        # Collection time is conservative: completion/edit time could mask a long fetch gap.
        candidates.append((when, meta.get('run_id', path.name)))
    checkpoint = max(candidates) if candidates else None
    hours = max(48, math.ceil((current - checkpoint[0]).total_seconds() / 3600 + 24)) if checkpoint else 96
    if current.astimezone(ZoneInfo('Asia/Shanghai')).weekday() == 0:
        hours = max(hours, 96)
    return {'hours': hours, 'checkpoint_run_id': checkpoint[1] if checkpoint else None,
            'checkpoint_at': checkpoint[0].isoformat() if checkpoint else None,
            'exceeds_seven_days': hours > 168, 'excluded_run_ids': excluded,
            'coverage_note': 'Nonempty run-level checkpoint only. Empty aggregate successes do not advance it; RSS success does not prove each feed succeeded.',
            'warning': 'Gap exceeds seven days; feed retention may require targeted recovery.' if hours > 168 else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('compare', 'record', 'window'):
        sub = commands.add_parser(command)
        sub.add_argument('--project-root', type=Path, required=True)
        if command == 'compare':
            sub.add_argument('--run-dir', type=Path, required=True)
            sub.add_argument('--output', type=Path, required=True)
        elif command == 'record':
            sub.add_argument('--review-file', type=Path, required=True)
        else:
            sub.add_argument('--now', help='Timezone-aware timestamp; defaults to the actual current time')
    args = parser.parse_args()
    try:
        if args.command == 'compare':
            result = compare(args.project_root, args.run_dir, args.output)
        elif args.command == 'record':
            result = record(args.project_root, args.review_file)
        else:
            result = window(args.project_root, args.now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
