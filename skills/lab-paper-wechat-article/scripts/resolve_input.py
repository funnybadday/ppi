#!/usr/bin/env python3
"""Normalize an explicitly selected item or manual news URLs; never fetch or draft."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit


def checked_url(value):
    if not isinstance(value, str):
        raise ValueError('A source URL is required')
    value = value.strip()
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Provide an HTTP(S) news URL without embedded credentials')
    if any(ord(char) < 32 for char in value):
        raise ValueError('Source URL contains control characters')
    return value


def selected_source_urls(selected):
    values = []
    source = selected.get('source')
    if isinstance(source, dict) and 'url' in source:
        values.append(source['url'])
    if 'url' in selected:
        values.append(selected['url'])
    for key in ('additional_sources', 'sources', 'source_urls'):
        if key not in selected:
            continue
        entries = selected[key]
        if not isinstance(entries, list):
            raise ValueError(key + ' must be a list of source URLs or source records')
        values.extend(entry.get('url') if isinstance(entry, dict) else entry
                      for entry in entries)
    if not values:
        raise ValueError('A source URL is required')
    return list(dict.fromkeys(checked_url(value) for value in values))


def resolve_selection(path, selection_id):
    if not selection_id:
        raise ValueError('An explicit --selection-id is required; old global selection is not used')
    document = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(document, list):
        items = document
    elif isinstance(document, dict) and isinstance(document.get('events'), list):
        items = document['events']
    elif isinstance(document, dict):
        items = [document]
    else:
        raise ValueError('Unsupported selection file')
    matches = [item for item in items if isinstance(item, dict)
               and item.get('event_id', item.get('id')) == selection_id]
    if len(matches) != 1:
        raise ValueError('The explicit ID must identify exactly one item')
    selected = matches[0]
    result = {'entry_type': 'horizon_selection', 'selection_id': selection_id,
              'selection_file': str(path.resolve()),
              'topic': selected.get('topic', selected.get('title')),
              'source_date': selected.get('source_date', selected.get('published_at')),
              'source_urls': selected_source_urls(selected),
              'inherited_context': {key: selected[key] for key in (
                  'verified_facts', 'verification_scope', 'evidence_boundary',
                  'next_check', 'raw_indexes', 'processing', 'content_type',
                  'user_context', 'event_key', 'change_type', 'change_note',
                  'new_information') if key in selected}}
    if isinstance(document, dict):
        result['source_run'] = document.get('source_run')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--selection-file', type=Path)
    source.add_argument('--url', action='append')
    parser.add_argument('--selection-id')
    args = parser.parse_args()
    try:
        if args.url:
            if args.selection_id:
                raise ValueError('--selection-id belongs to the selection-file entry')
            result = {'entry_type': 'manual_url', 'topic': None,
                      'source_urls': list(dict.fromkeys(checked_url(url) for url in args.url))}
        else:
            result = resolve_selection(args.selection_file, args.selection_id)
        result.update({'schema_version': 1, 'verification_status': 'needs_source_review'})
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
