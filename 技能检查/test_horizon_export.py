"""Exercise the actual offline export, independent of live feeds or model APIs."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'skills/lab-paper-workflow/scripts/export_horizon.py'


def item(item_id, score=None):
    result = {'id': item_id, 'title': '线索' + item_id,
              'url': 'https://example.org/' + item_id,
              'published_at': '2026-10-20T12:00:00Z',
              'metadata': {'feed_name': '测试公开订阅'}}
    if score is not None:
        result['processing'] = {'analysis': {'score': score, 'summary': '摘要' + item_id,
                                             'reason': '理由' + item_id, 'tags': ['AI试验']}}
    return result


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.run = self.root / 'run-sample'
        self.run.mkdir()
        self.out = self.root / 'delivery'

    def write_run(self, raw, scored, filtered, fetch_status='success'):
        data = {'meta.json': {'run_id': 'run-sample', 'created_at': '2026-10-20T17:40:00Z',
                             'since': '2026-10-19T17:40:00Z', 'hours': 24,
                             'fetch_status': fetch_status, 'filter_threshold_override': 5,
                             'fetch_report': {'status': fetch_status, 'sources': [
                                 {'source': 'RSS Feeds', 'status': fetch_status}]}},
                'raw_items.json': raw, 'scored_items.json': scored,
                'filtered_items.json': filtered}
        for name, value in data.items():
            (self.run / name).write_text(json.dumps(value, ensure_ascii=False))

    def export(self):
        return subprocess.run([sys.executable, str(SCRIPT), '--run-dir', str(self.run),
                               '--output-dir', str(self.out)], capture_output=True, text=True)

    def test_missing_scored_item_remains_unscored_and_in_full_attachment(self):
        # A partial model run must never become "all scored" or silently lose an item.
        self.write_run([item('a'), item('b'), item('c')],
                       [item('a', 8), item('b', 3)], [item('a', 8)])
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        manifest = json.loads((self.out / '导出记录.json').read_text())
        self.assertEqual(manifest['counts'], {'raw': 3, 'scored': 2, 'unscored': 1,
                                             'filtered': 1, 'review': 1})
        self.assertEqual(manifest['status'], 'partial')
        rows = json.loads((self.out / 'Horizon全量评分.json').read_text())
        self.assertEqual([r['id'] for r in rows], ['a', 'b', 'c'])
        self.assertIsNone(rows[2]['score'])
        self.assertEqual(rows[2]['status'], 'unscored')
        report = (self.out / 'Horizon筛选与摘要.txt').read_text()
        self.assertIn('摘要a', report)
        self.assertIn('理由a', report)
        self.assertIn('https://example.org/a', report)
        self.assertEqual(manifest['collection_date'], '2026-10-21')

    def test_empty_success_is_distinct_from_partial_fetch(self):
        self.write_run([], [], [])
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads((self.out / '导出记录.json').read_text())
        self.assertEqual(result['status'], 'empty')
        self.assertEqual(result['counts']['raw'], 0)

    def test_fetch_failure_survives_nonempty_scored_results(self):
        self.write_run([item('a')], [item('a', 8)], [item('a', 8)], 'partial')
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads((self.out / '导出记录.json').read_text())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['fetch_status'], 'partial')

    def test_inconsistent_filtered_ids_are_not_delivered_as_real_results(self):
        self.write_run([item('a')], [item('a', 8)], [item('not-fetched', 9)])
        r = self.export()
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(self.out.exists())

    def test_native_partial_failure_keeps_available_results_and_reports_partial(self):
        self.write_run([item('a')], [item('a', 8)], [item('a', 8)], 'partial_failure')
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads((self.out / '导出记录.json').read_text())
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['counts']['filtered'], 1)

    def test_native_failure_is_not_reported_as_an_empty_news_day(self):
        self.write_run([], [], [], 'failure')
        r = self.export()
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        result = json.loads((self.out / '导出记录.json').read_text())
        self.assertEqual(result['status'], 'failed')

    def test_repeat_export_does_not_overwrite_an_existing_delivery(self):
        self.write_run([item('a')], [item('a', 8)], [item('a', 8)])
        self.out.mkdir()
        sentinel = self.out / 'Horizon筛选与摘要.txt'
        sentinel.write_text('已审阅的历史交付')
        self.assertNotEqual(self.export().returncode, 0)
        self.assertEqual(sentinel.read_text(), '已审阅的历史交付')

    def test_daily_folder_appends_one_report_per_run_without_overwriting(self):
        self.write_run([item('a')], [item('a', 8)], [item('a', 8)])
        reports = self.root / 'Horizon日报'
        command = [sys.executable, str(SCRIPT), '--run-dir', str(self.run),
                   '--report-dir', str(reports)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        report = Path(json.loads(first.stdout)['result']['report_path'])
        original = report.read_bytes()
        self.assertEqual(len(list(reports.iterdir())), 1)
        self.assertIn('https://example.org/a', report.read_text())
        self.assertIn(str(self.run / 'scored_items.json'), report.read_text())
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(report.read_bytes(), original)
        meta = json.loads((self.run / 'meta.json').read_text())
        meta['run_id'] = 'run-second'
        (self.run / 'meta.json').write_text(json.dumps(meta))
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        self.assertEqual(len(list(reports.glob('*.txt'))), 2)
        self.assertEqual(report.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
