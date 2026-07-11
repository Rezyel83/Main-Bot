from flask import Blueprint, session, redirect, url_for, request, flash, current_app, jsonify
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
        r = hr.patch(f"{DAPI}{endpoint}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            json=data, timeout=8)
        return r.ok, r.status_code
    except Exception as ex:
        return False, str(ex)

def bot_post(endpoint, data):
    try:
        r = hr.post(f"{DAPI}{endpoint}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            json=data, timeout=8)
        return r.ok, r.json() if r.ok else r.status_code
    except Exception as ex:
        return False, str(ex)

def bot_delete(endpoint):
    try:
        r = hr.delete(f"{DAPI}{endpoint}",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}, timeout=8)
        return r.ok
    except:
        return False

@bp.route("/g/<gid>/channels/reorder", methods=["POST"])
@_lreq
@_greq
def reorder(gid):
    """Handle drag & drop reorder via AJAX"""
    data = request.get_json()
    if not data: return jsonify({"ok": False})
    try:
        r = hr.patch(
            f"{DAPI}/guilds/{gid}/channels",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
            json=data, timeout=8
        )
        return jsonify({"ok": r.ok, "status": r.status_code})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)})

@bp.route("/g/<gid>/channels", methods=["GET", "POST"])
@_lreq
@_greq
def gchannels(gid):
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    if request.method == "POST":
        action = request.form.get("action")

        if action == "rename":
            ch_id = request.form.get("channel_id", "")
            name  = request.form.get("new_name", "").strip()
            if ch_id and name:
                ok, code = bot_patch(f"/channels/{ch_id}", {"name": name})
                flash(f"✅ Umbenannt zu '{name}'" if ok else f"❌ Fehler: {code}", "success" if ok else "error")

        elif action == "move":
            ch_id  = request.form.get("channel_id", "")
            cat_id = request.form.get("cat_id", "") or None
            if ch_id:
                ok, code = bot_patch(f"/channels/{ch_id}", {"parent_id": cat_id})
                flash("✅ Verschoben!" if ok else f"❌ Fehler: {code}", "success" if ok else "error")

        elif action == "create_text":
            name   = request.form.get("name", "").strip()
            cat_id = request.form.get("cat_id", "") or None
            topic  = request.form.get("topic", "").strip()
            if name:
                data = {"name": name, "type": 0}
                if cat_id: data["parent_id"] = cat_id
                if topic: data["topic"] = topic
                ok, res = bot_post(f"/guilds/{gid}/channels", data)
                flash(f"✅ Kanal '{name}' erstellt!" if ok else f"❌ Fehler: {res}", "success" if ok else "error")

        elif action == "create_voice":
            name   = request.form.get("name", "").strip()
            cat_id = request.form.get("cat_id", "") or None
            if name:
                data = {"name": name, "type": 2}
                if cat_id: data["parent_id"] = cat_id
                ok, res = bot_post(f"/guilds/{gid}/channels", data)
                flash(f"✅ Sprachkanal '{name}' erstellt!" if ok else f"❌ Fehler: {res}", "success" if ok else "error")

        elif action == "create_category":
            name = request.form.get("name", "").strip()
            if name:
                ok, res = bot_post(f"/guilds/{gid}/channels", {"name": name, "type": 4})
                flash(f"✅ Kategorie '{name}' erstellt!" if ok else f"❌ Fehler: {res}", "success" if ok else "error")

        elif action == "set_topic":
            ch_id = request.form.get("channel_id", "")
            topic = request.form.get("topic", "")
            if ch_id:
                ok, code = bot_patch(f"/channels/{ch_id}", {"topic": topic})
                flash("✅ Topic gesetzt!" if ok else f"❌ Fehler: {code}", "success" if ok else "error")

        elif action == "set_slowmode":
            ch_id = request.form.get("channel_id", "")
            secs  = request.form.get("seconds", "0")
            if ch_id and secs.isdigit():
                ok, code = bot_patch(f"/channels/{ch_id}", {"rate_limit_per_user": int(secs)})
                flash(f"✅ Slowmode {secs}s gesetzt!" if ok else f"❌ Fehler: {code}", "success" if ok else "error")

        elif action == "delete":
            ch_id = request.form.get("channel_id", "")
            if ch_id:
                ok = bot_delete(f"/channels/{ch_id}")
                flash("✅ Gelöscht!" if ok else "❌ Fehler beim Löschen!", "success" if ok else "error")

    chs  = dget(f"/guilds/{gid}/channels", isbot=True) or []
    cats = sorted([c for c in chs if c.get("type") == 4], key=lambda x: x.get("position", 0))
    text_chs  = [c for c in chs if c.get("type") in [0, 5]]
    voice_chs = [c for c in chs if c.get("type") in [2, 13]]
    all_chs   = sorted([c for c in chs if c.get("type") in [0, 2, 5, 13]], key=lambda x: x.get("position", 0))

    cat_opts = '<option value="">— Keine Kategorie —</option>'
    for c in cats:
        cat_opts += f'<option value="{c["id"]}">{c["name"]}</option>'

    ch_type_icon = {0: "💬", 2: "🔊", 5: "📢", 13: "🎙️"}

    # Build structure HTML - categories with their channels
    structure = ""
    for cat in cats:
        cat_chs = sorted([c for c in all_chs if c.get("parent_id") == cat["id"]], key=lambda x: x.get("position", 0))
        cat_id = cat["id"]
        cat_name = cat["name"]

        structure += f'''
        <div class="cat-block" data-id="{cat_id}" style="margin-bottom:1.25rem;border:1px solid var(--bdr);border-radius:10px;overflow:hidden">
            <div style="background:var(--bg3);padding:.75rem 1rem;display:flex;align-items:center;justify-content:space-between">
                <div style="display:flex;align-items:center;gap:.75rem">
                    <span style="cursor:grab;color:var(--tx2);font-size:1.1rem" title="Ziehen zum Sortieren">⠿</span>
                    <span style="font-weight:600">📁 {cat_name}</span>
                    <span class="tag tag-gray" style="font-size:.7rem">{len(cat_chs)} Kanäle</span>
                </div>
                <div style="display:flex;gap:.4rem">
                    <button class="btn bs bsm" onclick="openRename('{cat_id}','{cat_name}')">✏️ Umbenennen</button>
                    <form method="POST" style="display:inline">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="channel_id" value="{cat_id}">
                        <button class="btn bd bsm" onclick="return confirm('Kategorie + alle Kanäle darin löschen?')">🗑️</button>
                    </form>
                </div>
            </div>
            <div class="ch-list" data-cat="{cat_id}" style="padding:.5rem">
        '''

        for ch in cat_chs:
            ch_id   = ch["id"]
            ch_name = ch["name"]
            icon    = ch_type_icon.get(ch.get("type", 0), "💬")
            topic   = ch.get("topic", "") or ""
            slow    = ch.get("rate_limit_per_user", 0)
            extra   = ""
            if topic:
                extra += f'<span class="tag tag-gray" style="font-size:.7rem" title="{topic}">📝 Topic</span> '
            if slow:
                extra += f'<span class="tag tag-orange" style="font-size:.7rem">🐢 {slow}s</span> '

            structure += f'''
            <div class="ch-item" data-id="{ch_id}" style="display:flex;align-items:center;justify-content:space-between;padding:.5rem .75rem;border-radius:6px;margin-bottom:.2rem;background:var(--bg2)">
                <div style="display:flex;align-items:center;gap:.6rem">
                    <span style="cursor:grab;color:var(--tx2)" title="Ziehen zum Sortieren">⠿</span>
                    <span>{icon} {ch_name}</span>
                    {extra}
                </div>
                <div style="display:flex;gap:.3rem">
                    <button class="btn bs bsm" onclick="openRename('{ch_id}','{ch_name}')">✏️</button>
                    <button class="btn bs bsm" onclick="openMove('{ch_id}','{ch_name}')">📂</button>
            '''
            if ch.get("type") == 0:
                structure += f'<button class="btn bs bsm" onclick="openTopic(\'{ch_id}\',\'{topic.replace(chr(39), "")}\')">📝</button>'
                structure += f'<button class="btn bs bsm" onclick="openSlowmode(\'{ch_id}\',{slow})">🐢</button>'
            structure += f'''
                    <form method="POST" style="display:inline">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="channel_id" value="{ch_id}">
                        <button class="btn bd bsm" onclick="return confirm('Kanal löschen?')">🗑️</button>
                    </form>
                </div>
            </div>
            '''

        structure += '</div></div>'

    # Uncategorized channels
    uncat = sorted([c for c in all_chs if not c.get("parent_id")], key=lambda x: x.get("position", 0))
    if uncat:
        structure += '<div style="margin-bottom:1.25rem;border:1px solid var(--bdr);border-radius:10px;overflow:hidden">'
        structure += '<div style="background:var(--bg3);padding:.75rem 1rem"><span style="font-weight:600;color:var(--tx2)">Ohne Kategorie</span></div>'
        structure += '<div class="ch-list" data-cat="" style="padding:.5rem">'
        for ch in uncat:
            ch_id   = ch["id"]
            ch_name = ch["name"]
            icon    = ch_type_icon.get(ch.get("type", 0), "💬")
            structure += f'''
            <div class="ch-item" data-id="{ch_id}" style="display:flex;align-items:center;justify-content:space-between;padding:.5rem .75rem;border-radius:6px;margin-bottom:.2rem;background:var(--bg2)">
                <div style="display:flex;align-items:center;gap:.6rem">
                    <span style="cursor:grab;color:var(--tx2)">⠿</span>
                    <span>{icon} {ch_name}</span>
                </div>
                <div style="display:flex;gap:.3rem">
                    <button class="btn bs bsm" onclick="openRename('{ch_id}','{ch_name}')">✏️</button>
                    <button class="btn bs bsm" onclick="openMove('{ch_id}','{ch_name}')">📂</button>
                    <form method="POST" style="display:inline">
                        <input type="hidden" name="action" value="delete">
                        <input type="hidden" name="channel_id" value="{ch_id}">
                        <button class="btn bd bsm" onclick="return confirm('Kanal löschen?')">🗑️</button>
                    </form>
                </div>
            </div>
            '''
        structure += '</div></div>'

    gname = g.get("name", "")
    body = nav
    body += '<div class="wrap">'
    body += sidebar(gid, "channels")
    body += '<main class="main">'
    body += alerts()
    body += f'<div class="pt">💬 Kanäle & Kategorien</div>'
    body += f'<p class="ps">{len(all_chs)} Kanäle · {len(cats)} Kategorien · {gname}</p>'

    # Quick create bar
    body += '<div class="card"><div class="ct">➕ Neu erstellen</div>'
    body += '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:1rem">'

    # Text channel
    body += '<div><div style="font-size:.85rem;font-weight:600;margin-bottom:.5rem">💬 Textkanal</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="create_text">'
    body += f'<div class="fg"><label class="lbl">Name</label><input name="name" class="inp" placeholder="z.B. allgemein" required></div>'
    body += f'<div class="fg"><label class="lbl">Kategorie</label><select name="cat_id" class="sel">{cat_opts}</select></div>'
    body += '<div class="fg"><label class="lbl">Topic (optional)</label><input name="topic" class="inp"></div>'
    body += '<button class="btn bp">Erstellen</button></form></div>'

    # Voice channel
    body += '<div><div style="font-size:.85rem;font-weight:600;margin-bottom:.5rem">🔊 Sprachkanal</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="create_voice">'
    body += f'<div class="fg"><label class="lbl">Name</label><input name="name" class="inp" placeholder="z.B. Gaming" required></div>'
    body += f'<div class="fg"><label class="lbl">Kategorie</label><select name="cat_id" class="sel">{cat_opts}</select></div>'
    body += '<button class="btn bp" style="margin-top:1.6rem">Erstellen</button></form></div>'

    # Category
    body += '<div><div style="font-size:.85rem;font-weight:600;margin-bottom:.5rem">📁 Kategorie</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="create_category">'
    body += '<div class="fg"><label class="lbl">Name</label><input name="name" class="inp" placeholder="z.B. INFO" required></div>'
    body += '<button class="btn bp" style="margin-top:3.55rem">Erstellen</button></form></div>'

    body += '</div></div>'

    # Structure
    body += '<div class="card"><div class="ct">📋 Serverstruktur <span style="font-size:.78rem;color:var(--tx2);font-weight:400">— ⠿ ziehen zum Sortieren</span></div>'
    body += structure
    body += '</div>'

    body += '</main></div>'

    # Modals + JS
    body += '''
    <!-- Rename Modal -->
    <div id="modal-rename" class="modal-bg">
        <div class="modal">
            <div class="modal-title">✏️ Umbenennen</div>
            <form method="POST">
                <input type="hidden" name="action" value="rename">
                <input type="hidden" name="channel_id" id="rename-id">
                <div class="fg"><label class="lbl">Neuer Name</label><input name="new_name" id="rename-val" class="inp" required></div>
                <div style="display:flex;gap:.5rem">
                    <button class="btn bp">Speichern</button>
                    <button type="button" class="btn bs" onclick="closeModals()">Abbrechen</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Move Modal -->
    <div id="modal-move" class="modal-bg">
        <div class="modal">
            <div class="modal-title">📂 In Kategorie verschieben</div>
            <form method="POST">
                <input type="hidden" name="action" value="move">
                <input type="hidden" name="channel_id" id="move-id">
                <div class="fg">
                    <label class="lbl">Ziel-Kategorie</label>
                    <select name="cat_id" class="sel">''' + cat_opts + '''</select>
                </div>
                <div style="display:flex;gap:.5rem">
                    <button class="btn bp">Verschieben</button>
                    <button type="button" class="btn bs" onclick="closeModals()">Abbrechen</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Topic Modal -->
    <div id="modal-topic" class="modal-bg">
        <div class="modal">
            <div class="modal-title">📝 Topic setzen</div>
            <form method="POST">
                <input type="hidden" name="action" value="set_topic">
                <input type="hidden" name="channel_id" id="topic-id">
                <div class="fg"><label class="lbl">Topic</label><input name="topic" id="topic-val" class="inp"></div>
                <div style="display:flex;gap:.5rem">
                    <button class="btn bp">Speichern</button>
                    <button type="button" class="btn bs" onclick="closeModals()">Abbrechen</button>
                </div>
            </form>
        </div>
    </div>

    <!-- Slowmode Modal -->
    <div id="modal-slow" class="modal-bg">
        <div class="modal">
            <div class="modal-title">🐢 Slowmode setzen</div>
            <form method="POST">
                <input type="hidden" name="action" value="set_slowmode">
                <input type="hidden" name="channel_id" id="slow-id">
                <div class="fg"><label class="lbl">Sekunden (0 = aus)</label><input name="seconds" id="slow-val" type="number" class="inp" min="0" max="21600"></div>
                <div style="display:flex;gap:.5rem">
                    <button class="btn bp">Speichern</button>
                    <button type="button" class="btn bs" onclick="closeModals()">Abbrechen</button>
                </div>
            </form>
        </div>
    </div>

    <script>
    function openRename(id, name) {
        document.getElementById("rename-id").value = id;
        document.getElementById("rename-val").value = name;
        document.getElementById("modal-rename").classList.add("open");
    }
    function openMove(id) {
        document.getElementById("move-id").value = id;
        document.getElementById("modal-move").classList.add("open");
    }
    function openTopic(id, topic) {
        document.getElementById("topic-id").value = id;
        document.getElementById("topic-val").value = topic;
        document.getElementById("modal-topic").classList.add("open");
    }
    function openSlowmode(id, secs) {
        document.getElementById("slow-id").value = id;
        document.getElementById("slow-val").value = secs;
        document.getElementById("modal-slow").classList.add("open");
    }
    function closeModals() {
        document.querySelectorAll(".modal-bg").forEach(m => m.classList.remove("open"));
    }
    document.querySelectorAll(".modal-bg").forEach(m => {
        m.addEventListener("click", e => { if(e.target === m) closeModals(); });
    });

    // Drag & Drop sorting
    function initDragDrop() {
        document.querySelectorAll(".ch-list").forEach(list => {
            let dragging = null;
            list.querySelectorAll(".ch-item").forEach(item => {
                item.setAttribute("draggable", "true");
                item.addEventListener("dragstart", () => {
                    dragging = item;
                    setTimeout(() => item.style.opacity = "0.4", 0);
                });
                item.addEventListener("dragend", () => {
                    item.style.opacity = "1";
                    dragging = null;
                    saveOrder();
                });
                item.addEventListener("dragover", e => {
                    e.preventDefault();
                    const after = getDragAfter(list, e.clientY);
                    if (after == null) list.appendChild(dragging);
                    else list.insertBefore(dragging, after);
                });
            });
        });

        // Category drag
        const catContainer = document.querySelector(".main");
        document.querySelectorAll(".cat-block").forEach(block => {
            const handle = block.querySelector("[title='Ziehen zum Sortieren']");
            if (!handle) return;
            block.setAttribute("draggable", "true");
            block.addEventListener("dragstart", e => {
                if (!e.target.closest(".cat-block > div:first-child")) { e.preventDefault(); return; }
                setTimeout(() => block.style.opacity = "0.4", 0);
            });
            block.addEventListener("dragend", () => {
                block.style.opacity = "1";
                saveOrder();
            });
        });
    }

    function getDragAfter(container, y) {
        const items = [...container.querySelectorAll(".ch-item:not([style*='opacity: 0.4'])")];
        return items.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;
            if (offset < 0 && offset > closest.offset) return { offset, element: child };
            return closest;
        }, { offset: Number.NEGATIVE_INFINITY }).element;
    }

    function saveOrder() {
        const positions = [];
        let pos = 0;
        document.querySelectorAll(".cat-block").forEach(cat => {
            positions.push({ id: cat.dataset.id, position: pos++ });
            cat.querySelectorAll(".ch-item").forEach(ch => {
                positions.push({ id: ch.dataset.id, position: pos++, parent_id: cat.dataset.id });
            });
        });
        document.querySelectorAll(".ch-list[data-cat=''] .ch-item").forEach(ch => {
            positions.push({ id: ch.dataset.id, position: pos++ });
        });

        fetch(window.location.pathname + "/reorder", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(positions)
        }).then(r => r.json()).then(d => {
            if (!d.ok) console.warn("Reorder failed:", d);
        });
    }

    initDragDrop();
    </script>
    '''

    return pg(body)
