from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime, timezone
from app import pg, alerts, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

bp = Blueprint("rl_teams", __name__)

RL_CSS = """
:root{--p:#8b5cf6;--pd:#7c3aed;--p2:rgba(139,92,246,.12);--p3:rgba(139,92,246,.25)}
.rl-nav{background:#0d0d14;border-bottom:1px solid #1e1b2e;padding:.875rem 1.5rem;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}
.rl-logo{font-size:1.1rem;font-weight:700;color:var(--p)}
.rl-wrap{display:flex;gap:1.5rem;padding:1.5rem;min-height:calc(100vh - 53px);background:#0a0a12}
.rl-main{flex:1}
.rl-card{background:#111120;border:1px solid #1e1b2e;border-radius:12px;padding:1.25rem;margin-bottom:1.25rem}
.rl-card-header{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:1rem;flex-wrap:wrap;gap:.75rem}
.rl-team-name{font-size:1.15rem;font-weight:700;color:#fff}
.rl-team-meta{font-size:.8rem;color:#6b7280;margin-top:.2rem}
.rl-actions{display:flex;gap:.5rem;flex-wrap:wrap}
.pb{background:var(--p);color:#fff;border:none;padding:.45rem .9rem;border-radius:7px;font-size:.82rem;font-weight:500;cursor:pointer;transition:all .15s}
.pb:hover{background:var(--pd)}
.pbd{background:#3b1f1f;color:#f87171;border:none;padding:.45rem .9rem;border-radius:7px;font-size:.82rem;font-weight:500;cursor:pointer;transition:all .15s}
.pbd:hover{background:#4c2626}
.pbs{background:#1e1b2e;color:#d1d5db;border:none;padding:.45rem .9rem;border-radius:7px;font-size:.82rem;font-weight:500;cursor:pointer;transition:all .15s}
.pbs:hover{background:#2a2740}
.rl-tbl{width:100%;border-collapse:collapse;margin-top:.75rem}
.rl-tbl th{text-align:left;padding:.6rem .875rem;color:#6b7280;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid #1e1b2e}
.rl-tbl td{padding:.75rem .875rem;border-bottom:1px solid #111120;font-size:.875rem}
.rl-tbl tr:hover td{background:rgba(139,92,246,.04)}
.rl-inp{width:100%;padding:.55rem .8rem;background:#1a1a2e;border:1px solid #2d2b4e;border-radius:7px;color:#fff;font-size:.85rem}
.rl-inp:focus{outline:none;border-color:var(--p)}
.rl-sel{padding:.55rem .8rem;background:#1a1a2e;border:1px solid #2d2b4e;border-radius:7px;color:#fff;font-size:.85rem}
.rl-sel:focus{outline:none;border-color:var(--p)}
.rl-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.75rem;margin-bottom:1rem}
.rl-stat{background:#0d0d1a;border:1px solid #1e1b2e;border-top:3px solid var(--p);border-radius:10px;padding:.875rem;text-align:center}
.rl-stat-v{font-size:1.5rem;font-weight:700;color:var(--p)}
.rl-stat-l{font-size:.75rem;color:#6b7280;margin-top:.2rem}
.badge{display:inline-flex;padding:.2rem .6rem;border-radius:20px;font-size:.72rem;font-weight:600}
.badge-captain{background:rgba(234,179,8,.15);color:#eab308}
.badge-leader{background:rgba(139,92,246,.2);color:#a78bfa}
.badge-trainer{background:rgba(59,130,246,.15);color:#60a5fa}
.badge-player{background:rgba(107,114,128,.15);color:#9ca3af}
.rl-section{font-size:.8rem;font-weight:600;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;margin:.875rem 0 .5rem}
.rl-add-row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:flex-end;margin-top:.75rem;padding-top:.75rem;border-top:1px solid #1e1b2e}
.rl-alert{padding:.75rem 1rem;border-radius:8px;margin-bottom:1rem;font-size:.875rem}
.rl-ok{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);color:#22c55e}
.rl-err{background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.2);color:#f87171}
.rl-winrate{font-size:.8rem;color:#a78bfa;font-weight:600}
.season-tab{display:inline-flex;padding:.35rem .8rem;border-radius:6px;font-size:.8rem;font-weight:500;cursor:pointer;border:1px solid #2d2b4e;color:#6b7280;background:#111120;margin-right:.35rem;margin-bottom:.5rem}
.season-tab.active{background:var(--p2);border-color:var(--p);color:var(--p)}
"""

