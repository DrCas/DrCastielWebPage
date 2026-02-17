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

function el(id){ return document.getElementById(id); }
function fmtBytes(n){
  if (n == null) return "—";
  const units = ["B","KB","MB","GB","TB"];
  let i = 0, v = Number(n);
  while (v >= 1024 && i < units.length-1){ v/=1024; i++; }
  return `${v.toFixed(i===0?0:1)} ${units[i]}`;
}
function fmtPct(n){ return (n == null) ? "—" : `${Math.round(n)}%`; }

function badgeFromHealth(h){
  const t = (h || "unknown").toLowerCase();
  if (t === "good") return { text:"GOOD", cls:"good" };
  if (t === "warn") return { text:"WARN", cls:"warn" };
  if (t === "bad")  return { text:"BAD",  cls:"bad" };
  return { text:"—", cls:"" };
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
      </div>
      <div style="margin-top:12px;">
        <a class="pill" href="${s.url}" target="_blank" rel="noreferrer">Open</a>
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
function setHtml(id, html){ const node = el(id); if (node) node.innerHTML = html; }
function setBadge(node, txt, cls){
  if (!node) return;
  node.textContent = txt;
  node.classList.remove("good","warn","bad");
  if (cls) node.classList.add(cls);
}

function renderPi(data){
  // Basic fields (API may return nulls)
  setText("piUptime", data?.pi?.uptime_human ?? "—");
  setText("cpuTemp",  data?.pi?.cpu_temp_c != null ? `${data.pi.cpu_temp_c.toFixed(1)}°C` : "—");
  setText("cpuLoad",  data?.pi?.load_1m != null ? `${data.pi.load_1m.toFixed(2)} (1m)` : "—");
  if (data?.pi?.mem){
    setText("mem", `${fmtPct(data.pi.mem.used_pct)} • ${fmtBytes(data.pi.mem.used_bytes)} / ${fmtBytes(data.pi.mem.total_bytes)}`);
  }else setText("mem", "—");
  if (data?.pi?.disk){
    setText("disk", `${fmtPct(data.pi.disk.used_pct)} • ${fmtBytes(data.pi.disk.used_bytes)} / ${fmtBytes(data.pi.disk.total_bytes)}`);
  }else setText("disk", "—");
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
  // 1) Render URL pings
  await Promise.all(CONFIG.services.map(async (s) => {
    const r = await pingUrl(s.url);
    setText(`reach-${s.id}`, r.ok ? "yes" : "no");
    setText(`lat-${s.id}`, r.ms != null ? `${r.ms} ms` : "—");
    const badge = el(`badge-${s.id}`);
    if (r.ok) setBadge(badge, "UP", "good");
    else setBadge(badge, "DOWN", "bad");
  }));

  // 2) Pull server-side status (preferred)
  try{
    const res = await fetch("/api/status", { cache: "no-store" });
    if (res.ok){
      const data = await res.json();
      renderPi(data);
    }else{
      renderPi(null);
    }
  }catch(e){
    renderPi(null);
  }
}

function boot(){
  renderServices();
  renderProjects();
  el("refreshBtn")?.addEventListener("click", refresh);
  refresh();
  setInterval(refresh, CONFIG.refreshMs);
}

boot();
