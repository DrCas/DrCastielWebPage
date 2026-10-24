"""Read-only dashboard API. A separate host monitor owns collection and history."""
import base64
import concurrent.futures
from contextlib import closing
import json
import re
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import bleach
import markdown
from flask import Blueprint, jsonify, request

api = Blueprint('dashboard', __name__)
STATE = Path(os.environ.get('DASHBOARD_STATE', '/status-disk'))
DB = STATE / 'dashboard.sqlite3'
OWNER = 'DrCas'
_cache = {}


def snapshot(name):
    try:
        data = json.loads((STATE / (name + '.json')).read_text())
        data['stale'] = time.time() - data.get('timestamp', 0) > (600 if name=='discovery' else 90)
        return data
    except (OSError, ValueError):
        return {'health': 'unknown', 'stale': True, 'error': 'Waiting for monitoring connection'}


def connect():
    return sqlite3.connect('file:' + DB.as_posix() + '?mode=ro', uri=True, timeout=3)


def domains():
    try:
        with closing(connect()) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute('SELECT * FROM domains WHERE enabled=1 ORDER BY hostname')]
    except sqlite3.Error: return []


def github(path, ttl=600):
    old = _cache.get(path)
    if old and time.time() - old[0] < ttl: return old[1]
    req = urllib.request.Request('https://api.github.com' + path, headers={
        'User-Agent': 'DrCastiel-Dashboard', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urllib.request.urlopen(req, timeout=12) as response: value = json.load(response)
        _cache[path] = (time.time(), value)
        return value
    except Exception:
        if old: return old[1]
        raise


def repository(name):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name): raise ValueError('Invalid project')
    repo = github(f'/repos/{OWNER}/{name}')
    if repo.get('private') or repo.get('owner', {}).get('login', '').lower() != OWNER.lower():
        raise ValueError('Project unavailable')
    return repo


@api.get('/api/status')
def status():
    return jsonify(timestamp=time.time(), pi=snapshot('pi'), server=snapshot('server'),
                   domains=domains(), discovery=snapshot('discovery'))


@api.get('/api/domains/<hostname>')
def domain_detail(hostname):
    item = next((x for x in domains() if x['hostname'] == hostname), None)
    if item is None: return jsonify(error='Domain not found'), 404
    with closing(connect()) as db:
        item['history'] = [dict(zip(('timestamp','state','http_status','latency_ms'), row)) for row in db.execute(
            'SELECT timestamp,state,http_status,latency_ms FROM samples WHERE hostname=? AND timestamp>? ORDER BY timestamp', (hostname, time.time()-30*86400))]
        item['events'] = [dict(zip(('timestamp','kind','message'), row)) for row in db.execute(
            'SELECT timestamp,kind,message FROM events WHERE hostname=? ORDER BY timestamp DESC LIMIT 40', (hostname,))]
    measured = [x for x in item['history'] if x['state'] in ('up','down')]
    item['uptime_pct'] = round(100*sum(x['state']=='up' for x in measured)/len(measured),2) if measured else None
    return jsonify(item)


@api.get('/api/projects')
def projects():
    try:
        result = []
        for page in range(1,21):
            batch = github(f'/users/{OWNER}/repos?per_page=100&sort=pushed&page={page}')
            result.extend(x for x in batch if not x.get('private'))
            if len(batch)<100: break
        return jsonify(owner=OWNER, projects=result, synced_at=time.time())
    except Exception: return jsonify(error='GitHub is temporarily unavailable. Try again shortly.'),503


@api.get('/api/projects/<name>')
def project_detail(name):
    try:
        repo = repository(name)
        root = f'/repos/{OWNER}/{repo["name"]}'
        def optional(suffix):
            try: return github(root+suffix)
            except urllib.error.HTTPError as error:
                if error.code in (404,409): return []
                raise
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(optional,path) for path in ('/readme','/contents','/commits?per_page=5','/releases?per_page=5')]
            readme,files,commits,releases = [future.result() for future in futures]
        raw = base64.b64decode(readme.get('content','')).decode('utf-8',errors='replace') if readme else 'This project has no README yet.'
        rendered = markdown.markdown(raw, extensions=['fenced_code','tables'])
        safe = bleach.clean(rendered, tags=['p','a','h1','h2','h3','h4','ul','ol','li','pre','code','blockquote','strong','em','hr','br','table','thead','tbody','tr','th','td','del'], attributes={'a':['href','title']}, protocols=['http','https'], strip=True)
        return jsonify(repo=repo, readme_html=safe, files=files, commits=commits, releases=releases)
    except (ValueError,urllib.error.HTTPError): return jsonify(error='Project unavailable'),404
    except Exception: return jsonify(error='GitHub is temporarily unavailable. Try again shortly.'),503


@api.get('/api/projects/<name>/files')
def project_files(name):
    try:
        repo = repository(name)
        path = request.args.get('path','')
        if len(path)>600 or any(p in ('..','.') for p in path.split('/')):
            return jsonify(error='Invalid file path'),400
        value = github(f'/repos/{OWNER}/{repo["name"]}/contents/'+urllib.parse.quote(path,safe='/'))
        if isinstance(value,dict) and value.get('type')=='file':
            text = base64.b64decode(value.get('content','')).decode('utf-8',errors='replace') if value.get('size',0)<=300000 else 'This file is too large to preview. Open it on GitHub.'
            value = {'type':'file','name':value['name'],'html_url':value['html_url'],'content':text}
        return jsonify(value)
    except Exception: return jsonify(error='This file could not be loaded.'),404
