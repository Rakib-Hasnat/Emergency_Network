from flask import Flask, request, jsonify, render_template_string, send_from_directory, make_response
import os
import io
import csv
import json
import time
import urllib.request
import urllib.error
from datetime import datetime

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
TEXT_FILE    = os.path.join(UPLOAD_FOLDER, "alerts.txt")
COMMENT_FILE = os.path.join(UPLOAD_FOLDER, "comments.json")

alerts   = []
comments = {}   # { alert_id: [ {ip, text, timestamp} ] }

# ── Battery data ─────────────────────────────────────────────────
# { "1": {node, voltage, percent, timestamp} }
battery_data = {}

# ── Heartbeat data ───────────────────────────────────────────────
# { "1": {node, ssid, ip, last_seen_ts, last_seen} }
# last_seen_ts is time.time() for age calculation
heartbeat_data = {}
HEARTBEAT_TIMEOUT = 90   # seconds — node marked offline after this

# ── Load alerts ──────────────────────────────────────────────────
if os.path.exists(TEXT_FILE):
    with open(TEXT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|", 4)
            if len(parts) >= 3:
                alerts.append({
                    "id":             parts[3] if len(parts) > 3 else "unknown",
                    "ip":             parts[0],
                    "message":        parts[1],
                    "image_filename": parts[2] if parts[2] != "None" else None,
                    "timestamp":      parts[3] if len(parts) > 3 else "Unknown",
                    "severity":       parts[4].split(",")[0] if len(parts) > 4 else "INFO",
                    "action":         parts[4].split(",", 1)[1] if len(parts) > 4 and "," in parts[4] else "Monitor situation",
                })

# ── Load comments ─────────────────────────────────────────────────
if os.path.exists(COMMENT_FILE):
    with open(COMMENT_FILE, "r", encoding="utf-8") as f:
        try:
            comments = json.load(f)
        except Exception:
            comments = {}

def save_comments():
    with open(COMMENT_FILE, "w", encoding="utf-8") as f:
        json.dump(comments, f, ensure_ascii=False)

# ── Offline classifier ────────────────────────────────────────────
def classify_alert(message):
    msg = message.lower()
    critical_keywords = [
        'fire','flood','earthquake','injury','injured','dead','dying',
        'trapped','help','emergency','collapse','collapsed','bleeding',
        'unconscious','attack','explosion','explode','drowning','drown',
        'crash','crushed','buried','murder','rescue','mayday','critical','severe',
        'urgent','sos','danger'
    ]
    moderate_keywords = [
        'damage','damaged','broken','missing','sick','pain','stuck',
        'need','water','food','medical','wound','hurt','risky','lost','stranded',
        'shelter','medicine','supply','supplies','hungry','thirsty',
        'cold','hot','leak','watchout','leaking','power','electricity'
    ]
    for w in critical_keywords:
        if w in msg:
            return 'CRITICAL', 'Immediate response required — contact emergency services now'
    for w in moderate_keywords:
        if w in msg:
            return 'MODERATE', 'Situation needs attention — dispatch assistance team'
    return 'INFO', 'Monitor situation and stay alert'


HTML_PAGE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EMER·NET — Emergency Alert Network</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap" rel="stylesheet">
<style>
:root {
  --bg:          #f5f3ee;
  --bg2:         #ffffff;
  --bg3:         #eeeae2;
  --border:      #ddd8cc;
  --red:         #e8220a;
  --red-light:   #fff0ee;
  --red-mid:     #ffd5d0;
  --orange:      #f07000;
  --orange-light:#fff5e6;
  --orange-mid:  #ffddb3;
  --green:       #00a854;
  --green-light: #e6fff2;
  --green-mid:   #b3f0d4;
  --blue:        #0066ff;
  --text:        #1c1a14;
  --text2:       #5a5648;
  --text3:       #9a9488;
  --sans:        'DM Sans', sans-serif;
  --display:     'Syne', sans-serif;
  --radius:      16px;
  --radius-sm:   10px;
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  min-height: 100vh;
}

/* HEADER */
header {
  position: sticky; top: 0; z-index: 200;
  background: var(--bg2);
  border-bottom: 1.5px solid var(--border);
  height: 64px;
  display: flex; align-items: center;
  justify-content: space-between;
  padding: 0 28px; gap: 16px;
}

.logo {
  font-family: var(--display); font-weight: 800; font-size: 1.25rem;
  color: var(--red); display: flex; align-items: center; gap: 10px; flex-shrink: 0;
}

.logo-icon {
  width: 32px; height: 32px; background: var(--red);
  border-radius: 8px; display: flex; align-items: center;
  justify-content: center; color: white; font-size: 1rem;
  animation: pulse-icon 2s ease-in-out infinite;
}

@keyframes pulse-icon {
  0%,100% { box-shadow: 0 0 0 0 rgba(232,34,10,0.4); }
  50%      { box-shadow: 0 0 0 8px rgba(232,34,10,0); }
}

.header-stats { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.stat-chip {
  display: flex; align-items: center; gap: 5px;
  padding: 5px 12px; border-radius: 999px;
  font-family: var(--display); font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.05em; border: 1.5px solid;
}

.stat-chip.live  { background:#e6fff2; border-color:#00c864; color:var(--green); }
.stat-chip.crit  { background:var(--red-light); border-color:var(--red-mid); color:var(--red); }
.stat-chip.mod   { background:var(--orange-light); border-color:var(--orange-mid); color:var(--orange); }
.stat-chip.infoc { background:var(--green-light); border-color:var(--green-mid); color:var(--green); }

.live-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--green);
  animation: blink 1.4s step-end infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }

.header-clock { font-family:var(--display); font-size:0.8rem; font-weight:600; color:var(--text3); flex-shrink:0; }

/* FEED */
.feed { max-width: 720px; margin: 0 auto; padding: 28px 20px 140px; display: flex; flex-direction: column; gap: 16px; }

.feed-header { display:flex; align-items:center; justify-content:space-between; margin-bottom:4px; }
.feed-title  { font-family:var(--display); font-weight:800; font-size:1.5rem; }
.feed-sub    { font-size:0.82rem; color:var(--text3); margin-top:2px; }

.header-actions { display:flex; gap:8px; }

.btn-refresh {
  background:var(--bg2); border:1.5px solid var(--border); border-radius:var(--radius-sm);
  padding:8px 16px; font-family:var(--display); font-weight:700; font-size:0.75rem;
  color:var(--text2); cursor:pointer; transition:all 0.18s; letter-spacing:0.04em;
}
.btn-refresh:hover { border-color:var(--red); color:var(--red); background:var(--red-light); }

.btn-export {
  background:var(--bg2); border:1.5px solid var(--border); border-radius:var(--radius-sm);
  padding:8px 16px; font-family:var(--display); font-weight:700; font-size:0.75rem;
  color:var(--text2); cursor:pointer; transition:all 0.18s; letter-spacing:0.04em;
  text-decoration:none; display:flex; align-items:center; gap:5px;
}
.btn-export:hover { border-color:var(--green); color:var(--green); background:var(--green-light); }

/* NODE STATUS PANEL */
.node-panel {
  background: var(--bg2); border: 1.5px solid var(--border);
  border-radius: var(--radius); padding: 18px 20px;
}
.panel-title {
  font-family: var(--display); font-weight: 800; font-size: 0.85rem;
  letter-spacing: 0.06em; color: var(--text2); margin-bottom: 14px;
  display: flex; align-items: center; gap: 8px;
}
.node-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
}
.node-card {
  border: 1.5px solid var(--border); border-radius: var(--radius-sm);
  padding: 12px 14px; text-align: center; transition: all 0.3s;
}
.node-card.online  { border-color: var(--green-mid); background: var(--green-light); }
.node-card.offline { border-color: var(--red-mid);   background: var(--red-light); }
.node-card.unknown { border-color: var(--border);    background: var(--bg3); }

