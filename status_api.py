"""=========================================================
DrCastiel Dashboard — status API (Flask blueprint)

What this does
- Provides /api/status JSON with Pi health + service status
- Uses only local reads + systemctl (no external calls)

Where to put it
- Easiest: drop into your Admin-Portal project and register blueprint
- Or create a tiny separate Flask app (recommended later)

Dependencies (recommended)
- psutil

Install:
  pip install psutil

Security notes
- This endpoint exposes system info. Keep it behind auth OR only serve
  on drcastiel.com (public is okay if you’re comfortable with it).
========================================================="""

from __future__ import annotations

import concurrent.futures
import os
import ssl
import time
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify

try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None  # type: ignore


bp = Blueprint("status_api", __name__)

PUBLIC_ENDPOINTS = [
    {"id": "dev", "name": "Crown Dev Site", "url": "https://dev.drcastiel.com"},
    {"id": "admin", "name": "Admin Portal", "url": "https://admin.drcastiel.com"},
    {"id": "home", "name": "DrCastiel Home", "url": "https://drcastiel.com"},
]


# ------------------------------
# Helpers
# ------------------------------

def _run(cmd: list[str]) -> str:
    """Run a command and return stdout (safe for systemctl show)."""
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=1.5)
        return out.strip()
    except Exception:
        return ""

def _systemctl_active_state(unit: str) -> Dict[str, Optional[str]]:
    """Return systemd ActiveState/SubState for a unit."""
    # systemctl show is stable for parsing
    out = _run(["systemctl", "show", unit, "--no-pager", "--property=ActiveState,SubState"])
    active = None
    sub = None
    for line in out.splitlines():
        if line.startswith("ActiveState="):
            active = line.split("=", 1)[1] or None
        elif line.startswith("SubState="):
            sub = line.split("=", 1)[1] or None
    return {"unit": unit, "active_state": active, "sub_state": sub}

def _uptime_seconds() -> Optional[float]:
    if psutil is None:
        return None
    try:
        return time.time() - psutil.boot_time()
    except Exception:
        return None

def _human_uptime(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    s = int(seconds)
    days, rem = divmod(s, 86400)
    hrs, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hrs}h {mins}m"
    if hrs > 0:
        return f"{hrs}h {mins}m"
    return f"{mins}m"

def _cpu_temp_c() -> Optional[float]:
    # Raspberry Pi typically exposes /sys/class/thermal/thermal_zone0/temp
    for p in (
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/thermal/thermal_zone1/temp",
    ):
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = f.read().strip()
            if raw.isdigit():
                return float(raw) / 1000.0
        except Exception:
            continue
    # psutil fallback (may work on some platforms)
    if psutil is not None:
        try:
            temps = psutil.sensors_temperatures()  # type: ignore[attr-defined]
            for _name, entries in temps.items():
                if entries:
                    return float(entries[0].current)
        except Exception:
            pass
    return None

def _load_1m() -> Optional[float]:
    try:
        return os.getloadavg()[0]
    except Exception:
        return None

def _mem_stats() -> Optional[Dict[str, Any]]:
    if psutil is None:
        return None
    try:
        vm = psutil.virtual_memory()
        return {
            "total_bytes": int(vm.total),
            "used_bytes": int(vm.used),
            "used_pct": float(vm.percent),
        }
    except Exception:
        return None

def _disk_stats(path: str = "/") -> Optional[Dict[str, Any]]:
    if psutil is None:
        try:
            du = shutil.disk_usage(path)
            used_pct = (du.used / du.total) * 100.0 if du.total else 0.0
            return {
                "total_bytes": int(du.total),
                "used_bytes": int(du.used),
                "used_pct": float(used_pct),
            }
        except Exception:
            return None
    try:
        du = psutil.disk_usage(path)
        return {
            "total_bytes": int(du.total),
            "used_bytes": int(du.used),
            "used_pct": float(du.percent),
        }
    except Exception:
        return None

