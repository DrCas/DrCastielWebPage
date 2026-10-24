"""Owner-only Minecraft management. Crafty credentials never leave this process."""
import concurrent.futures
import functools
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from uuid import UUID

from flask import Blueprint, g, jsonify, request
import jwt
import urllib3

servers_api = Blueprint('servers', __name__, url_prefix='/api/servers')
CONFIG = Path(os.environ.get('MANAGEMENT_CONFIG', '/run/secrets/management.json'))


class ManagementError(Exception):
    def __init__(self, message, status=502):
        self.message, self.status = message, status


@functools.lru_cache(maxsize=1)
def settings():
    try:
        config = json.loads(CONFIG.read_text())
        assert config['issuer'].startswith('https://')
        assert config['audiences'] and config['owners'] and len(config['csrf_secret']) >= 32
        return config
    except (OSError, ValueError, KeyError, AssertionError):
        raise ManagementError('Server management is waiting for its private connection.', 503)


@functools.lru_cache(maxsize=1)
def jwks():
    return jwt.PyJWKClient(settings()['issuer'].rstrip('/') + '/cdn-cgi/access/certs', timeout=5)


def owner_only(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        token = request.headers.get('Cf-Access-Jwt-Assertion', '')
        if not token:
            raise ManagementError('Sign in to your website to manage servers.', 401)
        config = settings()
        try:
            claims = jwt.decode(token, jwks().get_signing_key_from_jwt(token).key,
                                algorithms=['RS256'], issuer=config['issuer'],
                                audience=config['audiences'], leeway=30,
                                options={'require': ['exp', 'iat', 'aud', 'iss', 'email']})
            if claims['email'].lower() not in [x.lower() for x in config['owners']]:
                raise ManagementError('Only the website owner can manage servers.', 403)
        except jwt.PyJWTError:
            raise ManagementError('Your sign-in expired. Reload and sign in again.', 401)
        g.owner = claims['email'].lower()
        g.csrf = hmac.new(config['csrf_secret'].encode(), token.encode(), hashlib.sha256).hexdigest()
        if request.method == 'POST':
            if request.headers.get('Origin') not in config['origins'] or not hmac.compare_digest(
                    request.headers.get('X-CSRF-Token', ''), g.csrf):
                raise ManagementError('Refresh the page before sending a server command.', 403)
            if not request.is_json or request.content_length is None or request.content_length > 2048:
                raise ManagementError('Expected a small JSON request.', 400)
        return fn(*args, **kwargs)
    return wrapped


@servers_api.errorhandler(ManagementError)
def management_error(error):
    return jsonify(error=error.message), error.status


@servers_api.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'private, no-store'
    return response


@functools.lru_cache(maxsize=1)
def pool():
    config = settings()
    return urllib3.PoolManager(cert_reqs='CERT_REQUIRED', ca_certs=config['crafty_ca'],
                              assert_hostname=config['crafty_hostname'],
                              server_hostname=config['crafty_hostname'], maxsize=8)


def crafty(path, method='GET', body=None):
    config = settings()
    try:
        token = Path(config['crafty_token']).read_text().strip()
        response = pool().request(method, config['crafty_url'].rstrip('/') + '/api/v2' + path,
                                  headers={'Authorization': 'Bearer ' + token,
                                           'Content-Type': 'text/plain' if body is not None else 'application/json'},
                                  body=body.encode() if body is not None else None,
                                  timeout=urllib3.Timeout(connect=3, read=8), retries=False,
                                  redirect=False, preload_content=False)
        try:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ManagementError('Crafty returned more data than expected.')
            if response.status in (401, 403):
                raise ManagementError('Crafty denied access. Check the website API key permissions.', 503)
            if response.status == 404:
                raise ManagementError('This server is no longer available in Crafty.', 404)
            if response.status >= 300:
                raise ManagementError('Crafty could not complete the request.')
            data = json.loads(raw)
            if data.get('status') != 'ok':
                raise ManagementError('Crafty did not accept the request. Check its dashboard for details.')
            return data.get('data')
        finally:
            response.close()
            response.release_conn()
    except (OSError, urllib3.exceptions.HTTPError, ValueError):
        raise ManagementError('Cannot reach Crafty securely. Check that the server is online.', 503)


def server_uuid(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ManagementError('Invalid server address.', 400)


def number(value):
    try:
        return float(str(value).rstrip('%'))
    except (ValueError, TypeError):
        return None


def summary(server):
    sid = server_uuid(server.get('server_id') or server.get('server_uuid'))
    item = {'id': sid, 'name': str(server.get('server_name') or 'Minecraft server'),
            'created': server.get('created'), 'type': server.get('type') or 'Minecraft'}
    try:
        stats = crafty('/servers/' + sid + '/stats') or {}
        if isinstance(stats, list):
            stats = stats[0] if stats else {}
        state = 'running' if stats.get('running') else 'stopped'
        if stats.get('crashed'):
            state = 'crashed'
        if stats.get('updating'):
            state = 'updating'
        elif stats.get('waiting_start'):
            state = 'starting'
        item.update(state=state, players=stats.get('online', 0), max_players=stats.get('max', 0),
                    cpu=number(stats.get('cpu')), memory=stats.get('mem'),
                    memory_pct=number(stats.get('mem_percent')), world=stats.get('world_name'),
                    world_size=stats.get('world_size'), version=stats.get('version'),
                    started=stats.get('started'), port=stats.get('server_port'), checked_at=time.time())
    except ManagementError as error:
        item.update(state='unknown', error=error.message, checked_at=time.time())
    return item


def find_server(sid):
    sid = server_uuid(sid)
    servers = crafty('/servers') or []
    for server in servers:
        if str(server.get('server_id') or server.get('server_uuid')) == sid:
            return server
    raise ManagementError('This server is no longer available in Crafty.', 404)


@servers_api.get('')
@owner_only
def list_servers():
    servers = crafty('/servers') or []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        items = list(executor.map(summary, servers))
    return jsonify(servers=items, csrf=g.csrf, checked_at=time.time())


@servers_api.get('/<sid>')
@owner_only
def server_details(sid):
    return jsonify(server=summary(find_server(sid)), csrf=g.csrf)


@servers_api.get('/<sid>/console')
@owner_only
def console(sid):
    find_server(sid)
    lines = crafty('/servers/' + server_uuid(sid) + '/logs?file=false&colors=false&raw=false&html=false') or []
    if not isinstance(lines, list):
        raise ManagementError('Crafty returned an unexpected console format.')
    return jsonify(lines=[str(line)[:4000] for line in lines[-300:]], checked_at=time.time())


@servers_api.post('/<sid>/command')
@owner_only
def command(sid):
    sid = server_uuid(sid)
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        raise ManagementError('Expected a JSON object.', 400)
    action = payload.get('action')
    actions = {'start': 'start_server', 'stop': 'stop_server', 'restart': 'restart_server'}
    if action not in (*actions, 'console'):
        raise ManagementError('Unknown server action.', 400)
    text = payload.get('command', '')
    if action == 'console' and (not isinstance(text, str) or not text.strip() or len(text) > 512
                                or any(ord(char) < 32 or ord(char) == 127 for char in text)):
        raise ManagementError('Enter one console command, up to 512 characters.', 400)
    request_id = request.headers.get('X-Request-ID', '')
    if not re.fullmatch(r'[a-f0-9-]{36}', request_id):
        raise ManagementError('Missing command request ID. Refresh the page.', 400)
    server = summary(find_server(sid))
    if server['state'] not in ('running', 'stopped', 'crashed'):
        raise ManagementError('Wait until the server finishes changing state.', 409)
    if (action == 'start' and server['state'] == 'running') or (action != 'start' and server['state'] != 'running'):
        raise ManagementError('The server state changed. Refresh before trying again.', 409)
    # One transaction serializes controls across workers and prevents retried POSTs
    # from executing twice. A lost response is never retried automatically.
    db = sqlite3.connect(settings()['audit_db'], timeout=1)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS actions (request_id TEXT PRIMARY KEY, owner TEXT, server TEXT, action TEXT, at REAL, result TEXT)')
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM actions WHERE request_id=?', (request_id,)).fetchone():
            raise ManagementError('This command was already submitted. Refresh to check its result.', 409)
        recent = db.execute('SELECT at FROM actions WHERE server=? ORDER BY at DESC LIMIT 1', (sid,)).fetchone()
        if recent and time.time() - recent[0] < (1 if action == 'console' else 5):
            raise ManagementError('Please wait a moment before sending another command.', 429)
        db.execute('INSERT INTO actions VALUES (?,?,?,?,?,?)', (request_id, g.owner, sid, action, time.time(), 'submitted'))
        db.commit()
        try:
            if action == 'console':
                crafty('/servers/' + sid + '/stdin', 'POST', text.strip().lstrip('/'))
            else:
                crafty('/servers/' + sid + '/action/' + actions[action], 'POST')
        except ManagementError:
            db.execute('UPDATE actions SET result=? WHERE request_id=?', ('unconfirmed', request_id))
            db.commit()
            raise
        db.execute('UPDATE actions SET result=? WHERE request_id=?', ('accepted', request_id))
        db.commit()
    except sqlite3.OperationalError:
        raise ManagementError('Another command is being processed. Please wait.', 409)
    finally:
        db.close()
    return jsonify(ok=True, message='Command accepted by Crafty. Waiting for the server to update.')
