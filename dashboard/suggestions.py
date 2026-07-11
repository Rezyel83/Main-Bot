from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

# ── Shared decorators ─────────────────────────────────────────
def make_decorators():
    def lreq(f):
        @wraps(f)
        def dec(*a, **kw):
            if "user_id" not in session: return redirect(url_for("auth.login"))
            return f(*a, **kw)
        return dec

    def greq(f):
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
    return lreq, greq

from functools import wraps

# ════════════════════════════════════════════════════════════
# SUGGESTIONS
# ════════════════════════════════════════════════════════════
bp_sugg = Blueprint("suggestions", __name__)

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

@bp_sugg.route("/g/<gid>/sugg", methods=["GET", "POST"])
@_lreq
@_greq
def gsugg(gid):
    from utils import col, _find, _update
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    if request.method == "POST":
        action = request.form.get("action")
        msg_id = request.form.get("message_id", "")
        grund  = request.form.get("grund", "")
        if msg_id.isdigit():
            status = "angenommen" if action == "accept" else "abgelehnt"
            runasync(_update(col("suggestions"), {"message_id": int(msg_id)}, {"$set": {"status": status}}), bot)
            flash(f"Vorschlag {status}!", "success")

    tab = request.args.get("tab", "offen")
    suggs = runasync(_find(col("suggestions"), {"guild_id": int(gid), "status": tab}, sort=("ts", -1), limit=50), bot) or []

    rows = ""
    for s in suggs:
        user_str = get_member_name(gid, s.get("user_id", ""), bot)
        ts_str   = s["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(s.get("ts"), datetime) else "?"
        status_cls = {"offen": "tag-blue", "angenommen": "tag-green", "abgelehnt": "tag-red"}.get(s.get("status", ""), "tag-gray")
        rows += (
            f'<tr>'
            f'<td><span style="font-weight:500">{user_str}</span></td>'
            f'<td>{s.get("vorschlag","")[:80]}</td>'
            f'<td><span class="tag {status_cls}">{s.get("status","")}</span></td>'
            f'<td>{ts_str}</td>'
            f'<td>'
        )
        if tab == "offen":
            rows += (
                f'<form method="POST" style="display:flex;gap:.35rem">'
                f'<input type="hidden" name="message_id" value="{s.get("message_id","")}">'
                f'<button name="action" value="accept" class="btn bg-btn bsm">✅</button>'
                f'<button name="action" value="deny" class="btn bd bsm">❌</button>'
                f'</form>'
            )
        rows += '</td></tr>'

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "sugg") +
        '<main class="main">' + alerts() +
        '<div class="pt">Vorschläge</div>'
        f'<p class="ps">{g.get("name","")}</p>'
        f'<div style="display:flex;gap:.5rem;margin-bottom:1rem">'
        f'<a href="?tab=offen" class="btn {"bp" if tab=="offen" else "bs"}">💡 Offen</a>'
        f'<a href="?tab=angenommen" class="btn {"bp" if tab=="angenommen" else "bs"}">✅ Angenommen</a>'
        f'<a href="?tab=abgelehnt" class="btn {"bp" if tab=="abgelehnt" else "bs"}">❌ Abgelehnt</a>'
        f'</div>'
        '<div class="card"><table class="tbl"><thead><tr>'
        '<th>User / ID</th><th>Vorschlag</th><th>Status</th><th>Datum</th><th></th>'
        '</tr></thead><tbody>'
        + (rows or '<tr><td colspan="5" style="color:var(--tx2);text-align:center">Keine Vorschläge</td></tr>')
        + '</tbody></table></div></main></div>'
    )
    return pg(body)

bp = bp_sugg

# ════════════════════════════════════════════════════════════
# RSS
# ════════════════════════════════════════════════════════════
bp_rss = Blueprint("rss", __name__)

