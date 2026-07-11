from flask import Blueprint, session, redirect, url_for, current_app
from functools import wraps
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("overview", __name__)

def _lreq(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return dec

def _greq(f):
    @wraps(f)
    def dec(*a, **kw):
        from flask import flash
        gid = kw.get("gid")
        if not gid: return redirect(url_for("auth.dash"))
        ug = uguilds(session.get("access_token", ""))
        bg = {g["id"] for g in bguilds()}
        ug2 = next((g for g in ug if g["id"] == gid), None)
        if not ug2: flash("Kein Zugriff.", "error"); return redirect(url_for("auth.dash"))
        if gid not in bg: flash("Bot nicht auf diesem Server.", "error"); return redirect(url_for("auth.dash"))
        p = int(ug2.get("permissions", 0))
        if not (p & 0x8 or p & 0x20): flash("Keine Rechte.", "error"); return redirect(url_for("auth.dash"))
        return f(*a, **kw)
    return dec

@bp.route("/g/<gid>/ov")
@_lreq
@_greq
def gov(gid):
    from utils import col, _count, _findone
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []

    wc  = runasync(_count(col("warns"),    {"guild_id": int(gid)}), bot) or 0
    mc  = runasync(_count(col("cases"),    {"guild_id": int(gid)}), bot) or 0
    tc  = runasync(_count(col("tickets"),  {"guild_id": int(gid), "open": True}), bot) or 0
    gwc = runasync(_count(col("giveaways"),{"guild_id": int(gid), "active": True}), bot) or 0

    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
    member_role_id = cfg.get("member_count_role")

    # Get member count - prefer bot cache, fallback to API with counts
    guild_obj = bot.get_guild(int(gid))
    if guild_obj:
        if member_role_id:
            r = guild_obj.get_role(int(member_role_id))
            member_count = len(r.members) if r else guild_obj.member_count
        else:
            member_count = guild_obj.member_count
    else:
        # Fallback: API with approximate counts
        g_full = dget(f"/guilds/{gid}?with_counts=true", isbot=True) or {}
        member_count = g_full.get("approximate_member_count") or g_full.get("member_count") or "?"

    ping_ms = round(bot.latency * 1000) if bot.is_ready() else -1

    # Server icon
    icon_html = ""
    if g.get("icon"):
        icon_html = f'<img src="https://cdn.discordapp.com/icons/{gid}/{g["icon"]}.png" style="width:64px;height:64px;border-radius:12px;margin-right:1rem;">'

    gname = g.get("name", "")

    body = nav
    body += '<div class="wrap">'
    body += sidebar(gid, "ov")
    body += '<main class="main">'
    body += alerts()
    body += f'<div style="display:flex;align-items:center;margin-bottom:1.25rem">{icon_html}<div><div class="pt">{gname}</div><p class="ps">Server-Übersicht</p></div></div>'

    body += '<div class="grid">'
    body += f'<div class="stat"><div class="sv">{member_count}</div><div class="sl2">Mitglieder</div></div>'
    body += f'<div class="stat"><div class="sv">{len(chs)}</div><div class="sl2">Kanäle</div></div>'
    body += f'<div class="stat"><div class="sv">{len(rls)}</div><div class="sl2">Rollen</div></div>'
    body += f'<div class="stat"><div class="sv">{wc}</div><div class="sl2">Verwarnungen</div></div>'
    body += f'<div class="stat"><div class="sv">{mc}</div><div class="sl2">Mod Aktionen</div></div>'
    body += f'<div class="stat"><div class="sv">{tc}</div><div class="sl2">Offene Tickets</div></div>'
    body += f'<div class="stat"><div class="sv">{gwc}</div><div class="sl2">Aktive Giveaways</div></div>'
    body += '</div>'

    # Bot Status card
    main_status_cls = "tag-green" if bot.is_ready() else "tag-red"
    main_status_txt = f"🟢 Online ({ping_ms}ms)" if bot.is_ready() else "🔴 Offline"

    body += '<div class="card">'
    body += '<div class="ct">🤖 Bot Status <span style="font-size:.75rem;color:var(--tx2);font-weight:400">— aktualisiert alle 30s</span></div>'
    body += '<div style="display:flex;gap:2rem;flex-wrap:wrap">'
    body += f'<div><div style="font-size:.8rem;color:var(--tx2);margin-bottom:.3rem">Main Bot</div><span class="tag {main_status_cls} bot-status-main">{main_status_txt}</span></div>'
    body += f'<div><div style="font-size:.8rem;color:var(--tx2);margin-bottom:.3rem">Level Bot</div><span class="tag tag-gray bot-status-level">⏳ Prüfe...</span></div>'
    body += '</div></div>'

    # Quick access
    body += '<div class="card"><div class="ct">⚡ Schnellzugriff</div>'
    body += '<div style="display:flex;gap:.75rem;flex-wrap:wrap">'
    body += f'<a href="/g/{gid}/mod" class="btn bp">🛡️ Moderation</a>'
    body += f'<a href="/g/{gid}/eco" class="btn bp">💰 Economy</a>'
    body += f'<a href="/g/{gid}/gws" class="btn bp">🎉 Giveaways</a>'
    body += f'<a href="/g/{gid}/team" class="btn bp">👥 Team</a>'
    body += f'<a href="/g/{gid}/chperms" class="btn bs">🔐 Rechte</a>'
    body += f'<a href="/g/{gid}/sett" class="btn bs">⚙️ Einstellungen</a>'
    body += '</div></div>'

    body += '</main></div>'

    # Auto-refresh bot status
    body += '''<script>
function updateBotStatus() {
    fetch("/api/bot-status").then(r => r.json()).then(d => {
        document.querySelectorAll(".bot-status-main").forEach(el => {
            el.className = "tag " + (d.main.online ? "tag-green" : "tag-red") + " bot-status-main";
            el.textContent = d.main.online ? "🟢 Online (" + d.main.ping + "ms)" : "🔴 Offline";
        });
        document.querySelectorAll(".bot-status-level").forEach(el => {
            el.className = "tag " + (d.level.online ? "tag-green" : "tag-red") + " bot-status-level";
            el.textContent = d.level.online ? "🟢 Online (" + d.level.ping + "ms)" : "🔴 Offline";
        });
    }).catch(() => {});
}
updateBotStatus();
setInterval(updateBotStatus, 30000);
</script>'''

    return pg(body)
