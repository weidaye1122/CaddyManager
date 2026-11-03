#!/usr/bin/env python3
"""Run real systemd/Caddy acceptance in disposable Docker containers."""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', choices=('debian:bookworm-slim', 'ubuntu:24.04'), default='debian:bookworm-slim')
    parser.add_argument('--scenario', choices=('fresh', 'upgrade', 'all'), default='all')
    parser.add_argument('--package', type=Path, help='Optional actual Release archive to install')
    args = parser.parse_args()
    run_id = uuid.uuid4().hex[:10]
    builder = f'caddy-manager-qa-{run_id}'
    image = f'caddy-manager-qa:{run_id}'
    output = ROOT / '.local' / 'linux-tests' / f'{args.base.replace(":", "-")}-{run_id}'
    output.mkdir(parents=True)
    print(f'Linux acceptance: {args.base}; logs: {output}', flush=True)
    with (output / 'run.log').open('w') as log, tempfile.TemporaryDirectory(prefix='caddy-manager-linux-') as scratch:
        scratch = Path(scratch)
        def run(*cmd, check=True, capture=False):
            result = subprocess.run(cmd, cwd=ROOT, text=True, stdout=subprocess.PIPE if capture else log,
                                    stderr=subprocess.STDOUT, check=False)
            if check and result.returncode:
                raise RuntimeError(f'Command failed ({result.returncode}): {cmd[0:3]}; inspect {output / "run.log"}')
            return result.stdout.strip() if capture else result.returncode
        candidate = scratch / 'candidate.tar'
        if args.package:
            candidate.write_bytes(args.package.resolve().read_bytes())
        else:
            with candidate.open('wb') as archive:
                subprocess.run(['git', 'archive', 'HEAD'], cwd=ROOT, stdout=archive, check=True)
        legacy = scratch / 'legacy.tar'
        with legacy.open('wb') as archive:
            subprocess.run(['git', 'archive', 'v1.0.0'], cwd=ROOT, stdout=archive, check=True)
        container = None
        created_builder = False
        try:
            run('docker', 'buildx', 'create', '--name', builder, '--driver', 'docker-container')
            created_builder = True
            print('Preparing isolated Linux image...', flush=True)
            run('docker', 'buildx', 'build', '--builder', builder, '--load', '--build-arg', f'BASE={args.base}',
                '-t', image, '-f', str(ROOT / 'tests/integration/Dockerfile'), str(scratch))
            for scenario in ('fresh', 'upgrade') if args.scenario == 'all' else (args.scenario,):
                container = f'{builder}-{scenario}'
                print(f'Checking {scenario} installation...', flush=True)
                run('docker', 'run', '-d', '--name', container, '--privileged', '--cgroupns=private',
                    '--memory=768m', '--cpus=1', '--pids-limit=256',
                    '--tmpfs', '/run', '--tmpfs', '/run/lock', '--tmpfs', '/tmp', image)
                for _ in range(60):
                    state = run('docker', 'exec', container, 'systemctl', 'is-system-running', check=False, capture=True)
                    if state in ('running', 'degraded'):
                        break
                    if run('docker', 'inspect', '--format', '{{.State.Running}}', container, capture=True) != 'true':
                        raise RuntimeError('Temporary systemd container exited before startup.')
                    time.sleep(0.5)
                else:
                    raise RuntimeError('Temporary systemd container did not become ready.')
                run('docker', 'exec', container, 'mkdir', '-p', '/candidate', '/legacy', '/qa')
                run('docker', 'cp', str(candidate), f'{container}:/tmp/candidate.tar')
                run('docker', 'cp', str(legacy), f'{container}:/tmp/legacy.tar')
                extract = ['docker', 'exec', container, 'tar', '-xf', '/tmp/candidate.tar', '-C', '/candidate']
                if args.package:
                    extract += ['--strip-components=1']
                run(*extract)
                run('docker', 'exec', container, 'tar', '-xf', '/tmp/legacy.tar', '-C', '/legacy')
                run('docker', 'cp', str(ROOT / 'tests/integration/exercise.py'), f'{container}:/qa/exercise.py')
                result = run('docker', 'exec', container, 'python3', '/qa/exercise.py', '--scenario', scenario, check=False)
                run('docker', 'cp', f'{container}:/qa/result.json', str(output / f'{scenario}.json'), check=False)
                if result:
                    raise RuntimeError(f'{scenario} acceptance failed; inspect {output / "run.log"}')
                print((output / f'{scenario}.json').read_text(), flush=True)
                run('docker', 'rm', '-f', container)
                container = None
        finally:
            if container:
                run('docker', 'logs', container, check=False)
                run('docker', 'exec', container, 'journalctl', '--no-pager', '-n', '100', '-u', 'caddy', '-u', 'caddy-manager', check=False)
                run('docker', 'rm', '-f', container, check=False)
            run('docker', 'image', 'rm', image, check=False)
            if created_builder:
                run('docker', 'buildx', 'rm', '--force', builder, check=False)
    print('Completed; temporary containers, image and dedicated build cache removed.', flush=True)


if __name__ == '__main__':
    main()
