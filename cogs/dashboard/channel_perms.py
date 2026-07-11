from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
import json, os
import requests as hr
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("channel_perms", __name__)

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DAPI = "https://discord.com/api/v10"

PBITS = {
    "VIEW_CHANNEL": 0x400, "SEND_MESSAGES": 0x800, "READ_MESSAGE_HISTORY": 0x10000,
    "ADD_REACTIONS": 0x40, "ATTACH_FILES": 0x8000, "EMBED_LINKS": 0x4000,
    "USE_EXTERNAL_EMOJIS": 0x40000, "MENTION_EVERYONE": 0x20000,
    "MANAGE_MESSAGES": 0x2000, "MANAGE_CHANNELS": 0x10,
    "CONNECT": 0x100000, "SPEAK": 0x200000, "MUTE_MEMBERS": 0x400000,
    "DEAFEN_MEMBERS": 0x800000, "MOVE_MEMBERS": 0x1000000,
    "USE_APPLICATION_COMMANDS": 0x80000000, "SEND_MESSAGES_IN_THREADS": 0x4000000000,
    "MANAGE_THREADS": 0x400000000, "CREATE_INSTANT_INVITE": 0x1,
    "KICK_MEMBERS": 0x2, "BAN_MEMBERS": 0x4, "ADMINISTRATOR": 0x8,
    "MANAGE_GUILD": 0x20, "VIEW_AUDIT_LOG": 0x80, "MANAGE_ROLES": 0x10000000,
    "MANAGE_WEBHOOKS": 0x20000000, "MODERATE_MEMBERS": 0x10000000000,
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

@bp.route("/g/<gid>/chperms", methods=["GET", "POST"])
@_lreq
@_greq
def gchperms(gid):
    from bot import col, _findone, _update, ivcfg
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []

    cats  = [c for c in chs if c.get("type") == 4]
    tchs  = [c for c in chs if c.get("type") in [0, 5]]
    vchs  = [c for c in chs if c.get("type") in [2, 13]]
    all_chs = sorted(tchs + vchs, key=lambda c: c.get("position", 0))

    if request.method == "POST":
        action = request.form.get("action", "apply")

        if action == "apply":
            cid2   = request.form.get("channel_id")
            rid    = request.form.get("role_id")
            pdata  = request.form.get("perms", "{}")
            if cid2 and rid:
                try:
                    pd = json.loads(pdata)
                    al = 0; dn = 0
                    for pn, st in pd.items():
                        if pn in PBITS:
                            if st == "allow": al |= PBITS[pn]
                            elif st == "deny": dn |= PBITS[pn]
                    r2 = hr.put(
                        f"{DAPI}/channels/{cid2}/permissions/{rid}",
                        headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
                        json={"allow": str(al), "deny": str(dn), "type": 0},
                        timeout=8
                    )
                    if r2.ok: flash("✅ Berechtigungen gespeichert!", "success")
                    else: flash(f"❌ Discord Fehler: {r2.status_code}", "error")
                except Exception as ex:
                    flash(f"❌ Fehler: {ex}", "error")

        elif action == "save_preset":
            preset_name = request.form.get("preset_name", "").strip()
            role_id     = request.form.get("preset_role", "")
            pdata       = request.form.get("preset_perms", "{}")
            if preset_name and role_id:
                try:
                    pd = json.loads(pdata)
                    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
                    presets = cfg.get("channel_presets", [])
                    # max 30
                    if len(presets) >= 30:
                        flash("❌ Maximal 30 Presets!", "error")
                    else:
                        # Remove existing with same name
                        presets = [p for p in presets if p.get("name") != preset_name]
                        presets.append({
                            "name": preset_name,
                            "role_id": role_id,
                            "perms": pd
                        })
                        runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": {"channel_presets": presets}}), bot)
                        ivcfg(int(gid))
                        flash(f"Preset '{preset_name}' gespeichert!", "success")
                except Exception as ex:
                    flash(f"❌ Fehler: {ex}", "error")

        elif action == "apply_preset":
            preset_name = request.form.get("preset_name_apply", "")
            channel_id  = request.form.get("preset_channel", "")
            if preset_name and channel_id:
                cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
                presets = cfg.get("channel_presets", [])
                preset = next((p for p in presets if p["name"] == preset_name), None)
                if preset:
                    pd = preset.get("perms", {})
                    rid = preset.get("role_id", "")
                    al = 0; dn = 0
                    for pn, st in pd.items():
                        if pn in PBITS:
                            if st == "allow": al |= PBITS[pn]
                            elif st == "deny": dn |= PBITS[pn]
                    try:
                        r2 = hr.put(
                            f"{DAPI}/channels/{channel_id}/permissions/{rid}",
                            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Type": "application/json"},
                            json={"allow": str(al), "deny": str(dn), "type": 0},
                            timeout=8
                        )
                        if r2.ok: flash(f"Preset '{preset_name}' angewendet!", "success")
                        else: flash(f"❌ Discord Fehler: {r2.status_code}", "error")
                    except Exception as ex:
                        flash(f"❌ Fehler: {ex}", "error")

        elif action == "delete_preset":
            preset_name = request.form.get("preset_name_del", "")
            if preset_name:
                cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
                presets = [p for p in cfg.get("channel_presets", []) if p.get("name") != preset_name]
                runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": {"channel_presets": presets}}), bot)
                ivcfg(int(gid))
                flash(f"Preset '{preset_name}' gelöscht!", "success")

    # Load presets
    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
    presets = cfg.get("channel_presets", [])

    cat_opts = '<option value="">Alle Kategorien</option>' + "".join(
        f'<option value="{c["id"]}">{c["name"]}</option>' for c in cats
    )
    ch_opts = '<option value="">Channel wählen...</option>' + "".join(
        f'<option value="{c["id"]}" data-cat="{c.get("parent_id","")}">'
        f'{"#" if c.get("type") == 0 else "🔊 "}{c["name"]}</option>'
        for c in all_chs
    )
    role_opts = '<option value="">Rolle wählen...</option>' + "".join(
        f'<option value="{r["id"]}">@{r["name"]}</option>'
        for r in sorted(rls, key=lambda x: x.get("position", 0), reverse=True)
    )

    perm_items = "".join(
        f'<div class="perm-item">'
        f'<span>{pn.replace("_"," ").title()}</span>'
        f'<div class="pbtns" data-p="{pn}">'
        f'<button type="button" class="pb pa" onclick="sp(\'{pn}\',\'allow\')">✓</button>'
        f'<button type="button" class="pb pn on" onclick="sp(\'{pn}\',\'neutral\')">−</button>'
        f'<button type="button" class="pb pd" onclick="sp(\'{pn}\',\'deny\')">✕</button>'
        f'</div></div>'
        for pn in PBITS
    )

    preset_opts = '<option value="">Preset wählen...</option>' + "".join(
        f'<option value="{p["name"]}">{p["name"]} (@{next((r["name"] for r in rls if r["id"] == p.get("role_id","")),"?")})</option>'
        for p in presets
    )
    preset_rows = "".join(
        f'<tr>'
        f'<td><b>{p["name"]}</b></td>'
        f'<td>@{next((r["name"] for r in rls if r["id"] == p.get("role_id","")),"?")}</td>'
        f'<td>{len(p.get("perms",{}))} Rechte</td>'
        f'<td>'
        f'<form method="POST" style="display:inline">'
        f'<input type="hidden" name="action" value="delete_preset">'
        f'<input type="hidden" name="preset_name_del" value="{p["name"]}">'
        f'<button class="btn bd bsm" onclick="return confirm(\'Preset löschen?\')">🗑️</button>'
        f'</form>'
        f'</td></tr>'
        for p in presets
    )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "chperms") +
        '<main class="main">' + alerts() +
        '<div class="pt">🔐 Channel-Rechte</div>'
        f'<p class="ps">Berechtigungen pro Channel & Rolle &bull; {len(presets)}/30 Presets</p>'

        # Apply perms
        '<div class="card"><div class="ct">Rechte direkt setzen</div>'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem;margin-bottom:.875rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Kategorie filtern</label><select class="sel" onchange="filterCat(this.value)">{cat_opts}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Channel</label><select class="sel" id="chsel" onchange="document.getElementById(\'perm-ch\').value=this.value">{ch_opts}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Rolle</label><select class="sel" onchange="document.getElementById(\'perm-role\').value=this.value">{role_opts}</select></div>'
        '</div>'
        '<form method="POST" id="pf">'
        '<input type="hidden" name="action" value="apply">'
        '<input type="hidden" name="channel_id" id="perm-ch">'
        '<input type="hidden" name="role_id" id="perm-role">'
        '<input type="hidden" name="perms" id="perm-data">'
        '<div class="perm-grid">' + perm_items + '</div>'
        '<div style="display:flex;gap:.75rem;margin-top:1rem">'
        '<button type="submit" class="btn bp">💾 Speichern</button>'
        '<button type="button" class="btn bs" onclick="resetPerms()">🔄 Reset</button>'
        '</div></form></div>'

        # Save preset
        '<div class="card"><div class="ct">💾 Als Preset speichern</div>'
        '<form method="POST" style="display:grid;grid-template-columns:1fr 1fr auto;gap:.75rem;align-items:flex-end">'
        '<input type="hidden" name="action" value="save_preset">'
        '<input type="hidden" name="preset_perms" id="preset-perm-data">'
        '<div class="fg" style="margin:0"><label class="lbl">Preset Name</label><input name="preset_name" class="inp" placeholder="z.B. nur-lesen" required></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Für Rolle</label><select name="preset_role" class="sel" required>{role_opts}</select></div>'
        '<button class="btn bp" onclick="syncPresetPerms()">💾 Speichern</button>'
        '</form></div>'

        # Apply preset
        '<div class="card"><div class="ct">⚡ Preset anwenden</div>'
        '<form method="POST" style="display:grid;grid-template-columns:1fr 1fr auto;gap:.75rem;align-items:flex-end">'
        '<input type="hidden" name="action" value="apply_preset">'
        f'<div class="fg" style="margin:0"><label class="lbl">Preset</label><select name="preset_name_apply" class="sel" required>{preset_opts}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Channel</label><select name="preset_channel" class="sel" required>{ch_opts}</select></div>'
        '<button class="btn bp">⚡ Anwenden</button>'
        '</form></div>'

        # Preset list
        '<div class="card"><div class="ct">📋 Gespeicherte Presets</div>'
        '<table class="tbl"><thead><tr><th>Name</th><th>Rolle</th><th>Rechte</th><th></th></tr></thead><tbody>'
        + (preset_rows or '<tr><td colspan="4" style="color:var(--tx2);text-align:center">Keine Presets</td></tr>')
        + '</tbody></table></div>'
        '</main></div>'

        '<script>'
        'var ps={};'
        'function sp(n,s){ps[n]=s;var g=document.querySelector(\'[data-p="\'+n+\'"]\');'
        'g.querySelectorAll(".pb").forEach(b=>b.classList.remove("on"));'
        'g.querySelector(".p"+s[0]).classList.add("on");upd()}'
        'function upd(){var d=JSON.stringify(ps);document.getElementById("perm-data").value=d;}'
        'function resetPerms(){ps={};document.querySelectorAll(".pb").forEach(b=>b.classList.remove("on"));'
        'document.querySelectorAll(".pn").forEach(b=>b.classList.add("on"));upd()}'
        'function filterCat(cv){document.getElementById("chsel").querySelectorAll("option").forEach(o=>'
        '{o.style.display=(!cv||o.dataset.cat==cv||!o.value)?"":"none"})}'
        'function syncPresetPerms(){document.getElementById("preset-perm-data").value=JSON.stringify(ps)}'
        'resetPerms();'
        '</script>'
    )
    return pg(body)
