import os, math, hashlib, hmac, time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import aiohttp

load_dotenv()

DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:8000/callback")
BOT_OWNER_ID          = int(os.getenv("BOT_OWNER_ID", "0"))
SECRET_KEY            = os.getenv("SECRET_KEY", "geheim123")
GUILD_ID              = int(os.getenv("GUILD_ID", "0"))
DISCORD_TOKEN         = os.getenv("DISCORD_TOKEN", "")

mongo = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
db = mongo[os.getenv("MONGODB_DB", "rld_main")]
config_col        = db["config"]
warns_col         = db["warns"]
cases_col         = db["cases"]
economy_col       = db["economy"]
giveaway_col      = db["giveaways"]
suggest_col       = db["suggestions"]
team_col          = db["team"]
apps_col          = db["applications"]
rss_col           = db["rss_feeds"]
rl_teams_col      = db["rl_teams"]
notif_col         = db["notifications"]
dashboard_log_col = db["dashboard_logs"]
tickets_col       = db["tickets"]

# ── Auth ───────────────────────────────────────────────────────
def make_token(uid):
    msg = f"{uid}:{int(time.time()//3600)}"
    return hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest() + ":" + str(uid)

def verify_token(token):
    try:
        sig, uid = token.rsplit(":", 1)
        for offset in [0, -1]:
            msg = f"{uid}:{int(time.time()//3600)+offset}"
            if hmac.compare_digest(sig, hmac.new(SECRET_KEY.encode(), msg.encode(), hashlib.sha256).hexdigest()):
                return uid
    except: pass
    return None

def get_uid(request: Request):
    t = request.cookies.get("session")
    return verify_token(t) if t else None

def auth_check(request: Request):
    uid = get_uid(request)
    if not uid or int(uid) != BOT_OWNER_ID: raise HTTPException(403)
    return uid

async def discord_get(endpoint: str):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"https://discord.com/api{endpoint}", headers={"Authorization": f"Bot {DISCORD_TOKEN}"}) as r:
            return await r.json()

async def get_username(user_id: int) -> tuple:
    try:
        u = await discord_get(f"/users/{user_id}")
        name = u.get("global_name") or u.get("username", str(user_id))
        ah = u.get("avatar")
        avatar = f"https://cdn.discordapp.com/avatars/{user_id}/{ah}.png" if ah else f"https://cdn.discordapp.com/embed/avatars/{int(user_id)%5}.png"
        return name, avatar
    except: return str(user_id), f"https://cdn.discordapp.com/embed/avatars/0.png"

async def dashboard_log(uid, aktion, details=""):
    await dashboard_log_col.insert_one({"user_id": uid, "aktion": aktion, "details": details, "ts": datetime.utcnow()})

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

