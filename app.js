/* =========================================================
   DrCastiel Dashboard — client logic
   - Pings /api/status (same origin)
   - Optionally checks public URLs
   ========================================================= */

const CONFIG = {
  refreshMs: 15000,
  // "Services" are the cards you want to see uptime/latency for.
  // If you keep the /api/status API running, you can also show local unit status.
  services: [
    { id: "dev",   name: "Crown Dev Site",   url: "https://dev.drcastiel.com" },
    { id: "admin", name: "Admin Portal",     url: "https://admin.drcastiel.com" },
    { id: "home",  name: "DrCastiel Home",   url: "https://drcastiel.com" }
  ],
  // "Projects" are pinned links (not necessarily uptime-checked).
  projects: [
    { name: "Crown Graphics", desc: "Static site + quick-order forms", url: "https://dev.drcastiel.com" },
    { name: "Crown Admin Portal", desc: "Jobs + order intake + PDFs", url: "https://admin.drcastiel.com" },
    { name: "Crown-Webpage Repo", desc: "GitHub repository", url: "https://github.com/DrCas/Crown-Webpage" },
    { name: "MTGValueBot", desc: "Discord bot + pricing alerts", url: "#" },
    { name: "HaulAds", desc: "Trailer wrap advertising startup", url: "#" },
    { name: "Adventure Map Game", desc: "Unity GPS exploration concept", url: "#" }
  ]
};

// Health thresholds for progress bars and metrics
const THRESHOLDS = {
  uptime: { good: 95, warn: 90 },      // % uptime
  temp: { good: 70, warn: 80 },        // °C
  load: { good: 0.8, warn: 1.2 },      // factor of cpu_count
  memory: { good: 80, warn: 90 },      // % used
  disk: { good: 80, warn: 90 },        // % used
};

function el(id){ return document.getElementById(id); }
function clamp(n, min, max){ return Math.min(max, Math.max(min, n)); }

function fmtBytes(n){
  if (n == null) return "—";
  const units = ["B","KB","MB","GB","TB"];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < units.length-1){ v/=1024; i++; }
  return `${v.toFixed(i===0?0:1)} ${units[i]}`;
}

function fmtPct(n){ return (n == null) ? "—" : `${Math.round(n)}%`; }

// Determine color class based on value and thresholds
function colorForMetric(value, threshold){
  if (value == null) return "";
  if (value >= threshold.warn) return "bad";
  if (value >= threshold.good) return "warn";
  return "good";
}

function badgeFromHealth(h){
  const t = (h || "unknown").toLowerCase();
  if (t === "good") return { text:"GOOD", cls:"good" };
  if (t === "warn") return { text:"WARN", cls:"warn" };
  if (t === "bad")  return { text:"BAD",  cls:"bad" };
  return { text:"—", cls:"" };
}

function badgeForEndpoint(endpoint){
  if (!endpoint) return { text: "—", cls: "" };
  if (endpoint.ok) return { text: "UP", cls: "good" };
  return { text: "DOWN", cls: "bad" };
}

function statusApiCandidates(){
  return [
    "/api/status",
    new URL("api/status", window.location.href).href,
  ];
}

async function fetchStatusApi(){
  let lastError = null;
  for (const url of statusApiCandidates()){
    try{
      const res = await fetch(url, { cache: "no-store" });
      if (res.ok) return res;
      lastError = new Error(`Status API ${url} returned ${res.status}`);
    }catch(e){
      lastError = e;
    }
  }
  throw lastError;
}

async function pingUrl(url){
  const t0 = performance.now();
  try{
    // no-cors means we can't read status, but timing still tells us "reachable-ish".
    // If you want strict HTTP status, set up a server-side probe in /api/status.
    await fetch(url, { method: "GET", mode: "no-cors", cache: "no-store" });
    const ms = Math.round(performance.now() - t0);
    return { ok: true, ms };
  }catch(e){
    return { ok: false, ms: null };
  }
}

