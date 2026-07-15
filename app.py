import os, time
from datetime import timedelta
from flask import Flask, session, redirect, url_for
import requests as hr

DAPI = "https://discord.com/api/v10"
_ugc: dict = {}
_bgc: tuple = ([], 0.0)
_GTTL = 60

def dget(ep, token=None, isbot=False):
    hd = {"User-Agent": "RLD/1.0"}
    bot_token = os.getenv("DISCORD_BOT_TOKEN", "")
    if isbot: hd["Authorization"] = f"Bot {bot_token}"
    elif token: hd["Authorization"] = f"Bearer {token}"
    else: return None
    try:
        r = hr.get(f"{DAPI}{ep}", headers=hd, timeout=6)
        return r.json() if r.ok else None
    except: return None

def uguilds(tok) -> list:
    now = time.monotonic()
    if tok in _ugc:
        d, ts = _ugc[tok]
        if now - ts < _GTTL: return d
    d = dget("/users/@me/guilds", token=tok) or []
    if len(_ugc) > 100:
        del _ugc[min(_ugc, key=lambda k: _ugc[k][1])]
    _ugc[tok] = (d, now)
    return d

def bguilds() -> list:
    global _bgc
    now = time.monotonic()
    if now - _bgc[1] < _GTTL: return _bgc[0]
    d = dget("/users/@me/guilds", isbot=True) or []
    _bgc = (d, now)
    return d

def get_member_name(guild_id, user_id, bot=None):
    if bot:
        g = bot.get_guild(int(guild_id))
        if g:
            m = g.get_member(int(user_id))
            if m: return f"{m.display_name} / {user_id}"
    u = dget(f"/users/{user_id}", isbot=True)
    if u: return f"{u.get('username', user_id)} / {user_id}"
    return str(user_id)

def runasync(coro, bot, timeout=6):
    import asyncio as _a
    try:
        loop = bot.loop
        if loop is None or not loop.is_running(): return None
        fut = _a.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)
    except Exception:
        return None

