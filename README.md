# DrCastiel dashboard

A Flask dashboard with Overview, Servers, Domains, and Projects pages.

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

Checks: python -m unittest -v test_dashboard test_servers; node --check app.js; node --check servers.js

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

CasaOS launches apps using the current hostname and their original ports. The casa-app@.socket/service templates relay ports 19999 (Netdata), 9443 (Portainer), and 8384 (Syncthing) to CasServer. These sockets bind to the Pi Tailscale address and tailscale0 only. Crafty on port 8111 instead uses a second TLS server block in the dedicated gateway, with the same trusted public certificate and verified upstream TLS. Its original self-signed origin certificate is pinned at /etc/drcastiel/crafty-origin.pem and its hostname is explicitly validated. If Crafty regenerates that certificate, verify and update the pin and hostname in both the gateway and management configuration before reconnecting; never disable TLS verification. The old casa-app@8111.socket must remain disabled. Preserve $http_host including :8111 when proxying, otherwise Crafty rejects its WebSocket origin. Browser authentication and HTTP 101 were verified. Portainer's existing HTTP shortcut on its HTTPS port remains a separate existing protocol issue.

## Minecraft server management

/servers automatically discovers the servers visible to the dedicated Crafty API key. Each server has status, players, CPU/memory, basic details, recent console output, and start/stop/restart controls. New servers are created in Crafty and appear on the next 10-second poll. Console output polls every 3 seconds, displays only the last 300 lines as plain text, and accepts individual game console commands. No game servers were created during deployment.

All /api/servers routes require a cryptographically verified Cloudflare Access application JWT: fixed team issuer/JWKS URL, RS256 signatures, application audience, expiration, and owner email allowlist. POSTs additionally require an allowed same-site Origin, a JWT-bound HMAC CSRF token, and a unique request ID. Controls allow only start_server, stop_server, restart_server, or Minecraft stdin. Request IDs and brief action metadata are recorded in a separate SQLite database, with cooldowns and duplicate protection. Command contents and credentials are not logged. Responses are private and non-cacheable.

The approved Crafty key has COMMANDS, TERMINAL, and LOGS permissions only, without Full Access. It lives root-only at /etc/drcastiel/crafty-token. Root-only /etc/drcastiel/management.json contains issuer, audiences, owners, origins, csrf_secret, crafty_url, crafty_ca, crafty_hostname, crafty_token, and audit_db. Compose mounts this configuration, the key, and the pinned public certificate read-only at /run/secrets/{management.json,crafty-token,crafty-origin.pem}. The writable audit directory is /var/lib/drcastiel-management mounted at /management; it is separate from the read-only monitoring volume. No key, CSRF secret, Access token, or owner configuration belongs in Git or the Docker build context.

Deployment backup: /mnt/ssd/docker/web-stack/backups/minecraft-20261023-203331/compose.yml; previous image drcastiel-dashboard:before-minecraft. Restore that Compose file and retag the previous image to web-stack-www-site to roll back only www-site with --no-build. The prior deployed source is recoverable from the previous image or Git commit ff447fc. Gateway backup: /etc/drcastiel/casa-nginx.before-crafty.conf (restoring passthrough also requires disabling the 8111 TLS listener before re-enabling its socket).

Validation: 13 automated tests cover existing dashboard behavior, owner/signature/audience/expiry enforcement, CSRF, action allowlists, duplicate prevention, server discovery, console handling, and missing servers. Live validation confirmed verified upstream TLS, a real empty Crafty inventory, successful owner access, HTTP 401 without an Access JWT, and healthy existing containers. Start/stop/restart and stdin use mocked Crafty responses in tests; they still need an end-to-end check once the first real Minecraft server exists.
