#!/usr/bin/env python3
"""Load complete local writing examples after checking their original-file hashes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def load_examples(project):
    index = project / '语气参考/公众号原文/原文索引.json'
    data = json.loads(index.read_text(encoding='utf-8'))
    references = data.get('references')
    if not isinstance(references, list) or not references:
        raise ValueError('The local source index has no references')
    result = []
    for ref in references:
        html, text = [(Path(ref[key]) if Path(ref[key]).is_absolute()
                       else index.parent / ref[key]) for key in ('html', 'text')]
        html_digest = hashlib.sha256(html.read_bytes()).hexdigest()
        text_bytes = text.read_bytes()
        text_digest = hashlib.sha256(text_bytes).hexdigest()
        if html_digest != ref.get('html_sha256'):
            raise ValueError('Local HTML changed; inspect its body and resync the index: ' + str(html))
        if text_digest != ref.get('text_sha256'):
            raise ValueError('Local extracted body needs verification against the HTML: ' + str(text))
        body = text_bytes.decode('utf-8')
        if not body.strip():
            raise ValueError('The extracted body is empty: ' + str(text))
        result.append({'title': ref.get('title'), 'html': str(html.resolve()),
                       'text': str(text.resolve()), 'html_sha256': html_digest,
                       'text_sha256': text_digest, 'body_full_text': body})
    return {'index': str(index.resolve()), 'references': result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = load_examples(args.project_root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
