# DrCastiel dashboard

A Flask dashboard with Overview, Domains, and Projects pages.

- Overview reads Pi host metrics and private CasaOS Netdata metrics every 15 seconds.
- Domains sync from Cloudflare DNS every 5 minutes and are checked independently every minute.
- Domain detail pages show response codes, latency, recorded availability, observed status/configuration changes, and Cloudflare DNS modification dates.
- Projects read public DrCas repositories from GitHub. README, files, source previews, commits, and releases stay within this website; GitHub links are available separately.
- The server administration link is http://casa.drcastiel.com and resolves to its private Tailscale address. Tailscale is required. HTTP is carried inside the encrypted tailnet; a browser-trusted HTTPS endpoint is not configured.

## Production

Primary local checkout: G:/Projects/DrCastiel
Supporting backups and deployment files: G:/GPT Project Files/DrCastielWebPage
Pi deployment: /mnt/ssd/docker/web-stack/src/www-site
Compose service: www-site; 127.0.0.1:5080 -> container port 8000
Nginx and the existing Cloudflare Tunnel route public traffic to this service.

The separate drcastiel-monitor systemd service runs /opt/drcastiel/monitor.py with system Python and host psutil. State is under /var/lib/web-stack-status, mounted read-only at /status-disk in the web container. Never expose that directory as static files. The monitor is the only SQLite writer. Old uptime_history.json is preserved separately and is not treated as new minute-resolution history.

The Cloudflare API token is at /etc/drcastiel/cloudflare-token, owned by root, mode 600, outside the image and repository. Required scopes are Zone:Read and DNS:Read for the intended zones. All zones are included to discover newly added domains. If no token is available, discovery falls back to local tunnel and Nginx hostnames. A failed sync preserves the last successful inventory. Private casa.drcastiel.com is excluded from public website probes.

Server readings come from the existing Netdata endpoint over Tailscale, http://100.117.231.66:19999/api/v1/allmetrics?format=json. No public monitoring port or new SSH credential is needed. If either collector stops reporting for 90 seconds, its card explicitly shows stale data.

## Local development

Install requirements.txt and run local_dashboard.py. Set DASHBOARD_STATE to a directory containing monitor snapshots and dashboard.sqlite3 to use real monitoring data. The web process only reads the database. Production monitoring requires Linux and should not be started on a development Windows computer.

Checks: python -m unittest -v test_dashboard; node --check app.js

## Deployment and rollback

Back up the deployed source, compose.yml, and previous image before changes. Build the source into web-stack-www-site, then run docker compose up -d --no-deps --force-recreate www-site. Other services must remain running. Replace /opt/drcastiel/monitor.py and restart drcastiel-monitor when its source changes.

The October 23, 2026 deployment backup is /mnt/ssd/docker/web-stack/backups/www-site-redesign-20261023-194442 and the prior image is tagged drcastiel-dashboard:before-redesign. Restore source from its source/ directory and compose.yml from that backup; retag the prior image as web-stack-www-site, then recreate only www-site with --no-build. Monitoring history and existing uptime_history.json stay on the host.

GitHub is queried without credentials and only public repositories are published. Results are cached; GitHub outages can temporarily serve cached data. Private repositories require an authenticated private section before they can be included.
