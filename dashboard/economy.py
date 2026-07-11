from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from app import pg, alerts, sidebar, guild_nav, bguilds, uguilds, runasync, get_member_name

bp = Blueprint("economy", __name__)

def _lreq(f):
    @wraps(f)
    def dec(*a, **kw):
        if "user_id" not in session: return redirect(url_for("auth.login"))
        return f(*a, **kw)
    return dec

def _greq(f):
    @wraps(f)
    def dec(*a, **kw):
        from flask import flash
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

@bp.route("/g/<gid>/eco", methods=["GET", "POST"])
@_lreq
@_greq
def geco(gid):
    from utils import col, _find, _update, _findone, ivcfg
    from app import dget
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)

    if request.method == "POST":
        action = request.form.get("action")
        if action == "set_coins":
            uid = request.form.get("uid", "").strip()
            amt = request.form.get("amt", "0")
            if uid.isdigit() and amt.lstrip("-").isdigit():
                runasync(_update(col("economy"), {"guild_id": int(gid), "user_id": int(uid)}, {"$set": {"coins": int(amt)}}, upsert=True), bot)
                flash(f"Coins für {uid} auf {amt} gesetzt!", "success")
        elif action == "add_coins":
            uid = request.form.get("uid", "").strip()
            amt = request.form.get("amt", "0")
            if uid.isdigit() and amt.lstrip("-").isdigit():
                runasync(_update(col("economy"), {"guild_id": int(gid), "user_id": int(uid)}, {"$inc": {"coins": int(amt)}}, upsert=True), bot)
                word = "hinzugefügt" if int(amt) > 0 else "abgezogen"
                flash(f"{abs(int(amt))} Coins {word}!", "success")
        elif action == "reset_coins":
            uid = request.form.get("uid", "").strip()
            if uid.isdigit():
                runasync(_update(col("economy"), {"guild_id": int(gid), "user_id": int(uid)}, {"$set": {"coins": 0, "bank": 0}}, upsert=True), bot)
                flash(f"Economy für {uid} zurückgesetzt!", "success")
        elif action == "add_shop":
            name = request.form.get("item_name", "").strip()
            price = request.form.get("item_price", "0")
            desc = request.form.get("item_desc", "")
            role_id = request.form.get("item_role", "")
            if name and price.isdigit():
                item = {"name": name, "price": int(price), "description": desc}
                if role_id: item["role_id"] = role_id
                runasync(_update(col("config"), {"guild_id": int(gid)}, {"$push": {"shop": item}}, upsert=True), bot)
                ivcfg(int(gid))
                flash(f"Item '{name}' hinzugefügt!", "success")
        elif action == "remove_shop":
            name = request.form.get("item_name", "").strip()
            if name:
                runasync(_update(col("config"), {"guild_id": int(gid)}, {"$pull": {"shop": {"name": name}}}), bot)
                ivcfg(int(gid))
                flash(f"Item '{name}' entfernt!", "success")

    lb = runasync(_find(col("economy"), {"guild_id": int(gid)}, sort=("coins", -1), limit=30), bot) or []
    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
    shop = cfg.get("shop", [])
    roles = dget(f"/guilds/{gid}/roles", isbot=True) or []

    role_opts = '<option value="">-- Keine Rolle --</option>'
    for r in sorted(roles, key=lambda x: x.get("position", 0), reverse=True):
        role_opts += f'<option value="{r["id"]}">@{r["name"]}</option>'

    medals = ["🥇", "🥈", "🥉"]
    lb_rows = ""
    for idx, u in enumerate(lb):
        name = get_member_name(gid, u.get("user_id", ""), bot)
        medal = medals[idx] if idx < 3 else f"<b>#{idx+1}</b>"
        uid_val = u.get("user_id", "")
        lb_rows += (
            "<tr>"
            f"<td>{medal}</td>"
            f"<td><span style='font-weight:500'>{name}</span></td>"
            f"<td>{u.get('coins', 0)} 💰</td>"
            f"<td>{u.get('bank', 0)} 🏦</td>"
            f"<td>{u.get('coins', 0) + u.get('bank', 0)} 💎</td>"
            f"<td>{u.get('rep', 0)} ⭐</td>"
            "<td>"
            "<form method='POST' style='display:inline'>"
            "<input type='hidden' name='action' value='reset_coins'>"
            f"<input type='hidden' name='uid' value='{uid_val}'>"
            "<button class='btn bd bsm' onclick=\"return confirm('Economy zurücksetzen?')\">🔄</button>"
            "</form>"
            "</td>"
            "</tr>"
        )

    shop_rows = ""
    for it in shop:
        iname = it.get("name", "")
        shop_rows += (
            "<tr>"
            f"<td><b>{iname}</b></td>"
            f"<td>{it.get('price', 0)} Coins</td>"
            f"<td>{it.get('description', '–')}</td>"
            f"<td>{it.get('role_id', '–')}</td>"
            "<td>"
            "<form method='POST' style='display:inline'>"
            "<input type='hidden' name='action' value='remove_shop'>"
            f"<input type='hidden' name='item_name' value='{iname}'>"
            "<button class='btn bd bsm' onclick=\"return confirm('Item entfernen?')\">🗑️</button>"
            "</form>"
            "</td>"
            "</tr>"
        )

    gname = g.get("name", "")
    body = nav
    body += '<div class="wrap">'
    body += sidebar(gid, "eco")
    body += '<main class="main">'
    body += alerts()
    body += '<div class="pt">Economy</div>'
    body += f'<p class="ps">{gname}</p>'

    # Coins bearbeiten
    body += '<div class="card"><div class="ct">💰 Coins bearbeiten</div>'
    body += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem">'
    body += '<div><div style="font-size:.85rem;font-weight:600;margin-bottom:.75rem">Coins setzen</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="set_coins">'
    body += '<div class="fg"><label class="lbl">User ID</label><input name="uid" class="inp" placeholder="User ID" required></div>'
    body += '<div class="fg"><label class="lbl">Betrag</label><input name="amt" type="number" class="inp" required></div>'
    body += '<button class="btn bp">Setzen</button>'
    body += '</form></div>'
    body += '<div><div style="font-size:.85rem;font-weight:600;margin-bottom:.75rem">Coins hinzufügen / abziehen</div>'
    body += '<form method="POST">'
    body += '<input type="hidden" name="action" value="add_coins">'
    body += '<div class="fg"><label class="lbl">User ID</label><input name="uid" class="inp" placeholder="User ID" required></div>'
    body += '<div class="fg"><label class="lbl">Betrag (negativ = abziehen)</label><input name="amt" type="number" class="inp" required></div>'
    body += '<button class="btn bp">Anwenden</button>'
    body += '</form></div>'
    body += '</div></div>'

    # Shop
    body += '<div class="card"><div class="ct">🛒 Shop verwalten</div>'
    body += '<div style="font-size:.85rem;font-weight:600;margin-bottom:.75rem">Item hinzufügen</div>'
    body += '<form method="POST" style="display:grid;grid-template-columns:1fr 1fr 2fr 1fr auto;gap:.75rem;align-items:flex-end;margin-bottom:1rem">'
    body += '<input type="hidden" name="action" value="add_shop">'
    body += '<div class="fg" style="margin:0"><label class="lbl">Name</label><input name="item_name" class="inp" required></div>'
    body += '<div class="fg" style="margin:0"><label class="lbl">Preis</label><input name="item_price" type="number" class="inp" required></div>'
    body += '<div class="fg" style="margin:0"><label class="lbl">Beschreibung</label><input name="item_desc" class="inp"></div>'
    body += f'<div class="fg" style="margin:0"><label class="lbl">Rolle</label><select name="item_role" class="sel">{role_opts}</select></div>'
    body += '<button class="btn bp">➕</button>'
    body += '</form>'
    body += '<table class="tbl"><thead><tr><th>Name</th><th>Preis</th><th>Beschreibung</th><th>Rolle ID</th><th></th></tr></thead><tbody>'
    if shop_rows:
        body += shop_rows
    else:
        body += '<tr><td colspan="5" style="color:var(--tx2);text-align:center">Shop ist leer</td></tr>'
    body += '</tbody></table></div>'

    # Leaderboard
    body += '<div class="card"><div class="ct">🏆 Leaderboard</div>'
    body += '<table class="tbl"><thead><tr><th>#</th><th>User / ID</th><th>Wallet</th><th>Bank</th><th>Gesamt</th><th>Rep</th><th></th></tr></thead><tbody>'
    body += lb_rows
    body += '</tbody></table></div>'
    body += '</main></div>'

    return pg(body)
