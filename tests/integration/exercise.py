"""Destructive acceptance checks, restricted to the disposable test image."""

import argparse
import hashlib
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import tarfile
import threading
import time
import urllib.request

DATA = Path('/var/lib/caddy-manager')
APP = Path('/opt/caddy-manager')
ENV = Path('/etc/caddy-manager.env')
checks = []
client = None


def run(*cmd):
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()


def new_client():
    global client
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def api(path, method='GET', data=None):
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request('http://127.0.0.1:7080/api/' + path, data=body, method=method,
                                     headers={'Content-Type': 'application/json'})
    with client.open(request, timeout=10) as response:
        return json.load(response)


def eventually(function, timeout=40):
    end = time.monotonic() + timeout
    error = None
    while time.monotonic() < end:
        try:
            result = function()
            if result:
                return result
        except (OSError, ValueError, AssertionError, subprocess.CalledProcessError) as exc:
            error = exc
        time.sleep(0.3)
    raise AssertionError(f'Condition did not become true: {error}')


def passed(name):
    checks.append(name)
    print('PASS:', name, flush=True)


def install(source):
    output = run('bash', str(source / 'scripts/install.sh'))
    print(output, flush=True)
    new_client()
    eventually(lambda: api('auth/status'))


def snapshot():
    return {name: (DATA / name).read_bytes() for name in ('auth.json', 'sites.json', 'Caddyfile')}


def https_request(ca):
    context = ssl.create_default_context(cafile=str(ca))
    with socket.create_connection(('127.0.0.1', 443), timeout=5) as raw:
        with context.wrap_socket(raw, server_hostname='qa.localhost') as secure:
            certificate = hashlib.sha256(secure.getpeercert(binary_form=True)).hexdigest()
            secure.sendall(b'GET / HTTP/1.1\r\nHost: qa.localhost\r\nConnection: close\r\n\r\n')
            content = b''
            while True:
                chunk = secure.recv(8192)
                if not chunk:
                    break
                content += chunk
            assert b'qa upstream response' in content
            return certificate


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'qa upstream response'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', choices=('fresh', 'upgrade'), required=True)
    args = parser.parse_args()
    assert os.geteuid() == 0 and Path('/.dockerenv').exists()
    assert Path('/etc/caddy-manager-integration-only').is_file()
    assert Path('/proc/1/comm').read_text().strip() == 'systemd'
    assert not DATA.exists(), 'Test image already contains panel data.'
    server = ThreadingHTTPServer(('127.0.0.1', 18081), Upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    succeeded = False
    try:
        install(Path('/legacy' if args.scenario == 'upgrade' else '/candidate'))
        assert api('auth/status')['setupRequired']
        passed('new installation starts under systemd')
        password = secrets.token_urlsafe(24)
        credentials = dict(username='qatest', password=password)
        api('auth/setup', 'POST', {**credentials, 'confirmPassword': password})
        site = api('sites', 'POST', dict(domain='qa.localhost', upstream='127.0.0.1:18081',
                                        enabled=True, note='preserve during upgrade'))
        ca = eventually(lambda: next(iter(Path('/var/lib/caddy').rglob('pki/authorities/local/root.crt')), None))
        leaf = eventually(lambda: https_request(ca))
        root_certificate = ca.read_bytes()
        shutil.copyfile(ca, '/usr/local/share/ca-certificates/caddy-manager-qa.crt')
        run('update-ca-certificates')
        api(f'sites/{site["id"]}/certificate', 'POST')
        eventually(lambda: api('sites')[0]['certificate']['state'] == 'active')
        passed('real Caddy reverse proxy and trusted local HTTPS certificate work')
        preserved = snapshot()
        ENV.write_text(ENV.read_text() + '\nCADDY_MANAGER_QA_PRESERVE=yes\n')
        environment = ENV.read_bytes()
        install(Path('/candidate'))
        api('auth/login', 'POST', credentials)
        assert snapshot() == preserved
        assert ENV.read_bytes() == environment
        assert ca.read_bytes() == root_certificate
        assert eventually(lambda: https_request(ca)) == leaf
        assert (DATA / 'auth.json').stat().st_mode & 0o777 == 0o600
        info = json.loads((APP / 'install-info.json').read_text())
        assert info['status'] == 'ready'
        assert info['version'] == Path('/candidate/VERSION').read_text().strip()
        assert info['source'] == ('release' if Path('/candidate/release.json').exists() else 'directory')
        passed('upgrade/reinstall preserves account, sites, config, environment and certificate bytes')

        for service in ('caddy', 'caddy-manager'):
            assert run('systemctl', 'is-enabled', service) == 'enabled'
            assert run('systemctl', 'show', '--property=Restart', '--value', service) == 'on-failure'
            old_pid = run('systemctl', 'show', '--property=MainPID', '--value', service)
            run('systemctl', 'kill', '--kill-who=main', '--signal=SIGKILL', service)
            def restarted():
                current = run('systemctl', 'show', '--property=MainPID', '--value', service)
                return current not in ('0', old_pid) and run('systemctl', 'is-active', service) == 'active'
            eventually(restarted)
        new_client()
        eventually(lambda: api('auth/status'))
        api('auth/login', 'POST', credentials)
        assert snapshot() == preserved
        assert eventually(lambda: https_request(ca)) == leaf
        passed('both services restart after a simulated crash and retain data')

        run('systemctl', 'stop', 'caddy-manager')
        archive = Path(run('bash', str(APP / 'scripts/backup.sh')).splitlines()[-1])
        assert archive.stat().st_mode & 0o777 == 0o600
        with tarfile.open(archive) as saved:
            names = saved.getnames()
            assert 'var/lib/caddy-manager/auth.json' in names
            assert 'etc/caddy-manager.env' in names
        run('systemctl', 'stop', 'caddy')
        shutil.rmtree(DATA)
        ENV.unlink()
        run('tar', '-xzf', str(archive), '-C', '/')
        run('caddy', 'validate', '--config', str(DATA / 'Caddyfile'), '--adapter', 'caddyfile')
        run('systemctl', 'start', 'caddy')
        run('systemctl', 'start', 'caddy-manager')
        new_client()
        eventually(lambda: api('auth/status'))
        api('auth/login', 'POST', credentials)
        assert snapshot() == preserved
        assert ENV.read_bytes() == environment
        assert eventually(lambda: https_request(ca)) == leaf
        passed('real backup archive restores account, sites, environment and proxy operation')

        run('bash', str(APP / 'scripts/uninstall.sh'))
        assert (DATA / 'auth.json').read_bytes() == preserved['auth.json']
        assert (DATA / 'sites.json').read_bytes() == preserved['sites.json']
        assert not Path('/etc/systemd/system/caddy-manager.service').exists()
        assert run('systemctl', 'is-active', 'caddy') == 'active'
        passed('uninstall keeps panel data and leaves Caddy running')
        succeeded = True
    finally:
        server.shutdown()
        result = dict(scenario=args.scenario, success=succeeded, checks=checks,
                      os=Path('/etc/os-release').read_text(),
                      scope='isolated container; local CA HTTPS, not public ACME issuance')
        Path('/qa/result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
