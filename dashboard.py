import os
import math
import hashlib
import hmac
import time
import asyncio

from datetime import datetime, timedelta

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import aiohttp

load_dotenv()

# ── ENV ───────────────────────────────────────────────────────

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI",
    "http://localhost:8000/callback"
)

BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "0"))
SECRET_KEY = os.getenv("SECRET_KEY", "geheim123")

GUILD_ID = int(os.getenv("GUILD_ID", "0"))
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

# ── Mongo ─────────────────────────────────────────────────────

mongo = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
db = mongo[os.getenv("MONGODB_DB", "rld_main")]

config_col = db["config"]
warns_col = db["warns"]
cases_col = db["cases"]
economy_col = db["economy"]
giveaway_col = db["giveaways"]
suggest_col = db["suggestions"]
team_col = db["team"]
apps_col = db["applications"]
logs_col = db["logs"]
rss_col = db["rss_feeds"]
rl_teams_col = db["rl_teams"]
tournament_col = db["tournaments"]
voice_col = db["voice_stats"]
dashboard_log_col = db["dashboard_logs"]
notif_col = db["notifications"]

# ── Auth ──────────────────────────────────────────────────────

def make_token(uid):
    msg = f"{uid}:{int(time.time() // 3600)}"

    signature = hmac.new(
        SECRET_KEY.encode(),
        msg.encode(),
        hashlib.sha256
    ).hexdigest()

    return f"{signature}:{uid}"


def verify_token(token):
    try:
        sig, uid = token.rsplit(":", 1)

        for offset in [0, -1]:
            msg = f"{uid}:{int(time.time() // 3600) + offset}"

            expected = hmac.new(
                SECRET_KEY.encode(),
                msg.encode(),
                hashlib.sha256
            ).hexdigest()

            if hmac.compare_digest(sig, expected):
                return uid

    except Exception:
        pass

    return None


def get_uid(request: Request):
    token = request.cookies.get("session")

    if not token:
        return None

    return verify_token(token)


async def dashboard_log(uid, action, details=""):
    await dashboard_log_col.insert_one({
        "user_id": uid,
        "action": action,
        "details": details,
        "ts": datetime.utcnow()
    })


# ── FastAPI ───────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── CSS ───────────────────────────────────────────────────────

CSS = """
:root{
--bg:#080b14;
--bg2:#0d1220;
--card:#111827;
--card2:#1a2235;
--border:#1e2d4a;
--accent:#6c63ff;
--accent2:#a78bfa;
--green:#10b981;
--yellow:#f59e0b;
--red:#ef4444;
--text:#e2e8f0;
--muted:#64748b;
}

*{
box-sizing:border-box;
margin:0;
padding:0;
}

body{
background:var(--bg);
color:var(--text);
font-family:'Inter','Segoe UI',sans-serif;
min-height:100vh;
}

a{
text-decoration:none;
color:inherit;
}

.nav{
background:rgba(13,18,32,.95);
backdrop-filter:blur(12px);
border-bottom:1px solid var(--border);
padding:0 32px;
height:64px;
display:flex;
align-items:center;
justify-content:space-between;
position:sticky;
top:0;
z-index:100;
}

.layout{
display:flex;
min-height:calc(100vh - 64px);
}

.sidebar{
width:220px;
background:var(--bg2);
border-right:1px solid var(--border);
padding:24px 0;
}

.sidebar-item{
padding:12px 24px;
cursor:pointer;
color:var(--muted);
transition:.2s;
}

.sidebar-item:hover{
background:rgba(108,99,255,.08);
color:var(--text);
}

.sidebar-item.active{
background:rgba(108,99,255,.15);
color:var(--accent2);
border-left:3px solid var(--accent);
}

.main{
flex:1;
padding:32px;
}

.page{
display:none;
}

.page.active{
display:block;
}

.card{
background:var(--card);
border:1px solid var(--border);
border-radius:16px;
padding:24px;
}

.grid{
display:grid;
gap:16px;
}

.grid-4{
grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
}

.stat-card{
background:var(--card);
border:1px solid var(--border);
border-radius:16px;
padding:20px;
}

.stat-val{
font-size:2rem;
font-weight:800;
}

.stat-label{
font-size:13px;
color:var(--muted);
margin-top:6px;
}

.btn{
padding:9px 18px;
border:none;
border-radius:8px;
cursor:pointer;
font-weight:600;
}

.btn-danger{
background:var(--red);
color:white;
}

.btn-success{
background:var(--green);
color:white;
}

.btn-primary{
background:var(--accent);
color:white;
}

.table-row{
display:flex;
align-items:center;
gap:12px;
padding:12px;
border-radius:10px;
}

.table-row:hover{
background:var(--card2);
}

input{
background:var(--bg2);
border:1px solid var(--border);
color:var(--text);
padding:10px 14px;
border-radius:8px;
width:100%;
}

.toast{
position:fixed;
bottom:24px;
right:24px;
padding:14px 20px;
border-radius:10px;
font-weight:600;
z-index:9999;
transform:translateY(100px);
transition:.3s;
}

.toast.show{
transform:translateY(0);
}
"""

