"""Release tests use temporary Git repositories and local downloads only."""

import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_script('release')
metadata = load_script('install_metadata')


class ReleaseFlow(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='caddy-release-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'source with spaces'
        self.repo.mkdir()
        files = {
            'VERSION': '1.0.1\n', 'README.md': '当前版本：`1.0.1`\n',
            'CHANGELOG.md': '# 更新记录\n\n## 未归入新版本\n\n- Future\n\n## 1.0.1 — 2026-11-03\n\n- Release notes.\n',
            '.gitignore': '.local/\ndist/\n', 'flask_app.py': '# Fixture\n',
            'scripts/install.sh': '#!/bin/bash\nexit 99 # Must never execute in tests\n',
            'scripts/backup.sh': '# Fixture\n', 'scripts/uninstall.sh': '# Fixture\n',
            'public/index.html': '<html>Fixture</html>\n',
            'deploy/caddy-manager.service': '# Fixture\n',
            'requirements-flask.txt': 'Flask>=2.2,<4\n',
        }
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        shutil.copyfile(ROOT / 'install.sh', self.repo / 'install.sh')
        shutil.copyfile(ROOT / 'scripts/install_metadata.py', self.repo / 'scripts/install_metadata.py')
        self.git('init', '-q')
        self.git('config', 'user.name', 'Release Test')
        self.git('config', 'user.email', 'release@example.test')
        self.commit()
        self.git('tag', 'v1.0.1')
        self.patch = patch.object(release, 'ROOT', self.repo)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.assets = self.base / 'assets'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True,
                                       stderr=subprocess.STDOUT).strip()

    def commit(self):
        self.git('add', '.')
        self.git('-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'Fixture')

    def build(self):
        return release.build('v1.0.1', self.assets)

    def prepare(self, ref=None):
        work = self.base / f'download-{len(list(self.base.glob("download-*")))}'
        work.mkdir()
        log = work / 'requests.log'
        env = dict(os.environ, BOOTSTRAP=str(ROOT / 'install.sh'), WORK_DIR=str(work),
                   FIXTURE_DOWNLOADS=str(self.assets), REQUEST_LOG=str(log))
        env.pop('CADDY_MANAGER_VERSION', None)
        env.pop('CADDY_MANAGER_REPO', None)
        if ref is not None:
            env['CADDY_MANAGER_VERSION'] = ref
        command = '''source "$BOOTSTRAP"
download() {
  printf '%s\\n' "$1" >> "$REQUEST_LOG"
  cp "$FIXTURE_DOWNLOADS/${1##*/}" "$2"
}
prepare_release "$WORK_DIR"
'''
        result = subprocess.run(['bash', '-c', command], env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return result, work, log.read_text() if log.exists() else ''

    def checksum(self):
        digest = hashlib.sha256((self.assets / 'caddy-manager.tar.gz').read_bytes()).hexdigest()
        (self.assets / 'SHA256SUMS').write_text(f'{digest}  caddy-manager.tar.gz\n')

    def test_package_is_reproducible_and_identifies_exact_commit(self):
        (self.repo / '.local').mkdir()
        (self.repo / '.local/private-data').write_text('must not ship')
        commit = self.build()
        first = (self.assets / 'caddy-manager.tar.gz').read_bytes()
        self.build()
        self.assertEqual(first, (self.assets / 'caddy-manager.tar.gz').read_bytes())
        with tarfile.open(fileobj=io.BytesIO(first), mode='r:gz') as package:
            info = json.load(package.extractfile('caddy-manager/release.json'))
            self.assertEqual(info, dict(version='1.0.1', tag='v1.0.1', commit=commit))
            self.assertFalse(any('.local' in name or '/.git/' in name for name in package.getnames()))
        self.assertNotIn('Future', (self.assets / 'RELEASE_NOTES.md').read_text())
        for line in (self.assets / 'SHA256SUMS').read_text().splitlines():
            digest, name = line.split()
            self.assertEqual(digest, hashlib.sha256((self.assets / name).read_bytes()).hexdigest())

    def test_dirty_source_is_rejected(self):
        (self.repo / 'uncommitted.txt').write_text('uncommitted')
        with self.assertRaisesRegex(ValueError, '干净'):
            self.build()

    def test_tag_version_and_changelog_must_match(self):
        with self.assertRaisesRegex(ValueError, 'VERSION'):
            release.validate('v1.0.2')
        (self.repo / 'CHANGELOG.md').write_text('## 未归入新版本\n- Not released\n')
        with self.assertRaisesRegex(ValueError, 'CHANGELOG'):
            release.validate('v1.0.1')

    def test_tag_must_point_at_packaged_commit(self):
        (self.repo / 'new.txt').write_text('new commit')
        self.commit()
        with self.assertRaisesRegex(ValueError, '标签必须'):
            self.build()

    def test_older_version_cannot_replace_newer_release(self):
        self.git('tag', 'v2.0.0')
        with self.assertRaisesRegex(ValueError, '更高'):
            self.build()

    def test_default_and_pinned_install_use_release_assets(self):
        self.build()
        for ref, route in [(None, '/releases/latest/download/'), ('v1.0.1', '/releases/download/v1.0.1/')]:
            with self.subTest(ref=ref):
                result, work, requests = self.prepare(ref)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertTrue((work / 'caddy-manager/release.json').is_file())
                self.assertEqual(len(requests.splitlines()), 2)
                self.assertTrue(all(route in line for line in requests.splitlines()))

    def test_missing_release_never_falls_back_to_main(self):
        result, work, requests = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('不会回退', result.stdout)
        self.assertNotIn('/archive/', requests)
        self.assertFalse((work / 'caddy-manager').exists())

    def test_corrupt_package_is_not_extracted(self):
        self.build()
        with (self.assets / 'caddy-manager.tar.gz').open('ab') as package:
            package.write(b'corrupt')
        result, work, _ = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256 不匹配', result.stdout)
        self.assertFalse((work / 'caddy-manager').exists())

    def test_main_and_prerelease_are_not_stable_install_targets(self):
        for ref in ('main', 'v1.0.1-rc.1'):
            with self.subTest(ref=ref):
                result, _, requests = self.prepare(ref)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(requests, '')

    def test_pinned_version_mismatch_is_rejected(self):
        self.build()
        result, _, _ = self.prepare('v1.0.2')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('版本与请求不一致', result.stdout)

    def test_archive_path_escape_is_rejected(self):
        self.assets.mkdir()
        with tarfile.open(self.assets / 'caddy-manager.tar.gz', 'w:gz') as archive:
            member = tarfile.TarInfo('../escaped')
            member.size = 1
            archive.addfile(member, io.BytesIO(b'x'))
        self.checksum()
        result, _, _ = self.prepare()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('目录结构无效', result.stdout)
        self.assertFalse((self.base / 'escaped').exists())

    def test_install_metadata_distinguishes_source_and_release(self):
        source = metadata.source_info(self.repo)
        self.assertEqual(source['source'], 'git')
        self.assertFalse(source['dirty'])
        self.assertIsNone(source['tag'])
        self.build()
        result, work, _ = self.prepare()
        self.assertEqual(result.returncode, 0, result.stdout)
        unpacked = work / 'caddy-manager'
        output = work / 'install-info.json'
        for status in ('installing', 'ready', 'failed'):
            subprocess.run([sys.executable, str(ROOT / 'scripts/install_metadata.py'),
                            str(unpacked), '--output', str(output), '--status', status], check=True)
            info = json.loads(output.read_text())
            self.assertEqual(info['status'], status)
            self.assertEqual(info['source'], 'release')
            self.assertEqual(info['commit'], self.git('rev-parse', 'HEAD'))
        (unpacked / 'VERSION').write_text('1.0.2\n')
        with self.assertRaisesRegex(ValueError, '元数据'):
            metadata.source_info(unpacked)


if __name__ == '__main__':
    unittest.main()