CSS = """
:root{
  --bg:#0a0608;--bg2:#110b0d;--card:#1a0e10;--card2:#221318;
  --border:#3d1a1f;--accent:#dc2626;--accent2:#f87171;--accent3:#fca5a5;
  --green:#10b981;--yellow:#f59e0b;--blue:#3b82f6;--text:#f1e8e9;--muted:#9c7b7e;
}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Inter','Segoe UI',sans-serif;min-height:100vh;}
a{text-decoration:none;color:inherit;}
::selection{background:var(--accent);color:white;}
::-webkit-scrollbar{width:6px;}::-webkit-scrollbar-track{background:var(--bg2);}::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}

.nav{background:rgba(10,6,8,.95);backdrop-filter:blur(16px);border-bottom:1px solid var(--border);padding:0 32px;height:68px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:100;box-shadow:0 4px 24px rgba(220,38,38,.08);}
.nav-logo{display:flex;align-items:center;gap:12px;}
.nav-logo-icon{width:40px;height:40px;background:linear-gradient(135deg,var(--accent),#991b1b);border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 16px rgba(220,38,38,.4);}
.nav-logo-text{font-weight:800;font-size:1.1rem;background:linear-gradient(135deg,var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.nav-logo-sub{font-size:10px;color:var(--muted);letter-spacing:2px;text-transform:uppercase;}
.nav-credit{font-size:12px;color:var(--muted);}
.nav-user{display:flex;align-items:center;gap:10px;}
.nav-user img{width:36px;height:36px;border-radius:50%;border:2px solid var(--accent);}
.nav-logout{color:var(--accent2);font-size:13px;padding:7px 14px;border:1px solid var(--accent);border-radius:8px;transition:all .2s;font-weight:600;}
.nav-logout:hover{background:var(--accent);color:white;box-shadow:0 4px 12px rgba(220,38,38,.3);}

.layout{display:flex;min-height:calc(100vh - 68px);}
.sidebar{width:230px;background:var(--bg2);border-right:1px solid var(--border);padding:20px 0;position:sticky;top:68px;height:calc(100vh - 68px);flex-shrink:0;overflow-y:auto;}
.sidebar-section{padding:8px 20px 4px;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:1.5px;font-weight:700;}
.sidebar-item{display:flex;align-items:center;gap:10px;padding:11px 20px;color:var(--muted);font-size:13.5px;font-weight:500;cursor:pointer;transition:all .2s;border-left:3px solid transparent;margin:1px 0;}
.sidebar-item:hover{color:var(--text);background:rgba(220,38,38,.06);}
.sidebar-item.active{color:var(--accent2);background:rgba(220,38,38,.1);border-left-color:var(--accent);}
.sidebar-item .icon{font-size:16px;width:20px;text-align:center;}

.main{flex:1;padding:32px;overflow-y:auto;max-width:1200px;}
.page{display:none;animation:fadeIn .3s ease;}.page.active{display:block;}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

.card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px;position:relative;}
.card::before{content:'';position:absolute;top:0;left:24px;right:24px;height:1px;background:linear-gradient(90deg,transparent,var(--border),transparent);}
.card2{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px;}
.grid{display:grid;gap:16px;}
.grid-4{grid-template-columns:repeat(auto-fit,minmax(190px,1fr));}
.grid-2{grid-template-columns:repeat(auto-fit,minmax(320px,1fr));}
.grid-3{grid-template-columns:repeat(auto-fit,minmax(250px,1fr));}

.stat-card{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:22px 24px;position:relative;overflow:hidden;transition:transform .2s,box-shadow .2s;}
.stat-card:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3);}
.stat-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;}
.stat-card.red::before{background:linear-gradient(90deg,var(--accent),#f87171);}
.stat-card.green::before{background:linear-gradient(90deg,#10b981,#34d399);}
.stat-card.yellow::before{background:linear-gradient(90deg,#f59e0b,#fbbf24);}
.stat-card.blue::before{background:linear-gradient(90deg,#3b82f6,#60a5fa);}
.stat-card.purple::before{background:linear-gradient(90deg,#8b5cf6,#a78bfa);}
.stat-card.pink::before{background:linear-gradient(90deg,#ec4899,#f9a8d4);}
.stat-val{font-size:2.2rem;font-weight:800;line-height:1;background:linear-gradient(135deg,var(--text),var(--muted));-webkit-background-clip:text;-webkit-text-fill-color:transparent;}
.stat-label{color:var(--muted);font-size:13px;margin-top:6px;}
.stat-icon{position:absolute;right:20px;top:50%;transform:translateY(-50%);font-size:2.8rem;opacity:.08;}
.stat-trend{position:absolute;bottom:16px;right:20px;font-size:11px;font-weight:600;}

.btn{padding:10px 20px;border-radius:9px;border:none;cursor:pointer;font-weight:600;font-size:13.5px;transition:all .2s;display:inline-flex;align-items:center;gap:7px;letter-spacing:.2px;}
.btn:active{transform:scale(.97);}
.btn-primary{background:linear-gradient(135deg,var(--accent),#991b1b);color:white;box-shadow:0 4px 12px rgba(220,38,38,.3);}
.btn-primary:hover{box-shadow:0 6px 20px rgba(220,38,38,.45);transform:translateY(-1px);}
.btn-danger{background:linear-gradient(135deg,#7f1d1d,#991b1b);color:white;}
.btn-danger:hover{background:linear-gradient(135deg,#991b1b,#dc2626);}
.btn-success{background:linear-gradient(135deg,#065f46,#10b981);color:white;}
.btn-success:hover{background:linear-gradient(135deg,#10b981,#34d399);}
.btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border);}.btn-ghost:hover{border-color:var(--accent);color:var(--accent2);}
.btn-yellow{background:linear-gradient(135deg,#92400e,#f59e0b);color:white;}

input,select,textarea{background:var(--bg2);border:1px solid var(--border);color:var(--text);border-radius:9px;padding:10px 14px;font-size:13.5px;transition:border .2s,box-shadow .2s;width:100%;font-family:inherit;}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(220,38,38,.12);}
input::placeholder{color:var(--muted);}

.table-row{display:flex;align-items:center;gap:12px;padding:13px 16px;border-radius:10px;transition:background .15s;border-bottom:1px solid rgba(61,26,31,.5);}
.table-row:last-child{border-bottom:none;}
.table-row:hover{background:rgba(220,38,38,.05);}
.avatar{width:40px;height:40px;border-radius:50%;border:2px solid var(--border);object-fit:cover;}
.avatar-sm{width:32px;height:32px;border-radius:50%;border:1px solid var(--border);}

.badge{padding:4px 10px;border-radius:999px;font-size:11.5px;font-weight:700;letter-spacing:.3px;}
.badge-red{background:rgba(220,38,38,.15);color:#f87171;border:1px solid rgba(220,38,38,.2);}
.badge-green{background:rgba(16,185,129,.15);color:#34d399;border:1px solid rgba(16,185,129,.2);}
.badge-yellow{background:rgba(245,158,11,.15);color:#fbbf24;border:1px solid rgba(245,158,11,.2);}
.badge-blue{background:rgba(59,130,246,.15);color:#60a5fa;border:1px solid rgba(59,130,246,.2);}
.badge-purple{background:rgba(139,92,246,.15);color:#a78bfa;border:1px solid rgba(139,92,246,.2);}
.badge-muted{background:rgba(156,123,126,.1);color:var(--muted);border:1px solid var(--border);}

.section-title{font-size:1.15rem;font-weight:800;margin-bottom:20px;display:flex;align-items:center;gap:10px;color:var(--text);}
.section-title::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--border),transparent);}

.xp-bar{background:var(--border);border-radius:999px;height:8px;overflow:hidden;}
.xp-fill{background:linear-gradient(90deg,var(--accent),var(--accent2));height:100%;border-radius:999px;transition:width .6s ease;}

.toast{position:fixed;bottom:24px;right:24px;padding:14px 22px;border-radius:12px;font-weight:700;font-size:14px;z-index:9999;transform:translateY(120px);transition:transform .35s cubic-bezier(.34,1.56,.64,1);box-shadow:0 12px 32px rgba(0,0,0,.5);}
.toast.show{transform:translateY(0);}

.modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);z-index:1000;align-items:center;justify-content:center;}
.modal.open{display:flex;}
.modal-box{background:var(--card);border:1px solid var(--border);border-radius:20px;padding:32px;max-width:480px;width:90%;box-shadow:0 24px 64px rgba(0,0,0,.6);}

footer{text-align:center;padding:28px;color:var(--muted);font-size:13px;border-top:1px solid var(--border);margin-top:32px;}

.login-page{min-height:100vh;display:flex;align-items:center;justify-content:center;background:radial-gradient(ellipse at 30% 50%,rgba(220,38,38,.08) 0%,transparent 60%),radial-gradient(ellipse at 70% 50%,rgba(153,27,27,.06) 0%,transparent 60%),var(--bg);}
.login-card{text-align:center;max-width:460px;width:90%;padding:52px 48px;background:var(--card);border:1px solid var(--border);border-radius:28px;box-shadow:0 32px 80px rgba(0,0,0,.6),0 0 0 1px rgba(220,38,38,.1);}
.login-glow{width:88px;height:88px;background:linear-gradient(135deg,var(--accent),#7f1d1d);border-radius:22px;display:flex;align-items:center;justify-content:center;font-size:40px;margin:0 auto 28px;box-shadow:0 12px 40px rgba(220,38,38,.5);}

@media(max-width:768px){.sidebar{display:none;}.main{padding:16px;}.grid-4{grid-template-columns:1fr 1fr;}.grid-2{grid-template-columns:1fr;}}
"""