# ── JavaScript ────────────────────────────────────────────────

DASHBOARD_JS = """
async function api(url, method='GET', body=null) {

    const opts = {
        method,
        headers: {
            'Content-Type': 'application/json'
        }
    };

    if(body){
        opts.body = JSON.stringify(body);
    }

    const r = await fetch(url, opts);

    return r.json();
}

function toast(msg, type='success') {

    const t = document.getElementById('toast');

    t.textContent = msg;

    t.style.background =
        type === 'success'
        ? '#10b981'
        : '#ef4444';

    t.classList.add('show');

    setTimeout(() => {
        t.classList.remove('show');
    }, 3000);
}

function showPage(name){

    document.querySelectorAll('.page')
    .forEach(p => p.classList.remove('active'));

    document.querySelectorAll('.sidebar-item')
    .forEach(s => s.classList.remove('active'));

    document.getElementById('page-' + name)
    .classList.add('active');

    const nav = document.getElementById('nav-' + name);

    if(nav){
        nav.classList.add('active');
    }

    const loaders = {
        overview: loadOverview,
        moderation: loadModeration,
        economy: loadEconomy
    };

    if(loaders[name]){
        loaders[name]();
    }
}

async function loadOverview(){

    const data = await api('/api/overview');

    document.getElementById('ov-users').textContent =
        data.total_users || 0;

    document.getElementById('ov-warns').textContent =
        data.total_warns || 0;

    document.getElementById('ov-coins').textContent =
        data.total_coins || 0;
}

async function loadModeration(){

    const data = await api('/api/moderation/warns');

    const el = document.getElementById('warn-list');

    if(!data.warns || !data.warns.length){

        el.innerHTML = `
        <div style="color:var(--muted);padding:24px;text-align:center;">
            Keine Verwarnungen
        </div>
        `;

        return;
    }

    el.innerHTML = data.warns.map(w => `
        <div class="table-row">

            <div style="flex:1;">
                <div style="font-weight:600;">
                    ${w.username}
                </div>

                <div style="color:var(--muted);font-size:13px;">
                    ${w.reason}
                </div>
            </div>

            <div style="font-size:12px;color:var(--muted);">
                ${w.ts}
            </div>

            <button
                class="btn btn-danger"
                onclick="removeWarn('${w.id}')">
                ✕
            </button>

        </div>
    `).join('');
}

async function removeWarn(id){

    const r = await api(
        '/api/moderation/warn/' + id,
        'DELETE'
    );

    if(r.ok){
        toast('Verwarnung entfernt');
        loadModeration();
    }else{
        toast('Fehler', 'error');
    }
}

async function loadEconomy(){

    const data = await api('/api/economy/leaderboard');

    const el = document.getElementById('eco-list');

    if(!data.users || !data.users.length){

        el.innerHTML = `
        <div style="padding:24px;text-align:center;color:var(--muted);">
            Keine Daten
        </div>
        `;

        return;
    }

    el.innerHTML = data.users.map((u, i) => `
        <div class="table-row">

            <div style="width:40px;font-weight:700;">
                #${i + 1}
            </div>

            <div style="flex:1;">
                ${u.username}
            </div>

            <div style="color:#f59e0b;font-weight:700;">
                ${u.coins} Coins
            </div>

        </div>
    `).join('');
}

window.onload = () => {
    showPage('overview');
};
"""