.node-id    { font-family:var(--display); font-weight:800; font-size:1rem; margin-bottom:4px; }
.node-card.online  .node-id { color: var(--green); }
.node-card.offline .node-id { color: var(--red); }
.node-card.unknown .node-id { color: var(--text3); }

.node-status-label {
  font-family:var(--display); font-weight:700; font-size:0.65rem;
  letter-spacing:0.1em; padding:2px 8px; border-radius:999px; display:inline-block;
}
.node-card.online  .node-status-label { background:var(--green-mid); color:var(--green); }
.node-card.offline .node-status-label { background:var(--red-mid);   color:var(--red); }
.node-card.unknown .node-status-label { background:var(--border);    color:var(--text3); }

.node-ssid  { font-size:0.65rem; color:var(--text3); margin-top:5px; word-break:break-all; }
.node-age   { font-size:0.62rem; color:var(--text3); margin-top:3px; }

/* BATTERY PANEL */
.batt-panel {
  background: var(--bg2); border: 1.5px solid var(--border);
  border-radius: var(--radius); padding: 18px 20px;
}
.batt-row {
  display: flex; align-items: center; gap: 12px; margin-bottom: 10px;
}
.batt-row:last-child { margin-bottom: 0; }
.batt-node-label {
  font-family: var(--display); font-weight: 700; font-size: 0.75rem;
  color: var(--text3); width: 56px; flex-shrink: 0;
}
.batt-bar-wrap {
  flex: 1; background: var(--bg3); border-radius: 999px; height: 10px; overflow: hidden;
}
.batt-bar { height: 100%; border-radius: 999px; transition: width 0.6s ease, background 0.4s; }
.batt-pct  {
  font-family: var(--display); font-weight: 700; font-size: 0.72rem;
  width: 44px; text-align: right; flex-shrink: 0;
}
.batt-volt { font-size: 0.68rem; color: var(--text3); width: 44px; flex-shrink: 0; }
.batt-time { font-size: 0.62rem; color: var(--text3); }
.batt-offline { font-size: 0.78rem; color: var(--text3); font-style: italic; }

/* ALERT CARD */
.alert-card {
  background: var(--bg2); border: 1.5px solid var(--border);
  border-radius: var(--radius); overflow: hidden;
  animation: slideUp 0.3s cubic-bezier(.22,.68,0,1.2);
  transition: box-shadow 0.2s, transform 0.2s;
}
.alert-card:hover { box-shadow:0 8px 32px rgba(0,0,0,0.08); transform:translateY(-1px); }

@keyframes slideUp { from{opacity:0;transform:translateY(18px)} to{opacity:1;transform:translateY(0)} }

