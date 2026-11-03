#!/usr/bin/env python3
"""Validate a stable release and package the exact, clean tagged commit."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

VERSION_RE = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def validate(tag):
    for name in ('install.sh', 'flask_app.py', 'scripts/install.sh', 'scripts/install_metadata.py',
                 'scripts/backup.sh', 'scripts/uninstall.sh', 'public/index.html',
                 'deploy/caddy-manager.service', 'requirements-flask.txt'):
        if not (ROOT / name).is_file():
            raise ValueError(f'缺少发布所需文件：{name}')
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(VERSION_RE, version) or tag != f'v{version}':
        raise ValueError('正式标签必须为 vX.Y.Z，并与 VERSION 一致。')
    if f'当前版本：`{version}`' not in (ROOT / 'README.md').read_text():
        raise ValueError('README 的当前版本与 VERSION 不一致。')
    section = re.search(rf'^## {re.escape(version)} — (\d{{4}}-\d{{2}}-\d{{2}})\n(.*?)(?=^## |\Z)',
                        (ROOT / 'CHANGELOG.md').read_text(), re.M | re.S)
    if not section or not section.group(2).strip():
        raise ValueError('CHANGELOG 缺少该版本的日期和更新说明。')
    from datetime import date
    date.fromisoformat(section.group(1))
    return version, section.group(2).strip() + '\n'


def build(tag, output):
    version, notes = validate(tag)
    if git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('发布包只能从干净、已提交的工作区生成。')
    commit = git('rev-parse', 'HEAD')
    if git('rev-parse', f'refs/tags/{tag}^{{commit}}') != commit:
        raise ValueError('标签必须指向当前提交。')
    current = tuple(map(int, version.split('.')))
    for existing in git('tag', '--list').splitlines():
        if re.fullmatch('v' + VERSION_RE, existing) and tuple(map(int, existing[1:].split('.'))) > current:
            raise ValueError('已有更高的正式版本标签，不能将旧版本重新作为新版本发布。')
    archive = subprocess.check_output(['git', '-C', str(ROOT), 'archive', '--format=tar',
                                       '--prefix=caddy-manager/', commit])
    manifest = json.dumps({'version': version, 'tag': tag, 'commit': commit},
                          sort_keys=True, indent=2).encode() + b'\n'
    timestamp = int(git('show', '-s', '--format=%ct', commit))
    content = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source, \
         tarfile.open(fileobj=content, mode='w', format=tarfile.PAX_FORMAT) as target:
        for member in source:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f'发布包不允许链接或特殊文件：{member.name}')
            if member.name == 'caddy-manager/release.json':
                raise ValueError('release.json 由打包工具生成，不应提交到源码。')
            target.addfile(member, source.extractfile(member) if member.isfile() else None)
        info = tarfile.TarInfo('caddy-manager/release.json')
        info.size, info.mode, info.mtime = len(manifest), 0o644, timestamp
        target.addfile(info, io.BytesIO(manifest))
    output.mkdir(parents=True, exist_ok=True)
    package = output / 'caddy-manager.tar.gz'
    with package.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as zipped:
        zipped.write(content.getvalue())
    installer = output / 'install.sh'
    installer.write_bytes(subprocess.check_output(['git', '-C', str(ROOT), 'show', f'{commit}:install.sh']))
    (output / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in (package, installer)))
    (output / 'RELEASE_NOTES.md').write_text(notes)
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True, help='正式版本标签，例如 v1.0.1')
    parser.add_argument('--check', action='store_true', help='只核对版本及更新说明，允许尚未提交')
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    try:
        if args.check:
            validate(args.tag)
            print('版本与更新说明一致；此检查不代表测试、打包或发布已经完成。')
        else:
            commit = build(args.tag, args.output.resolve())
            print(f'已打包 {args.tag} ({commit})：{args.output}')
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'发布检查失败：{exc}\n')


if __name__ == '__main__':
    main()