JS = """
const IS_OWNER = true;
let cache = {};

async function api(url, method='GET', body=null) {
  const opts = {method, headers:{'Content-Type':'application/json'}};
  if(body) opts.body = JSON.stringify(body);
  try {
    const r = await fetch(url, opts);
    return await r.json();
  } catch(e) { return {error: e.message}; }
}

function toast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  const colors = {success:'#10b981', error:'#dc2626', info:'#3b82f6', warning:'#f59e0b'};
  t.style.background = colors[type] || colors.success;
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), 3500);
}

function showPage(name) {
  document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.sidebar-item').forEach(s=>s.classList.remove('active'));
  document.getElementById('page-'+name)?.classList.add('active');
  document.getElementById('nav-'+name)?.classList.add('active');
  const loaders = {
    overview: loadOverview, moderation: loadModeration,
    economy: loadEconomy, giveaways: loadGiveaways,
    suggestions: loadSuggestions, team: loadTeam,
    applications: loadApplications, rss: loadRss,
    rl_teams: loadRlTeams, notifications: loadNotifications,
    logs: loadLogs, settings: loadSettings,
    dashboard_logs: loadDashboardLogs,
  };
  if(loaders[name]) loaders[name]();
}

function timeAgo(ts) {
  if(!ts) return '?';
  const diff = (Date.now() - new Date(ts).getTime()) / 1000;
  if(diff < 60) return 'gerade eben';
  if(diff < 3600) return Math.floor(diff/60) + 'm ago';
  if(diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

// ── Overview ──────────────────────────────────────────────────
async function loadOverview() {
  const d = await api('/api/overview');
  document.getElementById('ov-users').textContent = (d.total_users||0).toLocaleString();
  document.getElementById('ov-warns').textContent = (d.total_warns||0).toLocaleString();
  document.getElementById('ov-cases').textContent = (d.total_cases||0).toLocaleString();
  document.getElementById('ov-tickets').textContent = (d.total_tickets||0).toLocaleString();
  document.getElementById('ov-coins').textContent = (d.total_coins||0).toLocaleString();
  document.getElementById('ov-apps').textContent = (d.total_apps||0).toLocaleString();
  document.getElementById('ov-giveaways').textContent = (d.total_giveaways||0).toLocaleString();
  document.getElementById('ov-team').textContent = (d.total_team||0).toLocaleString();
}

// ── Moderation ────────────────────────────────────────────────
async function loadModeration() {
  const d = await api('/api/moderation/warns');
  renderWarns(d.warns || []);
}

function renderWarns(warns) {
  const el = document.getElementById('warn-list');
  if(!warns.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;font-size:15px;">✨ Keine Verwarnungen</div>'; return; }
  el.innerHTML = warns.map(w => `
    <div class="table-row">
      <img class="avatar" src="${w.avatar}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
      <div style="flex:1;">
        <div style="font-weight:700;">${w.username}</div>
        <div style="color:var(--muted);font-size:13px;">${w.grund}</div>
      </div>
      <div style="text-align:right;">
        <div style="font-size:12px;color:var(--muted);">von ${w.mod}</div>
        <div style="font-size:11px;color:var(--muted);">${w.ts}</div>
      </div>
      <button class="btn btn-danger" onclick="removeWarn('${w.id}')" style="padding:7px 12px;font-size:12px;">✕</button>
    </div>`).join('');
}

async function searchUser() {
  const uid = document.getElementById('warn-search').value.trim();
  if(!uid) { loadModeration(); return; }
  const d = await api('/api/moderation/warns?user_id='+uid);
  renderWarns(d.warns || []);
}

async function removeWarn(id) {
  if(!confirm('Verwarnung wirklich löschen?')) return;
  const r = await api('/api/moderation/warn/'+id, 'DELETE');
  if(r.ok) { toast('✅ Verwarnung entfernt!'); loadModeration(); }
  else toast('❌ Fehler', 'error');
}

// ── Economy ───────────────────────────────────────────────────
async function loadEconomy() {
  const d = await api('/api/economy/leaderboard');
  const el = document.getElementById('eco-list');
  const medals = ['🥇','🥈','🥉'];
  if(!d.users?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Daten</div>'; return; }
  el.innerHTML = d.users.map((u,i) => `
    <div class="table-row">
      <div style="font-size:22px;width:40px;text-align:center;">${i<3?medals[i]:'<span style="color:var(--muted);font-weight:700;">#'+(i+1)+'</span>'}</div>
      <img class="avatar" src="${u.avatar}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
      <div style="flex:1;"><div style="font-weight:700;">${u.username}</div><div style="color:var(--muted);font-size:12px;">Bank: ${u.bank?.toLocaleString()||0} • Rep: ${u.rep||0}</div></div>
      <div style="text-align:right;"><div style="font-weight:800;color:var(--yellow);font-size:16px;">${u.coins.toLocaleString()}</div><div style="font-size:11px;color:var(--muted);">Coins</div></div>
      <button class="btn btn-ghost" onclick="openCoinModal('${u.user_id}','${u.username.replace(/'/g,'')}')" style="padding:7px 12px;font-size:13px;">✏️</button>
    </div>`).join('');
}

function openCoinModal(uid, name) {
  document.getElementById('coin-modal-name').textContent = name;
  document.getElementById('coin-uid').value = uid;
  document.getElementById('coin-amount').value = '';
  document.getElementById('coin-modal').classList.add('open');
}

async function saveCoins() {
  const uid = document.getElementById('coin-uid').value;
  const amount = parseInt(document.getElementById('coin-amount').value);
  if(isNaN(amount)) { toast('Ungültige Menge', 'error'); return; }
  const r = await api('/api/economy/coins', 'POST', {user_id: uid, amount});
  if(r.ok) { toast('✅ Coins aktualisiert!'); closeModal('coin-modal'); loadEconomy(); }
  else toast('❌ Fehler', 'error');
}

// ── Giveaways ─────────────────────────────────────────────────
async function loadGiveaways() {
  const d = await api('/api/giveaways');
  const el = document.getElementById('gw-list');
  if(!d.giveaways?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Giveaways</div>'; return; }
  el.innerHTML = d.giveaways.map(g => `
    <div class="card2" style="margin-bottom:12px;display:flex;align-items:center;gap:16px;">
      <div style="font-size:2rem;">🎉</div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:16px;">${g.preis}</div>
        <div style="color:var(--muted);font-size:13px;">${g.gewinner} Gewinner • ${g.active?'Endet: '+g.ends_at:'Beendet'}</div>
      </div>
      <span class="badge ${g.active?'badge-green':'badge-muted'}">${g.active?'🟢 Aktiv':'⚫ Beendet'}</span>
    </div>`).join('');
}

// ── Suggestions ───────────────────────────────────────────────
async function loadSuggestions() {
  const d = await api('/api/suggestions');
  const el = document.getElementById('suggest-list');
  if(!d.suggestions?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Vorschläge</div>'; return; }
  el.innerHTML = d.suggestions.map(s => `
    <div class="card2" style="margin-bottom:12px;">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
        <img class="avatar-sm" src="${s.avatar}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
        <div style="font-weight:700;">${s.username}</div>
        <div style="flex:1;"></div>
        <span class="badge ${s.status==='offen'?'badge-yellow':s.status==='angenommen'?'badge-green':'badge-red'}">${s.status}</span>
        <div style="color:var(--muted);font-size:11px;">${s.ts}</div>
      </div>
      <div style="color:var(--text);margin-bottom:12px;line-height:1.5;">${s.vorschlag}</div>
      ${s.status==='offen'?`<div style="display:flex;gap:8px;">
        <button class="btn btn-success" onclick="decideSuggest('${s.message_id}','accept')" style="padding:7px 14px;font-size:13px;">✅ Annehmen</button>
        <button class="btn btn-danger" onclick="decideSuggest('${s.message_id}','deny')" style="padding:7px 14px;font-size:13px;">❌ Ablehnen</button>
      </div>`:''}
    </div>`).join('');
}

async function decideSuggest(id, action) {
  const r = await api('/api/suggestions/'+action, 'POST', {message_id: id});
  if(r.ok) { toast('✅ Erledigt!'); loadSuggestions(); }
  else toast('❌ Fehler', 'error');
}

// ── Team ──────────────────────────────────────────────────────
async function loadTeam() {
  const d = await api('/api/team');
  const el = document.getElementById('team-list');
  if(!d.members?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Kein Team</div>'; return; }
  el.innerHTML = d.members.map(m => `
    <div class="table-row">
      <img class="avatar" src="${m.avatar}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
      <div style="flex:1;">
        <div style="font-weight:700;">${m.username}</div>
        <div style="color:var(--muted);font-size:12px;">seit ${m.joined}</div>
      </div>
      <span class="badge badge-red">${m.rolle}</span>
      ${m.abmeldungen?.length?'<span class="badge badge-yellow">Abgemeldet</span>':''}
      <button class="btn btn-danger" onclick="removeTeam('${m.user_id}')" style="padding:7px 12px;font-size:12px;">Entfernen</button>
    </div>`).join('');
}

async function removeTeam(uid) {
  if(!confirm('Wirklich entfernen?')) return;
  const r = await api('/api/team/'+uid, 'DELETE');
  if(r.ok) { toast('✅ Entfernt!'); loadTeam(); }
  else toast('❌ Fehler', 'error');
}

// ── Applications ──────────────────────────────────────────────
async function loadApplications() {
  const d = await api('/api/applications');
  const el = document.getElementById('app-list');
  if(!d.applications?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Bewerbungen</div>'; return; }
  el.innerHTML = d.applications.map(a => `
    <div class="card2" style="margin-bottom:16px;">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;">
        <img class="avatar" src="${a.avatar}" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
        <div>
          <div style="font-weight:800;font-size:16px;">${a.username}</div>
          <div style="color:var(--muted);font-size:12px;">${a.ts}</div>
        </div>
        <div style="flex:1;"></div>
        <span class="badge ${a.status==='offen'?'badge-yellow':a.status==='angenommen'?'badge-green':'badge-red'}">${a.status}</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px;">
        <div class="card2"><div style="color:var(--muted);font-size:11px;margin-bottom:4px;">ALTER</div><div style="font-weight:600;">${a.alter}</div></div>
        <div class="card2"><div style="color:var(--muted);font-size:11px;margin-bottom:4px;">VERFÜGBARKEIT</div><div style="font-weight:600;">${a.verfuegbarkeit}</div></div>
        <div class="card2" style="grid-column:1/-1;"><div style="color:var(--muted);font-size:11px;margin-bottom:4px;">ERFAHRUNG</div><div>${a.erfahrung}</div></div>
        <div class="card2" style="grid-column:1/-1;"><div style="color:var(--muted);font-size:11px;margin-bottom:4px;">WARUM ICH?</div><div>${a.warum}</div></div>
      </div>
      ${a.status==='offen'?`<div style="display:flex;gap:8px;">
        <button class="btn btn-success" onclick="decideApp('${a.user_id}','accept')" style="padding:8px 18px;">✅ Annehmen</button>
        <button class="btn btn-danger" onclick="decideApp('${a.user_id}','deny')" style="padding:8px 18px;">❌ Ablehnen</button>
      </div>`:''}
    </div>`).join('');
}

async function decideApp(uid, action) {
  const r = await api('/api/applications/'+action, 'POST', {user_id: uid});
  if(r.ok) { toast('✅ Erledigt!'); loadApplications(); }
  else toast('❌ Fehler', 'error');
}

// ── RSS ───────────────────────────────────────────────────────
async function loadRss() {
  const d = await api('/api/rss');
  const el = document.getElementById('rss-list');
  if(!d.feeds?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Feeds</div>'; return; }
  el.innerHTML = d.feeds.map(f => `
    <div class="table-row">
      <div style="font-size:24px;">📰</div>
      <div style="flex:1;"><div style="font-weight:700;">${f.name}</div><div style="color:var(--muted);font-size:12px;">${f.url.substring(0,60)}...</div></div>
      <span class="badge ${f.aktiv?'badge-green':'badge-muted'}">${f.aktiv?'Aktiv':'Pausiert'}</span>
      <button class="btn btn-danger" onclick="removeRss('${f.name}')" style="padding:7px 12px;font-size:12px;">✕</button>
    </div>`).join('');
}

async function removeRss(name) {
  if(!confirm('Feed "'+name+'" entfernen?')) return;
  const r = await api('/api/rss/'+encodeURIComponent(name), 'DELETE');
  if(r.ok) { toast('✅ Feed entfernt!'); loadRss(); }
  else toast('❌ Fehler', 'error');
}

// ── RL Teams ──────────────────────────────────────────────────
async function loadRlTeams() {
  const d = await api('/api/rl-teams');
  const el = document.getElementById('rl-teams-list');
  if(!d.teams?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Teams</div>'; return; }
  el.innerHTML = d.teams.map(t => `
    <div class="card2" style="margin-bottom:12px;">
      <div style="display:flex;align-items:center;gap:12px;">
        <div style="font-size:2.5rem;">🚗</div>
        <div style="flex:1;">
          <div style="font-weight:800;font-size:16px;">${t.name} <span class="badge badge-red">${t.format}</span></div>
          <div style="color:var(--muted);font-size:13px;">Captain: ${t.captain} • ${t.member_count} Member</div>
        </div>
        <div style="text-align:right;">
          <div style="font-weight:700;color:var(--green);">W: ${t.wins}</div>
          <div style="font-weight:700;color:var(--accent2);">L: ${t.losses}</div>
        </div>
      </div>
    </div>`).join('');
}

// ── Notifications ─────────────────────────────────────────────
async function loadNotifications() {
  const d = await api('/api/notifications');
  const el = document.getElementById('notif-list');
  if(!d.notifications?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Notifications</div>'; return; }
  el.innerHTML = d.notifications.map(n => `
    <div class="table-row">
      <div style="font-size:24px;">${n.type==='twitch'?'📺':'▶️'}</div>
      <div style="flex:1;"><div style="font-weight:700;">${n.name}</div></div>
      <span class="badge ${n.type==='twitch'?'badge-purple':'badge-red'}">${n.type.toUpperCase()}</span>
      <button class="btn btn-danger" onclick="removeNotif('${n._id}')" style="padding:7px 12px;font-size:12px;">✕</button>
    </div>`).join('');
}

async function removeNotif(id) {
  const r = await api('/api/notifications/'+id, 'DELETE');
  if(r.ok) { toast('✅ Entfernt!'); loadNotifications(); }
  else toast('❌ Fehler', 'error');
}

// ── Logs ──────────────────────────────────────────────────────
async function loadLogs() {
  const d = await api('/api/logs');
  const el = document.getElementById('logs-list');
  const emojis = {ban:'🔨',kick:'👢',warn:'⚠️',timeout:'⏰',unban:'✅',unwarn:'🔓'};
  const colors = {ban:'badge-red',kick:'badge-yellow',warn:'badge-yellow',timeout:'badge-blue',unban:'badge-green',unwarn:'badge-green'};
  if(!d.logs?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Logs</div>'; return; }
  el.innerHTML = d.logs.map(l => `
    <div class="table-row">
      <div style="font-size:20px;">${emojis[l.aktion]||'📋'}</div>
      <div style="flex:1;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="badge ${colors[l.aktion]||'badge-muted'}">${l.aktion}</span>
          <span style="color:var(--muted);font-size:12px;">Case #${l.case||'?'}</span>
        </div>
        <div style="color:var(--muted);font-size:13px;margin-top:3px;">${l.grund}</div>
      </div>
      <div style="color:var(--muted);font-size:12px;text-align:right;">${l.ts}</div>
    </div>`).join('');
}

// ── Settings ──────────────────────────────────────────────────
async function loadSettings() {
  const d = await api('/api/settings');
  if(!d.config) return;
  const c = d.config;
  document.getElementById('set-welcome-msg').value = c.welcome_msg || '';
  document.getElementById('set-goodbye-msg').value = c.goodbye_msg || '';
  document.getElementById('set-bot-status').value = c.custom_bot_status || '';
  document.getElementById('set-automod').checked = c.automod?.enabled || false;
  document.getElementById('set-anti-raid').checked = c.anti_raid || false;
  document.getElementById('set-starboard-min').value = c.starboard_min || 3;
  document.getElementById('set-slow-joiner').value = c.slow_joiner_minutes || 0;
}

async function saveSettings() {
  const data = {
    welcome_msg: document.getElementById('set-welcome-msg').value,
    goodbye_msg: document.getElementById('set-goodbye-msg').value,
    custom_bot_status: document.getElementById('set-bot-status').value,
    automod_enabled: document.getElementById('set-automod').checked,
    anti_raid: document.getElementById('set-anti-raid').checked,
    starboard_min: parseInt(document.getElementById('set-starboard-min').value)||3,
    slow_joiner_minutes: parseInt(document.getElementById('set-slow-joiner').value)||0,
  };
  const r = await api('/api/settings', 'POST', data);
  if(r.ok) toast('✅ Gespeichert!');
  else toast('❌ Fehler', 'error');
}

// ── Dashboard Logs ────────────────────────────────────────────
async function loadDashboardLogs() {
  const d = await api('/api/dashboard-logs');
  const el = document.getElementById('dlogs-list');
  if(!d.logs?.length) { el.innerHTML='<div style="color:var(--muted);text-align:center;padding:40px;">Keine Logs</div>'; return; }
  el.innerHTML = d.logs.map(l => `
    <div class="table-row">
      <div style="flex:1;"><div style="font-weight:600;">${l.aktion}</div><div style="color:var(--muted);font-size:12px;">${l.details}</div></div>
      <div style="color:var(--muted);font-size:12px;">${l.ts}</div>
    </div>`).join('');
}

// ── Modal Helper ──────────────────────────────────────────────
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
document.addEventListener('keydown', e => { if(e.key==='Escape') document.querySelectorAll('.modal.open').forEach(m=>m.classList.remove('open')); });

// Auto-load overview
window.addEventListener('load', () => loadOverview());
"""

