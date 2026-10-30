"""Check the two offline input routes and complete local few-shot loading."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/lab-paper-wechat-article/scripts'


class ArticleInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def call(self, name, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)],
                              capture_output=True, text=True)

    def test_explicit_candidate_overrides_old_top_level_selection(self):
        # Choosing the old global N02 would send the next article to the wrong story.
        pool = self.root / 'pool.json'
        pool.write_text(json.dumps({'selected_event_id': 'N02', 'events': [
            {'event_id': 'N01', 'topic': '甲骨文患者匹配', 'source_date': '2026-10-20',
             'source': {'url': 'https://example.org/oracle'},
             'verified_facts': '此前只核对了合作公告', 'verification_scope': '历史读取'},
            {'event_id': 'N02', 'topic': '旧选题', 'source': {'url': 'https://example.org/old'}}]}))
        r = self.call('resolve_input.py', '--selection-file', pool, '--selection-id', 'N01')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads(r.stdout)
        self.assertEqual(result['selection_id'], 'N01')
        self.assertEqual(result['topic'], '甲骨文患者匹配')
        self.assertEqual(result['source_urls'], ['https://example.org/oracle'])
        self.assertEqual(result['verification_status'], 'needs_source_review')

    def test_horizon_raw_item_can_be_selected_without_editorial_candidate(self):
        items = self.root / 'scored.json'
        items.write_text(json.dumps([{'id': 'rss:one', 'title': '一条原始线索',
                                     'url': 'https://example.org/raw'}]))
        r = self.call('resolve_input.py', '--selection-file', items, '--selection-id', 'rss:one')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(json.loads(r.stdout)['source_urls'], ['https://example.org/raw'])

    def test_selected_candidate_keeps_all_sources_in_first_seen_order(self):
        # Dropping a supplementary source loses evidence needed by the article writer.
        pool = self.root / 'pool.json'
        pool.write_text(json.dumps({'events': [{
            'event_id': 'E1', 'source': {'url': 'https://example.org/primary'},
            'url': 'https://example.org/raw',
            'additional_sources': [{'url': 'https://example.org/detail'},
                                   {'url': 'https://example.org/primary'}],
            'sources': ['https://example.org/background',
                        {'url': ' https://example.org/detail '}],
            'source_urls': ['https://example.org/diagram', 'https://example.org/raw']
        }]}))
        r = self.call('resolve_input.py', '--selection-file', pool, '--selection-id', 'E1')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(json.loads(r.stdout)['source_urls'], [
            'https://example.org/primary', 'https://example.org/raw',
            'https://example.org/detail', 'https://example.org/background',
            'https://example.org/diagram'])

    def test_selected_candidate_can_provide_sources_without_a_single_primary_url(self):
        pool = self.root / 'pool.json'
        pool.write_text(json.dumps({'id': 'raw:one', 'title': '一条线索',
                                    'source_urls': ['https://example.org/news']}))
        r = self.call('resolve_input.py', '--selection-file', pool, '--selection-id', 'raw:one')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(json.loads(r.stdout)['source_urls'], ['https://example.org/news'])

    def test_selected_candidate_keeps_editorial_context_as_inherited_material(self):
        # A practice explainer or an update must not silently become a new announcement.
        context = {
            'content_type': 'enterprise_practice_explainer', 'user_context': '按内容解读处理',
            'event_key': 'organization:project', 'change_type': 'substantive_update',
            'change_note': '补充具体任务', 'new_information': ['新增实施步骤'],
            'verified_facts': '此前读取的事实', 'verification_scope': '历史读取',
            'evidence_boundary': '仅支持所列事实', 'next_check': '核对原文',
            'raw_indexes': [3, 7], 'processing': {'status': 'previously_read'}}
        pool = self.root / 'pool.json'
        pool.write_text(json.dumps({'event_id': 'E1', 'url': 'https://example.org/news',
                                    **context}))
        r = self.call('resolve_input.py', '--selection-file', pool, '--selection-id', 'E1')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads(r.stdout)
        self.assertEqual(result['inherited_context'], context)
        self.assertEqual(result['verification_status'], 'needs_source_review')

    def test_invalid_supplementary_urls_fail_even_when_primary_source_is_valid(self):
        bad_sources = [
            {'url': 'file:///tmp/news'},
            {'additional_sources': [{'url': 'ftp://example.org/news'}]},
            {'sources': ['https://user:password@example.org/news']},
            {'sources': [{'url': 'https://example.org/a\nb'}]},
            {'source_urls': ['javascript:alert(1)']},
            {'source_urls': [None]},
            {'additional_sources': [{'title': '缺少网址'}]},
            {'source_urls': 'https://example.org/not-a-list'},
        ]
        pool = self.root / 'pool.json'
        for bad in bad_sources:
            with self.subTest(fields=list(bad)):
                pool.write_text(json.dumps({'event_id': 'E1',
                    'source': {'url': 'https://example.org/primary'}, **bad}))
                r = self.call('resolve_input.py', '--selection-file', pool, '--selection-id', 'E1')
                self.assertNotEqual(r.returncode, 0, r.stdout)
                self.assertFalse(json.loads(r.stderr)['ok'])

    def test_manual_urls_work_without_a_horizon_checkout_or_candidate_pool(self):
        # The direct webpage entry must not depend on a news run or inherited selection.
        r = self.call('resolve_input.py', '--url', 'https://example.org/news?a=1',
                      '--url', 'https://example.org/primary')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads(r.stdout)
        self.assertEqual(result['entry_type'], 'manual_url')
        self.assertEqual(result['source_urls'], ['https://example.org/news?a=1', 'https://example.org/primary'])
        self.assertIsNone(result['topic'])
        self.assertEqual(result['verification_status'], 'needs_source_review')
        self.assertEqual(list(self.root.iterdir()), [])

    def test_manual_urls_are_deduplicated_without_losing_a_source(self):
        r = self.call('resolve_input.py', '--url', 'https://example.org/news',
                      '--url', 'https://example.org/detail',
                      '--url', ' https://example.org/news ')
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(json.loads(r.stdout)['source_urls'],
                         ['https://example.org/news', 'https://example.org/detail'])

    def test_selection_without_an_explicit_id_never_falls_back_to_old_selection(self):
        pool = self.root / 'pool.json'
        pool.write_text(json.dumps({'selected_event_id': 'N02', 'events': []}))
        r = self.call('resolve_input.py', '--selection-file', pool)
        self.assertNotEqual(r.returncode, 0)

    def test_duplicate_selection_ids_fail_instead_of_silently_choosing_one(self):
        pool = self.root / 'pool.json'
        one = {'event_id': 'N01', 'source': {'url': 'https://example.org/a'}}
        pool.write_text(json.dumps({'events': [one, one]}))
        self.assertNotEqual(self.call('resolve_input.py', '--selection-file', pool,
                                      '--selection-id', 'N01').returncode, 0)

    def make_references(self):
        folder = self.root / '语气参考/公众号原文'
        folder.mkdir(parents=True)
        refs = []
        for name, body in [('临床', '临床正文起点\n具体工作解释\n临床正文终点'),
                           ('AI', 'AI正文起点\n实例和问题推进\nAI正文终点')]:
            html = folder / (name + '.html')
            text = folder / (name + '.txt')
            html.write_text('<div id="js_content">' + body + '</div>')
            text.write_text(body)
            refs.append({'html': html.name, 'text': text.name,
                         'html_sha256': hashlib.sha256(html.read_bytes()).hexdigest(),
                         'text_sha256': hashlib.sha256(text.read_bytes()).hexdigest()})
        (folder / '原文索引.json').write_text(json.dumps({'references': refs}))
        return folder

    def test_style_loader_returns_both_complete_bodies_with_original_paths(self):
        self.make_references()
        r = self.call('load_fewshots.py', '--project-root', self.root)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        refs = json.loads(r.stdout)['references']
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]['body_full_text'], '临床正文起点\n具体工作解释\n临床正文终点')
        self.assertEqual(refs[1]['body_full_text'], 'AI正文起点\n实例和问题推进\nAI正文终点')
        self.assertTrue(all(Path(ref['html']).is_file() for ref in refs))

    def test_modified_html_is_not_silently_paired_with_old_style_text(self):
        folder = self.make_references()
        (folder / '临床.html').write_text('已更改的原始HTML')
        r = self.call('load_fewshots.py', '--project-root', self.root)
        self.assertNotEqual(r.returncode, 0)


if __name__ == '__main__':
    unittest.main()
