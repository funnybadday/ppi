"""Exercise offline article-to-renderer input boundaries with real local files."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/lab-paper-xhs-post/scripts/prepare_input.py'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/5a0AAAAASUVORK5CYII=')


class XiaohongshuInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.article_dir = self.root / 'article'
        self.article_dir.mkdir()
        self.article = self.article_dir / 'article.json'
        self.copy = self.root / 'copy.json'
        self.source = self.root / '公众号正文.txt'
        self.source.write_text('原始公众号正文\n原文标点不得被改写。', encoding='utf-8')
        self.output = self.root / 'new-output' / 'manifest.json'
        self.cover = self.article_dir / 'cover.png'
        self.cover.write_bytes(PNG)
        self.sources = [
            {'label': '原始公告', 'publisher': '官方机构', 'url': 'https://example.org/news', 'date': '2026-10-01'},
            {'label': '正式方案', 'url': 'https://example.org/protocol?v=2', 'date': '2026-10-02'},
        ]
        self.write_article({'title': '临床研究平台进展', 'blocks': [
            {'type': 'p', 'text': '先说明任务。\n再保留原文中的换行与  AI 空格。'},
            {'type': 'h', 'text': '如何执行'},
            {'type': 'paragraph', 'text': '结果以原始文章为准。'}], 'sources': self.sources})
        self.copy.write_text(json.dumps({'cover_title': '研究平台接入AI', 'cover_summary': '围绕同一临床决策，连接模拟、分析与执行。',
            'post_title': '临床研究平台怎样接入AI', 'post_body': '一段已编辑好的发布正文。'}), encoding='utf-8')

    def write_article(self, article):
        self.article.write_text(json.dumps(article, ensure_ascii=False), encoding='utf-8')

    def call(self, *args, cover=True):
        command = [sys.executable, str(SCRIPT), '--article-json', str(self.article),
                   '--copy-json', str(self.copy), '--source-file', str(self.source), '--output', str(self.output)]
        if cover:
            command += ['--cover-image', 'cover.png']
        return subprocess.run(command + list(map(str, args)), cwd=self.root, capture_output=True, text=True)

    def assert_error(self, result, *contains):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        error = json.loads(result.stderr)
        self.assertFalse(error['ok'])
        for item in contains:
            self.assertIn(item, error['error'])
        self.assertFalse(self.output.exists())

    def test_canonicalizes_current_article_aliases_without_changing_body_or_sources(self):
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest['article']['blocks'], [
            {'type': 'paragraph', 'text': '先说明任务。\n再保留原文中的换行与  AI 空格。'},
            {'type': 'heading', 'text': '如何执行'},
            {'type': 'paragraph', 'text': '结果以原始文章为准。'}])
        self.assertEqual(manifest['article']['sources'], self.sources)
        self.assertEqual(manifest['source']['path'], str(self.source.resolve()))
        self.assertEqual(manifest['source']['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(manifest['cover']['image'], str(self.cover.resolve()))
        self.assertEqual(manifest['cover']['mode'], 'image')
        self.assertEqual(manifest['copy']['post_body'], '一段已编辑好的发布正文。')

    def test_resolves_article_media_from_explicit_asset_directories(self):
        assets = self.root / 'images'
        assets.mkdir()
        image = assets / 'diagram.png'
        image.write_bytes(PNG)
        self.write_article({'title': '图片支持', 'blocks': [
            {'type': 'paragraph', 'text': '正文'}, {'type': 'image', 'file': 'diagram.png', 'caption': '来源：实际公告'}],
            'sources': self.sources, 'theme': {'font_size': 44}})
        result = self.call('--asset-dir', assets, '--cover-caption', '来源：本篇已有素材')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest['article']['blocks'][1], {'type': 'image', 'file': str(image.resolve()), 'caption': '来源：实际公告'})
        self.assertEqual(manifest['cover']['caption'], '来源：本篇已有素材')
        self.assertEqual(manifest['theme'], {'font_size': 44})

    def test_rejects_ambiguous_media_instead_of_choosing_first_folder(self):
        assets = self.root / 'different-assets'
        assets.mkdir()
        (assets / 'cover.png').write_bytes(PNG + b'different')
        self.assert_error(self.call('--asset-dir', assets), 'Ambiguous', 'cover.png')

    def test_missing_cover_reports_requested_asset_without_borrowing_from_working_directory(self):
        self.cover.unlink()
        (self.root / 'cover.png').write_bytes(PNG)
        self.assert_error(self.call(), 'cover.png', 'not found')

    def test_text_cover_requires_explicit_mode(self):
        self.assert_error(self.call(cover=False), 'cover', '--cover-image')
        result = self.call('--cover-mode', 'text', cover=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest['cover']['mode'], 'text')
        self.assertNotIn('image', manifest['cover'])

    def test_missing_required_copy_fields_are_not_filled_from_article_title(self):
        copy = json.loads(self.copy.read_text())
        del copy['post_body']
        self.copy.write_text(json.dumps(copy))
        self.assert_error(self.call(), 'post_body')

    def test_unknown_article_block_type_is_not_silently_dropped(self):
        self.write_article({'title': '正文不得丢失', 'blocks': [
            {'type': 'paragraph', 'text': '第一段'}, {'type': 'quote', 'text': '这段也重要'}], 'sources': self.sources})
        self.assert_error(self.call(), 'quote', 'block')

    def test_existing_manifest_is_preserved(self):
        self.output.parent.mkdir()
        self.output.write_text('an existing approved manifest', encoding='utf-8')
        result = self.call()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('exists', json.loads(result.stderr)['error'])
        self.assertEqual(self.output.read_text(), 'an existing approved manifest')

    def test_rejects_source_metadata_without_a_valid_source_url(self):
        article = json.loads(self.article.read_text())
        article['sources'][1]['url'] = 'file:///tmp/fake-news'
        self.write_article(article)
        self.assert_error(self.call(), 'Source', 'HTTP')

    def test_missing_last_page_source_is_rejected_before_creating_manifest(self):
        article = json.loads(self.article.read_text())
        article['sources'] = []
        self.write_article(article)
        copy = json.loads(self.copy.read_text())
        copy['source_line'] = '   '
        self.copy.write_text(json.dumps(copy))
        self.assert_error(self.call(), 'source')

    def test_explicit_source_line_can_supply_a_source_without_a_url(self):
        article = json.loads(self.article.read_text())
        article['sources'] = []
        self.write_article(article)
        copy = json.loads(self.copy.read_text())
        copy['source_line'] = '来源：本篇已核实的官方公告，2026年10月。'
        self.copy.write_text(json.dumps(copy))
        result = self.call()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest['copy']['source_line'], '来源：本篇已核实的官方公告，2026年10月。')
        self.assertEqual(manifest['article']['sources'], [])

    def test_refuses_env_as_source_document(self):
        env = self.root / '.env'
        env.write_text('UNREAD_SECRET=never-display-this')
        self.source = env
        result = self.call()
        self.assert_error(result, 'article document')
        self.assertNotIn('UNREAD_SECRET', result.stderr)
        self.assertNotIn('never-display-this', result.stderr)

    def test_image_missing_from_all_supplied_directories_is_not_removed(self):
        article = json.loads(self.article.read_text())
        article['blocks'].append({'type': 'image', 'file': 'absent.png'})
        self.write_article(article)
        self.assert_error(self.call(), 'absent.png', 'not found')


if __name__ == '__main__':
    unittest.main()
