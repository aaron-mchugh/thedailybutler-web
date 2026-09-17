"""Exercise sync against temporary Git remotes; never touch GitHub or Vercel."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('website_sync', Path(__file__).parents[1] / 'build/sync.py')
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote, self.repo = root / 'remote.git', root / 'web'
        self.production = root / 'production'
        (self.production / 'episodes').mkdir(parents=True)
        subprocess.run(['git', 'init', '--bare', '--initial-branch=main', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', 'clone', str(self.remote), str(self.repo)], check=True, capture_output=True)
        sync.git(self.repo, 'config', 'user.name', 'Website Sync Test')
        sync.git(self.repo, 'config', 'user.email', 'test@example.invalid')
        (self.repo / 'build').mkdir()
        (self.repo / 'tests').mkdir()
        (self.repo / '.gitignore').write_text('__pycache__/\n')
        (self.repo / 'build/build.py').write_text(
            "import json, os\nfrom pathlib import Path\n"
            "Path('index.html').write_text('published content')\n"
            "Path('site-version.json').write_text(json.dumps({'content_sha256':'abc', 'episode_dates':['2026-09-17']}))\n"
            "if os.environ.get('SYNC_TEST_UNEXPECTED'): Path('private.txt').write_text('do not deploy')\n")
        (self.repo / 'tests/test_fixture.py').write_text(
            "import unittest, os\nclass Fixture(unittest.TestCase):\n"
            " def test_gate(self): self.assertFalse(os.environ.get('SYNC_TEST_FAIL'))\n")
        sync.git(self.repo, 'add', '.')
        sync.git(self.repo, 'commit', '-m', 'fixture')
        sync.git(self.repo, 'push', 'origin', 'main')
        self.initial = sync.git(self.repo, 'rev-parse', 'HEAD')
        self.allow = patch.object(sync, 'REMOTES', {str(self.remote)})
        self.allow.start()
        self.addCleanup(self.allow.stop)
        self.live = patch.object(sync, 'verify_live', return_value=['/', '/archive/'])
        self.verify = self.live.start()
        self.addCleanup(self.live.stop)

    def remote_head(self):
        return sync.git(self.repo, 'ls-remote', str(self.remote), 'refs/heads/main').split()[0]

    def test_build_test_push_verify_and_idempotent_retry(self):
        result = sync.sync(self.repo, self.production, episode='2026-09-17')
        self.assertEqual(result['status'], 'verified')
        self.assertTrue(result['pushed'])
        self.assertNotEqual(self.remote_head(), self.initial)
        self.assertEqual(self.remote_head(), sync.git(self.repo, 'rev-parse', 'HEAD'))
        self.assertEqual(self.remote_head(), sync.git(self.repo, 'rev-parse', 'origin/main'))
        self.assertEqual(sync.git(self.repo, 'status', '--porcelain'), '')
        again = sync.sync(self.repo, self.production)
        self.assertFalse(again['pushed'])
        self.assertEqual(again['commit'], result['commit'])
        self.assertEqual(self.verify.call_count, 2)

    def test_check_builds_without_modifying_checkout_or_remote(self):
        result = sync.sync(self.repo, self.production, check=True)
        self.assertEqual(result['status'], 'checked')
        self.assertEqual(self.remote_head(), self.initial)
        self.assertFalse((self.repo / 'index.html').exists())
        self.verify.assert_not_called()

    def test_dirty_checkout_is_preserved(self):
        (self.repo / 'user-work.txt').write_text('important')
        with self.assertRaisesRegex(sync.SyncError, 'uncommitted'):
            sync.sync(self.repo, self.production)
        self.assertEqual((self.repo / 'user-work.txt').read_text(), 'important')
        self.assertEqual(self.remote_head(), self.initial)

    def test_failed_tests_do_not_push(self):
        with patch.dict(os.environ, {'SYNC_TEST_FAIL': '1'}):
            with self.assertRaisesRegex(sync.SyncError, 'failed'):
                sync.sync(self.repo, self.production)
        self.assertEqual(self.remote_head(), self.initial)
        self.assertFalse((self.repo / 'index.html').exists())

    def test_unexpected_generated_file_does_not_push(self):
        with patch.dict(os.environ, {'SYNC_TEST_UNEXPECTED': '1'}):
            with self.assertRaisesRegex(sync.SyncError, 'allowlist'):
                sync.sync(self.repo, self.production)
        self.assertEqual(self.remote_head(), self.initial)

    def test_held_or_unpublished_requested_episode_does_not_push(self):
        with self.assertRaisesRegex(sync.SyncError, 'held or lacks'):
            sync.sync(self.repo, self.production, episode='2026-09-18')
        self.assertEqual(self.remote_head(), self.initial)

    def test_wrong_remote_and_local_ahead_are_rejected(self):
        with patch.object(sync, 'REMOTES', set()):
            with self.assertRaisesRegex(sync.SyncError, 'approved website'):
                sync.sync(self.repo, self.production)
        sync.git(self.repo, 'commit', '--allow-empty', '-m', 'unpublished local change')
        with self.assertRaisesRegex(sync.SyncError, 'differs from'):
            sync.sync(self.repo, self.production)
        self.assertEqual(self.remote_head(), self.initial)

    def test_failed_live_check_can_retry_without_another_commit(self):
        self.verify.side_effect = sync.SyncError('live verification timed out')
        with self.assertRaisesRegex(sync.SyncError, 'timed out'):
            sync.sync(self.repo, self.production)
        pushed = self.remote_head()
        self.verify.side_effect = None
        result = sync.sync(self.repo, self.production)
        self.assertEqual(result['commit'], pushed)
        self.assertEqual(result['status'], 'verified')
        self.assertFalse(result['pushed'])


class LiveVerificationTests(unittest.TestCase):
    def test_stale_marker_is_not_success(self):
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'archive').mkdir()
            (root / 'assets').mkdir()
            (root / 'index.html').write_text('home')
            (root / 'archive/index.html').write_text('archive')
            (root / 'assets/channel-logo-purple.webp').write_bytes(b'logo')
            with patch.object(sync.urllib.request, 'urlopen', return_value=io.BytesIO(b'{}')):
                with self.assertRaisesRegex(sync.SyncError, 'verification timed out'):
                    sync.verify_live(root, {'content_sha256': 'abc', 'episode_dates': []}, None, 0)


if __name__ == '__main__':
    unittest.main()
