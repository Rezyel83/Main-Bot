from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("notifications", __name__)

def _lreq(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return dec

def _greq(f):
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

@bp.route("/g/<gid>/notif", methods=["GET", "POST"])
@_lreq
@_greq
def gnotif(gid):
    from bot import col, _find
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []
    text_chs = [c for c in chs if c.get("type") == 0]

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_twitch":
            streamer = request.form.get("streamer", "").strip().lower()
            ch_id    = request.form.get("channel_id", "")
            role_id  = request.form.get("ping_role", "")
            msg      = request.form.get("message", "{streamer} ist jetzt live! 🎮")
            if streamer and ch_id:
                async def add_t():
                    await col("notifications").update_one(
                        {"guild_id": int(gid), "type": "twitch", "name": streamer},
                        {"$set": {
                            "channel_id": int(ch_id),
                            "ping_role_id": int(role_id) if role_id else None,
                            "message": msg, "live": False
                        }},
                        upsert=True
                    )
                runasync(add_t(), bot)
                flash(f"Twitch Notification für '{streamer}' eingerichtet!", "success")

        elif action == "remove":
            name = request.form.get("name", "")
            ntype = request.form.get("ntype", "twitch")
            async def rem_n():
                await col("notifications").delete_one({"guild_id": int(gid), "type": ntype, "name": name})
            runasync(rem_n(), bot)
            flash(f"Notification entfernt!", "success")

    notifs = runasync(_find(col("notifications"), {"guild_id": int(gid)}, sort=("name", 1)), bot) or []
    twitch_notifs = [n for n in notifs if n.get("type") == "twitch"]

    ch_opts = '<option value="">Kanal wählen...</option>' + "".join(
        f'<option value="{c["id"]}">#{c["name"]}</option>'
        for c in sorted(text_chs, key=lambda x: x.get("position", 0))
    )
    role_opts = '<option value="">-- Kein Ping --</option>' + "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>'
        for r in sorted(rls, key=lambda x: x.get("position", 0), reverse=True)
        if not r.get("managed") and r["name"] != "@everyone"
    )

    twitch_rows = ""
    for n in twitch_notifs:
        ch_name = next((c["name"] for c in chs if c["id"] == str(n.get("channel_id",""))), "?")
        ping_name = ""
        if n.get("ping_role_id"):
            r = next((r["name"] for r in rls if r["id"] == str(n["ping_role_id"])), "?")
            ping_name = f"@{r}"
        status_cls = "tag-green" if n.get("live") else "tag-gray"
        status_lbl = "🟢 Live" if n.get("live") else "⚫ Offline"
        twitch_rows += (
            f'<tr>'
            f'<td><b>twitch.tv/{n["name"]}</b></td>'
            f'<td>#{ch_name}</td>'
            f'<td>{ping_name or "–"}</td>'
            f'<td><span class="tag {status_cls}">{status_lbl}</span></td>'
            f'<td>'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="remove">'
            f'<input type="hidden" name="name" value="{n["name"]}">'
            f'<input type="hidden" name="ntype" value="twitch">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Entfernen?\')">🗑️</button>'
            f'</form>'
            f'</td></tr>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "notif") +
        '<main class="main">' + alerts() +
        '<div class="pt">🔔 Notifications</div>'
        f'<p class="ps">{g.get("name","")}</p>'

        '<div class="card"><div class="ct">🟣 Twitch Notification hinzufügen</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="add_twitch">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem">'
        '<div class="fg" style="margin:0"><label class="lbl">Twitch Streamer Name</label><input name="streamer" class="inp" placeholder="z.B. ninja" required></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Benachrichtigungs-Kanal</label><select name="channel_id" class="sel" required>{ch_opts}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Ping Rolle</label><select name="ping_role" class="sel">{role_opts}</select></div>'
        '</div>'
        '<div class="fg" style="margin-top:.75rem"><label class="lbl">Nachricht (verwende {streamer} als Platzhalter)</label>'
        '<input name="message" class="inp" value="{streamer} ist jetzt live! 🎮"></div>'
        '<button class="btn bp" style="margin-top:.5rem">➕ Hinzufügen</button>'
        '</form></div>'

        '<div class="card"><div class="ct">🟣 Twitch Notifications</div>'
        '<table class="tbl"><thead><tr><th>Streamer</th><th>Kanal</th><th>Ping</th><th>Status</th><th></th></tr></thead><tbody>'
        + (twitch_rows or '<tr><td colspan="5" style="color:var(--tx2);text-align:center">Keine Twitch Notifications</td></tr>')
        + '</tbody></table></div>'
        '</main></div>'
    )
    return pg(body)
