from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from datetime import datetime
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync, get_member_name

# ════════════════════════════════════════════════════════════
# MOD LOGS
# ════════════════════════════════════════════════════════════
bp_mlogs = Blueprint("mod_logs", __name__)

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

@bp_mlogs.route("/g/<gid>/mlogs", methods=["GET", "POST"])
@_lreq
@_greq
def gmlogs(gid):
    from utils import col, _find, _findone, _update, ivcfg
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    text_chs = [c for c in chs if c.get("type") == 0]

    if request.method == "POST":
        upd = {}
        for key in ["mod_log","ticket_log","automod_log","server_log","member_log","join_leave_log"]:
            val = request.form.get(key, "")
            upd[f"log_channels.{key}"] = int(val) if val else None
        runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": upd}, upsert=True), bot)
        ivcfg(int(gid))
        flash("Log-Kanäle gespeichert!", "success")

    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
    log_channels = cfg.get("log_channels", {})

    filt = request.args.get("aktion", "")
    q = {"guild_id": int(gid)}
    if filt: q["aktion"] = filt
    logs = runasync(_find(col("logs"), q, sort=("ts", -1), limit=100), bot) or []

    action_colors = {
        "ban": "br", "kick": "bor", "warn": "bdg bb",
        "timeout": "bdg bor", "unban": "bg"
    }

    log_rows = ""
    for l in logs:
        ts_str   = l["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(l.get("ts"), datetime) else "?"
        user_str = get_member_name(gid, l.get("target_id", ""), bot)
        mod_str  = get_member_name(gid, l.get("mod_id", ""), bot)
        aktion   = l.get("aktion", "")
        col_cls  = action_colors.get(aktion, "bdg bb")
        log_rows += (
            f'<tr>'
            f'<td>{ts_str}</td>'
            f'<td><span style="font-weight:500">{user_str}</span></td>'
            f'<td>{mod_str}</td>'
            f'<td><span class="bdg {col_cls}">{aktion}</span></td>'
            f'<td>{str(l.get("grund",""))[:60]}</td>'
            f'<td><span class="bdg bb">#{l.get("case","?")}</span></td>'
            f'</tr>'
        )

    def co(key, clist):
        cur = str(log_channels.get(key) or "")
        o = '<option value="">-- Deaktiviert --</option>'
        for c in clist:
            sel = " selected" if cur == c["id"] else ""
            o += f'<option value="{c["id"]}"{sel}>#{c["name"]}</option>'
        return o

    log_channel_labels = [
        ("mod_log", "🛡️ Mod Log"),
        ("ticket_log", "🎫 Ticket Log"),
        ("automod_log", "🤖 AutoMod Log"),
        ("server_log", "🏠 Server Log"),
        ("member_log", "👥 Member Log"),
        ("join_leave_log", "🚪 Join/Leave Log"),
    ]

    log_ch_form = ""
    for key, label in log_channel_labels:
        log_ch_form += (
            f'<div class="fg">'
            f'<label class="lbl">{label}</label>'
            f'<select name="{key}" class="sel">{co(key, text_chs)}</select>'
            f'</div>'
        )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "mlogs") +
        '<main class="main">' + alerts() +
        '<div class="pt">📋 Mod Logs</div>'
        f'<p class="ps">{g.get("name","")}</p>'

        '<div class="card"><div class="ct">⚙️ Log-Kanäle konfigurieren</div>'
        '<form method="POST">'
        f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem">{log_ch_form}</div>'
        '<button class="btn bp" style="margin-top:.5rem">💾 Speichern</button>'
        '</form></div>'

        f'<div style="display:flex;gap:.5rem;margin-bottom:1rem;flex-wrap:wrap">'
        f'<a href="?aktion=" class="btn {"bp" if not filt else "bs"}">Alle</a>'
        + "".join(
            f'<a href="?aktion={a}" class="btn {"bp" if filt==a else "bs"}">{a.title()}</a>'
            for a in ["ban","kick","warn","timeout","unban"]
        )
        + f'</div>'

        '<div class="card"><div class="ct">📜 Log Einträge</div>'
        '<table class="tbl"><thead><tr>'
        '<th>Zeit</th><th>User / ID</th><th>Moderator / ID</th><th>Aktion</th><th>Grund</th><th>Case</th>'
        '</tr></thead><tbody>'
        + (log_rows or '<tr><td colspan="6" style="color:var(--tx2);text-align:center">Keine Logs</td></tr>')
        + '</tbody></table></div>'
        '</main></div>'
    )
    return pg(body)

bp = bp_mlogs
