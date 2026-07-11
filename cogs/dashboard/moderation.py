from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

bp = Blueprint("moderation", __name__)

def lreq(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return dec

def greq(f):
    @wraps(f)
    def dec(*a, **kw):
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

def resolve_user(gid, uid, bot):
    """Returns 'Username / ID' string"""
    return get_member_name(gid, uid, bot)

@bp.route("/g/<gid>/mod", methods=["GET", "POST"])
@lreq
@greq
def gmod(gid):
    from bot import col, _find, _count
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    tab = request.args.get("tab", "warns")
    s = request.args.get("q", "")

    if request.method == "POST":
        action = request.form.get("action")
        # Warn a user
        if action == "warn":
            uid = request.form.get("uid", "").strip()
            grund = request.form.get("grund", "").strip()
            if uid.isdigit() and grund:
                import asyncio
                async def do_warn():
                    await col("warns").insert_one({
                        "guild_id": int(gid), "user_id": int(uid),
                        "mod_id": int(session["user_id"]),
                        "grund": grund, "ts": datetime.utcnow()
                    })
                runasync(do_warn(), bot)
                flash(f"Verwarnung für {uid} hinzugefügt!", "success")
        # Timeout
        elif action == "timeout":
            uid = request.form.get("uid", "").strip()
            minuten = request.form.get("minuten", "10")
            if uid.isdigit():
                guild_obj = bot.get_guild(int(gid))
                if guild_obj:
                    member = guild_obj.get_member(int(uid))
                    if member:
                        from datetime import timedelta
                        import discord
                        async def do_timeout():
                            await member.timeout(discord.utils.utcnow() + timedelta(minutes=int(minuten)), reason="Dashboard Timeout")
                        runasync(do_timeout(), bot)
                        flash(f"Timeout für {uid} gesetzt!", "success")

    # Warns
    q = {"guild_id": int(gid)}
    if s: q["$or"] = [{"grund": {"$regex": s, "$options": "i"}}]
    ws = runasync(_find(col("warns"), q, sort=("ts", -1), limit=50), bot) or []

    # Cases
    cases = runasync(_find(col("cases"), {"guild_id": int(gid)}, sort=("ts", -1), limit=30), bot) or []

    warn_rows = ""
    for w in ws:
        user_str = resolve_user(gid, w.get("user_id", ""), bot)
        mod_str  = resolve_user(gid, w.get("mod_id", ""), bot)
        ts_str   = w["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(w.get("ts"), datetime) else "?"
        warn_rows += (
            f'<tr>'
            f'<td><span style="font-weight:500">{user_str}</span></td>'
            f'<td>{mod_str}</td>'
            f'<td>{str(w.get("grund",""))[:60]}</td>'
            f'<td>{ts_str}</td>'
            f'<td>'
            f'<form method="POST" action="/g/{gid}/mod/del/{w["_id"]}" style="display:inline">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Warn löschen?\')">🗑️</button>'
            f'</form>'
            f'</td>'
            f'</tr>'
        )

    case_rows = ""
    action_colors = {"ban": "br", "kick": "bor", "warn": "bdg bb", "timeout": "bdg bor"}
    for c in cases:
        user_str = resolve_user(gid, c.get("target_id", ""), bot)
        mod_str  = resolve_user(gid, c.get("mod_id", ""), bot)
        ts_str   = c["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(c.get("ts"), datetime) else "?"
        aktion   = c.get("aktion", "")
        col_cls  = action_colors.get(aktion, "bdg bb")
        case_rows += (
            f'<tr>'
            f'<td><span class="bdg bb">#{c.get("case","?")}</span></td>'
            f'<td><span style="font-weight:500">{user_str}</span></td>'
            f'<td>{mod_str}</td>'
            f'<td><span class="bdg {col_cls}">{aktion}</span></td>'
            f'<td>{str(c.get("grund",""))[:50]}</td>'
            f'<td>{ts_str}</td>'
            f'</tr>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "mod") +
        '<main class="main">' + alerts() +
        '<div class="pt">Moderation</div>'
        f'<p class="ps">{g.get("name","")}</p>'

        # Quick actions
        '<div class="card"><div class="ct">⚡ Schnellaktion</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">'

        '<div>'
        '<div style="font-size:.85rem;font-weight:600;margin-bottom:.5rem">Verwarnung hinzufügen</div>'
        f'<form method="POST">'
        f'<input type="hidden" name="action" value="warn">'
        f'<div class="fg"><label class="lbl">User ID oder Name</label><input name="uid" class="inp" placeholder="User ID" required></div>'
        f'<div class="fg"><label class="lbl">Grund</label><input name="grund" class="inp" placeholder="Grund" required></div>'
        f'<button class="btn bp">Verwarnen</button>'
        f'</form>'
        '</div>'

        '<div>'
        '<div style="font-size:.85rem;font-weight:600;margin-bottom:.5rem">Timeout setzen</div>'
        f'<form method="POST">'
        f'<input type="hidden" name="action" value="timeout">'
        f'<div class="fg"><label class="lbl">User ID</label><input name="uid" class="inp" placeholder="User ID" required></div>'
        f'<div class="fg"><label class="lbl">Minuten</label><input name="minuten" type="number" class="inp" value="10" required></div>'
        f'<button class="btn bp">Timeout</button>'
        f'</form>'
        '</div>'
        '</div></div>'

        # Tabs
        f'<div style="display:flex;gap:.5rem;margin-bottom:1rem">'
        f'<a href="?tab=warns" class="btn {"bp" if tab=="warns" else "bs"}">⚠️ Verwarnungen ({len(ws)})</a>'
        f'<a href="?tab=cases" class="btn {"bp" if tab=="cases" else "bs"}">📋 Cases ({len(cases)})</a>'
        f'</div>'

        # Search
        f'<div class="card"><form method="GET" style="display:flex;gap:.75rem">'
        f'<input type="hidden" name="tab" value="{tab}">'
        f'<input name="q" class="inp" placeholder="Suchen..." value="{s}" style="max-width:300px">'
        f'<button class="btn bp">Suchen</button>'
        f'<a href="?tab={tab}" class="btn bs">Reset</a>'
        f'</form></div>'
    )

    if tab == "warns":
        body += (
            '<div class="card"><div class="ct">⚠️ Verwarnungen</div>'
            '<table class="tbl"><thead><tr>'
            '<th>User / ID</th><th>Moderator / ID</th><th>Grund</th><th>Datum</th><th></th>'
            '</tr></thead><tbody>'
            + warn_rows +
            '</tbody></table></div>'
        )
    else:
        body += (
            '<div class="card"><div class="ct">📋 Mod Cases</div>'
            '<table class="tbl"><thead><tr>'
            '<th>Case</th><th>User / ID</th><th>Moderator / ID</th><th>Aktion</th><th>Grund</th><th>Datum</th>'
            '</tr></thead><tbody>'
            + case_rows +
            '</tbody></table></div>'
        )

    body += '</main></div>'
    return pg(body)

@bp.route("/g/<gid>/mod/del/<wid>", methods=["POST"])
@lreq
@greq
def gdel(gid, wid):
    from bson import ObjectId
    from bot import col, _delete
    bot = current_app.bot
    runasync(_delete(col("warns"), {"_id": ObjectId(wid), "guild_id": int(gid)}), bot)
    flash("Verwarnung gelöscht!", "success")
    return redirect(f"/g/{gid}/mod")