@bp_rss.route("/g/<gid>/rss", methods=["GET", "POST"])
@_lreq
@_greq
def grss(gid):
    from utils import col, _find, _count
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []
    text_chs = [c for c in chs if c.get("type") == 0]

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            name    = request.form.get("name", "").strip()
            url     = request.form.get("url", "").strip()
            ch_id   = request.form.get("channel_id", "")
            role_id = request.form.get("ping_role", "")
            count   = runasync(_count(col("rss_feeds"), {"guild_id": int(gid)}), bot) or 0
            if count >= 5:
                flash("❌ Maximal 5 RSS Slots!", "error")
            elif name and url and ch_id:
                async def add_rss():
                    await col("rss_feeds").insert_one({
                        "guild_id": int(gid), "name": name, "url": url,
                        "channel_id": int(ch_id),
                        "ping_role_id": int(role_id) if role_id else None,
                        "aktiv": True, "added": datetime.utcnow()
                    })
                runasync(add_rss(), bot)
                flash(f"RSS Feed '{name}' hinzugefügt!", "success")
        elif action == "remove":
            name = request.form.get("name", "")
            async def rem_rss():
                await col("rss_feeds").delete_one({"guild_id": int(gid), "name": name})
            runasync(rem_rss(), bot)
            flash(f"Feed '{name}' entfernt!", "success")
        elif action == "toggle":
            name = request.form.get("name", "")
            async def tog_rss():
                f = await col("rss_feeds").find_one({"guild_id": int(gid), "name": name})
                if f:
                    await col("rss_feeds").update_one({"_id": f["_id"]}, {"$set": {"aktiv": not f.get("aktiv", True)}})
            runasync(tog_rss(), bot)
            flash("Feed Status geändert!", "success")

    feeds = runasync(_find(col("rss_feeds"), {"guild_id": int(gid)}), bot) or []

    ch_opts = '<option value="">Kanal wählen...</option>' + "".join(
        f'<option value="{c["id"]}">#{c["name"]}</option>' for c in sorted(text_chs, key=lambda x: x.get("position", 0))
    )
    role_opts = '<option value="">-- Kein Ping --</option>' + "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>'
        for r in sorted(rls, key=lambda x: x.get("position", 0), reverse=True)
        if not r.get("managed") and r["name"] != "@everyone"
    )

    feed_cards = ""
    for idx, f in enumerate(feeds, 1):
        ch_name = next((c["name"] for c in chs if c["id"] == str(f.get("channel_id", ""))), "?")
        ping_name = ""
        if f.get("ping_role_id"):
            r = next((r["name"] for r in rls if r["id"] == str(f["ping_role_id"])), "?")
            ping_name = f"<br>Ping: @{r}"
        aktiv = f.get("aktiv", True)
        feed_cards += (
            f'<div class="card" style="border-left:3px solid {"#22c55e" if aktiv else "#ef4444"}">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div>'
            f'<div style="font-weight:600">Slot {idx}: {f["name"]}</div>'
            f'<div style="font-size:.8rem;color:var(--tx2);margin-top:.25rem">'
            f'Kanal: #{ch_name}{ping_name}<br>'
            f'URL: <code style="font-size:.75rem">{f["url"][:60]}...</code>'
            f'</div></div>'
            f'<div style="display:flex;gap:.5rem">'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="toggle">'
            f'<input type="hidden" name="name" value="{f["name"]}">'
            f'<button class="btn {"bg-btn" if not aktiv else "bs"} bsm">{"▶️ Aktivieren" if not aktiv else "⏸️ Pausieren"}</button>'
            f'</form>'
            f'<form method="POST" style="display:inline">'
            f'<input type="hidden" name="action" value="remove">'
            f'<input type="hidden" name="name" value="{f["name"]}">'
            f'<button class="btn bd bsm" onclick="return confirm(\'Feed entfernen?\')">🗑️</button>'
            f'</form>'
            f'</div></div></div>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "rss") +
        '<main class="main">' + alerts() +
        '<div class="pt">RSS Feeds</div>'
        f'<p class="ps">{g.get("name","")} — {len(feeds)}/5 Slots belegt</p>'
        '<div class="card"><div class="ct">➕ Feed hinzufügen</div>'
        '<form method="POST">'
        '<input type="hidden" name="action" value="add">'
        '<div style="display:grid;grid-template-columns:1fr 2fr 1fr 1fr;gap:.75rem">'
        '<div class="fg" style="margin:0"><label class="lbl">Name</label><input name="name" class="inp" required></div>'
        '<div class="fg" style="margin:0"><label class="lbl">RSS URL</label><input name="url" class="inp" placeholder="https://..." required></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Kanal</label><select name="channel_id" class="sel" required>{ch_opts}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Ping Rolle</label><select name="ping_role" class="sel">{role_opts}</select></div>'
        '</div>'
        '<button class="btn bp" style="margin-top:.5rem">➕ Hinzufügen</button>'
        '</form></div>'
        + (feed_cards or '<div class="card"><p style="color:var(--tx2)">Keine RSS Feeds konfiguriert.</p></div>')
        + '</main></div>'
    )
    return pg(body)