SHARED_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--r:#ef4444;--rd:#dc2626;--bg:#0f0f0f;--bg2:#1a1a1a;--bg3:#262626;--tx:#fff;--tx2:#a1a1aa;--bdr:#333;--or:#f97316;--ord:#ea6c00}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;line-height:1.6}
a{color:inherit;text-decoration:none}
.nav{background:var(--bg2);border-bottom:1px solid var(--bdr);padding:.875rem 1.5rem;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}
.logo{font-size:1.1rem;font-weight:700;color:var(--r)}
.nav-r{display:flex;gap:.75rem;align-items:center;color:var(--tx2)}
.wrap{display:flex;min-height:calc(100vh - 53px)}
.side{width:220px;background:var(--bg2);border-right:1px solid var(--bdr);padding:1rem .75rem;flex-shrink:0}
.sl{display:flex;align-items:center;gap:.5rem;padding:.55rem .75rem;color:var(--tx2);border-radius:6px;margin-bottom:.2rem;font-size:.875rem;transition:all .15s}
.sl:hover,.sl.on{background:rgba(239,68,68,.12);color:var(--r)}
.sl.on.orange-nav{background:rgba(249,115,22,.12);color:var(--or)}
.main{flex:1;padding:1.5rem;overflow-y:auto}
.pt{font-size:1.5rem;font-weight:700;margin-bottom:.25rem}
.ps{color:var(--tx2);margin-bottom:1.25rem}
.card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:1.25rem;margin-bottom:1.25rem}
.card.orange{border-color:rgba(249,115,22,.3)}
.ct{font-size:1rem;font-weight:600;margin-bottom:.875rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:1.25rem}
.stat{background:var(--bg2);border:1px solid var(--bdr);border-top:3px solid var(--r);border-radius:10px;padding:1.125rem}
.stat.orange{border-top-color:var(--or)}
.sv{font-size:1.75rem;font-weight:700}
.sl2{color:var(--tx2);font-size:.8rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1rem;border-radius:7px;font-size:.85rem;font-weight:500;border:none;cursor:pointer;transition:all .15s}
.bp{background:var(--r);color:#fff}.bp:hover{background:var(--rd)}
.bo{background:var(--or);color:#fff}.bo:hover{background:var(--ord)}
.bs{background:var(--bg3);color:var(--tx)}.bs:hover{background:var(--bdr)}
.bd{background:#7f1d1d;color:#fff}.bd:hover{background:#991b1b}
.bg-btn{background:rgba(34,197,94,.15);color:#22c55e;border:1px solid rgba(34,197,94,.3)}.bg-btn:hover{background:rgba(34,197,94,.25)}
.bsm{padding:.3rem .65rem;font-size:.78rem}
.inp,.sel,.ta{width:100%;padding:.6rem .85rem;background:var(--bg3);border:1px solid var(--bdr);border-radius:7px;color:var(--tx);font-size:.85rem;transition:border .15s}
.inp:focus,.sel:focus,.ta:focus{outline:none;border-color:var(--r)}
.ta{min-height:80px;resize:vertical}
.lbl{display:block;margin-bottom:.35rem;font-size:.82rem;color:var(--tx2)}
.fg{margin-bottom:.875rem}
.tbl{width:100%;border-collapse:collapse}
.tbl th{text-align:left;padding:.65rem .875rem;color:var(--tx2);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bdr)}
.tbl td{padding:.8rem .875rem;border-bottom:1px solid var(--bdr)}
.tbl tr:hover{background:rgba(255,255,255,.02)}
.bdg{padding:.18rem .55rem;border-radius:20px;font-size:.72rem;font-weight:500}
.bg{background:rgba(34,197,94,.15);color:#22c55e}
.br{background:rgba(220,38,38,.15);color:#f87171}
.bb{background:rgba(59,130,246,.15);color:#60a5fa}
.bor{background:rgba(249,115,22,.15);color:#fb923c}
.al{padding:.8rem 1rem;border-radius:7px;margin-bottom:.875rem}
.aok{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);color:#22c55e}
.aer{background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.25);color:#f87171}
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1.1rem}
.sc{background:var(--bg2);border:1px solid var(--bdr);border-radius:12px;padding:1.1rem;transition:all .2s}
.sc:hover{border-color:var(--r);transform:translateY(-2px)}
.si{width:50px;height:50px;border-radius:10px;background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:1.1rem;font-weight:700;margin-bottom:.75rem;border:1px solid var(--bdr)}
.sn{font-weight:600;margin-bottom:.2rem}
.ss{color:var(--tx2);font-size:.82rem}
.lw{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0f0f0f,#1a0a0a)}
.lc{background:var(--bg2);border:1px solid var(--bdr);border-radius:16px;padding:2.25rem;text-align:center;max-width:360px;width:90%}
.lt{font-size:1.4rem;font-weight:700;margin-bottom:.3rem}
.ls{color:var(--tx2);margin-bottom:1.5rem}
.db{background:#5865F2;color:#fff;width:100%;justify-content:center;padding:.8rem;border-radius:10px;font-size:.9rem}.db:hover{background:#4752c4}
.footer{text-align:center;padding:1rem;color:var(--tx2);font-size:.78rem;border-top:1px solid var(--bdr);margin-top:2rem}
.tag{display:inline-flex;align-items:center;gap:.3rem;padding:.2rem .6rem;border-radius:20px;font-size:.75rem;font-weight:500}
.tag-green{background:rgba(34,197,94,.15);color:#22c55e}
.tag-red{background:rgba(220,38,38,.15);color:#f87171}
.tag-blue{background:rgba(59,130,246,.15);color:#60a5fa}
.tag-orange{background:rgba(249,115,22,.15);color:#fb923c}
.tag-gray{background:rgba(161,161,170,.15);color:#a1a1aa}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:200;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:var(--bg2);border:1px solid var(--bdr);border-radius:12px;padding:1.5rem;width:90%;max-width:480px}
.modal-title{font-size:1.1rem;font-weight:700;margin-bottom:1rem}
.divider{border:none;border-top:1px solid var(--bdr);margin:1rem 0}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:.4rem}
.status-online{background:#22c55e}
.status-offline{background:#ef4444}
.status-idle{background:#f59e0b}
.perm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:.75rem;margin-top:.875rem}
.perm-item{background:var(--bg3);border:1px solid var(--bdr);border-radius:8px;padding:.875rem;display:flex;justify-content:space-between;align-items:center;font-size:.82rem}
.pbtns{display:flex;gap:.35rem}
.pb{width:28px;height:28px;border:none;border-radius:5px;cursor:pointer;font-size:.7rem;transition:all .15s}
.pa{background:rgba(34,197,94,.2);color:#22c55e}.pa.on{background:#22c55e;color:#fff}
.pn{background:rgba(161,161,170,.2);color:var(--tx2)}.pn.on{background:var(--tx2);color:#000}
.pd{background:rgba(220,38,38,.2);color:#f87171}.pd.on{background:#ef4444;color:#fff}
@media(max-width:700px){.side{display:none}.main{padding:1rem}}
"""

BASE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RLD Dashboard</title>
<style>{css}</style>
</head>
<body>
{body}
<div class="footer">RLD Dashboard &mdash; Made by Rezyel &bull; &copy; 2026</div>
</body>
</html>"""

def pg(body, css_extra=""):
    return BASE_HTML.format(css=SHARED_CSS + css_extra, body=body)

def alerts():
    from flask import get_flashed_messages
    ms = get_flashed_messages(with_categories=True)
    return "".join(
        f'<div class="al {"aok" if c == "success" else "aer"}">{m}</div>'
        for c, m in ms
    )

def sidebar(gid, active, orange=False):
    cls = "orange-nav" if orange else ""
    links = [
        ("📊", "Übersicht", "ov"),
        ("🛡️", "Moderation", "mod"),
        ("💰", "Economy", "eco"),
        ("🎁", "Giveaways", "gws"),
        ("💡", "Vorschläge", "sugg"),
        ("👥", "Team", "team"),
        ("📝", "Bewerbungen", "apps"),
        ("📰", "RSS", "rss"),
        ("🚗", "RL Teams", "rl"),
        ("🔔", "Notifications", "notif"),
        ("🔐", "Channel-Rechte", "chperms"),
        ("💬", "Kanäle", "channels"),
        ("🎭", "Rollen", "roles"),
        ("📋", "Mod Logs", "mlogs"),
        ("🔢", "Counting", "counting"),
        ("⚙️", "Einstellungen", "sett"),
    ]
    _tb = ' target="_blank"'
    items = "".join(
        '<a href="/g/{g}/{e}" class="sl{o}"{t}>{i} {l}</a>'.format(
            g=gid, e=ep, o=("  on " + cls if ep == active else ""),
            t=(_tb if ep == "rl" else ""), i=ic, l=lb
        )
        for ic, lb, ep in links
    )
    return f'<aside class="side">{items}</aside>'

def guild_nav(gid, bot=None):
    g = dget(f"/guilds/{gid}", isbot=True) or {"name": gid}
    name = g.get("name", gid)
    username = session.get("username", "")
    return (
        f'<nav class="nav">'
        f'<div class="logo">🤖 {name}</div>'
        f'<div class="nav-r">'
        f'<a href="/dash" class="btn bs bsm">← Zurück</a>'
        f'<span>{username}</span>'
        f'<a href="/logout" class="btn bs bsm">Abmelden</a>'
        f'</div></nav>'
    ), g

def create_app(bot_instance):
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "")
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12)
    )
    app.bot = bot_instance

    import importlib
    for mod in ["auth","overview","moderation","economy","giveaways","suggestions","team",
                "applications","rss","rl_teams","notifications","channel_perms","channels",
                "mod_logs","settings","roles","counting","rl_bracket"]:
        try:
            m = importlib.import_module(f"dashboard.{mod}")
            app.register_blueprint(m.bp)
        except Exception as e:
            print(f"Dashboard import error {mod}: {e}")

    from flask import jsonify
    from datetime import datetime

    @app.route("/")
    def idx(): return redirect(url_for("auth.login"))

    @app.route("/ping")
    def ping(): return jsonify({"status": "alive", "time": datetime.utcnow().isoformat()})

    @app.route("/health")
    def health():
        ping_ms = round(bot_instance.latency * 1000) if bot_instance.is_ready() else -1
        return jsonify({"status": "ok", "ping_ms": ping_ms})

    @app.route("/api/bot-status")
    def bot_status():
        import requests as _hr, time as _t
        main_ok = bot_instance.is_ready()
        ping = round(bot_instance.latency * 1000) if main_ok else -1
        level_ok = False; level_ping = -1
        try:
            t0 = _t.monotonic()
            r = _hr.get("https://level-bot-h7jj.onrender.com/health", timeout=5)
            level_ping = round((_t.monotonic() - t0) * 1000)
            level_ok = r.status_code == 200
        except: pass
        return jsonify({"main": {"online": main_ok, "ping": ping}, "level": {"online": level_ok, "ping": level_ping}})

    return app