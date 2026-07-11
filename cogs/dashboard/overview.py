from flask import Blueprint, session, redirect, url_for, current_app
from functools import wraps
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("overview", __name__)

def lreq(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return dec

def greq(f):
    @wraps(f)
    def dec(*a, **kw):
        from flask import flash
        gid = kw.get("gid")
        if not gid: return redirect(url_for("auth.dash"))
        ug = uguilds(session.get("access_token", ""))
        bg = {g["id"] for g in bguilds()}
        ug2 = next((g for g in ug if g["id"] == gid), None)
        if not ug2: flash("Kein Zugriff.", "error"); return redirect(url_for("auth.dash"))
        if gid not in bg: flash("Bot ist nicht auf diesem Server.", "error"); return redirect(url_for("auth.dash"))
        p = int(ug2.get("permissions", 0))
        if not (p & 0x8 or p & 0x20): flash("Keine Rechte.", "error"); return redirect(url_for("auth.dash"))
        return f(*a, **kw)
    return dec

@bp.route("/g/<gid>/ov")
@lreq
@greq
def gov(gid):
    from bot import col, _count
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []

    wc   = runasync(_count(col("warns"), {"guild_id": int(gid)}), bot) or 0
    mc   = runasync(_count(col("cases"), {"guild_id": int(gid)}), bot) or 0
    tc   = runasync(_count(col("tickets"), {"guild_id": int(gid), "open": True}), bot) or 0
    gwc  = runasync(_count(col("giveaways"), {"guild_id": int(gid), "active": True}), bot) or 0

    # Member count (with optional role filter)
    from bot import _findone
    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
    member_role_id = cfg.get("member_count_role")
    guild_obj = bot.get_guild(int(gid))
    if guild_obj and member_role_id:
        r = guild_obj.get_role(int(member_role_id))
        member_count = len(r.members) if r else g.get("member_count", "?")
    else:
        member_count = g.get("member_count", "?")

    ping_ms = round(bot.latency * 1000) if bot.is_ready() else -1
    status_color = "#22c55e" if bot.is_ready() else "#ef4444"
    status_txt = f"Online ({ping_ms}ms)" if bot.is_ready() else "Offline"

    # Server icon
    icon_html = ""
    if g.get("icon"):
        icon_html = f'<img src="https://cdn.discordapp.com/icons/{gid}/{g["icon"]}.png" style="width:80px;height:80px;border-radius:16px;margin-bottom:1rem;display:block;">'

    body = (
        nav +
        '<div class="wrap">' + sidebar(gid, "ov") +
        '<main class="main">' + alerts() +
        f'<div style="display:flex;align-items:center;gap:1rem;margin-bottom:1.25rem">'
        f'{icon_html}'
        f'<div><div class="pt">{g.get("name","")}</div>'
        f'<p class="ps">Server-Übersicht</p></div>'
        f'</div>'
        f'<div class="grid">'
        f'<div class="stat"><div class="sv">{member_count}</div><div class="sl2">Mitglieder</div></div>'
        f'<div class="stat"><div class="sv">{len(chs)}</div><div class="sl2">Kanäle</div></div>'
        f'<div class="stat"><div class="sv">{len(rls)}</div><div class="sl2">Rollen</div></div>'
        f'<div class="stat"><div class="sv">{wc}</div><div class="sl2">Verwarnungen</div></div>'
        f'<div class="stat"><div class="sv">{mc}</div><div class="sl2">Mod Aktionen</div></div>'
        f'<div class="stat"><div class="sv">{tc}</div><div class="sl2">Offene Tickets</div></div>'
        f'<div class="stat"><div class="sv">{gwc}</div><div class="sl2">Aktive Giveaways</div></div>'
        f'</div>'
        f'<div class="card">'
        f'<div class="ct">🤖 Bot Status</div>'
        f'<div style="display:flex;gap:2rem;flex-wrap:wrap">'
        f'<div><div style="font-size:.8rem;color:var(--tx2);margin-bottom:.3rem">Main Bot</div>'
        f'<span class="tag {"tag-green" if bot.is_ready() else "tag-red"}">'
        f'{"🟢" if bot.is_ready() else "🔴"} {status_txt}</span></div>'
        f'<div><div style="font-size:.8rem;color:var(--tx2);margin-bottom:.3rem">Level Bot</div>'
        f'<span class="tag tag-gray">⚫ Nicht verbunden</span></div>'
        f'</div>'
        f'<div style="font-size:.75rem;color:var(--tx2);margin-top:.75rem">Aktualisiert alle 30s</div>'
        f'</div>'
        f'<div class="card"><div class="ct">⚡ Schnellzugriff</div>'
        f'<div style="display:flex;gap:.75rem;flex-wrap:wrap">'
        f'<a href="/g/{gid}/mod" class="btn bp">🛡️ Moderation</a>'
        f'<a href="/g/{gid}/eco" class="btn bp">💰 Economy</a>'
        f'<a href="/g/{gid}/gws" class="btn bp">🎉 Giveaways</a>'
        f'<a href="/g/{gid}/team" class="btn bp">👥 Team</a>'
        f'<a href="/g/{gid}/chperms" class="btn bs">🔐 Rechte</a>'
        f'<a href="/g/{gid}/sett" class="btn bs">⚙️ Einstellungen</a>'
        f'</div></div>'
        f'</main></div>'
    )
    css = '<script>setInterval(()=>fetch("/api/bot-status").then(r=>r.json()).then(d=>{document.querySelectorAll(".bot-status-main").forEach(el=>{el.textContent=d.main.online?"🟢 Online ("+d.main.ping+"ms)":"🔴 Offline"})}),30000)</script>'
    return pg(body, css)