ROLE_BADGES = {
    "Captain": "badge-captain",
    "Team Leader": "badge-leader",
    "Trainer": "badge-trainer",
    "Spieler": "badge-player",
}

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

def _winrate(w, l, d=0):
    total = w + l + d
    return f"{round(w/total*100)}%" if total else "—"

def _match_history_rows(matches):
    if not matches: return '<tr><td colspan="5" style="color:#6b7280;text-align:center">Keine Matches</td></tr>'
    rows = ""
    for m in reversed(matches[-20:]):
        res = m.get("result","?")
        color = "#22c55e" if res == "W" else ("#f87171" if res == "L" else "#f59e0b")
        rows += (
            f'<tr>'
            f'<td style="color:{color};font-weight:700">{res}</td>'
            f'<td>{m.get("opponent","—")}</td>'
            f'<td>{m.get("score","—")}</td>'
            f'<td>{m.get("season","—")}</td>'
            f'<td style="color:#6b7280;font-size:.78rem">{str(m.get("date",""))[:10]}</td>'
            f'</tr>'
        )
    return rows

@bp.route("/g/<gid>/rl", methods=["GET","POST"])
@_lreq
@_greq
def grl(gid):
    from utils import col, _find
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []
    season = request.args.get("season", "all")

    if request.method == "POST":
        action = request.form.get("action", "")
        tid = request.form.get("team_id", "")

        if action == "add_member" and tid:
            from bson import ObjectId
            uid = request.form.get("uid","").strip()
            epic = request.form.get("epic","").strip()
            rolle = request.form.get("rolle","Spieler")
            if uid.isdigit():
                user_str = get_member_name(gid, uid, bot).split(" / ")[0]
                async def _add():
                    t = await col("rl_teams").find_one({"_id": ObjectId(tid)})
                    if not t: return
                    field = "trainers" if rolle == "Trainer" else "members"
                    if rolle == "Trainer" and len(t.get("trainers",[])) >= 2: return
                    await col("rl_teams").update_one(
                        {"_id": ObjectId(tid)},
                        {"$push": {field: {"user_id": int(uid), "username": user_str, "epic": epic, "rolle": rolle, "since": datetime.now(timezone.utc).isoformat()[:10]}}}
                    )
                runasync(_add(), bot)
                flash(f"Mitglied hinzugefügt!", "success")

        elif action == "remove_member" and tid:
            from bson import ObjectId
            uid = request.form.get("uid","")
            is_trainer = request.form.get("is_trainer","0") == "1"
            async def _rem():
                field = "trainers" if is_trainer else "members"
                await col("rl_teams").update_one({"_id": ObjectId(tid)}, {"$pull": {field: {"user_id": int(uid)}}})
            runasync(_rem(), bot)
            flash("Mitglied entfernt!", "success")

        elif action == "update_epic" and tid:
            from bson import ObjectId
            uid = request.form.get("uid","")
            epic = request.form.get("epic","")
            async def _upd():
                await col("rl_teams").update_one({"_id": ObjectId(tid), "members.user_id": int(uid)}, {"$set": {"members.$.epic": epic}})
            runasync(_upd(), bot)
            flash("Epic Name aktualisiert!", "success")

        elif action == "result" and tid:
            from bson import ObjectId
            result = request.form.get("result","W")
            opponent = request.form.get("opponent","").strip()
            score = request.form.get("score","").strip()
            cur_season = request.form.get("cur_season","1")
            field = "wins" if result == "W" else ("losses" if result == "L" else "draws")
            match_entry = {"result": result, "opponent": opponent, "score": score, "season": cur_season, "date": datetime.now(timezone.utc).isoformat()}
            async def _res():
                await col("rl_teams").update_one({"_id": ObjectId(tid)}, {
                    "$inc": {field: 1, f"season_stats.{cur_season}.{field}": 1},
                    "$push": {"matches": match_entry}
                })
            runasync(_res(), bot)
            flash(f'{"Sieg" if result=="W" else ("Niederlage" if result=="L" else "Unentschieden")} eingetragen!', "success")

        elif action == "set_role" and tid:
            from bson import ObjectId
            role_id = request.form.get("role_id","")
            if role_id:
                async def _role():
                    t = await col("rl_teams").find_one({"_id": ObjectId(tid)})
                    if not t: return
                    guild_obj = bot.get_guild(int(gid))
                    if not guild_obj: return
                    r = guild_obj.get_role(int(role_id))
                    if not r: return
                    for m in t.get("members",[]):
                        if not isinstance(m, dict): continue
                        member = guild_obj.get_member(m["user_id"])
                        if member:
                            try: await member.add_roles(r)
                            except: pass
                runasync(_role(), bot)
                flash("Rolle vergeben!", "success")

        elif action == "announce" and tid:
            from bson import ObjectId
            msg = request.form.get("msg","").strip()
            ch_id = request.form.get("announce_channel","")
            if msg and ch_id:
                async def _ann():
                    import discord
                    ch = bot.get_channel(int(ch_id))
                    if not ch: return
                    t = await col("rl_teams").find_one({"_id": ObjectId(tid)})
                    name = t.get("name","Team") if t else "Team"
                    embed = discord.Embed(title=f"📢 {name}", description=msg, color=0x8b5cf6)
                    await ch.send(embed=embed)
                runasync(_ann(), bot)
                flash("Ankündigung gesendet!", "success")

        elif action == "rename" and tid:
            from bson import ObjectId
            new_name = request.form.get("new_name","").strip()
            if new_name:
                runasync(col("rl_teams").update_one({"_id": ObjectId(tid)}, {"$set": {"name": new_name}}), bot)
                flash("Team umbenannt!", "success")

        elif action == "delete" and tid:
            from bson import ObjectId
            runasync(col("rl_teams").delete_one({"_id": ObjectId(tid)}), bot)
            flash("Team gelöscht!", "success")

        return redirect(url_for("rl_teams.grl", gid=gid, season=season))

    teams = runasync(_find(col("rl_teams"), {"guild_id": int(gid)}, sort=("created",-1)), bot) or []

    # Channels for announcement dropdown
    channels = dget(f"/guilds/{gid}/channels", isbot=True) or []
    text_channels = [c for c in channels if c.get("type") == 0]
    ch_opts = "".join(f'<option value="{c["id"]}">#{c["name"]}</option>' for c in text_channels)

    role_opts = '<option value="">-- Keine --</option>' + "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>'
        for r in sorted(rls, key=lambda x: x.get("position",0), reverse=True)
        if not r.get("managed") and r["name"] != "@everyone"
    )

    # Alerts
    flash_html = ""
    from flask import get_flashed_messages
    for cat, msg in get_flashed_messages(with_categories=True):
        flash_html += f'<div class="rl-alert {"rl-ok" if cat=="success" else "rl-err"}">{msg}</div>'

    team_cards = ""
    for t in teams:
        if not isinstance(t, dict): continue
        tid = str(t["_id"])
        w = t.get("wins",0); l = t.get("losses",0); d = t.get("draws",0)
        wr = _winrate(w, l, d)
        members = [m for m in t.get("members",[]) if isinstance(m, dict)]
        trainers = [m for m in t.get("trainers",[]) if isinstance(m, dict)]
        matches = t.get("matches",[])
        cur_season = str(t.get("current_season","1"))

        member_rows = ""
        for m in members:
            mname = get_member_name(gid, m.get("user_id",""), bot)
            rolle = m.get("rolle","Spieler")
            badge_cls = ROLE_BADGES.get(rolle, "badge-player")
            member_rows += (
                f'<tr>'
                f'<td>{mname}</td>'
                f'<td><span class="badge {badge_cls}">{rolle}</span></td>'
                f'<td>'
                f'<form method="POST" style="display:flex;gap:.35rem">'
                f'<input type="hidden" name="action" value="update_epic">'
                f'<input type="hidden" name="team_id" value="{tid}">'
                f'<input type="hidden" name="uid" value="{m.get("user_id","")}">'
                f'<input name="epic" class="rl-inp" value="{m.get("epic","")}" placeholder="Epic Name" style="max-width:130px">'
                f'<button class="pb" style="white-space:nowrap">💾 Speichern</button>'
                f'</form>'
                f'</td>'
                f'<td style="color:#6b7280;font-size:.78rem">{m.get("since","—")}</td>'
                f'<td>'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="remove_member">'
                f'<input type="hidden" name="team_id" value="{tid}">'
                f'<input type="hidden" name="uid" value="{m.get("user_id","")}">'
                f'<input type="hidden" name="is_trainer" value="0">'
                f'<button class="pbd" onclick="return confirm(\'Entfernen?\')">🗑️ Entfernen</button>'
                f'</form>'
                f'</td></tr>'
            )

        for tr in trainers:
            trname = get_member_name(gid, tr.get("user_id",""), bot)
            member_rows += (
                f'<tr>'
                f'<td>{trname}</td>'
                f'<td><span class="badge badge-trainer">Trainer</span></td>'
                f'<td style="color:#6b7280">{tr.get("epic","—")}</td>'
                f'<td style="color:#6b7280;font-size:.78rem">{tr.get("since","—")}</td>'
                f'<td>'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="remove_member">'
                f'<input type="hidden" name="team_id" value="{tid}">'
                f'<input type="hidden" name="uid" value="{tr.get("user_id","")}">'
                f'<input type="hidden" name="is_trainer" value="1">'
                f'<button class="pbd" onclick="return confirm(\'Entfernen?\')">🗑️ Entfernen</button>'
                f'</form>'
                f'</td></tr>'
            )

        team_cards += f'''
<div class="rl-card">
  <div class="rl-card-header">
    <div>
      <div class="rl-team-name">🚗 {t.get("name","")} <span style="font-size:.8rem;color:#6b7280">({t.get("format","?")})</span></div>
      <div class="rl-team-meta">Captain: {get_member_name(gid, t.get("captain_id",""), bot)} &bull; Saison {cur_season}</div>
    </div>
    <div class="rl-actions">
      <form method="POST" style="display:flex;gap:.35rem">
        <input type="hidden" name="action" value="rename">
        <input type="hidden" name="team_id" value="{tid}">
        <input name="new_name" class="rl-inp" placeholder="Neuer Name" style="max-width:120px">
        <button class="pbs">✏️ Umbenennen</button>
      </form>
      <form method="POST" style="display:inline">
        <input type="hidden" name="action" value="delete">
        <input type="hidden" name="team_id" value="{tid}">
        <button class="pbd" onclick="return confirm('Team löschen?')">🗑️ Löschen</button>
      </form>
    </div>
  </div>

  <div class="rl-stats">
    <div class="rl-stat"><div class="rl-stat-v">{w}</div><div class="rl-stat-l">Siege</div></div>
    <div class="rl-stat"><div class="rl-stat-v" style="color:#f87171">{l}</div><div class="rl-stat-l">Niederlagen</div></div>
    <div class="rl-stat"><div class="rl-stat-v" style="color:#f59e0b">{d}</div><div class="rl-stat-l">Unentschieden</div></div>
    <div class="rl-stat"><div class="rl-stat-v">{wr}</div><div class="rl-stat-l">Winrate</div></div>
    <div class="rl-stat"><div class="rl-stat-v">{w-l:+d}</div><div class="rl-stat-l">Diff</div></div>
    <div class="rl-stat"><div class="rl-stat-v">{len(members)}</div><div class="rl-stat-l">Spieler</div></div>
  </div>

  <div class="rl-section">Kader</div>
  <table class="rl-tbl">
    <thead><tr><th>Spieler</th><th>Rolle</th><th>Epic Games</th><th>Dabei seit</th><th></th></tr></thead>
    <tbody>{member_rows or '<tr><td colspan="5" style="color:#6b7280;text-align:center">Keine Mitglieder</td></tr>'}</tbody>
  </table>

  <div class="rl-add-row">
    <form method="POST" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
      <input type="hidden" name="action" value="add_member">
      <input type="hidden" name="team_id" value="{tid}">
      <input name="uid" class="rl-inp" placeholder="User ID" style="max-width:120px" required>
      <input name="epic" class="rl-inp" placeholder="Epic Name" style="max-width:120px">
      <select name="rolle" class="rl-sel">
        <option>Spieler</option><option>Captain</option><option>Team Leader</option><option>Trainer</option>
      </select>
      <button class="pb">➕ Hinzufügen</button>
    </form>
  </div>

  <div class="rl-section" style="margin-top:1.25rem">Ergebnis eintragen</div>
  <form method="POST" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
    <input type="hidden" name="action" value="result">
    <input type="hidden" name="team_id" value="{tid}">
    <input type="hidden" name="cur_season" value="{cur_season}">
    <select name="result" class="rl-sel">
      <option value="W">✅ Sieg</option>
      <option value="L">❌ Niederlage</option>
      <option value="D">🟡 Unentschieden</option>
    </select>
    <input name="opponent" class="rl-inp" placeholder="Gegner" style="max-width:130px">
    <input name="score" class="rl-inp" placeholder="Score z.B. 3-1" style="max-width:100px">
    <button class="pb">➕ Eintragen</button>
  </form>

  <div class="rl-section" style="margin-top:1.25rem">Match Historie (letzte 20)</div>
  <table class="rl-tbl">
    <thead><tr><th>Ergebnis</th><th>Gegner</th><th>Score</th><th>Saison</th><th>Datum</th></tr></thead>
    <tbody>{_match_history_rows(matches)}</tbody>
  </table>

  <div class="rl-section" style="margin-top:1.25rem">Rolle vergeben</div>
  <form method="POST" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
    <input type="hidden" name="action" value="set_role">
    <input type="hidden" name="team_id" value="{tid}">
    <select name="role_id" class="rl-sel">{role_opts}</select>
    <button class="pbs">🎭 Allen Mitgliedern vergeben</button>
  </form>

  <div class="rl-section" style="margin-top:1.25rem">📢 Ankündigung</div>
  <form method="POST" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">
    <input type="hidden" name="action" value="announce">
    <input type="hidden" name="team_id" value="{tid}">
    <select name="announce_channel" class="rl-sel" style="max-width:180px">{ch_opts}</select>
    <input name="msg" class="rl-inp" placeholder="Nachricht..." style="max-width:280px" required>
    <button class="pb">📤 Senden</button>
  </form>

  <div style="margin-top:1rem;text-align:right">
    <a href="/g/{gid}/rl-bracket?team={tid}" target="_blank" class="pbs" style="display:inline-flex;align-items:center;gap:.4rem;padding:.45rem .9rem;border-radius:7px;font-size:.82rem;font-weight:500;text-decoration:none">🏆 Turnier Bracket</a>
  </div>
</div>'''

    html = f'''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RL Teams — {g.get("name","")}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{--p:#8b5cf6;--pd:#7c3aed;--p2:rgba(139,92,246,.12)}}
body{{font-family:system-ui,sans-serif;background:#0a0a12;color:#e5e7eb;min-height:100vh;line-height:1.6}}
a{{color:inherit;text-decoration:none}}
{RL_CSS}
</style>
</head>
<body>
<nav class="rl-nav">
  <div class="rl-logo">🚗 RL Teams — {g.get("name","")}</div>
  <div style="display:flex;gap:.75rem;align-items:center;color:#6b7280">
    <a href="/g/{gid}/rl-bracket" target="_blank" class="pb">🏆 Turnier</a>
    <a href="javascript:window.close()" class="pbs">✕ Schließen</a>
  </div>
</nav>
<div style="padding:1.5rem;max-width:1100px;margin:0 auto">
  {flash_html}
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1.25rem;flex-wrap:wrap;gap:.75rem">
    <div>
      <div style="font-size:1.5rem;font-weight:700">🚗 RL Teams</div>
      <div style="color:#6b7280;font-size:.875rem">{len(teams)} Teams &bull; {g.get("name","")}</div>
    </div>
    <div style="color:#6b7280;font-size:.8rem">Teams werden mit <code style="background:#1a1a2e;padding:.1rem .4rem;border-radius:4px">/rl-team-erstellen</code> angelegt</div>
  </div>
  {team_cards or '<div class="rl-card"><p style="color:#6b7280;text-align:center;padding:2rem">Keine RL Teams vorhanden.</p></div>'}
</div>
<div style="text-align:center;padding:1rem;color:#374151;font-size:.78rem;border-top:1px solid #1e1b2e;margin-top:2rem">RLD Dashboard &mdash; Made by Rezyel &bull; &copy; 2026</div>
</body>
</html>'''

    return html