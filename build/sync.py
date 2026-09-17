#!/usr/bin/env python3
"""Build/test published content in isolation, push to Vercel's Git source, verify live.

No media publication, hold changes, secret loading, force pushes, or source commits.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SITE = 'https://www.thedailybutler.com'
REMOTES = {'https://github.com/aaron-mchugh/thedailybutler-web.git',
           'git@github.com:aaron-mchugh/thedailybutler-web.git'}


class SyncError(RuntimeError):
    pass


def run(cwd, *command, env=None, timeout=180):
    result = subprocess.run(command, cwd=cwd, env=env, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        # Avoid recording subprocess output that might contain credential helpers' data.
        raise SyncError(f'{command[0]} {command[1]} failed (exit {result.returncode}); '
                        'inspect the command locally before retrying')
    return result.stdout.strip()


def git(cwd, *args):
    return run(cwd, 'git', *args)


def allowed_output(path):
    return (path in {'index.html', '404.html', 'sitemap.xml', 'robots.txt',
                     'site-version.json', 'build/asset-provenance.json'}
            or bool(re.fullmatch(r'(?:about|archive|subscribe|reader)/index\.html', path))
            or bool(re.fullmatch(r'(?:reader/\d{2}-\d{2}|episode/\d{4}-\d{2}-\d{2})/index\.html', path))
            or bool(re.fullmatch(r'assets/[a-zA-Z0-9_-]+\.webp', path))
            or path in {'css/site.css', 'js/site.js'})


def changed_paths(repo):
    # NUL-delimited filenames; git diff includes deletions and disables rename folding.
    tracked = git(repo, 'diff', '--no-renames', '--name-only', '-z', 'HEAD').split('\0')
    untracked = git(repo, 'ls-files', '--others', '--exclude-standard', '-z').split('\0')
    return sorted(set(p for p in tracked + untracked if p))


def verify_live(repo, marker, episode, timeout):
    paths = ['/', '/archive/']
    dates = [episode] if episode else marker['episode_dates'][-1:]
    paths += [f'/episode/{date}/' for date in dates]
    paths += ['/assets/channel-logo-purple.webp']
    expected = {}
    for path in paths:
        local = repo / (path.strip('/') + '/index.html' if path.endswith('/') else path.lstrip('/'))
        if path == '/':
            local = repo / 'index.html'
        expected[path] = hashlib.sha256(local.read_bytes()).hexdigest()
    deadline = time.monotonic() + timeout
    while True:
        try:
            def get(path):
                request = urllib.request.Request(SITE + path + '?site_sync=' + marker['content_sha256'],
                           headers={'User-Agent': 'DailyButlerWebsiteSync/1', 'Cache-Control': 'no-cache'})
                with urllib.request.urlopen(request, timeout=min(15, max(1, deadline - time.monotonic()))) as response:
                    return response.read()
            actual = json.loads(get('/site-version.json'))
            if actual != marker:
                raise ValueError('waiting for the expected release marker')
            for path, digest in expected.items():
                if hashlib.sha256(get(path)).hexdigest() != digest:
                    raise ValueError('waiting for matching page/asset content')
            return paths
        except (OSError, ValueError) as exc:
            if time.monotonic() >= deadline:
                raise SyncError('Push completed but live verification timed out; retry sync-website '
                                'without republishing the episode') from exc
            print('Waiting for Vercel to serve the tested website release…', file=sys.stderr, flush=True)
            time.sleep(min(5, max(0, deadline - time.monotonic())))


def sync(root, production, *, check=False, episode=None, timeout=300):
    root, production = Path(root).resolve(), Path(production).resolve()
    if episode and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', episode):
        raise SyncError('Episode must be YYYY-MM-DD')
    if not (production / 'episodes').is_dir():
        raise SyncError('Production episode folder not found')
    # Refuse to hide or publish somebody's uncommitted design work.
    if git(root, 'status', '--porcelain'):
        raise SyncError('Website checkout has uncommitted changes; commit/review them before syncing')
    if git(root, 'branch', '--show-current') != 'main':
        raise SyncError('Website checkout must be on main')
    remote = git(root, 'remote', 'get-url', '--push', 'origin')
    if remote not in REMOTES:
        raise SyncError('Website origin does not match the approved website repository')
    head = git(root, 'rev-parse', 'HEAD')
    remote_head = git(root, 'ls-remote', remote, 'refs/heads/main').split()[0]
    if head != remote_head:
        raise SyncError('Website main differs from origin/main; reconcile it before syncing')
    env = dict(os.environ, DAILY_BUTLER_REPO=str(production))
    result = {'status': 'checking', 'site_url': SITE, 'episode': episode}
    with tempfile.TemporaryDirectory(prefix='daily-butler-web-sync-') as temporary:
        stage = Path(temporary) / 'site'
        run(root, 'git', 'clone', '--quiet', '--no-hardlinks', str(root), str(stage))
        print('Building published episodes in an isolated checkout…', file=sys.stderr, flush=True)
        run(stage, sys.executable, 'build/build.py', env=env)
        marker = json.loads((stage / 'site-version.json').read_text())
        if episode and episode not in marker['episode_dates']:
            raise SyncError('Requested episode is held or lacks a verified publication receipt; no push made')
        print('Running website tests…', file=sys.stderr, flush=True)
        run(stage, sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v', env=env)
        git(stage, 'diff', '--check')
        paths = changed_paths(stage)
        if any(not allowed_output(p) for p in paths):
            raise SyncError('Build changed a file outside the generated-output allowlist')
        result.update(content_sha256=marker['content_sha256'], changed_files=paths,
                      episode_count=len(marker['episode_dates']), commit=head)
        if check:
            return dict(result, status='checked', pushed=False)
        # Recheck before committing/pushing in case an operator changed the checkout.
        if git(root, 'status', '--porcelain') or git(root, 'rev-parse', 'HEAD') != head:
            raise SyncError('Website checkout changed during the build; no push made')
        if paths:
            git(stage, 'config', 'user.name', git(root, 'config', 'user.name'))
            git(stage, 'config', 'user.email', git(root, 'config', 'user.email'))
            git(stage, 'add', '--', *paths)
            git(stage, 'commit', '-m', 'site: sync published episodes' + (f' ({episode})' if episode else ''))
            result['commit'] = git(stage, 'rev-parse', 'HEAD')
        # A non-force push also safely retries a previous successful push/failed verification.
        git(stage, 'push', remote, 'HEAD:refs/heads/main')
        result['pushed'] = bool(paths)
        # Only fast-forward our local checkout. Never reset, stash or overwrite user edits.
        if not git(root, 'status', '--porcelain') and git(root, 'rev-parse', 'HEAD') == head:
            git(root, 'fetch', str(stage), 'HEAD')
            git(root, 'merge', '--ff-only', 'FETCH_HEAD')
        else:
            result['local_checkout_note'] = 'Concurrent local edits preserved; fast-forward main before next sync'
        print('Verifying the live Vercel website…', file=sys.stderr, flush=True)
        result['verified_paths'] = verify_live(stage, marker, episode, timeout)
        return dict(result, status='verified')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production-repo', type=Path,
                        default=Path(os.environ.get('DAILY_BUTLER_REPO', '~/AI/the-daily-butler')).expanduser())
    parser.add_argument('--episode')
    parser.add_argument('--check', action='store_true', help='build and test only; no push or live changes')
    parser.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    # Lock lives in Git metadata, never in deployed or generated files.
    lock_path = Path(git(ROOT, 'rev-parse', '--absolute-git-dir')) / 'website-sync.lock'
    try:
        with lock_path.open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SyncError('Another website sync is running')
            result = sync(ROOT, args.production_repo, check=args.check,
                          episode=args.episode, timeout=args.timeout)
        print(json.dumps(result, indent=2))
        return 0
    except (SyncError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc),
                          'retry': 'daily-butler sync-website; do not republish media'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
