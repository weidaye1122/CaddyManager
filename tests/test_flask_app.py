import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

scratch = tempfile.TemporaryDirectory(prefix='caddy-manager-acceptance-')
os.environ['CADDY_MANAGER_DATA'] = scratch.name
os.environ['CADDY_MANAGER_SKIP_CADDY'] = '1'
import flask_app as panel

class Acceptance(unittest.TestCase):
    def setUp(self):
        panel.sites = []
        panel.auth = None
        panel.sessions.clear()
        panel.site_statuses.clear()
        self.client = panel.app.test_client()
        self.probes = patch.object(panel, 'refresh_statuses')
        self.probes.start()
    def tearDown(self):
        self.probes.stop()
    def login(self):
        r = self.client.post('/api/auth/setup', json=dict(username='admin',password='test-pass-1',confirmPassword='test-pass-1'))
        self.assertEqual(r.status_code,201,r.get_json())
    def test_auth_confirmation_and_logout(self):
        self.assertEqual(self.client.get('/api/sites').status_code,401)
        r=self.client.post('/api/auth/setup',json=dict(username='admin',password='test-pass-1',confirmPassword='wrong'))
        self.assertEqual(r.status_code,400)
        self.assertIsNone(panel.auth)
        self.login()
        self.assertNotIn('test-pass-1', panel.AUTH_FILE.read_text())
        self.assertEqual(panel.AUTH_FILE.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.client.post('/api/auth/setup',json={}).status_code,409)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/sites').status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json=dict(username='admin',password='wrong')).status_code,401)
        self.assertEqual(self.client.post('/api/auth/login',json=dict(username='admin',password='test-pass-1')).status_code,200)
    def test_sites_notes_backup_restore_and_protection(self):
        self.login()
        site=dict(domain='demo.example.com',upstream='127.0.0.1:8000',enabled=False,note='酒馆 <测试>')
        r=self.client.post('/api/sites',json=site)
        self.assertEqual(r.status_code,201,r.get_json())
        sid=r.get_json()['id']
        self.assertEqual(self.client.post('/api/sites',json=site).status_code,409)
        r=self.client.put('/api/sites/'+sid,json={**site,'note':'新的备注'})
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.get_json()['note'],'新的备注')
        backup=self.client.get('/api/backup').get_json()
        self.assertEqual(backup[0]['note'],'新的备注')
        self.assertEqual(self.client.post('/api/restore',json=backup*2).status_code,409)
        self.assertEqual(self.client.delete('/api/sites/'+sid).status_code,200)
        self.assertEqual(self.client.post('/api/restore',json=backup).status_code,200)
        self.assertEqual(self.client.get('/api/sites').get_json()[0]['note'],'新的备注')
    def test_same_domain_reuses_certificate(self):
        self.probes.stop()
        site=dict(id='same',domain='demo.example.com',upstream='127.0.0.1:1',enabled=True)
        panel.sites=[site]
        panel.site_statuses['same']={'state':'active','expiresAt':'2027-01-12T00:00:00Z'}
        with patch.object(panel.threading,'Timer') as timer:
            panel.refresh_statuses([{**site,'upstream':'127.0.0.1:2'}],[site])
            timer.assert_not_called()
        self.probes.start()
    def test_caddy_validate_and_reload_failure_preserve_config(self):
        directory=Path(scratch.name)
        config=directory/'Caddyfile'
        config.write_text('old config')
        site=dict(domain='demo.example.com',upstream='127.0.0.1:80',enabled=True,note='never in Caddyfile')
        with patch.object(panel,'SKIP_CADDY',False),patch.object(panel,'CADDYFILE',config):
            with patch.object(panel,'run',return_value=subprocess.CompletedProcess([],1,'','validation failed')):
                with self.assertRaisesRegex(RuntimeError,'校验失败'): panel.validate_and_reload([site])
            self.assertEqual(config.read_text(),'old config')
            results=[subprocess.CompletedProcess([],0,'',''),subprocess.CompletedProcess([],1,'','reload failed'),subprocess.CompletedProcess([],0,'','')]
            with patch.object(panel,'run',side_effect=results):
                with self.assertRaisesRegex(RuntimeError,'reload 失败'): panel.validate_and_reload([site])
            self.assertEqual(config.read_text(),'old config')
            with patch.object(panel,'run',return_value=subprocess.CompletedProcess([],0,'','')):
                panel.validate_and_reload([site])
            self.assertNotIn('never in Caddyfile',config.read_text())
    def test_static_types(self):
        for asset,mime in [('icon.svg','image/svg+xml'),('icon-192.png','image/png'),('apple-touch-icon.png','image/png'),('manifest.webmanifest','application/manifest+json')]:
            response=self.client.get('/'+asset)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.mimetype,mime)
            response.close()
        self.assertEqual(self.client.get('/api/status').status_code,401)

if __name__=='__main__': unittest.main()
