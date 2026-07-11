from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("counting", __name__)

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

@bp.route("/g/<gid>/counting", methods=["GET", "POST"])
@_lreq
@_greq
def gcounting(gid):
    from utils import col, _findone, _update, ivcfg
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    text_chs = sorted([c for c in chs if c.get("type") == 0], key=lambda x: x.get("position", 0))

    if request.method == "POST":
        action = request.form.get("action")
        if action == "setup":
            ch_id = request.form.get("channel_id", "")
            if ch_id:
                async def do_setup():
                    await col("config").update_one(
                        {"guild_id": int(gid)},
                        {"$set": {"counting_channel": int(ch_id)}},
                        upsert=True
                    )
                    await col("counting").update_one(
                        {"guild_id": int(gid)},
                        {"$set": {"count": 0, "last_user": None, "high_score": 0}},
                        upsert=True
                    )
                    ivcfg(int(gid))
                runasync(do_setup(), bot)
                flash("✅ Counting Kanal eingerichtet!", "success")
        elif action == "reset":
            async def do_reset():
                await col("counting").update_one(
                    {"guild_id": int(gid)},
                    {"$set": {"count": 0, "last_user": None}},
                    upsert=True
                )
            runasync(do_reset(), bot)
            flash("✅ Counting zurückgesetzt! Nächste Zahl: 1", "success")

    cfg   = runasync(_findone(col("config"),   {"guild_id": int(gid)}), bot) or {}
    state = runasync(_findone(col("counting"), {"guild_id": int(gid)}), bot) or {}
    counting_ch = cfg.get("counting_channel")
    current_count = state.get("count", 0)
    high_score    = state.get("high_score", 0)
    last_user_id  = state.get("last_user")

    last_user_str = "–"
    if last_user_id:
        guild_obj = bot.get_guild(int(gid))
        if guild_obj:
            m = guild_obj.get_member(int(last_user_id))
            last_user_str = f"{m.display_name} ({last_user_id})" if m else str(last_user_id)

    ch_name = "Nicht eingerichtet"
    if counting_ch:
        ch = next((c for c in chs if c["id"] == str(counting_ch)), None)
        ch_name = f"#{ch['name']}" if ch else str(counting_ch)

    ch_opts = '<option value="">Kanal wählen...</option>'
    for c in text_chs:
        sel = " selected" if str(c["id"]) == str(counting_ch or "") else ""
        ch_opts += f'<option value="{c["id"]}"{sel}>#{c["name"]}</option>'

    gname = g.get("name", "")
    body = nav
    body += '<div class="wrap">'
    body += sidebar(gid, "counting")
    body += '<main class="main">'
    body += alerts()
    body += '<div class="pt">🔢 Counting</div>'
    body += f'<p class="ps">{gname}</p>'

    # Stats
    body += '<div class="grid">'
    body += f'<div class="stat"><div class="sv">{current_count}</div><div class="sl2">Aktueller Stand</div></div>'
    body += f'<div class="stat"><div class="sv">{high_score}</div><div class="sl2">🏆 Rekord</div></div>'
    body += f'<div class="stat"><div class="sv">{ch_name}</div><div class="sl2">Counting Kanal</div></div>'
    body += '</div>'

    # Setup
    body += '<div class="card"><div class="ct">⚙️ Einstellungen</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="setup">'
    body += f'<div class="fg"><label class="lbl">Counting Kanal</label><select name="channel_id" class="sel">{ch_opts}</select></div>'
    body += '<button class="btn bp">💾 Speichern</button>'
    body += '</form></div>'

    # Info + Reset
    body += '<div class="card"><div class="ct">ℹ️ Regeln & Info</div>'
    body += '<div style="font-size:.9rem;line-height:1.8">'
    body += '<b>Wie funktioniert Counting?</b><br>'
    body += '✅ User schreiben der Reihe nach Zahlen (1, 2, 3...)<br>'
    body += '✅ Bot reagiert mit ✅ bei richtiger Zahl<br>'
    body += '❌ Falsche Zahl → Neustart von 1<br>'
    body += '❌ Gleicher User zweimal hintereinander → Neustart<br>'
    body += '🎉 Bei Meilensteinen (50, 100...) gibt es Extra-Reaktionen<br>'
    body += f'<br><b>Letzter Zähler:</b> {last_user_str}<br>'
    body += f'<b>Nächste Zahl:</b> {current_count + 1}'
    body += '</div>'
    body += '<div style="margin-top:1rem">'
    body += '<form method="POST" style="display:inline">'
    body += '<input type="hidden" name="action" value="reset">'
    body += '<button class="btn bd" onclick="return confirm(\'Counting wirklich zurücksetzen?\')">🔄 Counting zurücksetzen</button>'
    body += '</form></div></div>'

    body += '</main></div>'
    return pg(body)
