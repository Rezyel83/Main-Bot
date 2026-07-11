from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

bp = Blueprint("applications", __name__)

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

@bp.route("/g/<gid>/apps", methods=["GET", "POST"])
@_lreq
@_greq
def gapps(gid):
    from utils import col, _find, _update
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    if request.method == "POST":
        action = request.form.get("action")
        app_id = request.form.get("app_id", "")
        uid    = request.form.get("uid", "")
        grund  = request.form.get("grund", "Kein Grund")

        if action in ("accept", "deny") and app_id:
            from bson import ObjectId
            status = "angenommen" if action == "accept" else "abgelehnt"
            async def update_app():
                await col("applications").update_one(
                    {"_id": ObjectId(app_id)},
                    {"$set": {"status": status, "bearbeitet_von": int(session["user_id"]), "bearbeitet_at": datetime.utcnow()}}
                )
                if uid:
                    guild_obj = bot.get_guild(int(gid))
                    if guild_obj:
                        member = guild_obj.get_member(int(uid))
                        if member:
                            import discord
                            try:
                                if action == "accept":
                                    await member.send(f"🎉 Deine Bewerbung auf **{guild_obj.name}** wurde angenommen!")
                                else:
                                    await member.send(f"❌ Deine Bewerbung auf **{guild_obj.name}** wurde abgelehnt. Grund: {grund}")
                            except: pass
            runasync(update_app(), bot)
            flash(f"Bewerbung {status}!", "success")

        elif action == "create_internal":
            titel     = request.form.get("titel", "").strip()
            beschr    = request.form.get("beschreibung", "").strip()
            fragen_raw= request.form.get("fragen", "").strip()
            if titel:
                fragen = [f.strip() for f in fragen_raw.split("\n") if f.strip()]
                async def create_int():
                    await col("job_postings").insert_one({
                        "guild_id": int(gid), "titel": titel,
                        "beschreibung": beschr, "fragen": fragen,
                        "typ": "intern", "aktiv": True, "created": datetime.utcnow(),
                        "erstellt_von": int(session["user_id"])
                    })
                runasync(create_int(), bot)
                flash(f"Interne Ausschreibung '{titel}' erstellt!", "success")

        elif action == "create_extern":
            titel  = request.form.get("titel_ext", "").strip()
            beschr = request.form.get("beschreibung_ext", "").strip()
            fragen_raw = request.form.get("fragen_ext", "").strip()
            if titel:
                fragen = [f.strip() for f in fragen_raw.split("\n") if f.strip()]
                async def create_ext():
                    await col("job_postings").insert_one({
                        "guild_id": int(gid), "titel": titel,
                        "beschreibung": beschr, "fragen": fragen,
                        "typ": "extern", "aktiv": True, "created": datetime.utcnow(),
                        "erstellt_von": int(session["user_id"])
                    })
                runasync(create_ext(), bot)
                flash(f"Externe Ausschreibung '{titel}' erstellt!", "success")

        elif action == "toggle_posting":
            posting_id = request.form.get("posting_id", "")
            if posting_id:
                from bson import ObjectId
                async def toggle_p():
                    p = await col("job_postings").find_one({"_id": ObjectId(posting_id)})
                    if p:
                        await col("job_postings").update_one({"_id": ObjectId(posting_id)}, {"$set": {"aktiv": not p.get("aktiv", True)}})
                runasync(toggle_p(), bot)
                flash("Status geändert!", "success")

    tab = request.args.get("tab", "offen")

    # Applications
    apps = runasync(_find(col("applications"), {"guild_id": int(gid), "status": tab}, sort=("ts", -1), limit=50), bot) or []
    postings = runasync(_find(col("job_postings"), {"guild_id": int(gid)}, sort=("created", -1)), bot) or []

    # App rows
    app_cards = ""
    for a in apps:
        user_str = get_member_name(gid, a.get("user_id", ""), bot)
        ts_str   = a["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(a.get("ts"), datetime) else "?"
        typ_cls  = "tag-blue" if a.get("typ") == "intern" else "tag-orange"
        typ_lbl  = a.get("typ", "extern").title()

        app_cards += (
            f'<div class="card">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div>'
            f'<div style="font-weight:600">{user_str}</div>'
            f'<div style="font-size:.8rem;color:var(--tx2);margin-top:.2rem">'
            f'<span class="tag {typ_cls}">{typ_lbl}</span> &bull; {ts_str}'
            f'</div></div>'
        )
        if tab == "offen":
            app_cards += (
                f'<div style="display:flex;gap:.5rem">'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="accept">'
                f'<input type="hidden" name="app_id" value="{a["_id"]}">'
                f'<input type="hidden" name="uid" value="{a.get("user_id","")}">'
                f'<button class="btn bg-btn bsm">✅ Annehmen</button>'
                f'</form>'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="deny">'
                f'<input type="hidden" name="app_id" value="{a["_id"]}">'
                f'<input type="hidden" name="uid" value="{a.get("user_id","")}">'
                f'<input name="grund" placeholder="Grund" style="padding:.3rem .5rem;background:var(--bg3);border:1px solid var(--bdr);border-radius:5px;color:var(--tx);font-size:.78rem;width:120px">'
                f'<button class="btn bd bsm">❌ Ablehnen</button>'
                f'</form>'
                f'</div>'
            )
        app_cards += '</div>'

        # Fields
        for field, label in [("alter","Alter"),("erfahrung","Erfahrung"),("warum","Warum"),("verfuegbarkeit","Verfügbarkeit")]:
            if a.get(field):
                app_cards += f'<div style="margin-top:.5rem;font-size:.85rem"><b>{label}:</b> {a[field]}</div>'
        app_cards += '</div>'

    # Posting rows
    posting_rows = ""
    for p in postings:
        aktiv = p.get("aktiv", True)
        posting_rows += (
            f'<tr>'
            f'<td><b>{p["titel"]}</b></td>'
            f'<td><span class="tag {"tag-blue" if p.get("typ")=="intern" else "tag-orange"}">{p.get("typ","?").title()}</span></td>'
            f'<td><span class="tag {"tag-green" if aktiv else "tag-gray"}">{"Aktiv" if aktiv else "Inaktiv"}</span></td>'
            f'<td>{len(p.get("fragen",[]))} Fragen</td>'
            f'<td>'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="toggle_posting">'
            f'<input type="hidden" name="posting_id" value="{p["_id"]}">'
            f'<button class="btn bs bsm">{"⏸️" if aktiv else "▶️"}</button>'
            f'</form>'
            f'</td></tr>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "apps") +
        '<main class="main">' + alerts() +
        '<div class="pt">Bewerbungen</div>'
        f'<p class="ps">{g.get("name","")}</p>'

        # Tabs
        f'<div style="display:flex;gap:.5rem;margin-bottom:1rem">'
        f'<a href="?tab=offen" class="btn {"bp" if tab=="offen" else "bs"}">📋 Offen</a>'
        f'<a href="?tab=angenommen" class="btn {"bp" if tab=="angenommen" else "bs"}">✅ Angenommen</a>'
        f'<a href="?tab=abgelehnt" class="btn {"bp" if tab=="abgelehnt" else "bs"}">❌ Abgelehnt</a>'
        f'</div>'

        + (app_cards or '<div class="card"><p style="color:var(--tx2)">Keine Bewerbungen in dieser Kategorie.</p></div>')

        # Ausschreibungen
        + '<div class="card" style="margin-top:1.5rem"><div class="ct">📢 Ausschreibungen</div>'
        '<table class="tbl"><thead><tr><th>Titel</th><th>Typ</th><th>Status</th><th>Fragen</th><th></th></tr></thead><tbody>'
        + (posting_rows or '<tr><td colspan="5" style="color:var(--tx2);text-align:center">Keine Ausschreibungen</td></tr>')
        + '</tbody></table></div>'

        # Interne Ausschreibung erstellen
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem">'
        '<div class="card"><div class="ct">🔒 Interne Ausschreibung</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="create_internal">'
        '<div class="fg"><label class="lbl">Titel</label><input name="titel" class="inp" required></div>'
        '<div class="fg"><label class="lbl">Beschreibung</label><textarea name="beschreibung" class="ta"></textarea></div>'
        '<div class="fg"><label class="lbl">Fragen (eine pro Zeile)</label><textarea name="fragen" class="ta" placeholder="Was ist deine Erfahrung?\nWarum willst du ins Team?"></textarea></div>'
        '<button class="btn bp">Erstellen</button>'
        '</form></div>'

        '<div class="card"><div class="ct">🌍 Externe Ausschreibung</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="create_extern">'
        '<div class="fg"><label class="lbl">Titel</label><input name="titel_ext" class="inp" required></div>'
        '<div class="fg"><label class="lbl">Beschreibung</label><textarea name="beschreibung_ext" class="ta"></textarea></div>'
        '<div class="fg"><label class="lbl">Fragen (eine pro Zeile)</label><textarea name="fragen_ext" class="ta" placeholder="Dein Alter?\nDeine Verfügbarkeit?"></textarea></div>'
        '<button class="btn bp">Erstellen</button>'
        '</form></div>'
        '</div>'
        '</main></div>'
    )
    return pg(body)
