from flask import Blueprint, session, redirect, url_for, request, flash
from urllib.parse import quote
import requests as hr
import os, time

bp = Blueprint("auth", __name__)

DAPI = "https://discord.com/api/v10"
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:10000/callback")

def _pg(body):
    from dashboard import pg
    return pg(body)

def _al():
    from dashboard import alerts
    return alerts()

def _bguilds():
    from dashboard import bguilds
    return bguilds()

def _uguilds(tok):
    from dashboard import uguilds
    return uguilds(tok)

@bp.route("/login")
def login():
    if "user_id" in session:
        return redirect(url_for("auth.dash"))
    sc = "identify guilds"
    au = (f"https://discord.com/api/oauth2/authorize"
          f"?client_id={DISCORD_CLIENT_ID}"
          f"&redirect_uri={quote(DISCORD_REDIRECT_URI)}"
          f"&response_type=code&scope={quote(sc)}")
    body = (
        '<div class="lw">'
        '<div class="lc">'
        '<div style="font-size:2.5rem;margin-bottom:.875rem">🤖</div>'
        '<h1 class="lt">RLD Dashboard</h1>'
        '<p class="ls">Melde dich mit Discord an um fortzufahren</p>'
        + _al() +
        f'<a href="{au}" class="btn db">Mit Discord anmelden</a>'
        '</div></div>'
    )
    return _pg(body)

@bp.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("Kein Code erhalten.", "error")
        return redirect(url_for("auth.login"))
    try:
        r = hr.post(f"{DAPI}/oauth2/token", data={
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": DISCORD_REDIRECT_URI
        }, timeout=8)
        tok = r.json()
    except:
        flash("API Fehler.", "error")
        return redirect(url_for("auth.login"))
    if not r.ok:
        flash("Token Fehler.", "error")
        return redirect(url_for("auth.login"))
    from dashboard import dget
    u = dget("/users/@me", token=tok["access_token"])
    if not u:
        flash("User Fehler.", "error")
        return redirect(url_for("auth.login"))
    session.permanent = True
    session.update({
        "user_id": u["id"],
        "username": u["username"],
        "avatar": u.get("avatar"),
        "access_token": tok["access_token"]
    })
    return redirect(url_for("auth.dash"))

@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

@bp.route("/dash")
def dash():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))
    from flask import current_app
    bot = current_app.bot
    ug = _uguilds(session["access_token"])
    bg = {g["id"] for g in _bguilds()}
    gs = [g for g in ug if g["id"] in bg and (
        int(g.get("permissions", 0)) & 0x8 or int(g.get("permissions", 0)) & 0x20
    )]

    # Server cards
    cards = ""
    for g in gs:
        icon = ""
        if g.get("icon"):
            icon = f'<img src="https://cdn.discordapp.com/icons/{g["id"]}/{g["icon"]}.png" style="width:50px;height:50px;border-radius:10px;object-fit:cover;margin-bottom:.75rem;">'
        else:
            icon = f'<div class="si">{g["name"][:2]}</div>'
        cards += (
            f'<a href="/g/{g["id"]}/ov" class="sc">'
            f'{icon}'
            f'<div class="sn">{g["name"]}</div>'
            f'<div class="ss">Verwalten →</div>'
            f'</a>'
        )
    cards += (
        f'<a href="https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}'
        f'&permissions=8&scope=bot%20applications.commands" target="_blank" '
        f'class="sc" style="opacity:.55;border-style:dashed">'
        f'<div class="si" style="border-style:dashed;font-size:1.5rem">+</div>'
        f'<div class="sn">Bot hinzufügen</div>'
        f'<div class="ss">Server einladen</div>'
        f'</a>'
    )

    # Bot status
    ping_ms = round(bot.latency * 1000) if bot.is_ready() else -1
    status_dot = '<span class="status-dot status-online"></span>' if bot.is_ready() else '<span class="status-dot status-offline"></span>'
    status_txt = f"Online ({ping_ms}ms)" if bot.is_ready() else "Offline"

    body = (
        f'<nav class="nav">'
        f'<div class="logo">🤖 RLD Dashboard</div>'
        f'<div class="nav-r">'
        f'<span style="font-size:.8rem">{status_dot}{status_txt}</span>'
        f'<span>{session.get("username","")}</span>'
        f'<a href="/logout" class="btn bs bsm">Abmelden</a>'
        f'</div></nav>'
        f'<div class="wrap">'
        f'<aside class="side"><div style="color:var(--tx2);font-size:.82rem;padding:.5rem .75rem">Wähle einen Server</div></aside>'
        f'<main class="main">'
        + _al() +
        f'<div class="pt">Deine Server</div>'
        f'<p class="ps">Wähle einen Server zum Verwalten</p>'
        f'<div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:1.5rem">'
        f'<div class="stat"><div class="sv">{len(_bguilds())}</div><div class="sl2">Server mit Bot</div></div>'
        f'<div class="stat"><div class="sv">{len(gs)}</div><div class="sl2">Verwaltbar</div></div>'
        f'<div class="stat"><div class="sv">{ping_ms}ms</div><div class="sl2">Bot Latenz</div></div>'
        f'</div>'
        f'<div class="sg">{cards}</div>'
        f'</main></div>'
    )
    return _pg(body)