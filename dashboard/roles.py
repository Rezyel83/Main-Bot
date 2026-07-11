from flask import Blueprint, session, redirect, url_for, request, flash, current_app, jsonify
from functools import wraps
import os
import requests as hr
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds

bp = Blueprint("roles", __name__)

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

def hex_to_int(hex_color):
    """Convert #RRGGBB to int"""
    try:
        return int(hex_color.lstrip("#"), 16)
    except:
        return 0

def int_to_hex(color_int):
    """Convert int to #RRGGBB"""
    try:
        return f"#{color_int:06X}"
    except:
        return "#000000"

@bp.route("/g/<gid>/roles/reorder", methods=["POST"])
@_lreq
@_greq
def reorder_roles(gid):
    data = request.get_json()
    if not data: return jsonify({"ok": False})
    try:
        r = hr.patch(
            f"{DAPI}/guilds/{gid}/roles",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            json=data, timeout=8
        )
        return jsonify({"ok": r.ok, "status": r.status_code})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@bp.route("/g/<gid>/roles", methods=["GET", "POST"])
@_lreq
@_greq
def groles(gid):
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "create":
            name  = request.form.get("name", "").strip()
            color = request.form.get("color", "#000000")
            hoist = request.form.get("hoist") == "1"
            mentionable = request.form.get("mentionable") == "1"
            if name:
                r = hr.post(
                    f"{DAPI}/guilds/{gid}/roles",
                    headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
                    json={"name": name, "color": hex_to_int(color), "hoist": hoist, "mentionable": mentionable},
                    timeout=8
                )
                flash(f"✅ Rolle '{name}' erstellt!" if r.ok else f"❌ Fehler: {r.status_code}", "success" if r.ok else "error")

        elif action == "edit":
            role_id = request.form.get("role_id", "")
            name    = request.form.get("name", "").strip()
            color   = request.form.get("color", "#000000")
            hoist   = request.form.get("hoist") == "1"
            mentionable = request.form.get("mentionable") == "1"
            if role_id and name:
                r = hr.patch(
                    f"{DAPI}/guilds/{gid}/roles/{role_id}",
                    headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
                    json={"name": name, "color": hex_to_int(color), "hoist": hoist, "mentionable": mentionable},
                    timeout=8
                )
                flash(f"✅ Rolle aktualisiert!" if r.ok else f"❌ Fehler: {r.status_code}", "success" if r.ok else "error")

        elif action == "delete":
            role_id = request.form.get("role_id", "")
            if role_id:
                r = hr.delete(
                    f"{DAPI}/guilds/{gid}/roles/{role_id}",
                    headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"},
                    timeout=8
                )
                flash("✅ Rolle gelöscht!" if r.ok else f"❌ Fehler: {r.status_code}", "success" if r.ok else "error")

    roles = dget(f"/guilds/{gid}/roles", isbot=True) or []
    # Sort by position descending (highest = most powerful)
    roles_sorted = sorted(roles, key=lambda x: x.get("position", 0), reverse=True)
    # Filter out @everyone
    roles_display = [r for r in roles_sorted if r["name"] != "@everyone"]

    gname = g.get("name", "")
    body = nav
    body += '<div class="wrap">'
    body += sidebar(gid, "roles")
    body += '<main class="main">'
    body += alerts()
    body += '<div class="pt">🎭 Rollen</div>'
    body += f'<p class="ps">{len(roles_display)} Rollen · {gname} · <span style="color:var(--tx2);font-size:.85rem">⠿ ziehen zum Sortieren</span></p>'

    # Create role card
    body += '<div class="card"><div class="ct">➕ Neue Rolle erstellen</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="create">'
    body += '<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr auto;gap:.75rem;align-items:flex-end">'
    body += '<div class="fg" style="margin:0"><label class="lbl">Name</label><input name="name" class="inp" placeholder="z.B. Moderator" required></div>'
    body += '<div class="fg" style="margin:0"><label class="lbl">Farbe</label><input name="color" type="color" class="inp" value="#99aab5" style="height:38px;padding:.2rem;cursor:pointer"></div>'
    body += '<div class="fg" style="margin:0"><label class="lbl">Separat</label><select name="hoist" class="sel"><option value="1">Ja</option><option value="0">Nein</option></select></div>'
    body += '<div class="fg" style="margin:0"><label class="lbl">Erwähnbar</label><select name="mentionable" class="sel"><option value="0">Nein</option><option value="1">Ja</option></select></div>'
    body += '<button class="btn bp">Erstellen</button>'
    body += '</div></form></div>'

    # Roles list with drag & drop
    body += '<div class="card"><div class="ct">📋 Rollen verwalten</div>'
    body += '<div id="roles-list">'

    for role in roles_display:
        rid      = role["id"]
        rname    = role["name"]
        rcolor   = role.get("color", 0)
        hex_col  = int_to_hex(rcolor) if rcolor else "#99aab5"
        hoist    = role.get("hoist", False)
        mention  = role.get("mentionable", False)
        pos      = role.get("position", 0)
        managed  = role.get("managed", False)  # Bot roles can't be edited

        color_dot = f'<span style="width:14px;height:14px;border-radius:50%;background:{hex_col};display:inline-block;margin-right:.4rem;border:1px solid rgba(255,255,255,.1)"></span>'
        badges = ""
        if hoist:   badges += '<span class="tag tag-blue" style="font-size:.7rem">Separat</span> '
        if mention: badges += '<span class="tag tag-green" style="font-size:.7rem">Erwähnbar</span> '
        if managed: badges += '<span class="tag tag-gray" style="font-size:.7rem">Bot</span> '

        body += f'''
        <div class="role-item" data-id="{rid}" data-pos="{pos}"
             style="display:flex;align-items:center;justify-content:space-between;padding:.6rem .75rem;border-radius:8px;margin-bottom:.3rem;background:var(--bg3);border:1px solid var(--bdr)">
            <div style="display:flex;align-items:center;gap:.75rem">
                <span class="drag-handle" style="cursor:grab;color:var(--tx2);font-size:1.1rem;user-select:none" title="Ziehen zum Sortieren">⠿</span>
                {color_dot}
                <span style="font-weight:500">{rname}</span>
                {badges}
            </div>
            <div style="display:flex;gap:.4rem">
        '''
        if not managed:
            body += f'<button class="btn bs bsm" onclick="openEditRole(\'{rid}\',\'{rname}\',\'{hex_col}\',{str(hoist).lower()},{str(mention).lower()})">✏️ Bearbeiten</button>'
            body += f'''
                <form method="POST" style="display:inline">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="role_id" value="{rid}">
                    <button class="btn bd bsm" onclick="return confirm('Rolle löschen?')">🗑️</button>
                </form>
            '''
        body += '</div></div>'

    body += '</div></div>'  # end roles-list + card

    # Edit modal
    body += '''
    <div id="modal-edit-role" class="modal-bg">
        <div class="modal" style="max-width:400px">
            <div class="modal-title">✏️ Rolle bearbeiten</div>
            <form method="POST">
                <input type="hidden" name="action" value="edit">
                <input type="hidden" name="role_id" id="edit-role-id">
                <div class="fg"><label class="lbl">Name</label><input name="name" id="edit-role-name" class="inp" required></div>
                <div class="fg"><label class="lbl">Farbe</label><input name="color" id="edit-role-color" type="color" class="inp" style="height:38px;padding:.2rem;cursor:pointer"></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem">
                    <div class="fg"><label class="lbl">Separat anzeigen</label>
                        <select name="hoist" id="edit-role-hoist" class="sel">
                            <option value="1">Ja</option>
                            <option value="0">Nein</option>
                        </select>
                    </div>
                    <div class="fg"><label class="lbl">Erwähnbar</label>
                        <select name="mentionable" id="edit-role-mention" class="sel">
                            <option value="1">Ja</option>
                            <option value="0">Nein</option>
                        </select>
                    </div>
                </div>
                <div style="display:flex;gap:.5rem;margin-top:.5rem">
                    <button class="btn bp">💾 Speichern</button>
                    <button type="button" class="btn bs" onclick="document.getElementById('modal-edit-role').classList.remove('open')">Abbrechen</button>
                </div>
            </form>
        </div>
    </div>

    <script>
    function openEditRole(id, name, color, hoist, mention) {
        document.getElementById("edit-role-id").value = id;
        document.getElementById("edit-role-name").value = name;
        document.getElementById("edit-role-color").value = color;
        document.getElementById("edit-role-hoist").value = hoist ? "1" : "0";
        document.getElementById("edit-role-mention").value = mention ? "1" : "0";
        document.getElementById("modal-edit-role").classList.add("open");
    }
    document.querySelectorAll(".modal-bg").forEach(m => {
        m.addEventListener("click", e => { if(e.target === m) m.classList.remove("open"); });
    });

    // Drag & Drop for roles
    const list = document.getElementById("roles-list");
    let dragging = null;

    list.querySelectorAll(".role-item").forEach(item => {
        item.setAttribute("draggable", "true");
        item.addEventListener("dragstart", e => {
            if (!e.target.closest(".drag-handle") && e.target !== item) { e.preventDefault(); return; }
            dragging = item;
            setTimeout(() => item.style.opacity = "0.4", 0);
        });
        item.addEventListener("dragend", () => {
            item.style.opacity = "1";
            dragging = null;
            saveRoleOrder();
        });
        item.addEventListener("dragover", e => {
            e.preventDefault();
            if (!dragging || dragging === item) return;
            const box = item.getBoundingClientRect();
            const mid = box.top + box.height / 2;
            if (e.clientY < mid) list.insertBefore(dragging, item);
            else list.insertBefore(dragging, item.nextSibling);
        });
    });

    function saveRoleOrder() {
        const items = [...list.querySelectorAll(".role-item")];
        const total = items.length;
        const positions = items.map((el, idx) => ({
            id: el.dataset.id,
            position: total - idx  // highest position = top of list
        }));
        fetch(window.location.pathname + "/reorder", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(positions)
        }).then(r => r.json()).then(d => {
            if (d.ok) {
                // Brief green flash
                list.style.outline = "2px solid #22c55e";
                setTimeout(() => list.style.outline = "", 800);
            }
        }).catch(() => {});
    }
    </script>
    '''

    body += '</main></div>'
    return pg(body)
