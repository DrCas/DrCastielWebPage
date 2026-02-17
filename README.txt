DrCastiel Landing Dashboard (Starter Kit)

What you get
- A glassy dashboard landing page (index.html + styles.css + app.js)
- A Flask blueprint that exposes /api/status (status_api.py)
- Nginx snippet to serve the dashboard + proxy the API

How to deploy (Pi)
1) Create a folder for the dashboard:
   sudo mkdir -p /mnt/ssd/crowngfx/drcastiel-dashboard

2) Copy the 3 static files into it:
   index.html
   styles.css
   app.js

3) Add the API to your Admin-Portal:
   - Put status_api.py next to app.py
   - Register blueprint (see register_blueprint_snippet.txt)
   - pip install psutil in your Admin-Portal venv
   - restart your gunicorn service

4) Nginx:
   - Add/merge nginx_drcastiel_server_block.conf into your site config
   - reload nginx

Notes
- app.js includes placeholder projects (MTGValueBot / HaulAds / Adventure Map) set to '#'
  Replace those URLs when ready.
- If you prefer not to expose system stats publicly, protect /api/status with login,
  or restrict it to local-only and have the page fetch from a private endpoint.


Google Login Security (Gmail)
- local_dashboard.py now supports Google OAuth login and can restrict access by email.
- Install dependency:
   pip install Authlib

1) Create Google OAuth credentials
    - Open Google Cloud Console
    - APIs & Services -> Credentials -> Create Credentials -> OAuth client ID
    - Application type: Web application
    - Authorized redirect URI (local):
       http://127.0.0.1:5050/auth/google
    - Copy Client ID and Client Secret

2) Set environment variables (local)
    - Copy .env.example to .env (or set vars in your shell)
    - Required values:
       FLASK_SECRET_KEY
       GOOGLE_CLIENT_ID
       GOOGLE_CLIENT_SECRET
       ALLOWED_EMAILS (comma-separated Gmail addresses allowed to log in)

3) Run locally
    Windows PowerShell example:
    $env:FLASK_SECRET_KEY = "your-long-random-secret"
    $env:GOOGLE_CLIENT_ID = "..."
    $env:GOOGLE_CLIENT_SECRET = "..."
    $env:ALLOWED_EMAILS = "youremail@gmail.com"
    .venv\Scripts\python.exe local_dashboard.py

4) Behavior
    - Unauthenticated users are redirected to /login
    - /api/status returns 401 unless logged in
    - /logout clears session