function renderServices(){
  const host = el("serviceCards");
  host.innerHTML = "";
  for (const s of CONFIG.services){
    const card = document.createElement("div");
    card.className = "card span-4";
    card.innerHTML = `
      <div class="card-head">
        <div>
          <div class="card-title">${s.name}</div>
          <div class="card-subtitle">${s.url}</div>
        </div>
        <span id="badge-${s.id}" class="badge">—</span>
      </div>
      <div class="grid" style="grid-template-columns:repeat(2,1fr); gap:12px;">
        <div class="metric">
          <div class="label">Reachable</div>
          <div id="reach-${s.id}" class="value mono">—</div>
        </div>
        <div class="metric">
          <div class="label">Latency</div>
          <div id="lat-${s.id}" class="value mono">—</div>
        </div>
        <div class="metric" style="grid-column:1 / -1;">
          <div class="label">30d Uptime (15m samples)</div>
          <div class="progress"><span id="uptimebar-${s.id}" class="progress-fill"></span></div>
        </div>
      </div>
      <div class="service-footer">
        <a class="pill" href="${s.url}" target="_blank" rel="noreferrer">Open</a>
        <span id="uptime-inline-${s.id}" class="uptime-inline mono">—</span>
      </div>
    `;
    host.appendChild(card);
  }
}

function renderProjects(){
  const host = el("projectCards");
  host.innerHTML = "";
  for (const p of CONFIG.projects){
    const card = document.createElement("a");
    card.className = "card link span-4";
    card.href = p.url;
    if (p.url && p.url !== "#"){
      card.target = "_blank";
      card.rel = "noreferrer";
    }
    card.innerHTML = `
      <div class="card-title">${p.name}</div>
      <div class="card-subtitle">${p.desc || ""}</div>
    `;
    host.appendChild(card);
  }
}

function setText(id, txt){ const node = el(id); if (node) node.textContent = txt; }

function setProgress(id, pct, colorClass){
  const node = el(id);
  if (!node) return;
  const width = Number.isFinite(pct) ? clamp(pct, 0, 100) : 0;
  node.style.width = `${width.toFixed(0)}%`;
  // Remove existing color classes and apply new one
  node.classList.remove("good", "warn", "bad");
  if (colorClass) node.classList.add(colorClass);
}

function setBadge(node, txt, cls){
  if (!node) return;
  node.textContent = txt;
  node.classList.remove("good","warn","bad");
  if (cls) node.classList.add(cls);
}

function renderServiceStatusFromApi(data){
  const endpointList = data?.public_endpoints;
  if (!Array.isArray(endpointList)) return false;

  const endpointById = Object.fromEntries(endpointList.map((item) => [item.id, item]));
  for (const service of CONFIG.services){
    const endpoint = endpointById[service.id];
    if (!endpoint) continue;

    setText(`reach-${service.id}`, endpoint.ok ? "yes" : "no");
    setText(`lat-${service.id}`, endpoint.latency_ms != null ? `${endpoint.latency_ms} ms` : "—");
    
    // 30d Uptime with color-coded progress bar
    const uptime = endpoint.uptime_30d_pct;
    setText(`uptime-inline-${service.id}`, typeof uptime === "number" ? `${uptime.toFixed(1)}%` : "—");
    if (typeof uptime === "number") {
      const color = colorForMetric(uptime, THRESHOLDS.uptime);
      setProgress(`uptimebar-${service.id}`, uptime, color);
    } else {
      setProgress(`uptimebar-${service.id}`, null);
    }

    const badge = badgeForEndpoint(endpoint);
    setBadge(el(`badge-${service.id}`), badge.text, badge.cls);
  }

  return true;
}

