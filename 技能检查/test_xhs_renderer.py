"""Renderer failure boundaries, without launching a browser or fetching assets."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/lab-paper-xhs-post/scripts/render_pages.cjs'
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Requires an installed Node runtime')
class XiaohongshuRendererBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'article.txt'
        self.source.write_text('本次正文。', encoding='utf-8')
        self.input = self.root / 'manifest.json'
        self.output = self.root / 'new-render'
        self.manifest = {'schema_version': 1,
            'source': {'path': str(self.source), 'sha256': hashlib.sha256(self.source.read_bytes()).hexdigest()},
            'article': {'title': '本篇', 'blocks': [{'type': 'paragraph', 'text': '本次正文。'}],
                        'sources': []},
            'copy': {'cover_title': '本篇', 'cover_summary': '一句摘要'},
            'cover': {'mode': 'text'}}

    def call(self):
        self.input.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')
        return subprocess.run([NODE, str(SCRIPT), '--input', str(self.input),
            '--output-dir', str(self.output)], capture_output=True, text=True)

    def test_missing_source_cannot_silently_produce_news_pages(self):
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source attribution', result.stderr)
        self.assertFalse(self.output.exists())

    def test_changed_source_requires_reextraction_before_rendering(self):
        self.source.write_text('当前正文已经更新。', encoding='utf-8')
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA-256 mismatch', result.stderr)
        self.assertFalse(self.output.exists())

    def test_existing_render_directory_is_untouched(self):
        self.output.mkdir()
        sentinel = self.output / 'approved.png'
        sentinel.write_bytes(b'preserve original')
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('already exists', result.stderr)
        self.assertEqual(sentinel.read_bytes(), b'preserve original')
        self.assertEqual(list(self.output.iterdir()), [sentinel])
