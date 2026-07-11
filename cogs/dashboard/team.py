from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

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

# ════════════════════════════════════════════════════════════
# TEAM  (oranges Design)
# ════════════════════════════════════════════════════════════
bp_team = Blueprint("team", __name__)

TEAM_CSS = """
:root { --accent: var(--or); }
.sl:hover, .sl.on { background: rgba(249,115,22,.12) !important; color: var(--or) !important; }
.stat { border-top-color: var(--or) !important; }
.btn.bp { background: var(--or) !important; }
.btn.bp:hover { background: var(--ord) !important; }
.logo { color: var(--or) !important; }
"""

@bp_team.route("/g/<gid>/team", methods=["GET", "POST"])
@_lreq
@_greq
def gteam(gid):
    from bot import col, _find, _count
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            uid   = request.form.get("uid", "").strip()
            rolle = request.form.get("rolle", "Moderator")
            if uid.isdigit():
                async def add_member():
                    await col("team").update_one(
                        {"guild_id": int(gid), "user_id": int(uid)},
                        {"$set": {"guild_id": int(gid), "user_id": int(uid),
                                  "rolle": rolle, "joined": datetime.utcnow(),
                                  "aktiv": True, "notizen": [], "abmeldungen": []}},
                        upsert=True
                    )
                runasync(add_member(), bot)
                flash(f"Mitglied {uid} hinzugefügt!", "success")
        elif action == "remove":
            uid = request.form.get("uid", "")
            async def rem_member():
                await col("team").delete_one({"guild_id": int(gid), "user_id": int(uid)})
            runasync(rem_member(), bot)
            flash("Mitglied entfernt!", "success")
        elif action == "add_note":
            uid  = request.form.get("uid", "")
            note = request.form.get("note", "").strip()
            if uid and note:
                async def add_note():
                    await col("team").update_one(
                        {"guild_id": int(gid), "user_id": int(uid)},
                        {"$push": {"notizen": {"text": note, "ts": datetime.utcnow(), "von": int(session["user_id"])}}}
                    )
                runasync(add_note(), bot)
                flash("Notiz hinzugefügt!", "success")

    members = runasync(_find(col("team"), {"guild_id": int(gid), "aktiv": True}), bot) or []
    abmeld  = runasync(_find(col("team"), {"guild_id": int(gid), "aktiv": True, "abmeldungen.0": {"$exists": True}}), bot) or []

    role_opts = "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>'
        for r in sorted(rls, key=lambda x: x.get("position", 0), reverse=True)
        if not r.get("managed") and r["name"] != "@everyone"
    )

    member_cards = ""
    for m in members:
        user_str = get_member_name(gid, m.get("user_id", ""), bot)
        joined   = m["joined"].strftime("%d.%m.%Y") if isinstance(m.get("joined"), datetime) else "?"
        notes    = m.get("notizen", [])
        abmeld_list = m.get("abmeldungen", [])
        warns    = m.get("team_warns", [])

        member_cards += (
            f'<div class="card" style="border-left:3px solid var(--or)">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.75rem">'
            f'<div>'
            f'<div style="font-weight:600;font-size:1rem">{user_str}</div>'
            f'<div style="font-size:.8rem;color:var(--tx2)">'
            f'<span class="tag tag-orange">{m.get("rolle","Mitglied")}</span> &bull; Dabei seit {joined}'
            f'</div></div>'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="remove">'
            f'<input type="hidden" name="uid" value="{m.get("user_id","")}">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Mitglied entfernen?\')">Entfernen</button>'
            f'</form>'
            f'</div>'
        )
        if warns:
            member_cards += f'<div style="font-size:.8rem;color:#f87171;margin-bottom:.5rem">⚠️ {len(warns)} Team-Verwarnungen</div>'
        if abmeld_list:
            last = abmeld_list[-1]
            member_cards += f'<div style="font-size:.8rem;color:#fb923c;margin-bottom:.5rem">📅 Abgemeldet: {last.get("von","?")} – {last.get("bis","?")} ({last.get("grund","?")})</div>'
        if notes:
            member_cards += '<div style="font-size:.8rem;margin-bottom:.5rem"><b>Notizen:</b><br>' + "<br>".join(f"• {n['text']}" for n in notes[-3:]) + "</div>"

        member_cards += (
            f'<form method="POST" style="display:flex;gap:.5rem;margin-top:.5rem">'
            f'<input type="hidden" name="action" value="add_note">'
            f'<input type="hidden" name="uid" value="{m.get("user_id","")}">'
            f'<input name="note" class="inp" placeholder="Notiz hinzufügen..." style="flex:1">'
            f'<button class="btn bs bsm">➕</button>'
            f'</form>'
            f'</div>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "team") +
        '<main class="main">' + alerts() +
        f'<div class="pt" style="color:var(--or)">👥 Teambereich</div>'
        f'<p class="ps">{g.get("name","")}</p>'
        f'<div class="grid">'
        f'<div class="stat orange"><div class="sv">{len(members)}</div><div class="sl2">Teammitglieder</div></div>'
        f'<div class="stat orange"><div class="sv">{len(abmeld)}</div><div class="sl2">Abgemeldet</div></div>'
        f'</div>'
        f'<div class="card" style="border-color:rgba(249,115,22,.3)">'
        f'<div class="ct">➕ Mitglied hinzufügen</div>'
        f'<form method="POST" style="display:grid;grid-template-columns:1fr 1fr auto;gap:.75rem;align-items:flex-end">'
        f'<input type="hidden" name="action" value="add">'
        f'<div class="fg" style="margin:0"><label class="lbl">User ID</label><input name="uid" class="inp" placeholder="User ID" required></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Rolle</label><input name="rolle" class="inp" value="Moderator" required></div>'
        f'<button class="btn bo">Hinzufügen</button>'
        f'</form></div>'
        + (member_cards or '<div class="card"><p style="color:var(--tx2)">Keine Teammitglieder.</p></div>')
        + '</main></div>'
    )
    return pg(body, TEAM_CSS)

bp = bp_team