function renderPi(data){
  // Basic fields (API may return nulls)
  setText("piUptime", data?.pi?.uptime_human ?? "—");
  const uptimeSeconds = data?.pi?.uptime_seconds;
  const piUptimePct = Number.isFinite(uptimeSeconds)
    ? Math.min((Number(uptimeSeconds) / (30 * 24 * 60 * 60)) * 100, 100)
    : null;
  setProgress("meterPiUptime", piUptimePct);
  setText("piUptimePct", Number.isFinite(piUptimePct) ? `${piUptimePct.toFixed(2)}% / 30d` : "—");

  // CPU Temperature with color-coded bar
  const tempC = data?.pi?.cpu_temp_c;
  setText("cpuTemp", tempC != null ? `${tempC.toFixed(1)}°C` : "—");
  if (tempC != null) {
    const tempPct = (tempC / 85) * 100;
    const tempColor = colorForMetric(tempC, THRESHOLDS.temp);
    setProgress("meterCpuTemp", tempPct, tempColor);
  } else {
    setProgress("meterCpuTemp", null);
  }

  // CPU Load with color-coded bar
  const load = data?.pi?.load_1m;
  const cpuCount = data?.pi?.cpu_count ?? null;
  setText("cpuLoad", load != null ? `${load.toFixed(2)} (1m)` : "—");
  if (load != null && cpuCount) {
    const loadPct = (load / cpuCount) * 100;
    const loadColor = colorForMetric(load, THRESHOLDS.load);
    setProgress("meterCpuLoad", loadPct, loadColor);
  } else {
    setProgress("meterCpuLoad", null);
  }

  // Memory with color-coded bar
  if (data?.pi?.mem) {
    const memPct = data.pi.mem.used_pct;
    setText("mem", `${fmtPct(memPct)} • ${fmtBytes(data.pi.mem.used_bytes)} / ${fmtBytes(data.pi.mem.total_bytes)}`);
    const memColor = colorForMetric(memPct, THRESHOLDS.memory);
    setProgress("meterMem", memPct, memColor);
  } else {
    setText("mem", "—");
    setProgress("meterMem", null);
  }

  // Disk with color-coded bar
  if (data?.pi?.disk) {
    const diskPct = data.pi.disk.used_pct;
    setText("disk", `${fmtPct(diskPct)} • ${fmtBytes(data.pi.disk.used_bytes)} / ${fmtBytes(data.pi.disk.total_bytes)}`);
    const diskColor = colorForMetric(diskPct, THRESHOLDS.disk);
    setProgress("meterDisk", diskPct, diskColor);
  } else {
    setText("disk", "—");
    setProgress("meterDisk", null);
  }

  if (data?.pi?.net){
    setText("net", `↑ ${fmtBytes(data.pi.net.tx_bytes)} • ↓ ${fmtBytes(data.pi.net.rx_bytes)}`);
  }else setText("net", "—");

  // Service units (optional)
  setText("svcCloudflared", data?.services?.cloudflared?.active_state ?? "—");
  setText("svcGunicorn",    data?.services?.gunicorn?.active_state ?? "—");
  setText("svcNginx",       data?.services?.nginx?.active_state ?? "—");

  // Health badge
  const b = badgeFromHealth(data?.pi?.health);
  setBadge(el("piBadge"), b.text, b.cls);

  // Updated time
  const ts = data?.ts ? new Date(data.ts) : new Date();
  setText("lastUpdated", `Updated ${ts.toLocaleTimeString()}`);
}

async function refresh(){
  const refreshBtn = el("refreshBtn");
  if (refreshBtn) {
    refreshBtn.disabled = true;
    refreshBtn.textContent = "Refreshing…";
  }

  // Pull server-side status first (preferred)
  let renderedFromApi = false;
  try{
    const res = await fetchStatusApi();
    const data = await res.json();
    renderPi(data);
    renderedFromApi = renderServiceStatusFromApi(data);
  }catch(e){
    console.warn("Status API fetch failed:", e);
    setText("lastUpdated", "API unavailable");
    renderPi(null);
  }

  // Fallback to browser pings if API endpoint probes are unavailable.
  if (!renderedFromApi){
    await Promise.all(CONFIG.services.map(async (service) => {
      const result = await pingUrl(service.url);
      setText(`reach-${service.id}`, result.ok ? "yes" : "no");
      setText(`lat-${service.id}`, result.ms != null ? `${result.ms} ms` : "—");
      setText(`uptime-inline-${service.id}`, "—");
      setProgress(`uptimebar-${service.id}`, null);
      const badge = el(`badge-${service.id}`);
      if (result.ok) setBadge(badge, "UP", "good");
      else setBadge(badge, "DOWN", "bad");
    }));
  }

  if (refreshBtn) {
    refreshBtn.disabled = false;
    refreshBtn.textContent = "Refresh";
  }
}

function boot(){
  renderServices();
  renderProjects();
  
  // Refresh button
  const refreshBtn = el("refreshBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", refresh);
    refreshBtn.title = "Click to manually refresh data";
  }
  
  // Initial load and auto-refresh
  refresh();
  setInterval(refresh, CONFIG.refreshMs);
}

boot();
