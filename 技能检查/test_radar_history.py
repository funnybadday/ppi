"""Offline contract tests; all runs, reviews and ledgers live in temporary folders."""
import fcntl
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/lab-paper-workflow/scripts/radar_history.py'


class RadarHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ledger = self.root / '选题池/事件台账.json'

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def call(self, command, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), command,
                                 '--project-root', str(self.root), *map(str, args)],
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)['result']
        self.assertNotEqual(result.returncode, 0, result.stderr + result.stdout)
        return result

    def run_fixture(self, name, at, items, complete=False, fetch_status='success'):
        run = self.root / 'Horizon/data/mcp-runs' / name
        self.write(run / 'meta.json', {'run_id': name, 'created_at': at,
                   'updated_at': at, 'fetch_status': fetch_status})
        self.write(run / 'raw_items.json', items)
        if complete:
            scored = [{**x, 'processing': {'analysis': {'score': 3}}} for x in items]
            self.write(run / 'scored_items.json', scored)
            self.write(run / 'filtered_items.json', [])
        return run

    def item(self, name, url=None, content='old', title='Acme clinical trial tool'):
        return {'id': name, 'url': url or 'https://example.org/' + name,
                'title': title, 'content': content}

    def review(self, name='review.json', **changes):
        event = {'event_id': 'C01', 'topic': 'Acme患者匹配', 'source_date': '2026-10-20',
                 'source': {'url': 'https://example.org/Story?utm_source=feed'},
                 'verified_facts': '公布患者匹配工具', 'change_type': 'new',
                 'discovery_items': [{'item_id': 'a', 'discovery_url': 'https://news.example/a'}],
                 'horizon_score': 3.0}
        event.update(changes)
        return self.write(self.root / name, {'source_run': name, 'events': [event]})

    def record(self, path, ok=True):
        return self.call('record', '--review-file', path, ok=ok)

    def event(self):
        return json.loads(self.ledger.read_text())['events'][0]

    def test_compare_keeps_all_rows_and_flags_changes_without_company_merging(self):
        self.run_fixture('old', '2026-10-20T00:00:00Z', [self.item('a'), self.item('b')])
        run = self.run_fixture('current', '2026-10-21T00:00:00Z',
                               [self.item('a'), self.item('b', content='new result'), self.item('c')])
        # Future runs must not leak backwards into the comparison.
        self.run_fixture('future', '2026-10-22T00:00:00Z', [self.item('c')])
        before = (run / 'raw_items.json').read_bytes()
        output = self.root / 'history-context.json'
        self.call('compare', '--run-dir', run, '--output', output)
        data = json.loads(output.read_text())
        self.assertEqual([x['history_status'] for x in data['items']],
                         ['same_url_same_content', 'same_url_changed', 'new_url'])
        self.assertEqual(data['history_run_count'], 1)
        self.assertEqual((run / 'raw_items.json').read_bytes(), before)
        self.assertFalse(self.ledger.exists())

    def test_url_tracking_normalization_preserves_business_query_and_path_case(self):
        old = self.item('a', 'https://EXAMPLE.org:443/Story?id=1&utm_source=x#top')
        self.run_fixture('old', '2026-10-20T00:00:00Z', [old])
        run = self.run_fixture('new', '2026-10-21T00:00:00Z', [
            self.item('a', 'https://example.org/Story?id=1&fbclid=x&gclid=y'),
            self.item('b', 'https://example.org/Story?id=2'),
            self.item('c', 'https://example.org/story?id=1')])
        output = self.root / 'context.json'
        self.call('compare', '--run-dir', run, '--output', output)
        self.assertEqual([x['history_status'] for x in json.loads(output.read_text())['items']],
                         ['same_url_same_content', 'new_url', 'new_url'])

    def test_compare_attaches_known_events_by_source_and_discovery_url(self):
        self.record(self.review())
        run = self.run_fixture('new', '2026-10-21T00:00:00Z', [
            self.item('a', 'https://example.org/Story'), self.item('b', 'https://news.example/a')])
        output = self.root / 'context.json'
        self.call('compare', '--run-dir', run, '--output', output)
        data = json.loads(output.read_text())
        self.assertEqual(len(data['known_events']), 1)
        self.assertTrue(all(x['matched_event_keys'] == [self.event()['event_key']] for x in data['items']))

    def test_compare_cannot_overwrite_a_historical_raw_artifact(self):
        old = self.run_fixture('old', '2026-10-20T00:00:00Z', [self.item('a')])
        run = self.run_fixture('new', '2026-10-21T00:00:00Z', [self.item('b')])
        output = old / 'raw_items.json'
        before = output.read_bytes()
        self.call('compare', '--run-dir', run, '--output', output, ok=False)
        self.assertEqual(output.read_bytes(), before)

    def test_new_repeat_and_update_preserve_stable_key_scores_and_draft_status(self):
        self.record(self.review(status='drafted', article_directory='稿件/Acme患者匹配'))
        key = self.event()['event_key']
        self.record(self.review('repeat.json', event_key=key, change_type='repeat'))
        self.assertEqual(self.event()['status'], 'drafted')
        self.assertEqual(len(self.event()['recommendation_history']), 1)
        self.record(self.review('update.json', event_key=key, change_type='update',
                                change_note='公布前瞻性验证结果', verified_facts='报告新结果',
                                source={'url': 'https://example.org/new-results'}))
        event = self.event()
        self.assertEqual(event['event_key'], key)
        self.assertEqual(event['status'], 'drafted')
        self.assertEqual(event.get('article_directory'), '稿件/Acme患者匹配')
        self.assertEqual(len(event['recommendation_history']), 2)
        self.assertEqual(event['recommendation_history'][0]['horizon_score'], 3.0)
        self.assertEqual(event['verified_facts'], '报告新结果')
        self.assertEqual(len(event['sources']), 2)

    def test_idempotence_uses_review_content_and_does_not_rewrite_ledger(self):
        path = self.review()
        self.record(path)
        before = self.ledger.read_bytes()
        other_path = self.root / 'renamed.json'
        other_path.write_bytes(path.read_bytes())
        result = self.record(other_path)
        self.assertTrue(result['already_recorded'])
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_empty_completed_review_records_run_without_inventing_events(self):
        path = self.write(self.root / 'empty.json', {'source_run': 'run-empty',
                          'events': [], 'history_review': []})
        self.record(path)
        ledger = json.loads(self.ledger.read_text())
        self.assertEqual(ledger['events'], [])
        self.assertEqual(len(ledger['processed_reviews']), 1)
        self.assertEqual(next(iter(ledger['processed_reviews'].values()))['source_run'], 'run-empty')
        before = self.ledger.read_bytes()
        self.assertTrue(self.record(path)['already_recorded'])
        self.assertEqual(self.ledger.read_bytes(), before)
        for invalid in [{}, {'events': []}, {'source_run': 'run-no-decisions-field'}]:
            self.record(self.write(self.root / 'invalid-empty.json', invalid), ok=False)
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_repeat_updates_article_metadata_without_replacing_news_facts(self):
        self.record(self.review())
        key = self.event()['event_key']
        path = self.write(self.root / 'drafted.json', {'source_run': 'article-handoff',
            'history_review': [{'event_key': key, 'change_type': 'repeat',
                'status': 'drafted', 'article_directory': '稿件/Acme患者匹配',
                'verified_facts': 'This stale repeat must not replace the original facts'}]})
        self.record(path)
        event = self.event()
        self.assertEqual(event['status'], 'drafted')
        self.assertEqual(event['article_directory'], '稿件/Acme患者匹配')
        self.assertEqual(event['verified_facts'], '公布患者匹配工具')
        self.assertEqual(len(event['recommendation_history']), 1)

    def test_platform_conversion_preserves_other_platform_and_recommendation_count(self):
        self.record(self.review(status='drafted', platform_outputs={
            'wechat': {'review_status': 'approved', 'published': True,
                       'directory': '稿件/Acme患者匹配/公众号'}}))
        key = self.event()['event_key']
        path = self.write(self.root / 'xhs.json', {'events': [], 'history_review': [{
            'event_key': key, 'change_type': 'repeat', 'platform_outputs': {
                'xiaohongshu': {'review_status': 'awaiting_user_review', 'published': False,
                               'directory': '稿件/Acme患者匹配/小红书'}}}]})
        self.record(path)
        event = self.event()
        self.assertEqual(event['platform_outputs']['wechat']['review_status'], 'approved')
        self.assertTrue(event['platform_outputs']['wechat']['published'])
        self.assertFalse(event['platform_outputs']['xiaohongshu']['published'])
        self.assertEqual(event['status'], 'drafted')
        self.assertEqual(len(event['recommendation_history']), 1)

    def test_platform_approval_merges_metadata_without_implying_publication(self):
        self.record(self.review(status='drafted', platform_outputs={'xiaohongshu': {
            'review_status': 'awaiting_user_review', 'published': False,
            'directory': '稿件/Acme患者匹配/小红书'}}))
        path = self.write(self.root / 'approved.json', {'events': [], 'history_review': [{
            'event_key': self.event()['event_key'], 'change_type': 'repeat',
            'platform_outputs': {'xiaohongshu': {'review_status': 'approved',
                'approval_note': '用户明确认可本版'}}}]})
        self.record(path)
        output = self.event()['platform_outputs']['xiaohongshu']
        self.assertEqual(output['review_status'], 'approved')
        self.assertEqual(output['directory'], '稿件/Acme患者匹配/小红书')
        self.assertFalse(output['published'])

    def test_invalid_platform_metadata_cannot_commit_partial_changes(self):
        self.record(self.review())
        before = self.ledger.read_bytes()
        for invalid in [[], {'xiaohongshu': []}, {'other': {}},
                        {'wechat': {'review_status': 'generated'}},
                        {'wechat': {'published': 'false'}}]:
            path = self.write(self.root / 'bad-platform.json', {'events': [],
                'history_review': [{'event_key': self.event()['event_key'],
                    'change_type': 'repeat', 'platform_outputs': invalid}]})
            self.record(path, ok=False)
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_article_fact_update_does_not_invent_a_new_radar_recommendation(self):
        self.record(self.review(status='drafted', article_directory='稿件/Acme患者匹配'))
        key = self.event()['event_key']
        path = self.write(self.root / 'article-update.json', {'source_run': None,
            'events': [], 'history_review': [{'event_key': key, 'change_type': 'update',
                'change_note': '用户要求修订稿件，本次回源补充了正式可用范围',
                'verified_facts': '核对正式可用范围与当前产品说明',
                'source': {'url': 'https://example.org/product-scope'}}]})
        self.record(path)
        event = self.event()
        self.assertEqual(event['event_key'], key)
        self.assertEqual(event['status'], 'drafted')
        self.assertEqual(event['verified_facts'], '核对正式可用范围与当前产品说明')
        self.assertEqual(len(event['sources']), 2)
        self.assertEqual(len(event['recommendation_history']), 1)
        self.assertEqual(event['review_history'][-1]['change_type'], 'update')

    def test_observed_time_is_preserved_and_last_seen_cannot_move_backwards(self):
        path = self.review()
        review = json.loads(path.read_text())
        review['observed_at'] = '2026-10-20T09:30:00+08:00'
        self.write(path, review)
        self.record(path)
        event = self.event()
        self.assertEqual(event['first_seen'], '2026-10-20T09:30:00+08:00')
        self.assertEqual(event['last_seen'], '2026-10-20T09:30:00+08:00')
        self.assertNotEqual(event['review_history'][0]['recorded_at'], event['first_seen'])
        for at in ['2026-10-21T09:30:00+08:00', '2026-10-19T09:30:00+08:00']:
            value = {'source_run': at, 'observed_at': at, 'history_review': [
                {'event_key': event['event_key'], 'change_type': 'repeat'}]}
            self.record(self.write(self.root / 'backfill.json', value))
        event = self.event()
        self.assertEqual(event['first_seen'], '2026-10-19T09:30:00+08:00')
        self.assertEqual(event['last_seen'], '2026-10-21T09:30:00+08:00')
        self.assertEqual(event['review_history'][-1]['observed_at'], '2026-10-19T09:30:00+08:00')
        before = self.ledger.read_bytes()
        for bad_time in ['2026-10-19T09:30:00', 'not-a-date', None]:
            value['observed_at'] = bad_time
            self.record(self.write(self.root / 'bad-time.json', value), ok=False)
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_invalid_updates_and_new_existing_key_leave_ledger_unchanged(self):
        self.record(self.review())
        key = self.event()['event_key']
        before = self.ledger.read_bytes()
        for change in [dict(event_key=key, change_type='new'),
                       dict(event_key='missing', change_type='repeat'),
                       dict(event_key=key, change_type='update')]:
            self.record(self.review('bad.json', **change), ok=False)
            self.assertEqual(self.ledger.read_bytes(), before)

    def test_invalid_later_entry_cannot_partially_commit_a_valid_entry(self):
        path = self.review()
        review = json.loads(path.read_text())
        review['events'].append({'event_key': 'missing', 'change_type': 'repeat'})
        self.write(path, review)
        self.record(path, ok=False)
        self.assertFalse(self.ledger.exists())

    def test_history_review_pending_and_repeat_do_not_become_recommendations(self):
        self.record(self.review())
        key = self.event()['event_key']
        path = self.write(self.root / 'history.json', {'events': [], 'history_review': [
            {'event_key': key, 'change_type': 'repeat', 'event_id': 'R1'},
            {'change_type': 'pending', 'topic': 'Acme其他独立项目',
             'source': {'url': 'https://example.org/another-project'}, 'source_date': None}]})
        self.record(path)
        events = json.loads(self.ledger.read_text())['events']
        self.assertEqual(len(events), 2)
        self.assertEqual(len(events[0]['recommendation_history']), 1)
        self.assertEqual(events[1]['status'], 'pending')
        self.assertEqual(events[1]['recommendation_history'], [])

    def test_pending_can_advance_to_recommended_after_substantive_update(self):
        self.record(self.review(change_type='pending', status='pending'))
        self.record(self.review('update.json', event_key=self.event()['event_key'],
                                change_type='update', change_note='原始公告已取得'))
        self.assertEqual(self.event()['status'], 'recommended')

    def test_legacy_candidate_status_does_not_downgrade_published_event(self):
        self.record(self.review(status='published'))
        self.record(self.review('repeat.json', event_key=self.event()['event_key'],
                                change_type='repeat', status='awaiting_user_selection'))
        self.assertEqual(self.event()['status'], 'published')

    def test_atomic_replace_failure_preserves_existing_ledger_and_cleans_temp_file(self):
        self.record(self.review())
        before = self.ledger.read_bytes()
        spec = importlib.util.spec_from_file_location('radar_history_test', SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        next_review = self.review('next.json', source={'url': 'https://example.org/other'})
        with patch.object(module.os, 'replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                module.record(self.root, next_review)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(list(self.ledger.parent.glob('*.tmp')), [])

    def test_broken_ledger_fails_without_rebuilding_or_overwriting_output(self):
        self.ledger.parent.mkdir(parents=True)
        self.ledger.write_text('{bad json')
        self.record(self.review(), ok=False)
        self.assertEqual(self.ledger.read_text(), '{bad json')
        run = self.run_fixture('new', '2026-10-21T00:00:00Z', [self.item('a')])
        output = self.root / 'context.json'
        output.write_text('keep')
        self.call('compare', '--run-dir', run, '--output', output, ok=False)
        self.assertEqual(output.read_text(), 'keep')

    def test_lock_contention_does_not_overwrite_ledger(self):
        self.record(self.review())
        before = self.ledger.read_bytes()
        with self.ledger.with_suffix('.json.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.record(self.review('next.json', source={'url': 'https://example.org/other'}), ok=False)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_window_ignores_incomplete_failed_or_unscored_runs(self):
        self.run_fixture('complete', '2026-10-20T01:30:00Z', [self.item('a')], complete=True)
        self.run_fixture('partial', '2026-10-21T01:30:00Z', [self.item('a')],
                         complete=True, fetch_status='partial_failure')
        incomplete = self.run_fixture('unscored', '2026-10-21T02:30:00Z', [self.item('a')], complete=True)
        self.write(incomplete / 'scored_items.json', [self.item('a')])
        data = self.call('window', '--now', '2026-10-22T01:30:00Z')
        self.assertEqual(data['hours'], 72)
        self.assertEqual(data['checkpoint_run_id'], 'complete')

    def test_window_no_checkpoint_monday_minimum_and_long_gap(self):
        self.assertEqual(self.call('window', '--now', '2026-10-22T01:30:00Z')['hours'], 96)
        self.run_fixture('complete', '2026-10-25T01:30:00Z', [self.item('a')], complete=True)
        self.assertEqual(self.call('window', '--now', '2026-10-26T01:30:00Z')['hours'], 96)
        gap = self.call('window', '--now', '2026-11-05T01:30:00Z')
        self.assertGreater(gap['hours'], 168)
        self.assertTrue(gap['exceeds_seven_days'])

    def test_empty_aggregate_success_does_not_hide_an_earlier_collection_gap(self):
        self.run_fixture('complete', '2026-10-20T01:30:00Z', [self.item('a')], complete=True)
        self.run_fixture('empty-success', '2026-10-22T01:00:00Z', [], complete=True)
        data = self.call('window', '--now', '2026-10-22T01:30:00Z')
        self.assertEqual(data['checkpoint_run_id'], 'complete')
        self.assertEqual(data['hours'], 72)
        self.assertIn('empty-success', data['excluded_run_ids'])


if __name__ == '__main__':
    unittest.main()
