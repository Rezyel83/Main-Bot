from flask import Blueprint, session, redirect, url_for, request, flash, current_app
from functools import wraps
from app import pg, alerts, sidebar, guild_nav, dget, bguilds, uguilds, runasync

bp = Blueprint("settings", __name__)

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

@bp.route("/g/<gid>/sett", methods=["GET", "POST"])
@_lreq
@_greq
def gsett(gid):
    from bot import col, _findone, _update, ivcfg
    bot = current_app.bot
    nav, g = guild_nav(gid, bot)
    chs = dget(f"/guilds/{gid}/channels", isbot=True) or []
    rls = dget(f"/guilds/{gid}/roles", isbot=True) or []
    tch = [c for c in chs if c.get("type") == 0]
    vch = [c for c in chs if c.get("type") in [2, 13]]

    if request.method == "POST":
        section = request.form.get("section", "general")

        if section == "general":
            upd = {
                "prefix": request.form.get("prefix", "!") or "!",
                "anti_raid": request.form.get("anti_raid") == "1",
                "welcome_dm": request.form.get("welcome_dm") == "1",
                "slow_joiner_minutes": int(request.form.get("slow_joiner_minutes", "0") or "0"),
                "member_count_role": request.form.get("member_count_role") or None,
            }
            status = request.form.get("custom_bot_status", "").strip()
            if status:
                upd["custom_bot_status"] = status
                async def set_status():
                    import discord
                    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
                runasync(set_status(), bot)

            runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": upd}, upsert=True), bot)
            ivcfg(int(gid))
            flash("Allgemeine Einstellungen gespeichert!", "success")

        elif section == "welcome":
            upd = {
                "welcome_channel": request.form.get("welcome_channel") or None,
                "welcome_msg": request.form.get("welcome_msg", ""),
                "goodbye_channel": request.form.get("goodbye_channel") or None,
                "goodbye_msg": request.form.get("goodbye_msg", ""),
                "auto_role": request.form.get("auto_role") or None,
            }
            runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": upd}, upsert=True), bot)
            ivcfg(int(gid))
            flash("Willkommen-Einstellungen gespeichert!", "success")

        elif section == "roles":
            upd = {
                "verify_role": request.form.get("verify_role") or None,
                "auto_role": request.form.get("auto_role_r") or None,
                "member_count_role": request.form.get("member_count_role_r") or None,
            }
            runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": upd}, upsert=True), bot)
            ivcfg(int(gid))
            flash("Rollen-Einstellungen gespeichert!", "success")

        elif section == "automod":
            upd = {
                "automod.enabled": request.form.get("am_enabled") == "1",
                "automod.spam": request.form.get("am_spam") == "1",
                "automod.links": request.form.get("am_links") == "1",
                "automod.caps": request.form.get("am_caps") == "1",
                "automod.mention_limit": int(request.form.get("am_mentions", "5") or "5"),
            }
            bw_raw = request.form.get("bad_words", "")
            if bw_raw:
                words = [w.strip().lower() for w in bw_raw.split(",") if w.strip()]
                upd["automod.bad_words"] = words
            runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": upd}, upsert=True), bot)
            ivcfg(int(gid))
            flash("AutoMod-Einstellungen gespeichert!", "success")

        elif section == "channels":
            upd = {
                "suggest_channel": request.form.get("suggest_channel") or None,
                "birthday_channel": request.form.get("birthday_channel") or None,
                "starboard_channel": request.form.get("starboard_channel") or None,
                "starboard_min": int(request.form.get("starboard_min", "3") or "3"),
                "ticket_category": request.form.get("ticket_category") or None,
                "ticket_team_role": request.form.get("ticket_team_role") or None,
            }
            runasync(_update(col("config"), {"guild_id": int(gid)}, {"$set": upd}, upsert=True), bot)
            ivcfg(int(gid))
            flash("Kanal-Einstellungen gespeichert!", "success")

        elif section == "announce":
            ch_id   = request.form.get("announce_channel", "")
            msg     = request.form.get("announce_msg", "").strip()
            titel   = request.form.get("announce_titel", "").strip()
            use_embed = request.form.get("use_embed") == "1"
            if ch_id and msg:
                async def send_announce():
                    import discord
                    guild_obj = bot.get_guild(int(gid))
                    if not guild_obj: return
                    ch = guild_obj.get_channel(int(ch_id))
                    if not ch: return
                    if use_embed:
                        e = discord.Embed(title=titel or "Ankündigung", description=msg, color=discord.Color.red())
                        e.set_footer(text=guild_obj.name)
                        await ch.send(embed=e)
                    else:
                        await ch.send(msg)
                runasync(send_announce(), bot)
                flash(f"Nachricht gesendet!", "success")

    cfg = runasync(_findone(col("config"), {"guild_id": int(gid)}), bot) or {}
    am  = cfg.get("automod", {})

    def co(sel, clist, allow_none=True):
        cur = str(sel or "")
        o = '<option value="">-- Deaktiviert --</option>' if allow_none else ''
        for c in clist:
            s = " selected" if cur == str(c["id"]) else ""
            o += f'<option value="{c["id"]}"{s}>#{c["name"]}</option>'
        return o

    def ro(sel, all_roles=False):
        cur = str(sel or "")
        o = '<option value="">-- Keine --</option>'
        filtered = rls if all_roles else [r for r in rls if not r.get("managed") and r["name"] != "@everyone"]
        for r in sorted(filtered, key=lambda x: x.get("position", 0), reverse=True):
            s = " selected" if cur == str(r["id"]) else ""
            o += f'<option value="{r["id"]}"{s}>@{r["name"]}</option>'
        return o

    def cats_opts():
        o = '<option value="">-- Keine --</option>'
        for c in [c for c in chs if c.get("type") == 4]:
            s = " selected" if str(cfg.get("ticket_category","")) == c["id"] else ""
            o += f'<option value="{c["id"]}"{s}>{c["name"]}</option>'
        return o

    prefix        = cfg.get("prefix", "!")
    sj_min        = cfg.get("slow_joiner_minutes", 0)
    sb_min        = cfg.get("starboard_min", 3)
    bot_status    = cfg.get("custom_bot_status", "")
    am_enabled    = am.get("enabled", False)
    am_spam       = am.get("spam", True)
    am_links      = am.get("links", False)
    am_caps       = am.get("caps", False)
    am_ml         = am.get("mention_limit", 5)
    bad_words     = ", ".join(am.get("bad_words", []))
    anti_raid     = cfg.get("anti_raid", False)
    welcome_dm    = cfg.get("welcome_dm", False)
    welcome_msg   = cfg.get("welcome_msg", "")
    goodbye_msg   = cfg.get("goodbye_msg", "")

    def sel_bool(val):
        return ('selected' if val else '', '' if val else 'selected')

    ar_on, ar_off   = sel_bool(anti_raid)
    wdm_on, wdm_off = sel_bool(welcome_dm)

    def chk(val): return 'checked' if val else ''

    ch_opts_announce = '<option value="">Kanal wählen...</option>' + "".join(
        f'<option value="{c["id"]}">#{c["name"]}</option>' for c in sorted(tch, key=lambda x: x.get("position", 0))
    )

    body = (
        nav + '<div class="wrap">' + sidebar(gid, "sett") +
        '<main class="main">' + alerts() +
        f'<div class="pt">⚙️ Einstellungen</div>'
        f'<p class="ps">{g.get("name","")}</p>'

        # General
        '<div class="card"><div class="ct">🔧 Allgemein</div>'
        '<form method="POST"><input type="hidden" name="section" value="general">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Prefix</label><input name="prefix" class="inp" value="{prefix}" maxlength="5"></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Anti-Raid</label><select name="anti_raid" class="sel"><option value="1" {ar_on}>An</option><option value="0" {ar_off}>Aus</option></select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Slow Joiner (Minuten)</label><input name="slow_joiner_minutes" type="number" class="inp" value="{sj_min}"></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Welcome DM</label><select name="welcome_dm" class="sel"><option value="1" {wdm_on}>An</option><option value="0" {wdm_off}>Aus</option></select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Bot Status</label><input name="custom_bot_status" class="inp" value="{bot_status}" placeholder="z.B. 420 Member"></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Member-Zähler Rolle</label><select name="member_count_role" class="sel">{ro(cfg.get("member_count_role"))}</select></div>'
        '</div>'
        '<button class="btn bp" style="margin-top:.75rem">💾 Speichern</button>'
        '</form></div>'

        # Welcome / Goodbye
        '<div class="card"><div class="ct">👋 Willkommen & Abschied</div>'
        '<form method="POST"><input type="hidden" name="section" value="welcome">'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Willkommen-Kanal</label><select name="welcome_channel" class="sel">{co(cfg.get("welcome_channel"), tch)}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Abschied-Kanal</label><select name="goodbye_channel" class="sel">{co(cfg.get("goodbye_channel"), tch)}</select></div>'
        '</div>'
        f'<div class="fg"><label class="lbl">Willkommen-Nachricht <span style="color:var(--tx2)">({{user}} {{server}} {{count}})</span></label><textarea name="welcome_msg" class="ta">{welcome_msg}</textarea></div>'
        f'<div class="fg"><label class="lbl">Abschied-Nachricht</label><textarea name="goodbye_msg" class="ta">{goodbye_msg}</textarea></div>'
        f'<div class="fg"><label class="lbl">Auto-Rolle bei Beitritt</label><select name="auto_role" class="sel">{ro(cfg.get("auto_role"))}</select></div>'
        '<button class="btn bp">💾 Speichern</button>'
        '</form></div>'

        # Roles
        '<div class="card"><div class="ct">🎭 Rollen</div>'
        '<form method="POST"><input type="hidden" name="section" value="roles">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Verify-Rolle</label><select name="verify_role" class="sel">{ro(cfg.get("verify_role"))}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Auto-Rolle</label><select name="auto_role_r" class="sel">{ro(cfg.get("auto_role"))}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Member-Zähler Rolle</label><select name="member_count_role_r" class="sel">{ro(cfg.get("member_count_role"))}</select></div>'
        '</div>'
        '<button class="btn bp" style="margin-top:.75rem">💾 Speichern</button>'
        '</form></div>'

        # AutoMod
        '<div class="card"><div class="ct">🤖 AutoMod</div>'
        '<form method="POST"><input type="hidden" name="section" value="automod">'
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:.75rem">'
        f'<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem"><input type="checkbox" name="am_enabled" value="1" {chk(am_enabled)}> Aktiviert</label>'
        f'<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem"><input type="checkbox" name="am_spam" value="1" {chk(am_spam)}> Anti-Spam</label>'
        f'<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem"><input type="checkbox" name="am_links" value="1" {chk(am_links)}> Links blockieren</label>'
        f'<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem"><input type="checkbox" name="am_caps" value="1" {chk(am_caps)}> Caps blockieren</label>'
        '</div>'
        f'<div style="display:grid;grid-template-columns:1fr 2fr;gap:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Mention Limit</label><input name="am_mentions" type="number" class="inp" value="{am_ml}"></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Verbotene Wörter (kommagetrennt)</label><input name="bad_words" class="inp" value="{bad_words}"></div>'
        '</div>'
        '<button class="btn bp" style="margin-top:.75rem">💾 Speichern</button>'
        '</form></div>'

        # Channels
        '<div class="card"><div class="ct">💬 Kanal-Einstellungen</div>'
        '<form method="POST"><input type="hidden" name="section" value="channels">'
        '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Suggest-Kanal</label><select name="suggest_channel" class="sel">{co(cfg.get("suggest_channel"), tch)}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Geburtstags-Kanal</label><select name="birthday_channel" class="sel">{co(cfg.get("birthday_channel"), tch)}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Starboard-Kanal</label><select name="starboard_channel" class="sel">{co(cfg.get("starboard_channel"), tch)}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Starboard Min. ⭐</label><input name="starboard_min" type="number" class="inp" value="{sb_min}"></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Ticket Kategorie</label><select name="ticket_category" class="sel">{cats_opts()}</select></div>'
        f'<div class="fg" style="margin:0"><label class="lbl">Ticket Team-Rolle</label><select name="ticket_team_role" class="sel">{ro(cfg.get("ticket_team_role"))}</select></div>'
        '</div>'
        '<button class="btn bp" style="margin-top:.75rem">💾 Speichern</button>'
        '</form></div>'

        # Announce / Say
        '<div class="card"><div class="ct">📢 Nachricht senden</div>'
        '<form method="POST"><input type="hidden" name="section" value="announce">'
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:.75rem">'
        f'<div class="fg" style="margin:0"><label class="lbl">Kanal</label><select name="announce_channel" class="sel" required>{ch_opts_announce}</select></div>'
        '<div class="fg" style="margin:0"><label class="lbl">Titel (nur bei Embed)</label><input name="announce_titel" class="inp" placeholder="Ankündigung"></div>'
        '</div>'
        '<div class="fg"><label class="lbl">Nachricht</label><textarea name="announce_msg" class="ta" required placeholder="Nachricht hier eingeben..."></textarea></div>'
        '<label style="display:flex;align-items:center;gap:.4rem;font-size:.85rem;margin-bottom:.75rem"><input type="checkbox" name="use_embed" value="1"> Als Embed senden</label>'
        '<button class="btn bp">📢 Senden</button>'
        '</form></div>'

        '</main></div>'
    )
    return pg(body)