PAGES = """
<!-- OVERVIEW -->
<div class="page active" id="page-overview">
  <div class="section-title">📊 Server Übersicht</div>
  <div class="grid grid-4" style="margin-bottom:24px;">
    <div class="stat-card red"><div class="stat-val" id="ov-users">…</div><div class="stat-label">Economy User</div><div class="stat-icon">👥</div></div>
    <div class="stat-card yellow"><div class="stat-val" id="ov-warns">…</div><div class="stat-label">Verwarnungen</div><div class="stat-icon">⚠️</div></div>
    <div class="stat-card blue"><div class="stat-val" id="ov-cases">…</div><div class="stat-label">Mod Cases</div><div class="stat-icon">📋</div></div>
    <div class="stat-card green"><div class="stat-val" id="ov-tickets">…</div><div class="stat-label">Tickets</div><div class="stat-icon">🎫</div></div>
    <div class="stat-card yellow"><div class="stat-val" id="ov-coins">…</div><div class="stat-label">Coins gesamt</div><div class="stat-icon">💰</div></div>
    <div class="stat-card purple"><div class="stat-val" id="ov-apps">…</div><div class="stat-label">Bewerbungen</div><div class="stat-icon">📝</div></div>
    <div class="stat-card pink"><div class="stat-val" id="ov-giveaways">…</div><div class="stat-label">Giveaways</div><div class="stat-icon">🎉</div></div>
    <div class="stat-card red"><div class="stat-val" id="ov-team">…</div><div class="stat-label">Team Member</div><div class="stat-icon">👑</div></div>
  </div>
</div>

<!-- MODERATION -->
<div class="page" id="page-moderation">
  <div class="section-title">🛡️ Moderation</div>
  <div class="card">
    <div style="display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;">
      <input id="warn-search" placeholder="🔍 User ID suchen..." style="max-width:280px;">
      <button class="btn btn-primary" onclick="searchUser()">Suchen</button>
      <button class="btn btn-ghost" onclick="loadModeration()">🔄 Alle</button>
    </div>
    <div id="warn-list">Lädt…</div>
  </div>
</div>

<!-- ECONOMY -->
<div class="page" id="page-economy">
  <div class="section-title">💰 Economy Leaderboard</div>
  <div class="card"><div id="eco-list">Lädt…</div></div>
</div>

<!-- GIVEAWAYS -->
<div class="page" id="page-giveaways">
  <div class="section-title">🎉 Giveaways</div>
  <div class="card"><div id="gw-list">Lädt…</div></div>
</div>

<!-- SUGGESTIONS -->
<div class="page" id="page-suggestions">
  <div class="section-title">💡 Vorschläge</div>
  <div class="card"><div id="suggest-list">Lädt…</div></div>
</div>

<!-- TEAM -->
<div class="page" id="page-team">
  <div class="section-title">👥 Team</div>
  <div class="card"><div id="team-list">Lädt…</div></div>
</div>

<!-- APPLICATIONS -->
<div class="page" id="page-applications">
  <div class="section-title">📝 Bewerbungen</div>
  <div class="card"><div id="app-list">Lädt…</div></div>
</div>

<!-- RSS -->
<div class="page" id="page-rss">
  <div class="section-title">📰 RSS Feeds</div>
  <div class="card"><div id="rss-list">Lädt…</div></div>
</div>

<!-- RL TEAMS -->
<div class="page" id="page-rl_teams">
  <div class="section-title">🚗 RL Teams</div>
  <div class="card"><div id="rl-teams-list">Lädt…</div></div>
</div>

<!-- NOTIFICATIONS -->
<div class="page" id="page-notifications">
  <div class="section-title">📣 Notifications</div>
  <div class="card"><div id="notif-list">Lädt…</div></div>
</div>

<!-- LOGS -->
<div class="page" id="page-logs">
  <div class="section-title">📋 Mod Logs</div>
  <div class="card"><div id="logs-list">Lädt…</div></div>
</div>

<!-- SETTINGS -->
<div class="page" id="page-settings">
  <div class="section-title">⚙️ Einstellungen</div>
  <div class="grid grid-2" style="margin-bottom:16px;">
    <div class="card">
      <div class="section-title" style="font-size:1rem;">💬 Nachrichten</div>
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div><label style="color:var(--muted);font-size:12px;display:block;margin-bottom:4px;">WILLKOMMEN</label><textarea id="set-welcome-msg" rows="2"></textarea></div>
        <div><label style="color:var(--muted);font-size:12px;display:block;margin-bottom:4px;">ABSCHIED</label><textarea id="set-goodbye-msg" rows="2"></textarea></div>
        <div><label style="color:var(--muted);font-size:12px;display:block;margin-bottom:4px;">BOT STATUS</label><input id="set-bot-status" placeholder="z.B. RLD Server | /help"></div>
      </div>
    </div>
    <div class="card">
      <div class="section-title" style="font-size:1rem;">🛡️ Sicherheit</div>
      <div style="display:flex;flex-direction:column;gap:16px;">
        <label style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:12px;background:var(--card2);border-radius:8px;"><input type="checkbox" id="set-automod"> <div><div style="font-weight:600;">Auto-Mod</div><div style="color:var(--muted);font-size:12px;">Spam, Caps, Links filtern</div></div></label>
        <label style="display:flex;align-items:center;gap:10px;cursor:pointer;padding:12px;background:var(--card2);border-radius:8px;"><input type="checkbox" id="set-anti-raid"> <div><div style="font-weight:600;">Anti-Raid</div><div style="color:var(--muted);font-size:12px;">Massen-Beitritt blockieren</div></div></label>
        <div style="display:flex;gap:12px;">
          <div style="flex:1;"><label style="color:var(--muted);font-size:12px;display:block;margin-bottom:4px;">STARBOARD MIN ⭐</label><input id="set-starboard-min" type="number" style="width:100%;"></div>
          <div style="flex:1;"><label style="color:var(--muted);font-size:12px;display:block;margin-bottom:4px;">SLOW JOINER (Min)</label><input id="set-slow-joiner" type="number" style="width:100%;"></div>
        </div>
      </div>
    </div>
  </div>
  <button class="btn btn-primary" onclick="saveSettings()" style="font-size:15px;padding:12px 28px;">💾 Einstellungen speichern</button>
</div>

<!-- DASHBOARD LOGS -->
<div class="page" id="page-dashboard_logs">
  <div class="section-title">🔍 Dashboard Aktivitäten</div>
  <div class="card"><div id="dlogs-list">Lädt…</div></div>
</div>

<!-- MODALS -->
<div class="modal" id="coin-modal">
  <div class="modal-box">
    <div style="font-size:1.2rem;font-weight:800;margin-bottom:20px;">💰 Coins bearbeiten: <span id="coin-modal-name"></span></div>
    <input type="hidden" id="coin-uid">
    <input id="coin-amount" type="number" placeholder="Menge (negativ zum Entfernen)" style="margin-bottom:16px;">
    <div style="display:flex;gap:10px;">
      <button class="btn btn-primary" onclick="saveCoins()" style="flex:1;">Speichern</button>
      <button class="btn btn-ghost" onclick="closeModal('coin-modal')" style="flex:1;">Abbrechen</button>
    </div>
  </div>
</div>
"""

