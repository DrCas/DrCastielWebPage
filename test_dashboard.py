import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import dashboard_api
import monitor
from local_dashboard import app


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.state=Path(self.temp.name)
        self.patch=patch.object(dashboard_api,'STATE',self.state);self.patch.start()
        self.dbpatch=patch.object(dashboard_api,'DB',self.state/'dashboard.sqlite3');self.dbpatch.start()
        self.db=sqlite3.connect(self.state/'dashboard.sqlite3');monitor.init_db(self.db)
        self.client=app.test_client()
    def tearDown(self):
        self.db.close();self.patch.stop();self.dbpatch.stop();self.temp.cleanup()
    def test_sources_and_database_are_not_public(self):
        for path in ('/dashboard_api.py','/monitor.py','/uptime_history.json','/.env','/Dockerfile'):
            self.assertEqual(self.client.get(path).status_code,404,path)
        for path in ('/','/domains','/domains/example.com','/projects','/projects/demo','/app.js'):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code,200,path)
    def test_monitor_records_transitions_and_removals(self):
        monitor.upsert_domains(self.db,{'example.com':{'source':'test','fingerprint':'one'}})
        with patch.object(monitor,'probe',return_value=('example.com','down',404,12)):
            monitor.sample_domains(self.db)
        with patch.object(monitor,'probe',return_value=('example.com','up',200,8)):
            monitor.sample_domains(self.db)
        result=self.client.get('/api/domains/example.com').get_json()
        self.assertEqual(result['state'],'up');self.assertEqual(result['uptime_pct'],50)
        self.assertEqual(len(result['history']),2)
        self.assertTrue(any('Down → Up'==e['message'] for e in result['events']))
        monitor.upsert_domains(self.db,{})
        self.assertEqual(self.client.get('/api/status').get_json()['domains'],[])
    def test_stale_data_is_explicit(self):
        (self.state/'server.json').write_text(json.dumps({'timestamp':time.time()-100,'health':'good'}))
        self.assertTrue(self.client.get('/api/status').get_json()['server']['stale'])
    def test_readme_scripts_removed(self):
        import base64
        def mock(path,ttl=600):
            if path.endswith('/demo'):return {'name':'demo','owner':{'login':'DrCas'},'private':False}
            if path.endswith('/readme'):return {'content':base64.b64encode(b'<script>alert(1)</script><img src=x onerror=alert(1)>[click](javascript:alert(1))').decode()}
            return []
        with patch.object(dashboard_api,'github',side_effect=mock):
            response=self.client.get('/api/projects/demo')
        self.assertEqual(response.status_code,200)
        html=response.get_json()['readme_html']
        self.assertNotIn('<script',html);self.assertNotIn('<img',html);self.assertNotIn('javascript:',html)
    def test_invalid_repo_paths_and_private_destinations(self):
        with patch.object(dashboard_api,'repository',return_value={'name':'demo'}):
            self.assertEqual(self.client.get('/api/projects/demo/files?path=../secret').status_code,400)
        for url in ('http://example.com','https://127.0.0.1','https://100.117.231.66','https://example.com:8443'):
            self.assertFalse(monitor.public_url(url),url)


if __name__=='__main__':unittest.main()