# ── HTML ──────────────────────────────────────────────────────

def html_wrap(content, username="User", avatar=""):

    return f"""
<!DOCTYPE html>

<html lang="de">

<head>

<meta charset="UTF-8">

<meta name="viewport"
content="width=device-width, initial-scale=1.0">

<title>RLD Main Bot Dashboard</title>

<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap"
rel="stylesheet">

<style>
{CSS}
</style>

</head>

<body>

<nav class="nav">

    <div style="font-weight:800;font-size:1.2rem;">
        🎮 RLD Main Bot
    </div>

    <div style="display:flex;align-items:center;gap:12px;">

        {
            f'<img src="{avatar}" style="width:36px;height:36px;border-radius:50%;">'
            if avatar else ''
        }

        <span>{username}</span>

        <a href="/logout">
            Logout
        </a>

    </div>

</nav>

<div class="layout">

    <aside class="sidebar">

        <div class="sidebar-item active"
             id="nav-overview"
             onclick="showPage('overview')">

            📊 Übersicht

        </div>

        <div class="sidebar-item"
             id="nav-moderation"
             onclick="showPage('moderation')">

            🛡️ Moderation

        </div>

        <div class="sidebar-item"
             id="nav-economy"
             onclick="showPage('economy')">

            💰 Economy

        </div>

    </aside>

    <main class="main">
        {content}
    </main>

</div>

<div class="toast" id="toast"></div>

<script>
{DASHBOARD_JS}
</script>

</body>
</html>
"""


# ── Routes ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):

    content = """
    <div id="page-overview" class="page active">

        <div class="grid grid-4">

            <div class="stat-card">
                <div class="stat-val" id="ov-users">0</div>
                <div class="stat-label">User</div>
            </div>

            <div class="stat-card">
                <div class="stat-val" id="ov-warns">0</div>
                <div class="stat-label">Warns</div>
            </div>

            <div class="stat-card">
                <div class="stat-val" id="ov-coins">0</div>
                <div class="stat-label">Coins</div>
            </div>

        </div>

    </div>

    <div id="page-moderation" class="page">

        <div class="card">

            <h2 style="margin-bottom:16px;">
                Moderation
            </h2>

            <div id="warn-list"></div>

        </div>

    </div>

    <div id="page-economy" class="page">

        <div class="card">

            <h2 style="margin-bottom:16px;">
                Economy
            </h2>

            <div id="eco-list"></div>

        </div>

    </div>
    """

    return HTMLResponse(
        html_wrap(
            content=content,
            username="Admin"
        )
    )


# ── API ───────────────────────────────────────────────────────

@app.get("/api/overview")
async def api_overview():

    total_warns = await warns_col.count_documents({})
    total_users = await economy_col.count_documents({})

    coins = 0

    async for user in economy_col.find({}):
        coins += user.get("coins", 0)

    return {
        "total_users": total_users,
        "total_warns": total_warns,
        "total_coins": coins
    }


@app.get("/api/moderation/warns")
async def api_warns():

    warns = []

    async for w in warns_col.find().sort("ts", -1).limit(50):

        warns.append({
            "id": str(w.get("_id")),
            "username": w.get("username", "Unknown"),
            "reason": w.get("grund", "Kein Grund"),
            "ts": str(w.get("ts", ""))
        })

    return {
        "warns": warns
    }


@app.delete("/api/moderation/warn/{warn_id}")
async def delete_warn(warn_id: str):

    from bson import ObjectId

    try:

        await warns_col.delete_one({
            "_id": ObjectId(warn_id)
        })

        return {
            "ok": True
        }

    except Exception as e:

        return {
            "ok": False,
            "error": str(e)
        }


@app.get("/api/economy/leaderboard")
async def economy_leaderboard():

    users = []

    async for u in economy_col.find().sort("coins", -1).limit(50):

        users.append({
            "user_id": str(u.get("user_id")),
            "username": u.get("username", "Unknown"),
            "coins": u.get("coins", 0)
        })

    return {
        "users": users
    }


# ── Start ─────────────────────────────────────────────────────

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "dashboard:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )