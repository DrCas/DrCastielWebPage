from pathlib import Path
from flask import Flask, send_from_directory
from dashboard_api import api
from servers_api import servers_api

ROOT = Path(__file__).parent
app = Flask(__name__, static_folder=None)
app.register_blueprint(api)
app.register_blueprint(servers_api)

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
    response.cache_control.no_cache = True
    return response

@app.get('/healthz')
def healthz(): return {'ok': True}

@app.get('/')
@app.get('/domains')
@app.get('/domains/<hostname>')
@app.get('/projects')
@app.get('/projects/<name>')
@app.get('/servers')
@app.get('/servers/<server_id>')
def index(**kwargs): return send_from_directory(ROOT, 'index.html')

@app.get('/<asset>')
def asset(asset):
    if asset not in ('styles.css', 'app.js', 'servers.js', 'favicon.svg'):
        return {'error': 'Not found'}, 404
    return send_from_directory(ROOT, asset)

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5050, debug=False)