def build_page(uid, username, avatar):
    nav_sections = [
        ("", [("overview","📊","Übersicht")]),
        ("MODERATION", [("moderation","🛡️","Verwarnungen"),("logs","📋","Mod Logs")]),
        ("COMMUNITY", [("economy","💰","Economy"),("giveaways","🎉","Giveaways"),("suggestions","💡","Vorschläge"),("rss","📰","RSS Feeds")]),
        ("TEAM", [("team","👥","Team"),("applications","📝","Bewerbungen")]),
        ("ROCKET LEAGUE", [("rl_teams","🚗","RL Teams")]),
        ("BOT", [("notifications","📣","Notifications"),("settings","⚙️","Einstellungen"),("dashboard_logs","🔍","Dashboard Log")]),
    ]
    sidebar = ""
    for section, items in nav_sections:
        if section: sidebar += f'<div class="sidebar-section">{section}</div>'
        for key, icon, label in items:
            sidebar += f'<div class="sidebar-item" id="nav-{key}" onclick="showPage(\'{key}\')">' \
                       f'<span class="icon">{icon}</span>{label}</div>'

    return f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RLD Main Bot Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<nav class="nav">
  <div class="nav-logo">
    <div class="nav-logo-icon">🔴</div>
    <div>
      <div class="nav-logo-text">RLD Main Bot</div>
      <div class="nav-logo-sub">Dashboard</div>
    </div>
  </div>
  <div class="nav-credit">Made by <strong style="color:var(--accent2);">Rezyel83</strong> ❤️ AI</div>
  <div class="nav-user">
    {'<img src="'+avatar+'" onerror="this.style.display=\'none\'">' if avatar else ''}
    <span style="font-weight:700;">{username}</span>
    <a href="/logout" class="nav-logout">Ausloggen</a>
  </div>
