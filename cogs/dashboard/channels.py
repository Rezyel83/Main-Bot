from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
import os
import requests as hr
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds

bp = Blueprint("channels", __name__)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DAPI = "https://discord.com/api/v10"

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

def bot_patch(endpoint, data):
    try:
        r = hr.patch(
            f"{DAPI}{endpoint}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            json=data, timeout=8
        )
        return r.ok, r.status_code
    except Exception as ex:
        return False, str(ex)

def bot_post(endpoint, data):
    try:
        r = hr.post(
            f"{DAPI}{endpoint}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            json=data, timeout=8
        )
        return r.ok, r.json() if r.ok else r.status_code
    except Exception as ex:
        return False, str(ex)

def bot_delete(endpoint):
    try:
        r = hr.delete(
            f"{DAPI}{endpoint}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
            timeout=8
        )
        return r.ok
    except:
        return False

@bp.route("/g/<gid>/channels", methods=["GET", "POST"])
@_lreq
@_greq
def gchannels(gid):
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "rename_channel":
            ch_id   = request.form.get("channel_id", "")
            new_name = request.form.get("new_name", "").strip()
            if ch_id and new_name:
                ok, code = bot_patch(f"/channels/{ch_id}", {"name": new_name})
                if ok: flash(f"Kanal umbenannt zu '{new_name}'!", "success")
                else: flash(f"❌ Fehler: {code}", "error")

        elif action == "move_channel":
            ch_id  = request.form.get("channel_id", "")
            cat_id = request.form.get("category_id", "")
            if ch_id:
                data = {"parent_id": cat_id if cat_id else None}
                ok, code = bot_patch(f"/channels/{ch_id}", data)
                if ok: flash("Kanal verschoben!", "success")
                else: flash(f"❌ Fehler: {code}", "error")

        elif action == "create_channel":
            name    = request.form.get("ch_name", "").strip()
            typ     = request.form.get("ch_type", "0")
            cat_id  = request.form.get("ch_category", "")
            topic   = request.form.get("ch_topic", "").strip()
            if name:
                data = {"name": name, "type": int(typ)}
                if cat_id: data["parent_id"] = cat_id
                if topic and typ == "0": data["topic"] = topic
                ok, res = bot_post(f"/guilds/{gid}/channels", data)
                if ok: flash(f"Kanal '{name}' erstellt!", "success")
                else: flash(f"❌ Fehler: {res}", "error")

        elif action == "create_category":
            name = request.form.get("cat_name", "").strip()
            if name:
                ok, res = bot_post(f"/guilds/{gid}/channels", {"name": name, "type": 4})
                if ok: flash(f"Kategorie '{name}' erstellt!", "success")
                else: flash(f"❌ Fehler: {res}", "error")

        elif action == "rename_category":
            cat_id   = request.form.get("cat_id", "")
            new_name = request.form.get("cat_new_name", "").strip()
            if cat_id and new_name:
                ok, code = bot_patch(f"/channels/{cat_id}", {"name": new_name})
                if ok: flash(f"Kategorie umbenannt zu '{new_name}'!", "success")
                else: flash(f"❌ Fehler: {code}", "error")

        elif action == "delete_channel":
            ch_id = request.form.get("channel_id", "")
            if ch_id:
                ok = bot_delete(f"/channels/{ch_id}")
                if ok: flash("Kanal gelöscht!", "success")
                else: flash("❌ Fehler beim Löschen!", "error")

        elif action == "set_topic":
            ch_id = request.form.get("channel_id", "")
            topic = request.form.get("topic", "").strip()
            if ch_id:
                ok, code = bot_patch(f"/channels/{ch_id}", {"topic": topic})
                if ok: flash("Topic gesetzt!", "success")
                else: flash(f"❌ Fehler: {code}", "error")

        elif action == "set_slowmode":
            ch_id   = request.form.get("channel_id", "")
            seconds = request.form.get("seconds", "0")
            if ch_id and seconds.isdigit():
                ok, code = bot_patch(f"/channels/{ch_id}", {"rate_limit_per_user": int(seconds)})
                if ok: flash(f"Slowmode auf {seconds}s gesetzt!", "success")
                else: flash(f"❌ Fehler: {code}", "error")

    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    cats = sorted([c for c in chs if c.get("type") == 4], key=lambda x: x.get("position", 0))
    all_channels = sorted([c for c in chs if c.get("type") in [0, 2, 5, 13]], key=lambda x: x.get("position", 0))

    cat_opts_with_none = '<option value="">-- Keine Kategorie --</option>' + "".join(
        f'<option value="{c["id"]}">{c["name"]}</option>' for c in cats
    )

    # Build channel tree
    channel_tree = ""
    for cat in cats:
        cat_chs = [c for c in all_channels if c.get("parent_id") == cat["id"]]
        ch_type_icon = {"0": "💬", "2": "🔊", "5": "📢", "13": "🎙️"}

        channel_tree += (
            f'<div style="margin-bottom:1rem">'
            f'<div style="display:flex;align-items:center;justify-content:space-between;padding:.5rem .75rem;background:var(--bg3);border-radius:8px;margin-bottom:.5rem">'
            f'<span style="font-weight:600;font-size:.9rem">📁 {cat["name"]}</span>'
            f'<div style="display:flex;gap:.4rem">'
            # Rename category
            f'<form method="POST" style="display:flex;gap:.3rem">'
            f'<input type="hidden" name="action" value="rename_category">'
            f'<input type="hidden" name="cat_id" value="{cat["id"]}">'
            f'<input name="cat_new_name" class="inp" placeholder="Neuer Name" style="max-width:140px" required>'
            f'<button class="btn bs bsm">✏️</button>'
            f'</form>'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="delete_channel">'
            f'<input type="hidden" name="channel_id" value="{cat["id"]}">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Kategorie löschen? Alle Kanäle darin werden ebenfalls gelöscht!\')">🗑️</button>'
            f'</form>'
            f'</div></div>'
        )

        for ch in cat_chs:
            icon = ch_type_icon.get(str(ch.get("type", 0)), "💬")
            channel_tree += (
                f'<div style="display:flex;align-items:center;justify-content:space-between;padding:.4rem .75rem .4rem 1.5rem;border-radius:6px;margin-bottom:.25rem" '
                f'onmouseover="this.style.background=\'rgba(255,255,255,.03)\'" onmouseout="this.style.background=\'transparent\'">'
                f'<span style="font-size:.875rem">{icon} {ch["name"]}</span>'
                f'<div style="display:flex;gap:.3rem">'
                # Rename
                f'<form method="POST" style="display:flex;gap:.3rem">'
                f'<input type="hidden" name="action" value="rename_channel">'
                f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                f'<input name="new_name" class="inp" placeholder="Umbenennen" style="max-width:120px" required>'
                f'<button class="btn bs bsm">✏️</button>'
                f'</form>'
                # Move
                f'<form method="POST" style="display:flex;gap:.3rem">'
                f'<input type="hidden" name="action" value="move_channel">'
                f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                f'<select name="category_id" class="sel" style="max-width:130px">{cat_opts_with_none}</select>'
                f'<button class="btn bs bsm">📂</button>'
                f'</form>'
            )
            if ch.get("type") == 0:
                channel_tree += (
                    # Topic
                    f'<form method="POST" style="display:flex;gap:.3rem">'
                    f'<input type="hidden" name="action" value="set_topic">'
                    f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                    f'<input name="topic" class="inp" placeholder="Topic" value="{ch.get("topic","")}" style="max-width:120px">'
                    f'<button class="btn bs bsm">📝</button>'
                    f'</form>'
                    # Slowmode
                    f'<form method="POST" style="display:flex;gap:.3rem">'
                    f'<input type="hidden" name="action" value="set_slowmode">'
                    f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                    f'<input name="seconds" type="number" class="inp" value="{ch.get("rate_limit_per_user",0)}" style="max-width:70px;min-width:60px">'
                    f'<button class="btn bs bsm">🐢</button>'
                    f'</form>'
                )
            channel_tree += (
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="delete_channel">'
                f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                f'<button class="btn bd bsm" onclick="return confirm(\'Kanal löschen?\')">🗑️</button>'
                f'</form>'
                f'</div></div>'
            )
        channel_tree += '</div>'

    # Uncategorized
    uncat = [c for c in all_channels if not c.get("parent_id")]
    if uncat:
        channel_tree += '<div style="margin-bottom:1rem"><div style="font-size:.85rem;color:var(--tx2);margin-bottom:.5rem">Ohne Kategorie</div>'
        ch_type_icon = {"0": "💬", "2": "🔊", "5": "📢", "13": "🎙️"}
        for ch in uncat:
            icon = ch_type_icon.get(str(ch.get("type", 0)), "💬")
            channel_tree += (
                f'<div style="display:flex;align-items:center;justify-content:space-between;padding:.4rem .75rem;border-radius:6px;margin-bottom:.25rem">'
                f'<span style="font-size:.875rem">{icon} {ch["name"]}</span>'
                f'<div style="display:flex;gap:.3rem">'
                f'<form method="POST" style="display:flex;gap:.3rem">'
                f'<input type="hidden" name="action" value="rename_channel">'
                f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                f'<input name="new_name" class="inp" placeholder="Umbenennen" style="max-width:120px" required>'
                f'<button class="btn bs bsm">✏️</button>'
                f'</form>'
                f'<form method="POST" style="display:flex;gap:.3rem">'
                f'<input type="hidden" name="action" value="move_channel">'
                f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                f'<select name="category_id" class="sel" style="max-width:130px">{cat_opts_with_none}</select>'
                f'<button class="btn bs bsm">📂</button>'
                f'</form>'
                f'<form method="POST" style="display:inline">'
                f'<input type="hidden" name="action" value="delete_channel">'
                f'<input type="hidden" name="channel_id" value="{ch["id"]}">'
                f'<button class="btn bd bsm" onclick="return confirm(\'Kanal löschen?\')">🗑️</button>'
                f'</form>'
                f'</div></div>'
            )
        channel_tree += '</div>'

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "channels") +
        '<main class="main">' + alerts() +
        '<div class="pt">💬 Kanäle & Kategorien</div>'
        f'<p class="ps">{len(all_channels)} Kanäle &bull; {len(cats)} Kategorien &bull; {g.get("name","")}</p>'

        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.25rem">'
        '<div class="card"><div class="ct">➕ Kanal erstellen</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="create_channel">'
        '<div class="fg"><label class="lbl">Name</label><input name="ch_name" class="inp" required></div>'
        '<div class="fg"><label class="lbl">Typ</label>'
        '<select name="ch_type" class="sel">'
        '<option value="0">💬 Textkanal</option>'
        '<option value="2">🔊 Sprachkanal</option>'
        '<option value="5">📢 Ankündigungen</option>'
        '</select></div>'
        f'<div class="fg"><label class="lbl">Kategorie</label><select name="ch_category" class="sel">{cat_opts_with_none}</select></div>'
        '<div class="fg"><label class="lbl">Topic (nur Textkanäle)</label><input name="ch_topic" class="inp"></div>'
        '<button class="btn bp">Erstellen</button>'
        '</form></div>'

        '<div class="card"><div class="ct">📁 Kategorie erstellen</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="create_category">'
        '<div class="fg"><label class="lbl">Name</label><input name="cat_name" class="inp" required></div>'
        '<button class="btn bp">Erstellen</button>'
        '</form></div>'
        '</div>'

        '<div class="card"><div class="ct">📋 Serverstruktur</div>'
        + channel_tree
        + '</div></main></div>'
    )
    return pg(body)
