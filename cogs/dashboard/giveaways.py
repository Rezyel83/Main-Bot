from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime, timedelta
import re
from dashboard import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("giveaways", __name__)

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
        if gid not in bg: flash("Bot nicht auf diesem Server.", "error"); return redirect(url_for("auth.dash"))
        p = int(ug2.get("permissions", 0))
        if not (p & 0x8 or p & 0x20): flash("Keine Rechte.", "error"); return redirect(url_for("auth.dash"))
        return f(*a, **kw)
    return dec

@bp.route("/g/<gid>/gws", methods=["GET", "POST"])
@lreq
@greq
def ggws(gid):
    from bot import col, _find
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []
    text_chs = [c for c in chs if c.get("type") == 0]
    roles = [r for r in rls if not r.get("managed") and r["name"] != "@everyone"]

    if request.method == "POST":
        action = request.form.get("action")
        if action == "start":
            preis    = request.form.get("preis", "").strip()
            dauer    = request.form.get("dauer", "").strip()
            gewinner = request.form.get("gewinner", "1")
            kanal_id = request.form.get("kanal_id", "")
            rolle_id = request.form.get("rolle_id", "")
            embed_farbe = request.form.get("embed_farbe", "gold")
            beschreibung = request.form.get("beschreibung", "Reagiere mit 🎉 um teilzunehmen!")

            mt = re.match(r"(\d+)(m|h|d)", dauer.lower())
            if not mt:
                flash("❌ Dauer Format: 10m, 2h, 1d", "error")
            elif not preis:
                flash("❌ Preis angeben!", "error")
            elif not kanal_id:
                flash("❌ Kanal wählen!", "error")
            else:
                a, u = int(mt.group(1)), mt.group(2)
                dl = {"m": timedelta(minutes=a), "h": timedelta(hours=a), "d": timedelta(days=a)}[u]
                ea = datetime.utcnow() + dl

                farben = {"gold": 0xFFD700, "red": 0xEF4444, "blue": 0x3B82F6, "green": 0x22C55E, "purple": 0x8B5CF6}
                color_val = farben.get(embed_farbe, 0xFFD700)

                async def start_gw():
                    import discord
                    guild_obj = bot.get_guild(int(gid))
                    if not guild_obj: return
                    ch = guild_obj.get_channel(int(kanal_id))
                    if not ch: return
                    e = discord.Embed(title="🎉 GIVEAWAY", color=color_val)
                    e.description = (
                        f"**Preis:** {preis}\n"
                        f"**Gewinner:** {gewinner}\n"
                        f"**Endet:** <t:{int(ea.timestamp())}:R>\n\n"
                        f"{beschreibung}"
                    )
                    if rolle_id:
                        r = guild_obj.get_role(int(rolle_id))
                        if r: e.add_field(name="Benötigte Rolle", value=r.mention)
                    e.set_footer(text=f"Gestartet über Dashboard")
                    msg = await ch.send(embed=e)
                    await msg.add_reaction("🎉")
                    await col("giveaways").insert_one({
                        "guild_id": int(gid), "channel_id": int(kanal_id),
                        "message_id": msg.id, "preis": preis,
                        "gewinner": int(gewinner),
                        "rolle_id": int(rolle_id) if rolle_id else None,
                        "ends_at": ea, "active": True,
                        "gestartet_von": int(session["user_id"])
                    })

                runasync(start_gw(), bot)
                flash(f"✅ Giveaway für '{preis}' gestartet!", "success")

        elif action == "end":
            gw_id = request.form.get("gw_id", "")
            if gw_id:
                from bson import ObjectId
                async def end_gw():
                    gw = await col("giveaways").find_one({"_id": ObjectId(gw_id)})
                    if not gw: return
                    import random, discord
                    guild_obj = bot.get_guild(gw["guild_id"])
                    if not guild_obj: return
                    ch = guild_obj.get_channel(gw["channel_id"])
                    if not ch: return
                    try:
                        msg = await ch.fetch_message(gw["message_id"])
                        rx = discord.utils.get(msg.reactions, emoji="🎉")
                        us = [u async for u in rx.users() if not u.bot]
                        ws = random.sample(us, min(gw["gewinner"], len(us))) if us else []
                        e = discord.Embed(title="🎉 Giveaway Beendet!", color=discord.Color.green())
                        e.description = f"**Preis:** {gw['preis']}\n**Gewinner:** {', '.join(w.mention for w in ws) if ws else 'Niemand'}"
                        await msg.edit(embed=e)
                        if ws: await ch.send(f"🎉 {', '.join(w.mention for w in ws)} gewinnen **{gw['preis']}**!")
                    except: pass
                    await col("giveaways").update_one({"_id": gw["_id"]}, {"$set": {"active": False}})
                runasync(end_gw(), bot)
                flash("Giveaway beendet!", "success")

    # Active giveaways
    active_gws = runasync(_find(col("giveaways"), {"guild_id": int(gid), "active": True}, sort=("ends_at", 1)), bot) or []
    past_gws   = runasync(_find(col("giveaways"), {"guild_id": int(gid), "active": False}, sort=("ends_at", -1), limit=10), bot) or []

    ch_opts = '<option value="">Kanal wählen...</option>' + "".join(
        f'<option value="{c["id"]}">#{c["name"]}</option>' for c in sorted(text_chs, key=lambda x: x.get("position", 0))
    )
    role_opts = '<option value="">-- Keine Pflichtrolle --</option>' + "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>' for r in sorted(roles, key=lambda x: x.get("position", 0), reverse=True)
    )

    gw_rows = ""
    for gw in active_gws:
        ch_name = next((c["name"] for c in chs if c["id"] == str(gw.get("channel_id", ""))), "?")
        ends_ts = int(gw["ends_at"].timestamp()) if isinstance(gw.get("ends_at"), datetime) else 0
        gw_rows += (
            f'<tr>'
            f'<td><b>{gw["preis"]}</b></td>'
            f'<td>#{ch_name}</td>'
            f'<td>{gw["gewinner"]}</td>'
            f'<td><span class="tag tag-green"><t:{ends_ts}:R></span></td>'
            f'<td>'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="end">'
            f'<input type="hidden" name="gw_id" value="{gw["_id"]}">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Giveaway jetzt beenden?\')">⏹️ Beenden</button>'
            f'</form>'
            f'</td>'
            f'</tr>'
        )

    past_rows = ""
    for gw in past_gws:
        ch_name = next((c["name"] for c in chs if c["id"] == str(gw.get("channel_id", ""))), "?")
        past_rows += (
            f'<tr>'
            f'<td>{gw["preis"]}</td>'
            f'<td>#{ch_name}</td>'
            f'<td>{gw["gewinner"]}</td>'
            f'<td><span class="tag tag-gray">Beendet</span></td>'
            f'</tr>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "gws") +
        '<main class="main">' + alerts() +
        '<div class="pt">Giveaways</div>'
        f'<p class="ps">{g.get("name","")}</p>'

        '<div class="card"><div class="ct">🎉 Neues Giveaway starten</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="start">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem">'
        '<div class="fg" style="margin:0"><label class="lbl">Preis</label><input name="preis" class="inp" placeholder="z.B. Nitro" required></div>'
        '<div class="fg" style="margin:0"><label class="lbl">Dauer</label><input name="dauer" class="inp" placeholder="10m / 2h / 1d" required></div>'
        '<div class="fg" style="margin:0"><label class="lbl">Anzahl Gewinner</label><input name="gewinner" type="number" class="inp" value="1" min="1"></div>'
        '</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem;margin-top:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Kanal</label><select name="kanal_id" class="sel" required>{ch_opts}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Pflicht-Rolle</label><select name="rolle_id" class="sel">{role_opts}</select></div>'
        '<div class="fg" style="margin:0"><label class="lbl">Embed Farbe</label>'
        '<select name="embed_farbe" class="sel">'
        '<option value="gold">Gold</option><option value="red">Rot</option>'
        '<option value="blue">Blau</option><option value="green">Grün</option><option value="purple">Lila</option>'
        '</select></div>'
        '</div>'
        '<div class="fg" style="margin-top:.75rem"><label class="lbl">Beschreibung / Teilnahme-Text</label>'
        '<textarea name="beschreibung" class="ta">Reagiere mit 🎉 um teilzunehmen!</textarea></div>'
        '<button class="btn bp" style="margin-top:.5rem">🎉 Giveaway Starten</button>'
        '</form></div>'

        '<div class="card"><div class="ct">⏳ Aktive Giveaways</div>'
        '<table class="tbl"><thead><tr><th>Preis</th><th>Kanal</th><th>Gewinner</th><th>Endet</th><th></th></tr></thead><tbody>'
        + (gw_rows or '<tr><td colspan="5" style="color:var(--tx2);text-align:center">Keine aktiven Giveaways</td></tr>')
        + '</tbody></table></div>'

        '<div class="card"><div class="ct">📜 Vergangene Giveaways</div>'
        '<table class="tbl"><thead><tr><th>Preis</th><th>Kanal</th><th>Gewinner</th><th>Status</th></tr></thead><tbody>'
        + (past_rows or '<tr><td colspan="4" style="color:var(--tx2);text-align:center">Keine vergangenen Giveaways</td></tr>')
        + '</tbody></table></div>'
        '</main></div>'
    )
    return pg(body)