</nav>
<div class="layout">
  <aside class="sidebar">{sidebar}</aside>
  <main class="main">{PAGES}</main>
</div>
<footer>Made by <strong style="color:var(--accent2);">Rezyel83</strong> with ❤️ & AI &nbsp;•&nbsp; RLD Main Bot Dashboard</footer>
<div class="toast" id="toast"></div>
<script>{JS}</script>
</body></html>"""

# ── Routes ─────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if get_uid(request): return RedirectResponse("/dashboard")
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RLD Main Bot</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>{CSS}
.particle{{position:absolute;border-radius:50%;animation:rise linear infinite;}}
@keyframes rise{{0%{{transform:translateY(100vh) rotate(0deg);opacity:0}}10%{{opacity:.6}}90%{{opacity:.6}}100%{{transform:translateY(-100px) rotate(360deg);opacity:0}}}}
</style></head>
<body class="login-page" style="overflow:hidden;">
<div id="particles" style="position:fixed;inset:0;pointer-events:none;z-index:0;"></div>
<div class="login-card" style="position:relative;z-index:1;">
  <div class="login-glow">🔴</div>
  <h1 style="font-size:2.2rem;font-weight:900;margin-bottom:10px;background:linear-gradient(135deg,var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">RLD Main Bot</h1>
  <p style="color:var(--muted);margin-bottom:8px;font-size:15px;line-height:1.6;">Das offizielle Admin-Dashboard für den</p>
  <p style="color:var(--accent2);font-weight:800;font-size:16px;margin-bottom:32px;">🚗 Rocket League Deutschland Server</p>
  <a href="https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={DISCORD_REDIRECT_URI}&response_type=code&scope=identify" class="btn-discord" style="background:linear-gradient(135deg,var(--accent),#991b1b);box-shadow:0 8px 24px rgba(220,38,38,.4);">
    <svg width="22" height="22" viewBox="0 0 71 55" fill="white"><path d="M60.1 4.9A58.5 58.5 0 0045.6 1a40 40 0 00-1.8 3.6 54.2 54.2 0 00-16.2 0A40 40 0 0025.8 1 58.3 58.3 0 0011.3 5C1.6 19.7-1 34 .3 48a59 59 0 0017.9 9 42.4 42.4 0 003.7-5.9 38.3 38.3 0 01-5.8-2.8l1.4-1.1a42 42 0 0036 0l1.4 1.1a38.4 38.4 0 01-5.8 2.8 42 42 0 003.6 6 58.8 58.8 0 0018-9.1C72.2 32 68.4 17.7 60.1 4.9zM23.8 39.3c-3.5 0-6.4-3.2-6.4-7.1s2.8-7.1 6.4-7.1c3.5 0 6.4 3.2 6.3 7.1 0 3.9-2.8 7.1-6.3 7.1zm23.4 0c-3.5 0-6.4-3.2-6.4-7.1s2.8-7.1 6.4-7.1c3.5 0 6.4 3.2 6.3 7.1 0 3.9-2.8 7.1-6.3 7.1z"/></svg>
    Mit Discord einloggen
  </a>
  <p style="color:var(--muted);font-size:12px;margin-top:24px;">Nur für autorisierte Admins</p>
</div>
<script>
const p=document.getElementById('particles');
for(let i=0;i<25;i++){{
  const d=document.createElement('div');d.className='particle';
  const s=Math.random()*8+2;
  d.style.cssText=`width:${{s}}px;height:${{s}}px;left:${{Math.random()*100}}%;bottom:-10px;background:rgba(${{Math.random()>.5?'220,38,38':'248,113,113'}},${{Math.random()*.3+.05}});animation-duration:${{Math.random()*20+10}}s;animation-delay:${{Math.random()*15}}s;`;
  p.appendChild(d);
}}
</script>
</body></html>""")

