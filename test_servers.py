import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from local_dashboard import app
import servers_api as module
import time

SID = '5adcec83-684c-4555-a7e9-9d913203d07e'


class ServerManagementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = dict(issuer='https://team.cloudflareaccess.com', audiences=['dashboard'],
                           owners=['owner@example.com'], origins=['https://www.drcastiel.com'],
                           csrf_secret='x'*64, audit_db=str(Path(self.temp.name)/'audit.db'))
        self.settings = patch.object(module, 'settings', return_value=self.config)
        self.settings.start()
        self.keys = patch.object(module, 'jwks', return_value=Mock(get_signing_key_from_jwt=Mock(return_value=Mock(key=self.key.public_key()))))
        self.keys.start()
        self.client = app.test_client()
        self.token = self.sign()
        self.headers = {'Cf-Access-Jwt-Assertion': self.token}

    def tearDown(self):
        self.settings.stop()
        self.keys.stop()
        self.temp.cleanup()

    def sign(self, **overrides):
        claims = dict(iss=self.config['issuer'], aud='dashboard', email='owner@example.com', iat=int(time.time()), exp=int(time.time())+600)
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm='RS256')

    def write_headers(self):
        import hmac, hashlib
        return {**self.headers, 'Origin':'https://www.drcastiel.com',
                'X-CSRF-Token':hmac.new(self.config['csrf_secret'].encode(), self.token.encode(), hashlib.sha256).hexdigest(),
                'X-Request-ID':str(uuid4())}

    @staticmethod
    def crafty(path, method='GET', body=None):
        if path == '/servers':
            return [{'server_id': SID, 'server_name':'Private world'}]
        if path.endswith('/stats'):
            return {'running': True, 'online': 2, 'max':20, 'cpu':12.5, 'mem':'1GB'}
        if '/logs?' in path:
            return ['<script>alert(1)</script>', 'Player connected']
        return None

    def test_all_server_data_requires_verified_owner(self):
        for path in ('', '/'+SID, '/'+SID+'/console'):
            self.assertEqual(self.client.get('/api/servers'+path).status_code,401)
        for claims, status in (({'email':'other@example.com'},403),({'aud':'other'},401),({'exp':int(time.time())-100},401),({'iss':'https://evil.example'},401)):
            self.assertEqual(self.client.get('/api/servers',headers={'Cf-Access-Jwt-Assertion':self.sign(**claims)}).status_code,status)
        forged = jwt.encode(dict(email='owner@example.com'),'wrong-key-'*8,algorithm='HS256')
        self.assertEqual(self.client.get('/api/servers',headers={'Cf-Access-Jwt-Assertion':forged}).status_code,401)

    @patch.object(module,'crafty',return_value=[])
    def test_empty_inventory_is_real_and_not_demo(self, crafty):
        response=self.client.get('/api/servers',headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['servers'],[])
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_discovery_stats_and_plain_console(self):
        with patch.object(module,'crafty',side_effect=self.crafty):
            response=self.client.get('/api/servers',headers=self.headers)
            self.assertEqual(response.json['servers'][0]['players'],2)
            self.assertNotIn('path',response.json['servers'][0])
            response=self.client.get('/api/servers/'+SID+'/console',headers=self.headers)
            self.assertEqual(response.json['lines'][0],'<script>alert(1)</script>')

    def test_csrf_and_invalid_actions_cannot_reach_crafty(self):
        with patch.object(module,'crafty') as crafty:
            url='/api/servers/'+SID+'/command'
            self.assertEqual(self.client.post(url,json={'action':'stop'},headers=self.headers).status_code,403)
            headers=self.write_headers();headers['Origin']='https://evil.example'
            self.assertEqual(self.client.post(url,json={'action':'stop'},headers=headers).status_code,403)
            for payload in ({'action':'delete'},{'action':'console','command':'say hi\nstop'}):
                self.assertEqual(self.client.post(url,json=payload,headers=self.write_headers()).status_code,400)
            crafty.assert_not_called()

    def test_commands_are_allowlisted_and_duplicates_are_rejected(self):
        with patch.object(module,'crafty',side_effect=self.crafty) as crafty:
            headers=self.write_headers();url='/api/servers/'+SID+'/command'
            response=self.client.post(url,json={'action':'restart'},headers=headers)
            self.assertEqual(response.status_code,200)
            crafty.assert_any_call('/servers/'+SID+'/action/restart_server','POST')
            self.assertEqual(self.client.post(url,json={'action':'restart'},headers=headers).status_code,409)
            self.assertEqual(sum(c.args[1:]==('POST',) for c in crafty.call_args_list),1)

    def test_console_is_only_forwarded_to_game_stdin(self):
        with patch.object(module,'crafty',side_effect=self.crafty) as crafty:
            response=self.client.post('/api/servers/'+SID+'/command',json={'action':'console','command':'/say hello'},headers=self.write_headers())
            self.assertEqual(response.status_code,200)
            crafty.assert_any_call('/servers/'+SID+'/stdin','POST','say hello')

    def test_missing_server_cannot_be_controlled(self):
        with patch.object(module,'crafty',return_value=[]):
            response=self.client.post('/api/servers/'+SID+'/command',json={'action':'start'},headers=self.write_headers())
            self.assertEqual(response.status_code,404)


if __name__=='__main__':
    unittest.main()