.card-stripe { height:5px; width:100%; }
.card-stripe.CRITICAL { background:linear-gradient(90deg,var(--red),#ff6b4a); }
.card-stripe.MODERATE { background:linear-gradient(90deg,var(--orange),#ffb347); }
.card-stripe.INFO     { background:linear-gradient(90deg,var(--green),#7fff9e); }

.card-body { padding:18px 20px 14px; }

.card-meta { display:flex; align-items:center; gap:8px; margin-bottom:12px; flex-wrap:wrap; }

.sev-badge { font-family:var(--display); font-weight:700; font-size:0.65rem; letter-spacing:0.1em; padding:3px 10px; border-radius:999px; }
.sev-badge.CRITICAL { background:var(--red-light); color:var(--red); border:1.5px solid var(--red-mid); }
.sev-badge.MODERATE { background:var(--orange-light); color:var(--orange); border:1.5px solid var(--orange-mid); }
.sev-badge.INFO     { background:var(--green-light); color:var(--green); border:1.5px solid var(--green-mid); }

.card-seq  { font-family:var(--display); font-weight:700; font-size:0.68rem; color:var(--text3); }
.card-ip   { font-size:0.7rem; color:var(--text3); background:var(--bg3); padding:2px 8px; border-radius:6px; }
.card-time { font-size:0.68rem; color:var(--text3); margin-left:auto; }

.card-msg  { font-size:1rem; line-height:1.6; color:var(--text); margin-bottom:12px; word-break:break-word; }

.card-action {
  display:flex; align-items:center; gap:6px; font-size:0.75rem; font-weight:500;
  padding:8px 12px; border-radius:var(--radius-sm); margin-bottom:14px;
}
.card-action.CRITICAL { background:var(--red-light); color:var(--red); }
.card-action.MODERATE { background:var(--orange-light); color:var(--orange); }
.card-action.INFO     { background:var(--green-light); color:var(--green); }

.card-img {
  width:100%; max-height:260px; object-fit:cover;
  border-radius:var(--radius-sm); margin-bottom:14px; border:1.5px solid var(--border); display:block;
}

/* AI ADVICE BOX */
.ai-advice-wrap { border-top:1.5px solid var(--bg3); padding:12px 20px 16px; background:var(--bg); }
.btn-ai {
  display:flex; align-items:center; gap:6px;
  background:var(--bg2); border:1.5px solid var(--border);
  border-radius:var(--radius-sm); padding:7px 14px;
  font-family:var(--display); font-weight:700; font-size:0.72rem;
  color:var(--text2); cursor:pointer; transition:all 0.18s; letter-spacing:0.04em;
  margin-bottom:10px;
}
.btn-ai:hover { border-color:#0066ff; color:#0066ff; background:#e8f0ff; }
.btn-ai:disabled { opacity:0.5; cursor:not-allowed; }
.ai-box {
  display:none; background:#e8f0ff; border:1.5px solid #b3ccff;
  border-radius:var(--radius-sm); padding:12px 14px;
}
.ai-box.visible { display:block; animation:slideUp 0.25s ease; }
.ai-box-label {
  font-family:var(--display); font-weight:700; font-size:0.65rem;
  letter-spacing:0.1em; color:#0066ff; margin-bottom:6px;
  display:flex; align-items:center; gap:5px;
}
.ai-box-text { font-size:0.85rem; line-height:1.6; color:var(--text); }
.ai-spinner { display:inline-block; width:12px; height:12px; border:2px solid #b3ccff; border-top-color:#0066ff; border-radius:50%; animation:ai-spin 0.7s linear infinite; }
@keyframes ai-spin { to { transform:rotate(360deg); } }

/* COMMENTS */
.comments-section { border-top:1.5px solid var(--bg3); padding:14px 20px 18px; background:var(--bg); }
.comments-title   { font-family:var(--display); font-weight:700; font-size:0.72rem; color:var(--text3); letter-spacing:0.06em; margin-bottom:10px; }
.comment-list     { display:flex; flex-direction:column; gap:8px; margin-bottom:10px; }

.comment-item { background:var(--bg2); border:1.5px solid var(--border); border-radius:var(--radius-sm); padding:8px 12px; animation:slideUp 0.2s ease; }
.comment-meta { display:flex; gap:8px; align-items:center; margin-bottom:3px; }
.comment-ip   { font-size:0.65rem; color:var(--text3); background:var(--bg3); padding:1px 6px; border-radius:5px; }
.comment-time { font-size:0.62rem; color:var(--text3); }
.comment-text { font-size:0.85rem; color:var(--text); line-height:1.5; }

.comment-input-row { display:flex; gap:8px; align-items:center; }
.comment-input {
  flex:1; background:var(--bg2); border:1.5px solid var(--border);
  border-radius:var(--radius-sm); padding:8px 12px;
  font-family:var(--sans); font-size:0.85rem; color:var(--text); outline:none; transition:border-color 0.2s;
}
.comment-input:focus { border-color:var(--blue); }
.comment-input::placeholder { color:var(--text3); }

.btn-comment {
  background:var(--text); border:none; border-radius:var(--radius-sm);
  padding:8px 16px; font-family:var(--display); font-weight:700;
  font-size:0.72rem; color:white; cursor:pointer;
  transition:background 0.18s, transform 0.1s; white-space:nowrap; letter-spacing:0.04em;
}
.btn-comment:hover  { background:var(--red); }
.btn-comment:active { transform:scale(0.97); }

/* EMPTY */
.empty-state { text-align:center; padding:64px 20px; background:var(--bg2); border:1.5px dashed var(--border); border-radius:var(--radius); }
.empty-icon  { font-size:3rem; margin-bottom:16px; opacity:0.4; }
.empty-title { font-family:var(--display); font-weight:700; font-size:1.1rem; color:var(--text2); margin-bottom:6px; }
.empty-sub   { font-size:0.85rem; color:var(--text3); }

/* FAB */
.fab {
  position:fixed; bottom:32px; right:32px; z-index:300;
  width:60px; height:60px; background:var(--red); border:none;
  border-radius:50%; cursor:pointer; display:flex; align-items:center;
  justify-content:center; font-size:1.6rem; color:white;
  box-shadow:0 4px 20px rgba(232,34,10,0.45);
  transition:transform 0.25s cubic-bezier(.34,1.56,.64,1), background 0.2s;
}
.fab:hover { transform:scale(1.1); background:#c41a00; }
.fab.open  { transform:rotate(45deg) scale(1.05); }

/* COMPOSE OVERLAY */
.compose-overlay { display:none; position:fixed; inset:0; background:rgba(28,26,20,0.4); z-index:290; backdrop-filter:blur(3px); }
.compose-overlay.open { display:block; }

/* COMPOSE PANEL */
.compose-panel {
  position:fixed; bottom:110px; right:24px;
  width:min(480px, calc(100vw - 48px));
  background:var(--bg2); border:1.5px solid var(--border);
  border-radius:var(--radius); z-index:300;
  box-shadow:0 24px 64px rgba(0,0,0,0.18);
  transform:translateY(24px) scale(0.96); opacity:0; pointer-events:none;
  transition:transform 0.3s cubic-bezier(.22,.68,0,1.2), opacity 0.25s ease;
}
.compose-panel.open { transform:translateY(0) scale(1); opacity:1; pointer-events:all; }

.compose-header { padding:18px 20px 0; display:flex; align-items:center; justify-content:space-between; margin-bottom:16px; }
.compose-title  { font-family:var(--display); font-weight:800; font-size:1rem; }

.compose-close {
  background:var(--bg3); border:none; border-radius:8px;
  width:30px; height:30px; font-size:1rem; color:var(--text2);
  cursor:pointer; display:flex; align-items:center; justify-content:center; transition:background 0.18s;
}
.compose-close:hover { background:var(--red-light); color:var(--red); }

.compose-body { padding:0 20px 20px; }

.c-label { font-family:var(--display); font-weight:700; font-size:0.68rem; letter-spacing:0.08em; color:var(--text3); text-transform:uppercase; margin-bottom:6px; display:block; }

.c-textarea {
  width:100%; background:var(--bg); border:1.5px solid var(--border);
  border-radius:var(--radius-sm); padding:12px 14px;
  font-family:var(--sans); font-size:0.92rem; color:var(--text);
  line-height:1.5; resize:vertical; outline:none; min-height:90px;
  transition:border-color 0.2s; margin-bottom:14px;
}
.c-textarea:focus { border-color:var(--red); }
.c-textarea::placeholder { color:var(--text3); }

.c-img-zone {
  background:var(--bg); border:1.5px dashed var(--border);
  border-radius:var(--radius-sm); padding:18px; text-align:center;
  cursor:pointer; position:relative; transition:all 0.2s; margin-bottom:14px;
}
.c-img-zone:hover,.c-img-zone.dragover { border-color:var(--red); background:var(--red-light); }
.c-img-zone input { position:absolute; inset:0; opacity:0; cursor:pointer; width:100%; height:100%; }
.c-img-label { font-family:var(--display); font-weight:600; font-size:0.75rem; color:var(--text3); }

.c-preview { display:none; margin-bottom:12px; position:relative; }
.c-preview img { width:100%; max-height:120px; object-fit:cover; border-radius:var(--radius-sm); border:1.5px solid var(--border); }
.c-preview-info { font-size:0.68rem; color:var(--green); font-family:var(--display); font-weight:600; margin-top:4px; }
.c-remove { position:absolute; top:6px; right:6px; background:rgba(28,26,20,0.7); border:none; border-radius:6px; color:white; font-size:0.7rem; padding:2px 8px; cursor:pointer; font-family:var(--display); font-weight:700; }

.btn-broadcast {
  width:100%; background:var(--red); border:none; border-radius:var(--radius-sm);
  padding:14px; font-family:var(--display); font-weight:800; font-size:0.9rem;
  letter-spacing:0.06em; color:white; cursor:pointer;
  transition:background 0.2s, transform 0.1s; position:relative; overflow:hidden;
}
.btn-broadcast:hover  { background:#c41a00; }
.btn-broadcast:active { transform:scale(0.99); }
.btn-broadcast:disabled { opacity:0.5; cursor:not-allowed; }

.btn-prog { position:absolute; left:0; top:0; bottom:0; width:0%; background:rgba(255,255,255,0.2); transition:width 0.3s; }

/* TOAST */
#toast {
  position:fixed; top:80px; left:50%;
  transform:translateX(-50%) translateY(-20px);
  background:var(--text); color:white;
  font-family:var(--display); font-weight:700; font-size:0.8rem;
  letter-spacing:0.05em; padding:10px 24px;
  border-radius:999px; opacity:0;
  transition:all 0.3s cubic-bezier(.22,.68,0,1.2);
  z-index:999; white-space:nowrap; pointer-events:none;
}
#toast.show { opacity:1; transform:translateX(-50%) translateY(0); }
#toast.ok   { background:var(--green); }
#toast.err  { background:var(--red); }

/* RESIZE OVERLAY */
#resize-overlay { display:none; position:fixed; inset:0; background:rgba(28,26,20,0.6); z-index:998; align-items:center; justify-content:center; backdrop-filter:blur(4px); }
#resize-overlay.show { display:flex; }
.resize-box { background:var(--bg2); border:1.5px solid var(--border); border-radius:var(--radius); padding:32px 40px; text-align:center; }
.resize-spinner { width:36px; height:36px; border:3px solid var(--border); border-top-color:var(--red); border-radius:50%; animation:spin 0.8s linear infinite; margin:0 auto 16px; }
@keyframes spin { to{transform:rotate(360deg)} }
.resize-text { font-family:var(--display); font-weight:700; font-size:0.85rem; color:var(--text2); letter-spacing:0.06em; }

@media(max-width:540px){
  header{padding:0 16px;}
  .header-stats{gap:5px;}
  .stat-chip{padding:4px 8px;font-size:0.65rem;}
  .feed{padding:20px 12px 120px;}
  .fab{bottom:20px;right:20px;}
  .compose-panel{right:12px;bottom:90px;}
  .node-grid{grid-template-columns:repeat(3,1fr);}
}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">⚡</div>
    EMER·NET
  </div>
  <div class="header-stats" id="headerStats">
    <div class="stat-chip live"><div class="live-dot"></div> LIVE</div>
  </div>
  <div class="header-clock" id="clock">--:--:--</div>
</header>

<div class="feed">
  <div class="feed-header">
    <div>
      <div class="feed-title">Alert Feed</div>
      <div class="feed-sub" id="feedSub">Loading...</div>
    </div>
    <div class="header-actions">
      <a class="btn-export" href="/export" download="emergency_alerts.csv">⬇ Export CSV</a>
      <button class="btn-refresh" onclick="fetchAlerts()">↻ Refresh</button>
    </div>
  </div>

  <!-- NODE STATUS PANEL -->
  <div class="node-panel">
    <div class="panel-title">📡 NODE STATUS</div>
    <div class="node-grid" id="nodeGrid">
      <div class="node-card unknown"><div class="node-id">NODE 1</div><div class="node-status-label">WAITING</div><div class="node-ssid">EmergencyNet_1</div><div class="node-age">No heartbeat yet</div></div>
      <div class="node-card unknown"><div class="node-id">NODE 2</div><div class="node-status-label">WAITING</div><div class="node-ssid">EmergencyNet_2</div><div class="node-age">No heartbeat yet</div></div>
      <div class="node-card unknown"><div class="node-id">NODE 3</div><div class="node-status-label">WAITING</div><div class="node-ssid">EmergencyNet_3</div><div class="node-age">No heartbeat yet</div></div>
    </div>
  </div>

  <!-- BATTERY PANEL -->
  <div class="batt-panel">
    <div class="panel-title">🔋 BATTERY STATUS</div>
    <div id="batteryList"><div class="batt-offline">Waiting for Node 1 battery data...</div></div>
  </div>

  <div id="alertList"></div>
</div>

<button class="fab" id="fab" onclick="toggleCompose()">+</button>
<div class="compose-overlay" id="composeOverlay" onclick="closeCompose()"></div>

<div class="compose-panel" id="composePanel">
  <div class="compose-header">
    <div class="compose-title">📡 Broadcast Alert</div>
    <button class="compose-close" onclick="closeCompose()">✕</button>
  </div>
  <div class="compose-body">
    <label class="c-label">Message</label>
    <textarea class="c-textarea" id="msgInput" placeholder="Describe the emergency situation..."></textarea>
    <label class="c-label">Image (optional)</label>
    <div class="c-img-zone" id="dropZone">
      <input type="file" id="fileInput" accept="image/*">
      <div style="font-size:1.4rem;margin-bottom:6px">📷</div>
      <div class="c-img-label">TAP OR DROP · max 10MB · auto-resized</div>
    </div>
    <div class="c-preview" id="cPreview">
      <img id="previewImg" src="" alt="preview">
      <div class="c-preview-info" id="previewInfo"></div>
      <button class="c-remove" onclick="removeImage()">✕ Remove</button>
    </div>
    <button class="btn-broadcast" id="btnSend" onclick="sendAlert()">
      <div class="btn-prog" id="btnProg"></div>
      <span id="btnLabel">BROADCAST ALERT</span>
    </button>
  </div>
</div>

<div id="toast"></div>
<div id="resize-overlay">
  <div class="resize-box">
    <div class="resize-spinner"></div>
    <div class="resize-text">PROCESSING IMAGE...</div>
  </div>
</div>

<script>
function updateClock(){ document.getElementById('clock').textContent=new Date().toTimeString().slice(0,8); }
setInterval(updateClock,1000); updateClock();

function toggleCompose(){
  document.getElementById('composePanel').classList.contains('open')?closeCompose():openCompose();
}
function openCompose(){
  document.getElementById('composePanel').classList.add('open');
  document.getElementById('composeOverlay').classList.add('open');
  document.getElementById('fab').classList.add('open');
  setTimeout(()=>document.getElementById('msgInput').focus(),300);
}
function closeCompose(){
  document.getElementById('composePanel').classList.remove('open');
  document.getElementById('composeOverlay').classList.remove('open');
  document.getElementById('fab').classList.remove('open');
}

let toastTimer;
function toast(msg,type='ok'){
  const el=document.getElementById('toast');
  el.textContent=msg; el.className='show '+type;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>el.className='',2800);
}

const TARGET_BYTES=48000;
let resizedBlob=null,resizedName='';

document.getElementById('dropZone').addEventListener('dragover',e=>{e.preventDefault();e.currentTarget.classList.add('dragover');});
document.getElementById('dropZone').addEventListener('dragleave',e=>{e.currentTarget.classList.remove('dragover');});
document.getElementById('dropZone').addEventListener('drop',e=>{e.preventDefault();e.currentTarget.classList.remove('dragover');if(e.dataTransfer.files[0])handleFile(e.dataTransfer.files[0]);});
document.getElementById('fileInput').addEventListener('change',e=>{if(e.target.files[0])handleFile(e.target.files[0]);});

function handleFile(file){
  if(!file.type.startsWith('image/')){toast('Not an image','err');return;}
  if(file.size>10*1024*1024){toast('Max 10MB','err');return;}
  document.getElementById('resize-overlay').classList.add('show');
  resizedName=file.name.replace(/\.[^.]+$/,'.jpg');
  const reader=new FileReader();
  reader.onload=e=>{const img=new Image();img.onload=()=>compressToTarget(img,file.size);img.src=e.target.result;};
  reader.readAsDataURL(file);
}

function compressToTarget(img,origSize){
  let w=img.naturalWidth,h=img.naturalHeight,MAX_DIM=1280;
  if(w>MAX_DIM||h>MAX_DIM){if(w>=h){h=Math.round(h*MAX_DIM/w);w=MAX_DIM;}else{w=Math.round(w*MAX_DIM/h);h=MAX_DIM;}}
  const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
  let lo=0.05,hi=0.92,quality=0.7,attempts=0;
  function tryQ(q){
    canvas.width=w;canvas.height=h;ctx.drawImage(img,0,0,w,h);
    canvas.toBlob(b=>{
      attempts++;if(!b){done(null);return;}
      if(b.size<=TARGET_BYTES||attempts>=10){done(b);}
      else{hi=q;quality=(lo+hi)/2;if(b.size>TARGET_BYTES*3){w=Math.round(w*0.75);h=Math.round(h*0.75);quality=0.7;lo=0.05;hi=0.92;attempts=0;}if(w<60||h<60){done(b);return;}tryQ(quality);}
    },'image/jpeg',q);
  }
  function done(b){
    document.getElementById('resize-overlay').classList.remove('show');
    if(!b){toast('Image failed','err');return;}
    resizedBlob=b;
    document.getElementById('previewImg').src=URL.createObjectURL(b);
    document.getElementById('previewInfo').textContent=`✓ Ready  ${(b.size/1024).toFixed(1)}KB  (was ~${(origSize/1024).toFixed(0)}KB)`;
    document.getElementById('cPreview').style.display='block';
    document.getElementById('dropZone').style.display='none';
  }
  tryQ(quality);
}

function removeImage(){
  resizedBlob=null;resizedName='';
  document.getElementById('previewImg').src='';
  document.getElementById('cPreview').style.display='none';
  document.getElementById('dropZone').style.display='block';
  document.getElementById('fileInput').value='';
}

async function sendAlert(){
  const msg=document.getElementById('msgInput').value.trim();
  if(!msg){toast('Enter a message','err');return;}
  const btn=document.getElementById('btnSend'),lbl=document.getElementById('btnLabel'),prog=document.getElementById('btnProg');
  btn.disabled=true;lbl.textContent='SENDING...';prog.style.width='35%';
  const fd=new FormData();fd.append('message',msg);
  if(resizedBlob)fd.append('image',resizedBlob,resizedName);
  try{
    prog.style.width='70%';
    const r=await fetch('/send',{method:'POST',body:fd});
    prog.style.width='100%';
    if(r.ok){
      const d=await r.json();
      const icons={CRITICAL:'🔴',MODERATE:'🟡',INFO:'🟢'};
      toast(`${icons[d.severity]||'✓'} ${d.severity} alert broadcast`,'ok');
      document.getElementById('msgInput').value='';
      removeImage();closeCompose();
      setTimeout(fetchAlerts,400);
    }else{toast('Server error '+r.status,'err');}
  }catch(e){toast('Network error','err');}
  setTimeout(()=>{btn.disabled=false;lbl.textContent='BROADCAST ALERT';prog.style.width='0%';},600);
}

function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

function renderComment(c){
  return `<div class="comment-item">
    <div class="comment-meta">
      <span class="comment-ip">${escHtml(c.ip)}</span>
      <span class="comment-time">${escHtml(c.timestamp)}</span>
    </div>
    <div class="comment-text">${escHtml(c.text)}</div>
  </div>`;
}

async function postComment(alertId,inputEl,listEl){
  const text=inputEl.value.trim();if(!text)return;
  inputEl.value='';
  try{
    const r=await fetch('/comment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alert_id:alertId,text})});
    if(r.ok){const d=await r.json();listEl.insertAdjacentHTML('beforeend',renderComment(d.comment));}
  }catch(e){toast('Comment failed','err');}
}

/* ── AI ADVICE ───────────────────────────────────────────────── */
const _alertData = {};   /* id -> {message, severity} */

async function fetchAIAdvice(id){
  const btn  = document.getElementById('ai-btn-'  + id);
  const box  = document.getElementById('ai-box-'  + id);
  const text = document.getElementById('ai-text-' + id);
  if(!btn || !box || !text) return;

  const alert = _alertData[id];
  if(!alert){ text.textContent='Alert data missing.'; box.classList.add('visible'); return; }

  btn.disabled = true;
  btn.innerHTML = '<div class="ai-spinner"></div> Thinking...';
  box.classList.add('visible');
  text.textContent = 'Asking AI — this may take 10–20 seconds...';

  try {
    const r = await fetch('/ai-advice', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ message: alert.message, severity: alert.severity })
    });
    const d = await r.json();
    text.textContent = d.advice || 'No advice returned.';
    btn.innerHTML = '🤖 Refresh AI Advice';
  } catch(e) {
    text.textContent = 'Failed to reach AI — is Ollama running?';
    btn.innerHTML = '🤖 Retry AI Advice';
  }
  btn.disabled = false;
}

/* ── NODE STATUS ─────────────────────────────────────────────── */
async function fetchHeartbeat(){
  try{
    const r=await fetch('/heartbeat');
    const d=await r.json();
    const grid=document.getElementById('nodeGrid');
    const now=Date.now()/1000;  /* seconds */
    const timeout=90;
    grid.innerHTML='';
    [1,2,3].forEach(n=>{
      const nd=d.heartbeat[String(n)];
      let cls='unknown', label='WAITING', age='No heartbeat yet', ssid='EmergencyNet_'+n;
      if(nd){
        ssid=nd.ssid||ssid;
        const secs=Math.floor(now-nd.last_seen_ts);
        if(secs<timeout){
          cls='online'; label='ONLINE';
          age=secs<60?`${secs}s ago`:`${Math.floor(secs/60)}m ${secs%60}s ago`;
        } else {
          cls='offline'; label='OFFLINE';
          age=`Last seen ${nd.last_seen}`;
        }
      }
      grid.innerHTML+=`
        <div class="node-card ${cls}">
          <div class="node-id">NODE ${n}</div>
          <div class="node-status-label">${label}</div>
          <div class="node-ssid">${escHtml(ssid)}</div>
          <div class="node-age">${escHtml(age)}</div>
        </div>`;
    });
  }catch(_){}
}

/* ── BATTERY ─────────────────────────────────────────────────── */
async function fetchBattery(){
  try{
    const r=await fetch('/battery');
    const d=await r.json();
    const list=document.getElementById('batteryList');
    const entries=Object.values(d.battery);
    if(entries.length===0){
      list.innerHTML='<div class="batt-offline">No battery data yet — waiting for Node 1...</div>';
      return;
    }
    list.innerHTML=entries.map(b=>{
      const pct=Math.min(100,Math.max(0,b.percent));
      const color=pct>60?'var(--green)':pct>30?'var(--orange)':'var(--red)';
      const icon=pct>60?'🟢':pct>30?'🟡':'🔴';
      return `<div class="batt-row">
        <div class="batt-node-label">NODE ${b.node}</div>
        <div class="batt-bar-wrap"><div class="batt-bar" style="width:${pct}%;background:${color}"></div></div>
        <div class="batt-pct" style="color:${color}">${icon} ${pct.toFixed(0)}%</div>
        <div class="batt-volt">${b.voltage.toFixed(2)}V</div>
        <div class="batt-time">${escHtml(b.timestamp)}</div>
      </div>`;
    }).join('');
  }catch(_){}
}

/* ── ALERTS ──────────────────────────────────────────────────── */
async function fetchAlerts(){
  try{
    const r=await fetch('/alerts'),data=await r.json();
    const arr=data.alerts.slice().reverse();
    document.getElementById('feedSub').textContent=arr.length+' alert'+(arr.length!==1?'s':'')+' recorded';

    const counts={CRITICAL:0,MODERATE:0,INFO:0};
    arr.forEach(a=>{const s=a.severity||'INFO';if(counts[s]!==undefined)counts[s]++;});
    const sb=document.getElementById('headerStats');
    sb.innerHTML='<div class="stat-chip live"><div class="live-dot"></div> LIVE</div>';
    if(counts.CRITICAL>0)sb.innerHTML+=`<div class="stat-chip crit">🔴 ${counts.CRITICAL}</div>`;
    if(counts.MODERATE>0)sb.innerHTML+=`<div class="stat-chip mod">🟡 ${counts.MODERATE}</div>`;
    if(counts.INFO>0)sb.innerHTML+=`<div class="stat-chip infoc">🟢 ${counts.INFO}</div>`;

    const list=document.getElementById('alertList');
    if(arr.length===0){
      list.innerHTML=`<div class="empty-state"><div class="empty-icon">📡</div><div class="empty-title">No alerts yet</div><div class="empty-sub">Tap + to broadcast the first alert</div></div>`;
      return;
    }
    list.innerHTML='';
    arr.forEach((a,i)=>{
      const sev=a.severity||'INFO';
      const id=String(a.id||a.timestamp||i).replace(/[^a-zA-Z0-9_-]/g,'_');
      const num=String(data.alerts.length-i).padStart(3,'0');

      /* store alert data safely — avoids broken onclick string escaping */
      _alertData[id] = { message: a.message || '', severity: sev };

      const card=document.createElement('div');
      card.className='alert-card';
      card.innerHTML=`
        <div class="card-stripe ${sev}"></div>
        <div class="card-body">
          <div class="card-meta">
            <span class="sev-badge ${sev}">${sev}</span>
            <span class="card-seq">#${num}</span>
            <span class="card-ip">${escHtml(a.ip)}</span>
            <span class="card-time">${escHtml(a.timestamp||'')}</span>
          </div>
          <div class="card-msg">${escHtml(a.message)}</div>
          ${a.image_filename?`<img class="card-img" src="/uploads/${escHtml(a.image_filename)}" loading="lazy" alt="Alert image">`:''}
          ${a.action?`<div class="card-action ${sev}"><span>⚡</span> ${escHtml(a.action)}</div>`:''}
        </div>
        <div class="ai-advice-wrap">
          <button class="btn-ai" id="ai-btn-${id}" onclick="fetchAIAdvice('${id}')">
            🤖 Get AI Advice
          </button>
          <div class="ai-box" id="ai-box-${id}">
            <div class="ai-box-label">🤖 AI ASSISTANCE</div>
            <div class="ai-box-text" id="ai-text-${id}"></div>
          </div>
        </div>
        <div class="comments-section">
          <div class="comments-title">💬 RESPONSES</div>
          <div class="comment-list" id="clist-${id}"></div>
          <div class="comment-input-row">
            <label for="cinput-${id}" style="display:none">Response</label>
            <input class="comment-input" id="cinput-${id}" placeholder="Add a response..." maxlength="300">
            <button class="btn-comment" onclick="postComment('${escHtml(a.id||a.timestamp||String(i))}',document.getElementById('cinput-${id}'),document.getElementById('clist-${id}'))">Reply</button>
          </div>
        </div>`;
      list.appendChild(card);
      card.querySelector(`#cinput-${id}`).addEventListener('keydown',e=>{
        if(e.key==='Enter')postComment(a.id||a.timestamp||String(i),document.getElementById(`cinput-${id}`),document.getElementById(`clist-${id}`));
      });
    });

    try{
      const cr=await fetch('/comments'),cd=await cr.json();
      arr.forEach((a,i)=>{
        const rawId=a.id||a.timestamp||String(i);
        const id=String(rawId).replace(/[^a-zA-Z0-9_-]/g,'_');
        const el=document.getElementById('clist-'+id);
        if(el&&cd.comments[rawId])el.innerHTML=cd.comments[rawId].map(renderComment).join('');
      });
    }catch(_){}
  }catch(e){toast('Failed to load alerts','err');}
}

/* ── POLL ALL ────────────────────────────────────────────────── */
setInterval(fetchAlerts,   30000);
setInterval(fetchHeartbeat, 30000);
setInterval(fetchBattery,   60000);

fetchAlerts();
fetchHeartbeat();
fetchBattery();
</script>
</body>
</html>
"""

# ── Ollama AI Advice ──────────────────────────────────────────────

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2:0.5b"

def ask_ollama(message, severity):
    prompt = (
        f"You are an emergency response assistant. "
        f"An alert has been received with severity level: {severity}.\n"
        f"Alert message: \"{message}\"\n\n"
        f"Give short, clear, practical advice in 2-3 sentences. "
        f"Focus on immediate actions people should take."
    )
    try:
        payload = json.dumps({
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }).encode("utf-8")
        req = urllib.request.Request(
            OLLAMA_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("response", "No response from AI.").strip()
    except Exception as e:
        return f"AI unavailable: {str(e)}"

@app.route('/ai-advice', methods=['POST'])
def ai_advice():
    data     = request.get_json(force=True)
    message  = str(data.get('message', '')).strip()
    severity = str(data.get('severity', 'INFO')).strip()
    if not message:
        return jsonify({"advice": "No message provided."}), 400
    advice = ask_ollama(message, severity)
    return jsonify({"advice": advice})

# ── Routes ────────────────────────────────────────────────────────

@app.route('/')
def home():
    resp = make_response(render_template_string(HTML_PAGE))
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/send', methods=['POST'])
def send():
    message        = request.form.get('message', '').strip()
    image          = request.files.get('image')
    image_filename = None
    if not message:
        return jsonify({"status": "error", "reason": "empty message"}), 400
    if image and image.filename:
        image.seek(0, 2); size = image.tell(); image.seek(0)
        if size > 55 * 1024:
            return jsonify({"status": "error", "reason": "image too large"}), 413
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = os.path.splitext(image.filename)[1] or '.jpg'
        image_filename = f"{ts}{ext}"
        image.save(os.path.join(UPLOAD_FOLDER, image_filename))
    sender_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    severity, action = classify_alert(message)
    alert = {"id": timestamp, "ip": sender_ip, "message": message,
             "image_filename": image_filename, "timestamp": timestamp,
             "severity": severity, "action": action}
    alerts.append(alert)
    with open(TEXT_FILE, "a", encoding="utf-8") as f:
        f.write(f"{sender_ip}|{message}|{image_filename}|{timestamp}|{severity},{action}\n")
    return jsonify({"status": "received", "severity": severity, "action": action})


@app.route('/alerts')
def get_alerts():
    return jsonify({"alerts": alerts})


@app.route('/comment', methods=['POST'])
def add_comment():
    data     = request.get_json(force=True)
    alert_id = str(data.get('alert_id', '')).strip()
    text     = str(data.get('text', '')).strip()[:300]
    if not alert_id or not text:
        return jsonify({"status": "error"}), 400
    sender_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    comment   = {"ip": sender_ip, "text": text, "timestamp": timestamp}
    if alert_id not in comments:
        comments[alert_id] = []
    comments[alert_id].append(comment)
    save_comments()
    return jsonify({"status": "ok", "comment": comment})


@app.route('/comments')
def get_comments():
    return jsonify({"comments": comments})


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


# ── Battery ───────────────────────────────────────────────────────

@app.route('/battery', methods=['POST'])
def update_battery():
    data    = request.get_json(force=True)
    node    = str(data.get('node', '?'))
    voltage = float(data.get('voltage', 0))
    percent = float(data.get('percent', 0))
    battery_data[node] = {
        "node":      node,
        "voltage":   round(voltage, 2),
        "percent":   round(percent, 1),
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    return jsonify({"status": "ok"})


@app.route('/battery', methods=['GET'])
def get_battery():
    return jsonify({"battery": battery_data})


# ── Heartbeat ─────────────────────────────────────────────────────

@app.route('/heartbeat', methods=['POST'])
def update_heartbeat():
    data = request.get_json(force=True)
    node = str(data.get('node', '?'))
    heartbeat_data[node] = {
        "node":         node,
        "ssid":         data.get('ssid', ''),
        "ip":           data.get('ip', ''),
        "last_seen_ts": time.time(),                             # epoch seconds for age calc in JS
        "last_seen":    datetime.now().strftime("%H:%M:%S")     # human-readable
    }
    return jsonify({"status": "ok"})


@app.route('/heartbeat', methods=['GET'])
def get_heartbeat():
    return jsonify({"heartbeat": heartbeat_data})


# ── CSV Export ────────────────────────────────────────────────────

@app.route('/export')
def export_csv():
    """
    Download all alerts as a CSV file.
    Columns: #, Timestamp, IP, Severity, Message, Action, Image
    """
    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow(["#", "Timestamp", "Sender IP", "Severity", "Message", "Action", "Image Filename"])

    # Data rows
    for i, a in enumerate(alerts, start=1):
        writer.writerow([
            i,
            a.get("timestamp", ""),
            a.get("ip", ""),
            a.get("severity", "INFO"),
            a.get("message", ""),
            a.get("action", ""),
            a.get("image_filename") or ""
        ])

    output.seek(0)
    filename = f"emergency_alerts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    resp = make_response(output.getvalue())
    resp.headers["Content-Disposition"] = f"attachment; filename={filename}"
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    return resp


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
