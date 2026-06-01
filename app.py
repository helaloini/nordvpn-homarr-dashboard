#!/usr/bin/env python3
"""
NordVPN Dashboard — A lightweight Flask web app that wraps the nordvpn CLI
and exposes a live status dashboard with connect/disconnect controls.

Designed to run on a Debian/Ubuntu machine (or LXC container) where the
NordVPN CLI is already installed and logged in.  Can be embedded as an
iFrame widget in Homarr or any other dashboard.
"""

import os
import subprocess
from flask import Flask, Response, jsonify, redirect, request

app = Flask(__name__)

# ──────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────
LISTEN_HOST = os.environ.get("VPN_DASH_HOST", "0.0.0.0")
LISTEN_PORT = int(os.environ.get("VPN_DASH_PORT", "8080"))
POLL_INTERVAL_MS = int(os.environ.get("VPN_DASH_POLL_MS", "8000"))

# systemd services don't set $HOME — nordvpn CLI needs it to find its
# config / socket.  We inject it explicitly into every subprocess call.
_NORDVPN_ENV = {**os.environ, "HOME": os.environ.get("HOME", "/root")}


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────

def run_nordvpn(*args: str, timeout: int = 30) -> str:
    """Execute a `nordvpn` CLI command and return its stdout."""
    try:
        result = subprocess.run(
            ["nordvpn", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_NORDVPN_ENV,
        )
        return result.stdout.strip() or result.stderr.strip()
    except subprocess.TimeoutExpired:
        return "Error: command timed out"
    except Exception as exc:
        return f"Error: {exc}"


def parse_status() -> dict:
    """Parse the output of `nordvpn status` into a structured dict."""
    raw = run_nordvpn("status")
    data: dict = {"raw": raw, "connected": False}

    for line in raw.splitlines():
        line = line.strip().lstrip("- ")
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()

        if key == "status":
            data["connected"] = value.lower() == "connected"
            data["status"] = value
        elif key == "hostname":
            data["hostname"] = value
        elif key == "ip":
            data["ip"] = value
        elif key == "country":
            data["country"] = value
        elif key == "city":
            data["city"] = value
        elif key in ("current_technology", "technology"):
            data["technology"] = value
        elif key in ("current_protocol", "protocol"):
            data["protocol"] = value
        elif key == "transfer":
            data["transfer"] = value
        elif key == "uptime":
            data["uptime"] = value

    return data


# ──────────────────────────────────────────────
#  JSON API
# ──────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    """Return NordVPN status as JSON."""
    return jsonify(parse_status())


@app.route("/api/connect", methods=["POST"])
def api_connect():
    """Connect to NordVPN.  Accepts optional ``{"country": "US"}`` body."""
    body = request.get_json(silent=True) or {}
    country = body.get("country", "")
    args = ["connect"]
    if country:
        args.append(country)
    output = run_nordvpn(*args, timeout=45)
    return jsonify({"output": output, **parse_status()})


@app.route("/api/disconnect", methods=["POST"])
def api_disconnect():
    """Disconnect from NordVPN."""
    output = run_nordvpn("disconnect")
    return jsonify({"output": output, **parse_status()})


# ──────────────────────────────────────────────
#  Dashboard UI
# ──────────────────────────────────────────────

@app.route("/")
def index():
    """Serve the dashboard page.

    Also handles ``?action=connect`` and ``?action=disconnect`` query
    parameters so that the buttons work even when embedded inside an
    iframe with an overlay that blocks JavaScript click events (e.g.
    Homarr dashboard widgets).
    """
    action = request.args.get("action", "").lower()
    if action == "connect":
        run_nordvpn("connect", timeout=45)
        return redirect("/")
    if action == "disconnect":
        run_nordvpn("disconnect")
        return redirect("/")
    return Response(HTML_PAGE.replace("{{POLL_INTERVAL}}", str(POLL_INTERVAL_MS)),
                    mimetype="text/html")


# ── Inline HTML/CSS/JS ──────────────────────────
# The entire frontend is served from this single string so that the
# project has zero external file dependencies.

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NordVPN Dashboard</title>
<meta name="description" content="Live NordVPN status monitor with connect and disconnect controls.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg:         #0b0e14;
    --surface:    #111620;
    --surface-2:  #181d28;
    --border:     rgba(255,255,255,.06);
    --text:       #e2e8f0;
    --text-dim:   #64748b;
    --accent:     #38bdf8;
    --green:      #22c55e;
    --green-glow: rgba(34,197,94,.25);
    --red:        #ef4444;
    --red-glow:   rgba(239,68,68,.25);
    --amber:      #f59e0b;
    --radius:     14px;
    --transition: .3s cubic-bezier(.4,0,.2,1);
  }

  body {
    font-family: 'Inter', -apple-system, system-ui, sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 16px;
    overflow: hidden;
  }

  /* ── Card ── */
  .card {
    width: 100%; max-width: 420px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 24px;
    position: relative;
    overflow: hidden;
  }
  .card::before {
    content: '';
    position: absolute; top: 0; left: 0; right: 0;
    height: 3px;
    background: linear-gradient(90deg, var(--accent), var(--green));
    opacity: .8;
    transition: background var(--transition);
  }
  .card.disconnected::before {
    background: linear-gradient(90deg, var(--red), var(--amber));
  }

  /* ── Header ── */
  .header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
  .header-left { display: flex; align-items: center; gap: 10px; }
  .logo {
    width: 32px; height: 32px; border-radius: 8px;
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
    background: linear-gradient(135deg, #1e40af, #3b82f6);
    flex-shrink: 0;
  }
  .header h1 { font-size: 15px; font-weight: 700; letter-spacing: -.3px; }

  /* ── Beacon ── */
  .beacon {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green-glow), 0 0 20px var(--green-glow);
    animation: pulse 2s ease-in-out infinite;
    flex-shrink: 0;
  }
  .beacon.off {
    background: var(--red);
    box-shadow: 0 0 8px var(--red-glow), 0 0 20px var(--red-glow);
    animation: pulse-red 2s ease-in-out infinite;
  }
  .beacon.loading {
    background: var(--amber);
    box-shadow: 0 0 8px rgba(245,158,11,.25);
    animation: blink 1s linear infinite;
  }
  @keyframes pulse     { 0%,100%{opacity:1;transform:scale(1)}  50%{opacity:.6;transform:scale(1.2)} }
  @keyframes pulse-red { 0%,100%{opacity:1;transform:scale(1)}  50%{opacity:.5;transform:scale(1.15)} }
  @keyframes blink     { 0%{opacity:.4} 50%{opacity:1} 100%{opacity:.4} }

  /* ── Status banner ── */
  .status-banner {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 16px;
    display: flex; align-items: center; gap: 12px;
    transition: border-color var(--transition);
  }
  .status-banner.connected  { border-color: rgba(34,197,94,.2); }
  .status-banner.disconnected { border-color: rgba(239,68,68,.15); }
  .status-text { font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; }
  .status-text.on  { color: var(--green); }
  .status-text.off { color: var(--red); }

  /* ── Detail grid ── */
  .details { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 20px; }
  .detail {
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px 14px;
    transition: transform var(--transition), border-color var(--transition);
  }
  .detail:hover { transform: translateY(-1px); border-color: rgba(255,255,255,.1); }
  .detail.full  { grid-column: 1 / -1; }
  .detail-label {
    font-size: 10px; font-weight: 600;
    text-transform: uppercase; letter-spacing: .8px;
    color: var(--text-dim); margin-bottom: 4px;
  }
  .detail-value { font-size: 13px; font-weight: 600; color: var(--text); word-break: break-all; }
  .detail-value.mono { font-family: 'JetBrains Mono','Fira Code',monospace; font-size: 12px; font-weight: 500; }

  /* ── Action buttons ── */
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .btn {
    font-family: 'Inter', sans-serif;
    font-size: 13px; font-weight: 600;
    padding: 12px 16px;
    border: none; border-radius: 10px;
    cursor: pointer;
    text-decoration: none;
    transition: all var(--transition);
    display: flex; align-items: center; justify-content: center; gap: 8px;
    letter-spacing: .2px;
  }
  .btn:active { transform: scale(.97); }
  .btn-connect {
    background: linear-gradient(135deg, #166534, #15803d);
    color: #bbf7d0;
    box-shadow: 0 2px 12px rgba(22,101,52,.3);
  }
  .btn-connect:hover { box-shadow: 0 4px 20px rgba(22,101,52,.5); transform: translateY(-1px); }
  .btn-disconnect {
    background: linear-gradient(135deg, #991b1b, #b91c1c);
    color: #fecaca;
    box-shadow: 0 2px 12px rgba(153,27,27,.3);
  }
  .btn-disconnect:hover { box-shadow: 0 4px 20px rgba(153,27,27,.5); transform: translateY(-1px); }
  .btn .icon { font-size: 16px; }

  /* ── Toast ── */
  .toast {
    position: fixed; bottom: 20px; left: 50%;
    transform: translateX(-50%) translateY(80px);
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 10px 20px;
    font-size: 12px; font-weight: 500; color: var(--text);
    opacity: 0;
    transition: all .4s cubic-bezier(.4,0,.2,1);
    pointer-events: none; z-index: 100;
    max-width: 90%; text-align: center;
  }
  .toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }

  /* ── Refresh progress bar ── */
  .refresh-bar {
    position: absolute; bottom: 0; left: 0;
    height: 2px; background: var(--accent); opacity: .5;
    animation: shrink 8s linear infinite;
    border-radius: 0 0 var(--radius) var(--radius);
  }
  @keyframes shrink { from{width:100%} to{width:0%} }

  /* ── Skeleton loader ── */
  .skeleton {
    background: linear-gradient(90deg, var(--surface-2) 25%, #1e2533 50%, var(--surface-2) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 6px; height: 16px;
  }
  @keyframes shimmer { from{background-position:200% 0} to{background-position:-200% 0} }
</style>
</head>
<body>

<div class="card" id="card">
  <div class="refresh-bar" id="refreshBar"></div>

  <div class="header">
    <div class="header-left">
      <div class="logo">🛡</div>
      <h1>NordVPN</h1>
    </div>
    <div class="beacon loading" id="beacon"></div>
  </div>

  <div class="status-banner" id="statusBanner">
    <span class="status-text" id="statusText">Checking…</span>
  </div>

  <div class="details" id="details">
    <div class="detail">
      <div class="detail-label">Server</div>
      <div class="detail-value" id="valServer"><div class="skeleton"></div></div>
    </div>
    <div class="detail">
      <div class="detail-label">IP Address</div>
      <div class="detail-value mono" id="valIP"><div class="skeleton"></div></div>
    </div>
    <div class="detail">
      <div class="detail-label">Country</div>
      <div class="detail-value" id="valCountry"><div class="skeleton"></div></div>
    </div>
    <div class="detail">
      <div class="detail-label">City</div>
      <div class="detail-value" id="valCity"><div class="skeleton"></div></div>
    </div>
    <div class="detail">
      <div class="detail-label">Protocol</div>
      <div class="detail-value" id="valProto"><div class="skeleton"></div></div>
    </div>
    <div class="detail">
      <div class="detail-label">Uptime</div>
      <div class="detail-value" id="valUptime"><div class="skeleton"></div></div>
    </div>
    <div class="detail full">
      <div class="detail-label">Transfer</div>
      <div class="detail-value mono" id="valTransfer"><div class="skeleton"></div></div>
    </div>
  </div>

  <div class="actions">
    <a class="btn btn-connect" id="btnConnect" href="/?action=connect">
      <span class="icon">⚡</span> Connect
    </a>
    <a class="btn btn-disconnect" id="btnDisconnect" href="/?action=disconnect">
      <span class="icon">✕</span> Disconnect
    </a>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
  const $ = id => document.getElementById(id);
  const POLL_INTERVAL = {{POLL_INTERVAL}};

  function render(data) {
    const on = data.connected;
    $('card').className        = 'card' + (on ? '' : ' disconnected');
    $('beacon').className      = 'beacon' + (on ? '' : ' off');
    $('statusBanner').className = 'status-banner ' + (on ? 'connected' : 'disconnected');
    const st = $('statusText');
    st.className   = 'status-text ' + (on ? 'on' : 'off');
    st.textContent = on ? '● Connected' : '○ Disconnected';

    const set = (id, val) => $(id).textContent = val || '—';
    set('valServer',   data.hostname);
    set('valIP',       data.ip);
    set('valCountry',  data.country);
    set('valCity',     data.city);
    set('valProto',    [data.technology, data.protocol].filter(Boolean).join(' / '));
    set('valUptime',   data.uptime);
    set('valTransfer', data.transfer);

    // restart the refresh-bar animation
    const bar = $('refreshBar');
    bar.style.animation = 'none';
    bar.offsetHeight;
    bar.style.animation = '';
  }

  function showToast(msg, ms = 3000) {
    const t = $('toast');
    t.textContent = msg;
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), ms);
  }

  async function fetchStatus() {
    try {
      const r = await fetch('/api/status');
      render(await r.json());
    } catch { showToast('⚠ Failed to fetch status'); }
  }

  fetchStatus();
  setInterval(fetchStatus, POLL_INTERVAL);
</script>
</body>
</html>
"""

# ──────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host=LISTEN_HOST, port=LISTEN_PORT)