@app.get("/callback")
async def callback(code: str):
    uid = avatar = username = ""
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post("https://discord.com/api/oauth2/token", data={
                "client_id": DISCORD_CLIENT_ID, "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code", "code": code, "redirect_uri": DISCORD_REDIRECT_URI,
            }) as r:
                data = await r.json()
            token = data.get("access_token")
            if not token: return HTMLResponse("<h1>Login fehlgeschlagen</h1>")
            async with session.get("https://discord.com/api/users/@me", headers={"Authorization": f"Bearer {token}"}) as r2:
                user = await r2.json()
            uid = user.get("id","")
            if not uid: return HTMLResponse("<h1>Fehler</h1>")
            ah = user.get("avatar")
            avatar = f"https://cdn.discordapp.com/avatars/{uid}/{ah}.png" if ah else ""
            username = user.get("global_name") or user.get("username","")
            print(f"✅ Login: {username} ({uid})")
    except Exception as e:
        print(f"❌ OAuth: {e}")
        return HTMLResponse(f"<h1>Fehler: {e}</h1>")
    if int(uid) != BOT_OWNER_ID:
        return HTMLResponse("<h1>❌ Kein Zugriff</h1><p>Nur für Admins.</p>")
    resp = RedirectResponse("/dashboard", status_code=302)
    resp.set_cookie("session", make_token(uid), max_age=86400*7, httponly=True, samesite="lax", secure=True)
    resp.set_cookie("uid", uid, max_age=86400*7, samesite="lax", secure=True)
    resp.set_cookie("avatar", avatar, max_age=86400*7, samesite="lax", secure=True)
    resp.set_cookie("username", username, max_age=86400*7, samesite="lax", secure=True)
    return resp

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    uid = get_uid(request)
    if not uid: return RedirectResponse("/")
    if int(uid) != BOT_OWNER_ID:
        return HTMLResponse("<h1>❌ Kein Zugriff</h1>")
    username = request.cookies.get("username","Admin")
    avatar = request.cookies.get("avatar","")
    return HTMLResponse(build_page(uid, username, avatar))

@app.get("/logout")
async def logout():
    r = RedirectResponse("/")
    for c in ["session","uid","avatar","username"]: r.delete_cookie(c)
    return r

@app.get("/health")
async def health(): return {"status":"ok"}

# ── API ────────────────────────────────────────────────────────
@app.get("/api/overview")
async def api_overview(request: Request):
    auth_check(request)
    return {
        "total_users": await economy_col.count_documents({"guild_id": GUILD_ID}),
        "total_warns": await warns_col.count_documents({"guild_id": GUILD_ID}),
        "total_cases": await cases_col.count_documents({"guild_id": GUILD_ID}),
        "total_tickets": await tickets_col.count_documents({"guild_id": GUILD_ID}),
        "total_apps": await apps_col.count_documents({"guild_id": GUILD_ID, "status": "offen"}),
        "total_giveaways": await giveaway_col.count_documents({"guild_id": GUILD_ID, "active": True}),
        "total_team": await team_col.count_documents({"guild_id": GUILD_ID, "aktiv": True}),
        "total_coins": (await economy_col.aggregate([{"$match":{"guild_id":GUILD_ID}},{"$group":{"_id":None,"t":{"$sum":"$coins"}}}]).to_list(1) or [{"t":0}])[0]["t"],
    }

@app.get("/api/moderation/warns")
async def api_warns(request: Request, user_id: str = None):
    auth_check(request)
    query = {"guild_id": GUILD_ID}
    if user_id: query["user_id"] = int(user_id)
    warns = await warns_col.find(query).sort("ts",-1).limit(50).to_list(50)
    result = []
    for w in warns:
        name, av = await get_username(w.get("user_id",0))
        mod_name, _ = await get_username(w.get("mod_id",0))
        result.append({"id":str(w["_id"]),"user_id":str(w.get("user_id")),"username":name,"avatar":av,"mod":mod_name,"grund":w.get("grund","?"),"ts":w["ts"].strftime("%d.%m %H:%M") if isinstance(w.get("ts"),datetime) else "?"})
    return {"warns": result}

@app.delete("/api/moderation/warn/{warn_id}")
async def api_delete_warn(warn_id: str, request: Request):
    from bson import ObjectId
    uid = auth_check(request)
    await warns_col.delete_one({"_id": ObjectId(warn_id)})
    await dashboard_log(uid, "warn_delete", warn_id)
    return {"ok": True}

@app.get("/api/economy/leaderboard")
async def api_eco_lb(request: Request):
    auth_check(request)
    users = await economy_col.find({"guild_id":GUILD_ID}).sort("coins",-1).limit(20).to_list(20)
    result = []
    for u in users:
        name, av = await get_username(u["user_id"])
        result.append({"user_id":str(u["user_id"]),"username":name,"avatar":av,"coins":u.get("coins",0),"bank":u.get("bank",0),"rep":u.get("rep",0)})
    return {"users": result}

@app.post("/api/economy/coins")
async def api_eco_coins(request: Request):
    uid = auth_check(request)
    body = await request.json()
    target = int(body.get("user_id",0)); amount = int(body.get("amount",0))
    await economy_col.update_one({"guild_id":GUILD_ID,"user_id":target},{"$inc":{"coins":amount}},upsert=True)
    await dashboard_log(uid,"eco_coins",f"User {target}: {amount:+}")
    return {"ok":True}

