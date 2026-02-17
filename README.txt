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

Public Mode (current)
- local_dashboard.py is configured as public: no Google login required.
- The dashboard and /api/status are accessible without session auth.
