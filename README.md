# DrCastiel dashboard

A Flask dashboard with Overview, Domains, and Projects pages.

- Overview reads Pi host metrics and private CasaOS Netdata metrics every 15 seconds.
- Domains sync from Cloudflare DNS every 5 minutes and are checked independently every minute.
- Domain detail pages show response codes, latency, recorded availability, observed status/configuration changes, and Cloudflare DNS modification dates.
- Projects read public DrCas repositories from GitHub. README, files, source previews, commits, and releases stay within this website; GitHub links are available separately.
- The server administration link is https://casa.drcastiel.com. It resolves to the Pi's private Tailscale address, where a dedicated HTTPS gateway forwards traffic over Tailscale to CasaOS. Tailscale is required. A publicly trusted Let's Encrypt certificate is installed and renews automatically.

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

## Protected endpoint checks

Existing Cloudflare Access protection remains enabled. The monitor recognizes Access login redirects and does not treat their HTTP 200 as website health. For hostnames explicitly configured in local Nginx or the local tunnel it separately checks the local origin using the original Host header, and labels the detail page "Local origin + protected edge". Protected services without a verified local origin remain "Protected" rather than being counted as operational. Public checks continue to validate HTTPS and reject private destinations and private redirects. Old edge-only samples from initial setup were excluded from availability after this validation correction.


## CasaOS HTTPS

`casa.drcastiel.com` has a DNS-only A record pointing to the Pi's Tailscale address (100.71.117.23). The dedicated `drcastiel-casa.service` runs a separate Nginx master listening only on that address, port 443. It also permits only source addresses in the tailnet IPv4 range; other requests are denied. It forwards HTTP and WebSocket traffic over Tailscale to CasServer (100.117.231.66:80). The public website's Nginx master is independent, so CasaOS gateway startup/retry does not block the public websites if Tailscale starts later.

Configuration templates are in deploy/casa-nginx.conf and deploy/drcastiel-casa.service. Installed paths are /etc/drcastiel/casa-nginx.conf and /etc/systemd/system/drcastiel-casa.service. A separate vhost in /etc/nginx/sites-available/casa.drcastiel.com redirects HTTP to HTTPS only for Tailscale clients; it rejects other client addresses. It does not create a public Cloudflare Tunnel route for CasaOS.

The certificate is at /etc/letsencrypt/live/casa.drcastiel.com/fullchain.pem; its private key stays on the Pi. Certbot uses DNS-01 validation with the pre-existing tunnel account's Cloudflare credential, stored root-only at /etc/letsencrypt/cloudflare/casa.ini. No credential or certificate private key belongs in this repository. certbot.timer handles renewal; /etc/letsencrypt/renewal-hooks/deploy/reload-casa validates and reloads the private gateway after successful renewal. The dashboard's read-only DNS discovery token is unchanged.

Validate with `sudo nginx -t -c /etc/drcastiel/casa-nginx.conf`, `sudo systemctl status drcastiel-casa`, and `sudo certbot renew --dry-run --cert-name casa.drcastiel.com --run-deploy-hooks --no-random-sleep-on-renew`. DNS and prior gateway configuration backups are under /mnt/ssd/docker/web-stack/backups/casa-https-20261023-200911.

CasaOS launches several apps using the current hostname and their original ports. To preserve these shortcuts after the HTTPS hostname moves to the Pi, the casa-app@.socket/service templates relay ports 19999 (Netdata), 8111 (Crafty), 9443 (Portainer), and 8384 (Syncthing) to the same ports on CasServer. The sockets bind only to the Pi's Tailscale address AND tailscale0 interface, run unprivileged socket-proxy services on demand, and restart with tailscaled. App protocols/certificates pass through unchanged. These relays do not expose public listeners or replace the apps' own TLS certificates. Netdata and Syncthing were verified HTTP 200; Crafty's original TLS certificate was verified unchanged. The existing Portainer shortcut uses HTTP on port 9443 and returns HTTP 400 both directly and through the relay; its separate protocol configuration is unchanged.