@app.get("/api/giveaways")
async def api_giveaways(request: Request):
    auth_check(request)
    gws = await giveaway_col.find({"guild_id":GUILD_ID}).sort("ends_at",-1).limit(20).to_list(20)
    return {"giveaways":[{"preis":g.get("preis"),"gewinner":g.get("gewinner",1),"active":g.get("active",False),"ends_at":g["ends_at"].strftime("%d.%m %H:%M") if isinstance(g.get("ends_at"),datetime) else "?"} for g in gws]}

@app.get("/api/suggestions")
async def api_suggestions(request: Request):
    auth_check(request)
    sugs = await suggest_col.find({"guild_id":GUILD_ID}).sort("ts",-1).limit(30).to_list(30)
    result = []
    for s in sugs:
        name, av = await get_username(s.get("user_id",0))
        result.append({"message_id":str(s.get("message_id")),"user_id":str(s.get("user_id")),"username":name,"avatar":av,"vorschlag":s.get("vorschlag",""),"status":s.get("status","offen"),"ts":s["ts"].strftime("%d.%m %H:%M") if isinstance(s.get("ts"),datetime) else "?"})
    return {"suggestions": result}

@app.post("/api/suggestions/{action}")
async def api_suggest_action(action: str, request: Request):
    uid = auth_check(request)
    body = await request.json()
    status = "angenommen" if action=="accept" else "abgelehnt"
    await suggest_col.update_one({"message_id":int(body.get("message_id",0))},{"$set":{"status":status}})
    await dashboard_log(uid,f"suggest_{action}",str(body.get("message_id")))
    return {"ok":True}

@app.get("/api/team")
async def api_team(request: Request):
    auth_check(request)
    members = await team_col.find({"guild_id":GUILD_ID,"aktiv":True}).to_list(50)
    result = []
    for m in members:
        name, av = await get_username(m["user_id"])
        result.append({"user_id":str(m["user_id"]),"username":name,"avatar":av,"rolle":m.get("rolle","?"),"joined":m["joined"].strftime("%d.%m.%Y") if isinstance(m.get("joined"),datetime) else "?","abmeldungen":m.get("abmeldungen",[])})
    return {"members": result}

@app.delete("/api/team/{user_id}")
async def api_team_remove(user_id: str, request: Request):
    uid = auth_check(request)
    await team_col.delete_one({"guild_id":GUILD_ID,"user_id":int(user_id)})
    await dashboard_log(uid,"team_remove",user_id)
    return {"ok":True}

@app.get("/api/applications")
async def api_applications(request: Request):
    auth_check(request)
    apps = await apps_col.find({"guild_id":GUILD_ID}).sort("ts",-1).limit(30).to_list(30)
    result = []
    for a in apps:
        name, av = await get_username(a["user_id"])
        result.append({"user_id":str(a["user_id"]),"username":name,"avatar":av,"alter":a.get("alter","?"),"erfahrung":a.get("erfahrung","?"),"warum":a.get("warum","?"),"verfuegbarkeit":a.get("verfuegbarkeit","?"),"status":a.get("status","offen"),"ts":a["ts"].strftime("%d.%m %H:%M") if isinstance(a.get("ts"),datetime) else "?"})
    return {"applications": result}

@app.post("/api/applications/{action}")
async def api_app_action(action: str, request: Request):
    uid = auth_check(request)
    body = await request.json()
    target = int(body.get("user_id",0))
    status = "angenommen" if action=="accept" else "abgelehnt"
    await apps_col.update_one({"guild_id":GUILD_ID,"user_id":target,"status":"offen"},{"$set":{"status":status}})
    await dashboard_log(uid,f"app_{action}",str(target))
    return {"ok":True}

@app.get("/api/rss")
async def api_rss(request: Request):
    auth_check(request)
    feeds = await rss_col.find({"guild_id":GUILD_ID}).to_list(30)
    return {"feeds":[{"name":f.get("name"),"url":f.get("url",""),"aktiv":f.get("aktiv",True)} for f in feeds]}

@app.delete("/api/rss/{name}")
async def api_rss_remove(name: str, request: Request):
    uid = auth_check(request)
    await rss_col.delete_one({"guild_id":GUILD_ID,"name":name})
    await dashboard_log(uid,"rss_remove",name)
    return {"ok":True}

@app.get("/api/rl-teams")
async def api_rl_teams(request: Request):
    auth_check(request)
    teams = await rl_teams_col.find({"guild_id":GUILD_ID}).to_list(30)
    result = []
    for t in teams:
        cap_name, _ = await get_username(t.get("captain_id",0))
        result.append({"name":t.get("name"),"format":t.get("format","3v3"),"captain":cap_name,"member_count":len(t.get("members",[])),"wins":t.get("wins",0),"losses":t.get("losses",0)})
    return {"teams": result}

@app.get("/api/notifications")
async def api_notifications(request: Request):
    auth_check(request)
    notifs = await notif_col.find({"guild_id":GUILD_ID}).to_list(30)
    return {"notifications":[{"_id":str(n["_id"]),"type":n.get("type"),"name":n.get("name")} for n in notifs]}

@app.delete("/api/notifications/{notif_id}")
async def api_notif_remove(notif_id: str, request: Request):
    from bson import ObjectId
    uid = auth_check(request)
    await notif_col.delete_one({"_id":ObjectId(notif_id)})
    await dashboard_log(uid,"notif_remove",notif_id)
    return {"ok":True}

@app.get("/api/logs")
async def api_logs(request: Request):
    auth_check(request)
    logs = await cases_col.find({"guild_id":GUILD_ID}).sort("ts",-1).limit(50).to_list(50)
    return {"logs":[{"case":l.get("case"),"aktion":l.get("aktion"),"grund":l.get("grund","?"),"ts":l["ts"].strftime("%d.%m %H:%M") if isinstance(l.get("ts"),datetime) else "?"} for l in logs]}

@app.get("/api/settings")
async def api_settings(request: Request):
    auth_check(request)
    cfg = await config_col.find_one({"guild_id":GUILD_ID}) or {}
    cfg.pop("_id",None)
    return {"config":cfg}

@app.post("/api/settings")
async def api_settings_save(request: Request):
    uid = auth_check(request)
    body = await request.json()
    await config_col.update_one({"guild_id":GUILD_ID},{"$set":{"welcome_msg":body.get("welcome_msg"),"goodbye_msg":body.get("goodbye_msg"),"custom_bot_status":body.get("custom_bot_status"),"anti_raid":body.get("anti_raid",False),"starboard_min":body.get("starboard_min",3),"slow_joiner_minutes":body.get("slow_joiner_minutes",0),"automod.enabled":body.get("automod_enabled",False)}},upsert=True)
    await dashboard_log(uid,"settings_save","Einstellungen gespeichert")
    return {"ok":True}

@app.get("/api/dashboard-logs")
async def api_dashboard_logs(request: Request):
    auth_check(request)
    logs = await dashboard_log_col.find({}).sort("ts",-1).limit(50).to_list(50)
    return {"logs":[{"user_id":str(l.get("user_id")),"aktion":l.get("aktion"),"details":l.get("details",""),"ts":l["ts"].strftime("%d.%m %H:%M") if isinstance(l.get("ts"),datetime) else "?"} for l in logs]}