def _net_io() -> Optional[Dict[str, Any]]:
    if psutil is None:
        return None
    try:
        io = psutil.net_io_counters()
        return {"tx_bytes": int(io.bytes_sent), "rx_bytes": int(io.bytes_recv)}
    except Exception:
        return None

def _health(mem: Optional[Dict[str, Any]], disk: Optional[Dict[str, Any]], temp_c: Optional[float]) -> str:
    """Very simple health heuristic."""
    score = 0
    # memory
    if mem and mem.get("used_pct") is not None:
        if mem["used_pct"] < 80: score += 1
        elif mem["used_pct"] < 90: score += 0
        else: score -= 1
    # disk
    if disk and disk.get("used_pct") is not None:
        if disk["used_pct"] < 80: score += 1
        elif disk["used_pct"] < 90: score += 0
        else: score -= 1
    # temp
    if temp_c is not None:
        if temp_c < 70: score += 1
        elif temp_c < 80: score += 0
        else: score -= 1

    if score >= 2:
        return "good"
    if score <= -1:
        return "bad"
    return "warn"

def _probe_http(url: str, timeout: float = 2.5) -> Dict[str, Any]:
    started = time.perf_counter()
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "DrCastielStatus/1.0"},
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            latency_ms = round((time.perf_counter() - started) * 1000)
            return {
                "ok": 200 <= status < 500,
                "http_status": status,
                "latency_ms": latency_ms,
                "error": None,
            }
    except urllib.error.HTTPError as err:
        latency_ms = round((time.perf_counter() - started) * 1000)
        status = int(getattr(err, "code", 0) or 0)
        return {
            "ok": 200 <= status < 500,
            "http_status": status or None,
            "latency_ms": latency_ms,
            "error": None,
        }
    except Exception as err:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "ok": False,
            "http_status": None,
            "latency_ms": latency_ms,
            "error": str(err),
        }

def _public_endpoint_status() -> list[Dict[str, Any]]:
    results_by_id: Dict[str, Dict[str, Any]] = {}

    def _check(endpoint: Dict[str, str]) -> tuple[str, Dict[str, Any]]:
        return endpoint["id"], _probe_http(endpoint["url"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(PUBLIC_ENDPOINTS), 4)) as pool:
        futures = [pool.submit(_check, endpoint) for endpoint in PUBLIC_ENDPOINTS]
        for future in concurrent.futures.as_completed(futures):
            endpoint_id, result = future.result()
            results_by_id[endpoint_id] = result

    ordered = []
    for endpoint in PUBLIC_ENDPOINTS:
        endpoint_result = results_by_id.get(endpoint["id"], {
            "ok": False,
            "http_status": None,
            "latency_ms": None,
            "error": "Probe failed",
        })
        ordered.append({
            "id": endpoint["id"],
            "name": endpoint["name"],
            "url": endpoint["url"],
            **endpoint_result,
        })
    return ordered


# ------------------------------
# Route
# ------------------------------

@bp.get("/api/status")
def api_status():
    uptime_s = _uptime_seconds()
    temp_c = _cpu_temp_c()
    mem = _mem_stats()
    disk = _disk_stats("/")
    net = _net_io()

    payload = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "public_endpoints": _public_endpoint_status(),
        "pi": {
            "uptime_seconds": uptime_s,
            "uptime_human": _human_uptime(uptime_s),
            "cpu_temp_c": temp_c,
            "load_1m": _load_1m(),
            "mem": mem,
            "disk": disk,
            "net": net,
            "health": _health(mem, disk, temp_c),
        },
        "services": {
            # Change unit names if yours differ:
            "cloudflared": _systemctl_active_state("cloudflared.service"),
            "gunicorn": _systemctl_active_state("crown-admin.service"),
            "nginx": _systemctl_active_state("nginx.service"),
        },
    }
    return jsonify(payload)
