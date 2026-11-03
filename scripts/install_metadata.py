#!/usr/bin/env python3
"""Record package identity and installation status without reading user data."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess


def source_info(source):
    source = source.resolve()
    version = (source / 'VERSION').read_text().strip()
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', version):
        raise ValueError('VERSION 格式无效。')
    release = source / 'release.json'
    if release.exists():
        info = json.loads(release.read_text())
        if (not isinstance(info, dict) or info.get('version') != version or info.get('tag') != f'v{version}' or
                not re.fullmatch(r'[a-f0-9]{40}', str(info.get('commit', '')))):
            raise ValueError('发布元数据与版本不一致。')
        return {'version': version, 'tag': info['tag'], 'commit': info['commit'],
                'source': 'release', 'dirty': False}
    info = {'version': version, 'tag': None, 'commit': None, 'source': 'directory', 'dirty': None}
    try:
        def git(*args):
            return subprocess.check_output(['git', '-C', str(source), *args], text=True,
                                           stderr=subprocess.DEVNULL).strip()
        if Path(git('rev-parse', '--show-toplevel')).resolve() == source:
            info.update(source='git', commit=git('rev-parse', 'HEAD'),
                        dirty=bool(git('status', '--porcelain', '--untracked-files=all')))
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--status', choices=('installing', 'ready', 'failed'), default='installing')
    args = parser.parse_args()
    info = source_info(args.source)
    if args.output:
        info.update(status=args.status, recorded_at=datetime.now(timezone.utc).isoformat())
        temp = args.output.with_name(args.output.name + '.tmp')
        temp.write_text(json.dumps(info, ensure_ascii=False, indent=2) + '\n')
        temp.chmod(0o644)
        temp.replace(args.output)
    else:
        print(json.dumps(info, ensure_ascii=False))


if __name__ == '__main__':
    main()
