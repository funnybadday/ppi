#!/usr/bin/env python3
"""Normalize edited article/copy JSON for the offline Xiaohongshu renderer.

This tool neither extracts Word/TXT content nor writes news, fetches media, or
infers a cover from another case. Read the actual article before structuring it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit


DOCUMENT_EXTENSIONS = {'.docx', '.txt', '.md', '.html', '.htm', '.json'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}
COPY_FIELDS = ('cover_title', 'cover_summary', 'post_title', 'post_body')
BLOCK_TYPES = {'p': 'paragraph', 'h': 'heading', 'paragraph': 'paragraph', 'heading': 'heading', 'image': 'image'}


def reject_env(path):
    if any(part.lower().startswith('.env') for part in Path(path).parts):
        raise ValueError('Expected an article document or media file; environment files are not accepted')


def existing_file(value, description, extensions):
    raw = Path(value).expanduser()
    reject_env(raw)
    resolved = raw.resolve()
    reject_env(resolved)
    if resolved.suffix.lower() not in extensions:
        raise ValueError(f'{description} must be an article document' if description == 'Source file' else f'{description} has an unsupported extension: {raw.name}')
    if not resolved.is_file():
        raise ValueError(f'{description} not found: {resolved}')
    return resolved


def read_json(value, description):
    path = existing_file(value, description, {'.json'})
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f'{description} is not valid UTF-8 JSON: {path}') from error
    if not isinstance(data, dict):
        raise ValueError(f'{description} must contain a JSON object')
    return path, data


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{field} must contain nonempty text')
    return value


def resolve_media(value, article_directory, asset_directories, description):
    required_text(value, description)
    if re.match(r'^[a-z][a-z0-9+.-]*:', value, flags=re.I):
        raise ValueError(f'{description} must use a local media path: {value}')
    raw = Path(value).expanduser()
    reject_env(raw)
    choices = [raw] if raw.is_absolute() else [directory / raw for directory in [article_directory, *asset_directories]]
    found = []
    for choice in choices:
        resolved = choice.resolve()
        reject_env(resolved)
        if resolved.is_file() and resolved not in found:
            found.append(resolved)
    if not found:
        raise ValueError(f'{description} not found: {value}; searched the article JSON directory and supplied --asset-dir directories')
    if len(found) > 1:
        raise ValueError(f'Ambiguous {description}: {value}; matches: ' + ', '.join(map(str, found)))
    if found[0].suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError(f'{description} has an unsupported image extension: {found[0].name}')
    return str(found[0])


def validate_sources(sources):
    if not isinstance(sources, list):
        raise ValueError('article.sources must be an array')
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f'Source {index} must be an object')
        if not any(isinstance(source.get(key), str) and source[key].strip() for key in ('label', 'publisher', 'date', 'url')):
            raise ValueError(f'Source {index} has no usable source description')
        for key in ('label', 'publisher', 'date', 'url'):
            if key in source and not isinstance(source[key], str):
                raise ValueError(f'Source {index}.{key} must be a string')
        if source.get('url'):
            url = source['url']
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme.lower() in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                valid = False
            if not valid or any(char.isspace() for char in url):
                raise ValueError(f'Source {index} URL must be a valid HTTP or HTTPS URL without credentials')
    return sources


def prepare(options):
    output = Path(options.output).expanduser().absolute()
    reject_env(output)
    if output.exists() or output.is_symlink():
        raise ValueError(f'Output manifest already exists; choose a new path: {output}')
    article_path, article = read_json(options.article_json, 'Article JSON')
    _, copy = read_json(options.copy_json, 'Copy JSON')
    source_path = existing_file(options.source_file, 'Source file', DOCUMENT_EXTENSIONS)
    asset_directories = []
    for value in options.asset_dir:
        folder = Path(value).expanduser().resolve()
        reject_env(folder)
        if not folder.is_dir():
            raise ValueError(f'Asset directory not found: {folder}')
        asset_directories.append(folder)
    required_text(article.get('title'), 'article.title')
    blocks = article.get('blocks')
    if not isinstance(blocks, list) or not blocks:
        raise ValueError('article.blocks must be a nonempty array')
    normalized = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get('type') not in BLOCK_TYPES:
            kind = block.get('type') if isinstance(block, dict) else type(block).__name__
            raise ValueError(f'Unsupported article block type at {index}: {kind}')
        result = dict(block)
        result['type'] = BLOCK_TYPES[block['type']]
        if result['type'] == 'image':
            result['file'] = resolve_media(block.get('file'), article_path.parent, asset_directories, f'Image block {index}')
            if 'caption' in result and not isinstance(result['caption'], str):
                raise ValueError(f'Image block {index}.caption must be a string')
        else:
            required_text(block.get('text'), f'Article block {index}.text')
        normalized.append(result)
    for field in COPY_FIELDS:
        required_text(copy.get(field), f'copy.{field}')
    if 'source_line' in copy and not isinstance(copy['source_line'], str):
        raise ValueError('copy.source_line must be a string')
    if 'hashtags' in copy and (not isinstance(copy['hashtags'], list) or any(not isinstance(item, str) for item in copy['hashtags'])):
        raise ValueError('copy.hashtags must be an array of strings')
    cover = {'mode': options.cover_mode}
    if options.cover_mode == 'image':
        if not options.cover_image:
            raise ValueError('An image cover requires --cover-image; use --cover-mode text only for an explicitly requested text cover')
        cover['image'] = resolve_media(options.cover_image, article_path.parent, asset_directories, 'Cover image')
    elif options.cover_image:
        raise ValueError('--cover-mode text cannot be combined with --cover-image')
    if options.cover_caption is not None:
        cover['caption'] = options.cover_caption
    normalized_article = {**article, 'blocks': normalized, 'sources': validate_sources(article.get('sources', []))}
    if not normalized_article['sources'] and not copy.get('source_line', '').strip():
        raise ValueError('Last-page source is required: provide at least one article.sources record or a nonempty copy.source_line')
    normalized_article.pop('theme', None)
    manifest = {'schema_version': 1, 'article': normalized_article, 'copy': copy, 'cover': cover,
                'source': {'path': str(source_path), 'sha256': hashlib.sha256(source_path.read_bytes()).hexdigest()}}
    if 'theme' in article:
        if not isinstance(article['theme'], dict):
            raise ValueError('theme must be an object; renderer validates supported fields and dimensions')
        manifest['theme'] = article['theme']
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as handle:
        handle.write(encoded)
    return {'ok': True, 'output': str(output), 'source': manifest['source'], 'block_count': len(normalized),
            'source_count': len(normalized_article['sources']), 'cover_mode': cover['mode']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--article-json', required=True, help='Structured article JSON; relative media paths start here')
    parser.add_argument('--copy-json', required=True, help='Edited cover_title, cover_summary, post_title and post_body JSON')
    parser.add_argument('--source-file', required=True, help='Actual completed article document to hash; no automatic Word/TXT extraction')
    parser.add_argument('--cover-image', help='Local cover path; relative to article JSON or an explicit asset directory')
    parser.add_argument('--cover-mode', choices=('image', 'text'), default='image')
    parser.add_argument('--cover-caption')
    parser.add_argument('--asset-dir', action='append', default=[], help='Explicit local media directory; repeat for multiple directories')
    parser.add_argument('--output', required=True, help='New renderer manifest; existing files are never replaced')
    options = parser.parse_args()
    try:
        result = prepare(options)
    except (OSError, ValueError, TypeError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
