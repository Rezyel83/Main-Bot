from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from dashboard import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

bp = Blueprint("rl_teams", __name__)

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

@bp.route("/g/<gid>/rl", methods=["GET", "POST"])
@_lreq
@_greq
def grl(gid):
    from bot import col, _find
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add_member":
            team_id  = request.form.get("team_id", "")
            uid      = request.form.get("uid", "").strip()
            epic     = request.form.get("epic", "").strip()
            rolle    = request.form.get("rolle", "Spieler")
            if team_id and uid.isdigit():
                from bson import ObjectId
                user_str = get_member_name(gid, uid, bot).split(" / ")[0]
                async def add_m():
                    t = await col("rl_teams").find_one({"_id": ObjectId(team_id)})
                    if not t: return
                    if rolle.lower() == "trainer":
                        if len(t.get("trainers", [])) >= 2:
                            return
                        await col("rl_teams").update_one(
                            {"_id": ObjectId(team_id)},
                            {"$push": {"trainers": {"user_id": int(uid), "username": user_str, "epic": epic}}}
                        )
                    else:
                        await col("rl_teams").update_one(
                            {"_id": ObjectId(team_id)},
                            {"$push": {"members": {"user_id": int(uid), "username": user_str, "epic": epic, "rolle": rolle}}}
                        )
                runasync(add_m(), bot)
                flash(f"Mitglied {uid} hinzugefügt!", "success")

        elif action == "remove_member":
            team_id = request.form.get("team_id", "")
            uid     = request.form.get("uid", "")
            is_trainer = request.form.get("is_trainer", "0") == "1"
            if team_id and uid:
                from bson import ObjectId
                async def rem_m():
                    if is_trainer:
                        await col("rl_teams").update_one(
                            {"_id": ObjectId(team_id)},
                            {"$pull": {"trainers": {"user_id": int(uid)}}}
                        )
                    else:
                        await col("rl_teams").update_one(
                            {"_id": ObjectId(team_id)},
                            {"$pull": {"members": {"user_id": int(uid)}}}
                        )
                runasync(rem_m(), bot)
                flash("Mitglied entfernt!", "success")

        elif action == "update_epic":
            team_id = request.form.get("team_id", "")
            uid     = request.form.get("uid", "")
            epic    = request.form.get("epic", "")
            if team_id and uid:
                from bson import ObjectId
                async def upd_epic():
                    await col("rl_teams").update_one(
                        {"_id": ObjectId(team_id), "members.user_id": int(uid)},
                        {"$set": {"members.$.epic": epic}}
                    )
                runasync(upd_epic(), bot)
                flash("Epic Name aktualisiert!", "success")

        elif action == "result":
            team_id  = request.form.get("team_id", "")
            won      = request.form.get("won", "1") == "1"
            if team_id:
                from bson import ObjectId
                field = "wins" if won else "losses"
                async def add_result():
                    await col("rl_teams").update_one({"_id": ObjectId(team_id)}, {"$inc": {field: 1}})
                runasync(add_result(), bot)
                flash(f'{"Sieg" if won else "Niederlage"} eingetragen!', "success")

        elif action == "set_role":
            team_id = request.form.get("team_id", "")
            role_id = request.form.get("role_id", "")
            if team_id and role_id:
                from bson import ObjectId
                async def set_role():
                    t = await col("rl_teams").find_one({"_id": ObjectId(team_id)})
                    if not t: return
                    guild_obj = bot.get_guild(int(gid))
                    if not guild_obj: return
                    r = guild_obj.get_role(int(role_id))
                    if not r: return
                    import discord
                    for m in t.get("members", []):
                        member = guild_obj.get_member(m["user_id"])
                        if member:
                            try: await member.add_roles(r)
                            except: pass
                runasync(set_role(), bot)
                flash("Rolle vergeben!", "success")

        elif action == "rename":
            team_id  = request.form.get("team_id", "")
            new_name = request.form.get("new_name", "").strip()
            if team_id and new_name:
                from bson import ObjectId
                async def rename_t():
                    await col("rl_teams").update_one({"_id": ObjectId(team_id)}, {"$set": {"name": new_name}})
                runasync(rename_t(), bot)
                flash("Team umbenannt!", "success")

        elif action == "delete":
            team_id = request.form.get("team_id", "")
            if team_id:
                from bson import ObjectId
                async def del_t():
                    await col("rl_teams").delete_one({"_id": ObjectId(team_id)})
                runasync(del_t(), bot)
                flash("Team gelöscht!", "success")

    teams = runasync(_find(col("rl_teams"), {"guild_id": int(gid)}, sort=("created", -1)), bot) or []

    role_opts = '<option value="">-- Keine Rolle --</option>' + "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>'
        for r in sorted(rls, key=lambda x: x.get("position", 0), reverse=True)
        if not r.get("managed") and r["name"] != "@everyone"
    )

    team_cards = ""
    for t in teams:
        tid = str(t["_id"])
        cap_str = get_member_name(gid, t.get("captain_id", ""), bot)
        members = t.get("members", [])
        trainers = t.get("trainers", [])

        member_rows = ""
        for m in members:
            mname = get_member_name(gid, m.get("user_id", ""), bot)
            member_rows += (
                f'<tr>'
                f'<td>{mname}</td>'
                f'<td>{m.get("rolle","Spieler")}</td>'
                f'<td>'
                f'<form method="POST" style="display:flex;gap:.3rem">'
                f'<input type="hidden" name="action" value="update_epic">'
                f'<input type="hidden" name="team_id" value="{tid}">'
                f'<input type="hidden" name="uid" value="{m.get("user_id","")}">'
                f'<input name="epic" class="inp" value="{m.get("epic","")}" placeholder="Epic Name" style="max-width:140px">'
                f'<button class="btn bs bsm">💾</button>'
                f'</form>'
                f'</td>'
                f'<td>'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="remove_member">'
                f'<input type="hidden" name="team_id" value="{tid}">'
                f'<input type="hidden" name="uid" value="{m.get("user_id","")}">'
                f'<input type="hidden" name="is_trainer" value="0">'
                f'<button class="btn bd bsm" onclick="return confirm(\'Entfernen?\')">🗑️</button>'
                f'</form>'
                f'</td></tr>'
            )

        trainer_rows = ""
        for tr in trainers:
            trname = get_member_name(gid, tr.get("user_id", ""), bot)
            trainer_rows += (
                f'<tr>'
                f'<td>{trname}</td>'
                f'<td><span class="tag tag-blue">Trainer</span></td>'
                f'<td>{tr.get("epic","–")}</td>'
                f'<td>'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="remove_member">'
                f'<input type="hidden" name="team_id" value="{tid}">'
                f'<input type="hidden" name="uid" value="{tr.get("user_id","")}">'
                f'<input type="hidden" name="is_trainer" value="1">'
                f'<button class="btn bd bsm" onclick="return confirm(\'Entfernen?\')">🗑️</button>'
                f'</form>'
                f'</td></tr>'
            )

        team_cards += (
            f'<div class="card">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem">'
            f'<div>'
            f'<div style="font-size:1.1rem;font-weight:700">🚗 {t["name"]} <span style="font-size:.85rem;color:var(--tx2)">({t.get("format","?")})</span></div>'
            f'<div style="font-size:.8rem;color:var(--tx2)">Captain: {cap_str} &bull; W/L: {t.get("wins",0)}/{t.get("losses",0)}</div>'
            f'</div>'
            f'<div style="display:flex;gap:.5rem;flex-wrap:wrap">'

            # Rename
            f'<form method="POST" style="display:flex;gap:.3rem">'
            f'<input type="hidden" name="action" value="rename">'
            f'<input type="hidden" name="team_id" value="{tid}">'
            f'<input name="new_name" class="inp" placeholder="Neuer Name" style="max-width:120px">'
            f'<button class="btn bs bsm">✏️</button>'
            f'</form>'

            # Result
            f'<form method="POST" style="display:flex;gap:.3rem">'
            f'<input type="hidden" name="action" value="result">'
            f'<input type="hidden" name="team_id" value="{tid}">'
            f'<select name="won" class="sel" style="max-width:100px">'
            f'<option value="1">Sieg</option><option value="0">Niederlage</option>'
            f'</select>'
            f'<button class="btn bp bsm">➕</button>'
            f'</form>'

            # Set role
            f'<form method="POST" style="display:flex;gap:.3rem">'
            f'<input type="hidden" name="action" value="set_role">'
            f'<input type="hidden" name="team_id" value="{tid}">'
            f'<select name="role_id" class="sel" style="max-width:120px">{role_opts}</select>'
            f'<button class="btn bs bsm">🎭 Rolle</button>'
            f'</form>'

            # Delete
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="delete">'
            f'<input type="hidden" name="team_id" value="{tid}">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Team löschen?\')">🗑️</button>'
            f'</form>'
            f'</div></div>'

            # Members table
            f'<table class="tbl"><thead><tr><th>Spieler / ID</th><th>Rolle</th><th>Epic Games</th><th></th></tr></thead><tbody>'
            + member_rows
            + trainer_rows
            + '</tbody></table>'

            # Add member
            f'<div style="margin-top:.75rem">'
            f'<div style="font-size:.85rem;font-weight:600;margin-bottom:.5rem">Mitglied hinzufügen</div>'
            f'<form method="POST" style="display:flex;gap:.5rem;flex-wrap:wrap">'
            f'<input type="hidden" name="action" value="add_member">'
            f'<input type="hidden" name="team_id" value="{tid}">'
            f'<input name="uid" class="inp" placeholder="User ID" style="max-width:130px" required>'
            f'<input name="epic" class="inp" placeholder="Epic Name" style="max-width:130px">'
            f'<select name="rolle" class="sel" style="max-width:120px">'
            f'<option>Spieler</option><option>Trainer</option><option>Captain</option>'
            f'</select>'
            f'<button class="btn bp bsm">➕ Hinzufügen</button>'
            f'</form>'
            f'</div>'
            f'</div>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "rl") +
        '<main class="main">' + alerts() +
        '<div class="pt">🚗 RL Teams</div>'
        f'<p class="ps">{len(teams)} Teams &bull; {g.get("name","")}</p>'
        + (team_cards or '<div class="card"><p style="color:var(--tx2)">Keine RL Teams vorhanden. Erstelle eines mit <code>/rl-team-erstellen</code>.</p></div>')
        + '</main></div>'
    )
    return pg(body)