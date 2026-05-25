import discord
from discord.ext import commands, tasks
from discord import app_commands
import os, asyncio, threading, time, random, re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from typing import Optional
from motor.motor_asyncio import AsyncIOMotorClient
import uvicorn
from fastapi import FastAPI

load_dotenv()

# ── FastAPI Keep-Alive ─────────────────────────────────────────
app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "bot": "RLD Main Bot", "uptime": str(datetime.utcnow())}

@app.get("/health")
async def health():
    return {"status": "ok", "ping": round(bot.latency * 1000) if bot.is_ready() else -1}

# ❌ ALT (FastAPI/UVICORN - funktioniert nicht mit Flask)
from fastapi import FastAPI
import uvicorn

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "bot": "RLD Main Bot", "uptime": str(datetime.utcnow())}

@app.get("/health")
async def health():
    return {"status": "ok", "ping": round(bot.latency * 1000) if bot.is_ready() else -1}
# ✅ NEU (Flask - WSGI kompatibel)
from flask import Flask

flask_app = Flask(__name__)

@flask_app.route("/")
def root():
    return {"status": "ok", "bot": "RLD Main Bot", "uptime": str(datetime.utcnow())}

@flask_app.route("/ping")
def ping():
    return {"status": "alive"}

@flask_app.route("/health")
def health():
    return {"status": "ok", "ping": round(bot.latency * 1000) if bot.is_ready() else -1}

def starte_webserver():
    port = int(os.getenv("PORT", "8000"))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


async def keep_alive():
    url = os.getenv("RENDER_EXTERNAL_URL", "")
    if not url:
        print("⚠️ RENDER_EXTERNAL_URL nicht gesetzt, Keep-alive deaktiviert")
        return
    await asyncio.sleep(30)
    while True:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        print("🏓 Keep-alive ping erfolgreich")
        except asyncio.TimeoutError:
            print("⚠️ Keep-alive Timeout")
        except Exception as e:
            print(f"⚠️ Keep-alive Fehler: {e}")
        await asyncio.sleep(540)

# ── MongoDB ────────────────────────────────────────────────────
mongo = AsyncIOMotorClient(os.getenv("MONGODB_URI"))
db = mongo[os.getenv("MONGODB_DB", "rld_main")]
warns_col     = db["warns"]
config_col    = db["config"]
tickets_col   = db["tickets"]
reminders_col = db["reminders"]
team_col      = db["team"]
apps_col      = db["applications"]
logs_col      = db["logs"]
economy_col   = db["economy"]
giveaway_col  = db["giveaways"]
suggest_col   = db["suggestions"]
starboard_col = db["starboard"]
afk_col       = db["afk"]
cases_col     = db["cases"]
birthday_col  = db["birthdays"]
rss_col       = db["rss_feeds"]
rss_seen_col  = db["rss_seen"]
rl_teams_col  = db["rl_teams"]
tournament_col = db["tournaments"]
custom_cmd_col = db["custom_commands"]
voice_col     = db["voice_stats"]
profiles_col  = db["profiles"]
notif_col     = db["notifications"]
dashboard_log_col = db["dashboard_logs"]

# ── Config Helfer ──────────────────────────────────────────────
async def hole_config(gid: Optional[int]) -> dict:
    if not gid: return {}
    doc = await config_col.find_one({"guild_id": gid})
    if not doc:
        doc = {
            "guild_id": gid, "prefix": "!",
            "mod_log": None, "welcome_channel": None,
            "welcome_msg": "Willkommen {user} auf {server}! 🎉",
            "goodbye_channel": None, "goodbye_msg": "{user} hat den Server verlassen.",
            "auto_role": None, "verify_role": None,
            "ticket_category": None, "ticket_log": None, "ticket_team_role": None,
            "starboard_channel": None, "starboard_min": 3,
            "suggest_channel": None, "suggest_log": None,
            "bump_channel": None, "birthday_channel": None,
            "automod": {"enabled": False, "spam": True, "links": False, "caps": False, "bad_words": [], "duplicate": False, "mention_limit": 5},
            "anti_raid": False, "welcome_dm": False,
            "stat_channels": {},
            "coin_multiplier_roles": {},
            "shop": [],
            "perm_presets": {},
            "custom_bot_status": None,
            "slow_joiner_minutes": 0,
        }
        await config_col.insert_one(doc)
    return doc

async def log_aktion(guild_id, mod_id, target_id, aktion, grund):
    case_num = await cases_col.count_documents({"guild_id": guild_id}) + 1
    await cases_col.insert_one({
        "guild_id": guild_id, "case": case_num, "mod_id": mod_id,
        "target_id": target_id, "aktion": aktion, "grund": grund, "ts": datetime.utcnow()
    })
    await logs_col.insert_one({
        "guild_id": guild_id, "mod_id": mod_id, "target_id": target_id,
        "aktion": aktion, "grund": grund, "ts": datetime.utcnow(), "case": case_num
    })
    return case_num

# ── Economy Helfer ─────────────────────────────────────────────
async def hole_eco(gid, uid):
    doc = await economy_col.find_one({"guild_id": gid, "user_id": uid})
    if not doc:
        doc = {"guild_id": gid, "user_id": uid, "coins": 0, "bank": 0, "last_daily": None, "last_work": None, "last_fish": None, "last_mine": None, "streak": 0, "inventory": [], "rep": 0, "last_rep": None}
        await economy_col.insert_one(doc)
    return doc

async def add_coins(gid, uid, amount):
    await economy_col.update_one({"guild_id": gid, "user_id": uid}, {"$inc": {"coins": amount}}, upsert=True)

# ── Bot Setup ──────────────────────────────────────────────────
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
start_time = datetime.utcnow()
spam_tracker = {}
recent_joins = []

# ══════════════════════════════════════════════════════════════
# EVENTS
# ══════════════════════════════════════════════════════════════
@bot.event
async def on_ready():
    print(f"✅ {bot.user} online")
    try:
        synced = await bot.tree.sync()
        print(f"✅ {len(synced)} Commands gesynced")
    except Exception as e:
        print(f"❌ Sync Fehler: {e}")
    reminder_loop.start()
    rss_check_loop.start()
    birthday_loop.start()
    stat_channel_loop.start()
    giveaway_loop.start()
    twitch_check_loop.start()
    asyncio.ensure_future(keep_alive())
    cfg_all = await config_col.find({}).to_list(100)
    for cfg in cfg_all:
        if cfg.get("custom_bot_status"):
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=cfg["custom_bot_status"]))
            return
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"{sum((g.member_count or 0) for g in bot.guilds)} Member | /help"))

@bot.event
async def on_member_join(member: discord.Member):
    cfg = await hole_config(member.guild.id)
    # Slow Joiner Check
    slow_min = cfg.get("slow_joiner_minutes", 0)
    if slow_min > 0:
        age = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).total_seconds() / 60
        if age < slow_min:
            try:
                await member.send(f"Dein Account ist zu neu. Komm in {slow_min} Minuten wieder.")
                await member.kick(reason="Account zu neu (Slow Joiner Protection)")
            except: pass
            return
    # Anti-Raid
    if cfg.get("anti_raid"):
        now = time.time()
        recent_joins.append(now)
        recent_joins_filtered = [j for j in recent_joins if now - j < 10]
        recent_joins.clear()
        recent_joins.extend(recent_joins_filtered)
        if len(recent_joins) >= 10:
            try:
                await member.kick(reason="Anti-Raid: Zu viele Beitritte")
                return
            except: pass
    # Auto-Rolle
    if cfg.get("auto_role"):
        role = member.guild.get_role(int(cfg["auto_role"]))
        if role:
            try: await member.add_roles(role)
            except: pass
    # Willkommen
    if cfg.get("welcome_channel"):
        ch = member.guild.get_channel(int(cfg["welcome_channel"]))
        if ch:
            msg = cfg.get("welcome_msg", "Willkommen {user}!").replace("{user}", member.mention).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count))
            e = discord.Embed(description=msg, color=discord.Color.green())
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)
    # Welcome DM
    if cfg.get("welcome_dm"):
        try:
            await member.send(embed=discord.Embed(title=f"Willkommen auf {member.guild.name}!", description=cfg.get("welcome_msg","").replace("{user}", member.display_name), color=discord.Color.blurple()))
        except: pass

@bot.event
async def on_member_remove(member: discord.Member):
    cfg = await hole_config(member.guild.id)
    if cfg.get("goodbye_channel"):
        ch = member.guild.get_channel(int(cfg["goodbye_channel"]))
        if ch:
            msg = cfg.get("goodbye_msg", "{user} hat den Server verlassen.").replace("{user}", str(member)).replace("{server}", member.guild.name)
            e = discord.Embed(description=msg, color=discord.Color.red())
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or not msg.guild: return
    cfg = await hole_config(msg.guild.id)

    # AFK Check
    afk = await afk_col.find_one({"guild_id": msg.guild.id, "user_id": msg.author.id})
    if afk:
        await afk_col.delete_one({"_id": afk["_id"]})
        try: await msg.channel.send(f"👋 Willkommen zurück {msg.author.mention}! AFK aufgehoben.", delete_after=5)
        except: pass

    # Mentions → AFK Check
    for mention in msg.mentions:
        afk_user = await afk_col.find_one({"guild_id": msg.guild.id, "user_id": mention.id})
        if afk_user:
            try: await msg.channel.send(f"💤 **{mention.display_name}** ist AFK: {afk_user.get('grund', 'Kein Grund')}", delete_after=10)
            except: pass

    # Custom Commands
    custom = await custom_cmd_col.find_one({"guild_id": msg.guild.id, "trigger": msg.content.lower().split()[0] if msg.content else ""})
    if custom:
        await msg.channel.send(custom["response"])

    # Coins für Aktivität
    eco = await hole_eco(msg.guild.id, msg.author.id)
    await add_coins(msg.guild.id, msg.author.id, 1)

    # AutoMod
    automod = cfg.get("automod", {})
    if automod.get("enabled") and msg.guild and not msg.author.guild_permissions.manage_messages:
        # Bad Words
        if automod.get("bad_words"):
            for word in automod["bad_words"]:
                if word.lower() in msg.content.lower():
                    try: await msg.delete(); await msg.channel.send(f"{msg.author.mention} Verbotenes Wort!", delete_after=5)
                    except: pass
                    return
        # Caps
        if automod.get("caps") and len(msg.content) > 10:
            caps = sum(1 for c in msg.content if c.isupper())
            if caps / len(msg.content) > 0.7:
                try: await msg.delete(); await msg.channel.send(f"{msg.author.mention} Bitte keine Großbuchstaben!", delete_after=5)
                except: pass
                return
        # Links
        if automod.get("links") and re.search(r'https?://|discord\.gg/', msg.content):
            try: await msg.delete(); await msg.channel.send(f"{msg.author.mention} Links nicht erlaubt!", delete_after=5)
            except: pass
            return
        # Mention Spam
        mention_limit = automod.get("mention_limit", 5)
        if len(msg.mentions) >= mention_limit:
            try:
                await msg.delete()
                until = discord.utils.utcnow() + timedelta(minutes=5)
                await msg.author.timeout(until, reason="Mention Spam") if hasattr(msg.author, 'timeout') else None
                await msg.channel.send(f"{msg.author.mention} Mention Spam! 5 Minuten Timeout.", delete_after=5)
            except: pass
            return
        # Spam Detection
        key = f"{msg.guild.id}:{msg.author.id}"
        now = time.time()
        if key not in spam_tracker: spam_tracker[key] = []
        spam_tracker[key] = [t for t in spam_tracker[key] if now - t < 5]
        spam_tracker[key].append(now)
        if len(spam_tracker[key]) >= 5:
            try:
                until = discord.utils.utcnow() + timedelta(minutes=2)
                await msg.author.timeout(until, reason="Spam") if hasattr(msg.author, 'timeout') else None
                await msg.channel.send(f"{msg.author.mention} Spam erkannt! 2 Minuten Timeout.", delete_after=5)
            except: pass

    await bot.process_commands(msg)

@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if user.bot: return
    if not reaction.message.guild: return
    cfg = await hole_config(reaction.message.guild.id)
    # Starboard
    sb_channel_id = cfg.get("starboard_channel")
    sb_min = cfg.get("starboard_min", 3)
    if sb_channel_id and str(reaction.emoji) == "⭐" and reaction.count >= sb_min:
        sb_ch = reaction.message.guild.get_channel(int(sb_channel_id)) if reaction.message.guild else None
        if sb_ch:
            existing = await starboard_col.find_one({"message_id": reaction.message.id})
            if not existing:
                e = discord.Embed(description=reaction.message.content, color=discord.Color.gold())
                e.set_author(name=reaction.message.author.display_name, icon_url=reaction.message.author.display_avatar.url)
                e.add_field(name="Original", value=f"[Springe zur Nachricht]({reaction.message.jump_url})")
                if reaction.message.attachments:
                    e.set_image(url=reaction.message.attachments[0].url)
                sb_msg = await sb_ch.send(f"⭐ **{reaction.count}** | {reaction.message.channel.mention}", embed=e)
                await starboard_col.insert_one({"message_id": reaction.message.id, "sb_message_id": sb_msg.id})

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # Voice Stats
    key = f"{member.guild.id}:{member.id}"
    if after.channel and not before.channel:
        await voice_col.update_one({"guild_id": member.guild.id, "user_id": member.id}, {"$set": {"join_time": time.time()}}, upsert=True)
    elif not after.channel and before.channel:
        doc = await voice_col.find_one({"guild_id": member.guild.id, "user_id": member.id})
        if doc and doc.get("join_time"):
            minutes = (time.time() - doc["join_time"]) / 60
            await voice_col.update_one({"guild_id": member.guild.id, "user_id": member.id}, {"$inc": {"total_minutes": minutes}, "$unset": {"join_time": ""}})
            await add_coins(member.guild.id, member.id, int(minutes * 2))

    # Temp Voice
    cfg = await hole_config(member.guild.id)
    temp_cat = cfg.get("temp_voice_category")
    if after.channel and temp_cat and str(after.channel.category_id) == str(temp_cat):
        if after.channel.name == "➕ Erstelle Channel":
            new_ch = await member.guild.create_voice_channel(f"🎮 {member.display_name}", category=after.channel.category)
            await member.move_to(new_ch)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound): return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Keine Berechtigung!"); return
    print(f"❌ [{ctx.command}]: {error}")

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = "❌ Fehler!"
    if isinstance(error, app_commands.CheckFailure): msg = "❌ Keine Berechtigung!"
    print(f"❌ Slash [{interaction.command.name if interaction.command else '?'}]: {error}")
    try:
        if interaction.response.is_done(): await interaction.followup.send(msg, ephemeral=True)
        else: await interaction.response.send_message(msg, ephemeral=True)
    except: pass

# ── Permission Checks ──────────────────────────────────────────
def is_mod():
    async def pred(i): return i.user.guild_permissions.kick_members or i.user.guild_permissions.administrator
    return app_commands.check(pred)

def is_admin():
    async def pred(i): return i.user.guild_permissions.administrator
    return app_commands.check(pred)

# ══════════════════════════════════════════════════════════════
# MODERATION
# ══════════════════════════════════════════════════════════════
async def _mod_log(guild, embed):
    cfg = await hole_config(guild.id)
    if cfg.get("mod_log"):
        ch = guild.get_channel(int(cfg["mod_log"]))
        if ch:
            try: await ch.send(embed=embed)
            except: pass

@bot.tree.command(name="ban", description="Bannt einen User.")
@is_mod()
async def ban_cmd(interaction: discord.Interaction, user: discord.Member, grund: str = "Kein Grund", delete_days: int = 0):
    await interaction.response.defer()
    if hasattr(user, 'top_role') and hasattr(interaction.user, 'top_role') and user.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ Du kannst diesen User nicht bannen!"); return
    try: await user.send(f"Du wurdest von **{interaction.guild.name if interaction.guild else 'this server'}** gebannt.\nGrund: {grund}")
    except: pass
    if interaction.guild:
        await interaction.guild.ban(user, reason=grund, delete_message_days=delete_days)
    case = await log_aktion(interaction.guild_id, interaction.user.id, user.id, "ban", grund)
    e = discord.Embed(title=f"🔨 Ban | Case #{case}", color=discord.Color.red())
    e.add_field(name="User", value=f"{user} ({user.id})", inline=True)
    e.add_field(name="Mod", value=interaction.user.mention, inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await interaction.followup.send(embed=e)
    await _mod_log(interaction.guild, e)

@bot.tree.command(name="unban", description="Entbannt einen User.")
@is_mod()
async def unban_cmd(interaction: discord.Interaction, user_id: str, grund: str = "Kein Grund"):
    await interaction.response.defer()
    try:
        user = await bot.fetch_user(int(user_id))
        if interaction.guild:
            await interaction.guild.unban(user, reason=grund)
        await interaction.followup.send(f"✅ **{user}** entbannt.")
    except: await interaction.followup.send("❌ User nicht gefunden.")

@bot.tree.command(name="kick", description="Kickt einen User.")
@is_mod()
async def kick_cmd(interaction: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
    await interaction.response.defer()
    if hasattr(user, 'top_role') and hasattr(interaction.user, 'top_role') and user.top_role >= interaction.user.top_role:
        await interaction.followup.send("❌ Du kannst diesen User nicht kicken!"); return
    try: await user.send(f"Du wurdest von **{interaction.guild.name if interaction.guild else 'this server'}** gekickt.\nGrund: {grund}")
    except: pass
    await user.kick(reason=grund)
    case = await log_aktion(interaction.guild_id, interaction.user.id, user.id, "kick", grund)
    e = discord.Embed(title=f"👢 Kick | Case #{case}", color=discord.Color.orange())
    e.add_field(name="User", value=f"{user}", inline=True)
    e.add_field(name="Mod", value=interaction.user.mention, inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await interaction.followup.send(embed=e)
    await _mod_log(interaction.guild, e)

@bot.tree.command(name="timeout", description="Timeout für einen User.")
@is_mod()
async def timeout_cmd(interaction: discord.Interaction, user: discord.Member, minuten: int, grund: str = "Kein Grund"):
    await interaction.response.defer()
    until = discord.utils.utcnow() + timedelta(minutes=minuten)
    if hasattr(user, 'timeout'):
        await user.timeout(until, reason=grund)
    case = await log_aktion(interaction.guild_id, interaction.user.id, user.id, "timeout", grund)
    e = discord.Embed(title=f"⏰ Timeout | Case #{case}", color=discord.Color.yellow())
    e.add_field(name="User", value=user.mention, inline=True)
    e.add_field(name="Dauer", value=f"{minuten} Min", inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await interaction.followup.send(embed=e)
    await _mod_log(interaction.guild, e)

@bot.tree.command(name="untimeout", description="Timeout aufheben.")
@is_mod()
async def untimeout_cmd(interaction: discord.Interaction, user: discord.Member):
    await user.timeout(None)
    await interaction.response.send_message(f"✅ Timeout von {user.mention} aufgehoben.")

@bot.tree.command(name="warn", description="Verwarnt einen User.")
@is_mod()
async def warn_cmd(interaction: discord.Interaction, user: discord.Member, grund: str):
    await interaction.response.defer()
    await warns_col.insert_one({"guild_id": interaction.guild_id, "user_id": user.id, "mod_id": interaction.user.id, "grund": grund, "ts": datetime.utcnow()})
    count = await warns_col.count_documents({"guild_id": interaction.guild_id, "user_id": user.id})
    case = await log_aktion(interaction.guild_id, interaction.user.id, user.id, "warn", grund)
    try: await user.send(f"Verwarnung auf **{interaction.guild.name if interaction.guild else 'this server'}**\nGrund: {grund}\nVerwarnungen: {count}")
    except: pass
    e = discord.Embed(title=f"⚠️ Warn | Case #{case}", color=discord.Color.yellow())
    e.add_field(name="User", value=user.mention, inline=True)
    e.add_field(name="Anzahl", value=str(count), inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await interaction.followup.send(embed=e)
    await _mod_log(interaction.guild, e)

@bot.tree.command(name="warns", description="Verwarnungen anzeigen.")
@is_mod()
async def warns_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    warns = await warns_col.find({"guild_id": interaction.guild_id, "user_id": user.id}).sort("ts", -1).to_list(20)
    e = discord.Embed(title=f"⚠️ Verwarnungen: {user.display_name}", color=discord.Color.yellow())
    if not warns: e.description = "Keine Verwarnungen."
    else:
        for i, w in enumerate(warns, 1):
            mod = interaction.guild.get_member(w["mod_id"]) if interaction.guild else None
            e.add_field(name=f"#{i} – {w['ts'].strftime('%d.%m.%Y')}", value=f"{w['grund']}\nMod: {mod.mention if mod else '?'}", inline=False)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="unwarn", description="Letzte Verwarnung entfernen.")
@is_mod()
async def unwarn_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    last = await warns_col.find_one({"guild_id": interaction.guild_id, "user_id": user.id}, sort=[("ts", -1)])
    if not last: await interaction.followup.send("❌ Keine Verwarnungen."); return
    await warns_col.delete_one({"_id": last["_id"]})
    await interaction.followup.send(f"✅ Letzte Verwarnung von {user.mention} entfernt.")

@bot.tree.command(name="clearwarns", description="[Admin] Alle Verwarnungen löschen.")
@is_admin()
async def clearwarns_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    r = await warns_col.delete_many({"guild_id": interaction.guild_id, "user_id": user.id})
    await interaction.followup.send(f"✅ {r.deleted_count} Verwarnungen gelöscht.")

@bot.tree.command(name="case", description="Case Details anzeigen.")
@is_mod()
async def case_cmd(interaction: discord.Interaction, nummer: int):
    await interaction.response.defer()
    case = await cases_col.find_one({"guild_id": interaction.guild_id, "case": nummer})
    if not case: await interaction.followup.send("❌ Case nicht gefunden."); return
    mod = interaction.guild.get_member(case["mod_id"]) if interaction.guild else None
    target = interaction.guild.get_member(case["target_id"]) if interaction.guild else None
    e = discord.Embed(title=f"📋 Case #{nummer}", color=discord.Color.blurple())
    e.add_field(name="Aktion", value=case["aktion"], inline=True)
    e.add_field(name="User", value=str(target) if target else str(case["target_id"]), inline=True)
    e.add_field(name="Mod", value=mod.mention if mod else str(case["mod_id"]), inline=True)
    e.add_field(name="Grund", value=case["grund"], inline=False)
    e.add_field(name="Datum", value=case["ts"].strftime("%d.%m.%Y %H:%M"), inline=True)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="clear", description="Nachrichten löschen.")
@is_mod()
async def clear_cmd(interaction: discord.Interaction, anzahl: int, user: Optional[discord.Member] = None):
    await interaction.response.defer(ephemeral=True)
    def check(m): return user is None or m.author == user
    deleted = await interaction.channel.purge(limit=min(anzahl, 100), check=check) if interaction.channel and hasattr(interaction.channel, 'purge') else []
    await interaction.followup.send(f"✅ {len(deleted)} Nachrichten gelöscht.", ephemeral=True)

@bot.tree.command(name="slowmode", description="Slowmode setzen.")
@is_mod()
async def slowmode_cmd(interaction: discord.Interaction, sekunden: int):
    if interaction.channel and hasattr(interaction.channel, 'edit'):
        await interaction.channel.edit(slowmode_delay=sekunden) if hasattr(interaction.channel, 'edit') else None
    await interaction.response.send_message(f"✅ Slowmode: **{sekunden}s**")

@bot.tree.command(name="lock", description="Kanal sperren.")
@is_mod()
async def lock_cmd(interaction: discord.Interaction):
    if interaction.channel and interaction.guild and hasattr(interaction.channel, 'set_permissions') and hasattr(interaction.guild, 'default_role'):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
    await interaction.response.send_message("🔒 Kanal gesperrt.")

@bot.tree.command(name="unlock", description="Kanal entsperren.")
@is_mod()
async def unlock_cmd(interaction: discord.Interaction):
    if interaction.channel and interaction.guild and hasattr(interaction.channel, 'set_permissions') and hasattr(interaction.guild, 'default_role'):
        await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
    await interaction.response.send_message("🔓 Kanal entsperrt.")

@bot.tree.command(name="raid-mode", description="[Admin] Raid Mode aktivieren/deaktivieren.")
@is_admin()
async def raid_mode_cmd(interaction: discord.Interaction, aktiv: bool):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"anti_raid": aktiv}}, upsert=True)
    await interaction.response.send_message(f"{'🚨 Raid Mode AKTIVIERT' if aktiv else '✅ Raid Mode deaktiviert'}")

# ══════════════════════════════════════════════════════════════
# INFO COMMANDS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="userinfo", description="User Informationen.")
async def userinfo_cmd(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()
    u = user or interaction.user
    warns = await warns_col.count_documents({"guild_id": interaction.guild_id, "user_id": u.id})
    eco = await hole_eco(interaction.guild_id, u.id)
    e = discord.Embed(title=f"👤 {u.display_name}", color=u.color)
    e.set_thumbnail(url=u.display_avatar.url)
    e.add_field(name="ID", value=str(u.id), inline=True)
    e.add_field(name="Erstellt", value=u.created_at.strftime("%d.%m.%Y"), inline=True)
    e.add_field(name="Beigetreten", value=u.joined_at.strftime("%d.%m.%Y") if u.joined_at else "?", inline=True)
    e.add_field(name="Rollen", value=" ".join(r.mention for r in u.roles[1:]) or "Keine", inline=False)
    e.add_field(name="⚠️ Warns", value=str(warns), inline=True)
    e.add_field(name="💰 Coins", value=str(eco.get("coins", 0)), inline=True)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="serverinfo", description="Server Informationen.")
async def serverinfo_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    g = interaction.guild
    e = discord.Embed(title=f"🏠 {g.name}", color=discord.Color.blurple())
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="ID", value=str(g.id), inline=True)
    e.add_field(name="Owner", value=str(g.owner), inline=True)
    e.add_field(name="Erstellt", value=g.created_at.strftime("%d.%m.%Y"), inline=True)
    e.add_field(name="👥 Member", value=str(g.member_count), inline=True)
    e.add_field(name="💬 Kanäle", value=str(len(g.channels)), inline=True)
    e.add_field(name="🎭 Rollen", value=str(len(g.roles)), inline=True)
    e.add_field(name="Boost Level", value=str(g.premium_tier), inline=True)
    e.add_field(name="Boosts", value=str(g.premium_subscription_count), inline=True)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="avatar", description="Avatar anzeigen.")
async def avatar_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    u = user or interaction.user
    e = discord.Embed(title=f"🖼️ {u.display_name}", color=discord.Color.blurple())
    e.set_image(url=u.display_avatar.url)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="ping", description="Bot Latenz.")
async def ping_cmd(interaction: discord.Interaction):
    uptime = datetime.utcnow() - start_time
    hours, rem = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(rem, 60)
    await interaction.response.send_message(f"🏓 Pong! **{round(bot.latency * 1000)}ms** | Uptime: {hours}h {minutes}m {seconds}s")

@bot.tree.command(name="timestamp", description="Discord Timestamp erstellen.")
async def timestamp_cmd(interaction: discord.Interaction, datum: str, uhrzeit: str = "00:00", posten: bool = False):
    try:
        dt = datetime.strptime(f"{datum} {uhrzeit}", "%d.%m.%Y %H:%M")
        ts = int(dt.timestamp())
        formats = {
            "Kurze Zeit": f"`<t:{ts}:t>`  → <t:{ts}:t>",
            "Lange Zeit": f"`<t:{ts}:T>`  → <t:{ts}:T>",
            "Kurzes Datum": f"`<t:{ts}:d>`  → <t:{ts}:d>",
            "Langes Datum": f"`<t:{ts}:D>`  → <t:{ts}:D>",
            "Datum + Zeit": f"`<t:{ts}:f>`  → <t:{ts}:f>",
            "Relativ": f"`<t:{ts}:R>`  → <t:{ts}:R>",
        }
        e = discord.Embed(title="🕐 Discord Timestamp", color=discord.Color.blurple())
        for name, val in formats.items():
            e.add_field(name=name, value=val, inline=False)
        if posten:
            await interaction.response.send_message(f"<t:{ts}:F>")
        else:
            await interaction.response.send_message(embed=e)
    except:
        await interaction.response.send_message("❌ Format: DD.MM.YYYY und HH:MM")

# ══════════════════════════════════════════════════════════════
# FUN COMMANDS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="8ball", description="Stelle eine Frage!")
async def ball_cmd(interaction: discord.Interaction, frage: str):
    antworten = ["Ja!", "Definitiv ja!", "Sehr wahrscheinlich.", "Vielleicht.", "Eher nicht.", "Definitiv nein!", "Frag später nochmal.", "Die Zeichen sagen ja.", "Unmöglich.", "Ohne Zweifel!"]
    e = discord.Embed(title="🎱 8Ball", color=discord.Color.purple())
    e.add_field(name="❓ Frage", value=frage, inline=False)
    e.add_field(name="🎱 Antwort", value=random.choice(antworten), inline=False)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="coinflip", description="Münze werfen.")
async def coinflip_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(f"🪙 **{random.choice(['Kopf 👑', 'Zahl 🔢'])}**")

@bot.tree.command(name="würfel", description="Würfel werfen.")
async def wuerfel_cmd(interaction: discord.Interaction, anzahl: int = 1, seiten: int = 6):
    anzahl = min(anzahl, 10)
    ergebnisse = [random.randint(1, seiten) for _ in range(anzahl)]
    e = discord.Embed(title="🎲 Würfel", color=discord.Color.green())
    e.add_field(name="Ergebnisse", value=" | ".join(str(r) for r in ergebnisse))
    e.add_field(name="Summe", value=str(sum(ergebnisse)))
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="rps", description="Schere Stein Papier.")
async def rps_cmd(interaction: discord.Interaction, wahl: str):
    optionen = ["schere", "stein", "papier"]
    wahl = wahl.lower()
    if wahl not in optionen: await interaction.response.send_message("❌ Wähle: schere, stein, papier!"); return
    bot_wahl = random.choice(optionen)
    emojis = {"schere": "✂️", "stein": "🪨", "papier": "📄"}
    if wahl == bot_wahl: result = "🤝 Unentschieden!"
    elif (wahl=="schere" and bot_wahl=="papier") or (wahl=="stein" and bot_wahl=="schere") or (wahl=="papier" and bot_wahl=="stein"): result = "🎉 Du gewinnst!"
    else: result = "😔 Bot gewinnt!"
    e = discord.Embed(title="✂️🪨📄 RPS", color=discord.Color.blurple())
    e.add_field(name="Du", value=emojis[wahl], inline=True)
    e.add_field(name="Bot", value=emojis[bot_wahl], inline=True)
    e.add_field(name="Ergebnis", value=result, inline=False)
    await interaction.response.send_message(embed=e)

@bot.tree.command(name="quote", description="Inspirierendes Zitat.")
async def quote_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://zenquotes.io/api/random") as r:
                data = await r.json()
        e = discord.Embed(description=f'*"{data[0]["q"]}"*\n\n— **{data[0]["a"]}**', color=discord.Color.gold())
        await interaction.followup.send(embed=e)
    except: await interaction.followup.send("❌ Fehler beim Laden.")

@bot.tree.command(name="fact", description="Zufälliger Fakt.")
async def fact_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://uselessfacts.jsph.pl/random.json?language=de") as r:
                data = await r.json()
        e = discord.Embed(title="💡 Fakt", description=data.get("text", "Kein Fakt."), color=discord.Color.teal())
        await interaction.followup.send(embed=e)
    except: await interaction.followup.send("❌ Fehler beim Laden.")

@bot.tree.command(name="gif", description="GIF suchen.")
async def gif_cmd(interaction: discord.Interaction, suche: str):
    await interaction.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"https://api.tenor.com/v1/search?q={suche}&limit=10&key=LIVDSRZULELA") as r:
                data = await r.json()
        results = data.get("results", [])
        if not results: await interaction.followup.send("❌ Kein GIF gefunden."); return
        gif = random.choice(results)
        await interaction.followup.send(gif["media"][0]["gif"]["url"])
    except: await interaction.followup.send("❌ Fehler.")

@bot.tree.command(name="poll", description="Abstimmung erstellen.")
async def poll_cmd(interaction: discord.Interaction, frage: str, option1: str, option2: str, option3: str = None, option4: str = None):
    optionen = [o for o in [option1, option2, option3, option4] if o]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
    e = discord.Embed(title=f"📊 {frage}", description="\n".join(f"{emojis[i]} {opt}" for i, opt in enumerate(optionen)), color=discord.Color.blurple())
    e.set_footer(text=f"von {interaction.user.display_name}")
    await interaction.response.send_message(embed=e)
    msg = await interaction.original_response()
    for i in range(len(optionen)): await msg.add_reaction(emojis[i])

@bot.tree.command(name="calc", description="Rechnung ausführen.")
async def calc_cmd(interaction: discord.Interaction, rechnung: str):
    if re.search(r'[a-zA-Z_]', rechnung.replace('e', '').replace('pi', '')):
        await interaction.response.send_message("❌ Ungültig!"); return
    try:
        result = eval(rechnung.replace('^', '**'))
        await interaction.response.send_message(f"🧮 `{rechnung}` = **{result}**")
    except: await interaction.response.send_message("❌ Ungültige Rechnung!")

@bot.tree.command(name="meme", description="Zufälliges Meme.")
async def meme_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme") as r:
                data = await r.json()
        e = discord.Embed(title=data.get("title", "Meme"), color=discord.Color.random())
        e.set_image(url=data.get("url"))
        e.set_footer(text=f"r/{data.get('subreddit', '?')}")
        await interaction.followup.send(embed=e)
    except: await interaction.followup.send("❌ Kein Meme geladen.")

@bot.tree.command(name="status-setzen", description="Persönlichen Status setzen.")
async def status_setzen_cmd(interaction: discord.Interaction, status: str):
    await profiles_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$set": {"status": status}}, upsert=True)
    await interaction.response.send_message(f"✅ Status gesetzt: *{status}*", ephemeral=True)

# ══════════════════════════════════════════════════════════════
# AFK SYSTEM
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="afk", description="AFK setzen.")
async def afk_cmd(interaction: discord.Interaction, grund: str = "AFK"):
    await afk_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$set": {"grund": grund, "ts": datetime.utcnow()}}, upsert=True)
    await interaction.response.send_message(f"💤 AFK gesetzt: *{grund}*")

# ══════════════════════════════════════════════════════════════
# REMINDERS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="remindme", description="Erinnerung setzen.")
async def remindme_cmd(interaction: discord.Interaction, zeit: str, nachricht: str):
    match = re.match(r'(\d+)(m|h|d)', zeit.lower())
    if not match: await interaction.response.send_message("❌ Format: 10m, 2h, 1d"); return
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
    await reminders_col.insert_one({"user_id": interaction.user.id, "channel_id": interaction.channel_id, "nachricht": nachricht, "remind_at": datetime.utcnow() + delta, "done": False})
    await interaction.response.send_message(f"⏰ Erinnerung in **{zeit}**: *{nachricht}*", ephemeral=True)

@tasks.loop(minutes=1)
async def reminder_loop():
    reminders = await reminders_col.find({"done": False, "remind_at": {"$lte": datetime.utcnow()}}).to_list(50)
    for r in reminders:
        try:
            ch = bot.get_channel(r["channel_id"])
            user = await bot.fetch_user(r["user_id"])
            if ch: await ch.send(f"⏰ {user.mention} Erinnerung: **{r['nachricht']}**")
            await reminders_col.update_one({"_id": r["_id"]}, {"$set": {"done": True}})
        except: pass

# ══════════════════════════════════════════════════════════════
# ECONOMY
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="eco-balance", description="Kontostand anzeigen.")
async def balance_cmd(interaction: discord.Interaction, user: discord.Member = None):
    await interaction.response.defer()
    ziel = user or interaction.user
    eco = await hole_eco(interaction.guild_id, ziel.id)
    e = discord.Embed(title=f"💰 {ziel.display_name}", color=discord.Color.gold())
    e.add_field(name="👛 Wallet", value=f"{eco.get('coins', 0)} Coins", inline=True)
    e.add_field(name="🏦 Bank", value=f"{eco.get('bank', 0)} Coins", inline=True)
    e.add_field(name="💎 Gesamt", value=f"{eco.get('coins', 0) + eco.get('bank', 0)} Coins", inline=True)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="eco-daily", description="Tägliche Coins abholen.")
async def daily_eco_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    now = datetime.utcnow()
    last = eco.get("last_daily")
    if last:
        diff = now - (last if isinstance(last, datetime) else datetime.fromisoformat(str(last)))
        if diff < timedelta(hours=20):
            warte = timedelta(hours=20) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await interaction.followup.send(f"⏰ Warte noch **{h}h {r//60}m**!"); return
        streak = eco.get("streak", 0) + 1 if diff < timedelta(hours=48) else 1
    else: streak = 1
    amount = 200 + (streak * 10)
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": amount}, "$set": {"last_daily": now, "streak": streak}})
    e = discord.Embed(title="💰 Daily!", description=f"+**{amount} Coins** | 🔥 Streak: **{streak}**", color=discord.Color.gold())
    await interaction.followup.send(embed=e)

@bot.tree.command(name="eco-work", description="Arbeiten gehen.")
async def work_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    now = datetime.utcnow()
    last = eco.get("last_work")
    if last:
        diff = now - (last if isinstance(last, datetime) else datetime.fromisoformat(str(last)))
        if diff < timedelta(hours=4):
            warte = timedelta(hours=4) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await interaction.followup.send(f"⏰ Warte noch **{h}h {r//60}m**!"); return
    jobs = ["Pizza geliefert 🍕", "Code geschrieben 💻", "Rocket League gespielt 🚗", "Stream moderiert 🎮", "Designs erstellt 🎨"]
    amount = random.randint(50, 150)
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": amount}, "$set": {"last_work": now}})
    await interaction.followup.send(f"💼 {random.choice(jobs)} → **+{amount} Coins**")

@bot.tree.command(name="eco-fish", description="Angeln gehen.")
async def fish_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    now = datetime.utcnow()
    last = eco.get("last_fish")
    if last:
        diff = now - (last if isinstance(last, datetime) else datetime.fromisoformat(str(last)))
        if diff < timedelta(hours=2):
            warte = timedelta(hours=2) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await interaction.followup.send(f"⏰ Warte noch **{h}h {r//60}m**!"); return
    fische = [("🦐 Garnele", 10), ("🐟 Fisch", 30), ("🐠 Tropenfisch", 50), ("🐡 Kugelfisch", 70), ("🦈 Hai", 200), ("👢 Stiefel", 0), ("🗑️ Müll", 0)]
    fisch, wert = random.choice(fische)
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": wert}, "$set": {"last_fish": now}})
    msg = f"🎣 Du hast **{fisch}** gefangen!" + (f" → **+{wert} Coins**" if wert > 0 else " → Leider nichts wert.")
    await interaction.followup.send(msg)

@bot.tree.command(name="eco-mine", description="Schürfen gehen.")
async def mine_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    now = datetime.utcnow()
    last = eco.get("last_mine")
    if last:
        diff = now - (last if isinstance(last, datetime) else datetime.fromisoformat(str(last)))
        if diff < timedelta(hours=2):
            warte = timedelta(hours=2) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await interaction.followup.send(f"⏰ Warte noch **{h}h {r//60}m**!"); return
    mineralien = [("🪨 Stein", 5), ("⛏️ Kohle", 20), ("🪙 Kupfer", 40), ("🔩 Eisen", 60), ("💎 Diamant", 300), ("🥇 Gold", 150)]
    mineral, wert = random.choice(mineralien)
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": wert}, "$set": {"last_mine": now}})
    await interaction.followup.send(f"⛏️ Du hast **{mineral}** gefunden! → **+{wert} Coins**")

@bot.tree.command(name="eco-gamble", description="Coins setzen.")
async def gamble_cmd(interaction: discord.Interaction, menge: int):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    if eco.get("coins", 0) < menge:
        await interaction.followup.send("❌ Nicht genug Coins!"); return
    if random.random() > 0.5:
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": menge}})
        await interaction.followup.send(f"🎰 Gewonnen! **+{menge} Coins**")
    else:
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": -menge}})
        await interaction.followup.send(f"🎰 Verloren! **-{menge} Coins**")

@bot.tree.command(name="eco-rob", description="Versuche Coins zu stehlen.")
async def rob_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    if user.id == interaction.user.id:
        await interaction.followup.send("❌ Du kannst dich nicht selbst ausrauben!"); return
    victim = await hole_eco(interaction.guild_id, user.id)
    robber = await hole_eco(interaction.guild_id, interaction.user.id)
    if victim.get("coins", 0) < 100:
        await interaction.followup.send("❌ Das Opfer hat zu wenig Coins!"); return
    if random.random() > 0.4:
        steal = random.randint(50, min(500, victim["coins"]))
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": user.id}, {"$inc": {"coins": -steal}})
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": steal}})
        await interaction.followup.send(f"🦹 Erfolgreich! Du hast **{steal} Coins** von {user.mention} gestohlen!")
    else:
        fine = random.randint(100, 300)
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": -fine}})
        await interaction.followup.send(f"👮 Erwischt! Du zahlst **{fine} Coins** Strafe.")

@bot.tree.command(name="eco-pay", description="Coins transferieren.")
async def pay_cmd(interaction: discord.Interaction, user: discord.Member, menge: int):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    if eco.get("coins", 0) < menge:
        await interaction.followup.send("❌ Nicht genug Coins!"); return
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": -menge}})
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": user.id}, {"$inc": {"coins": menge}}, upsert=True)
    await interaction.followup.send(f"✅ **{menge} Coins** an {user.mention} überwiesen!")

@bot.tree.command(name="eco-leaderboard", description="Reichste User.")
async def eco_lb_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    top = await economy_col.find({"guild_id": interaction.guild_id}).sort("coins", -1).limit(10).to_list(10)
    medals = ["🥇","🥈","🥉"]
    e = discord.Embed(title="💰 Reichste User", color=discord.Color.gold())
    desc = ""
    for i, u in enumerate(top):
        try: member = await bot.fetch_user(u["user_id"]); name = member.display_name
        except: name = f"User {u['user_id']}"
        prefix = medals[i] if i < 3 else f"**{i+1}.**"
        desc += f"{prefix} {name} — {u.get('coins', 0)} Coins\n"
    e.description = desc or "Keine Daten."
    await interaction.followup.send(embed=e)

@bot.tree.command(name="eco-slots", description="Slot Machine spielen.")
async def slots_cmd(interaction: discord.Interaction, einsatz: int):
    await interaction.response.defer()
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    if eco.get("coins", 0) < einsatz:
        await interaction.followup.send("❌ Nicht genug Coins!"); return
    symbole = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
    result = [random.choice(symbole) for _ in range(3)]
    if result[0] == result[1] == result[2]:
        if result[0] == "💎": gewinn = einsatz * 10
        elif result[0] == "7️⃣": gewinn = einsatz * 7
        elif result[0] == "⭐": gewinn = einsatz * 5
        else: gewinn = einsatz * 3
        msg = f"🎰 {''.join(result)}\n🎉 JACKPOT! **+{gewinn} Coins**"
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": gewinn}})
    elif result[0] == result[1] or result[1] == result[2]:
        gewinn = einsatz
        msg = f"🎰 {''.join(result)}\n✅ Zwei gleiche! **+{gewinn} Coins**"
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": gewinn}})
    else:
        msg = f"🎰 {''.join(result)}\n❌ Verloren! **-{einsatz} Coins**"
        await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": -einsatz}})
    await interaction.followup.send(msg)

@bot.tree.command(name="eco-shop", description="Shop anzeigen.")
async def shop_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    cfg = await hole_config(interaction.guild_id)
    items = cfg.get("shop", [])
    if not items: await interaction.followup.send("❌ Shop ist leer."); return
    e = discord.Embed(title="🛒 Shop", color=discord.Color.green())
    for item in items:
        e.add_field(name=f"{item['name']} – {item['price']} Coins", value=item.get("description", "Kein Beschreibung"), inline=False)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="eco-buy", description="Item kaufen.")
async def buy_cmd(interaction: discord.Interaction, item_name: str):
    await interaction.response.defer()
    cfg = await hole_config(interaction.guild_id)
    item = next((i for i in cfg.get("shop", []) if i["name"].lower() == item_name.lower()), None)
    if not item: await interaction.followup.send("❌ Item nicht gefunden."); return
    eco = await hole_eco(interaction.guild_id, interaction.user.id)
    if eco.get("coins", 0) < item["price"]:
        await interaction.followup.send("❌ Nicht genug Coins!"); return
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$inc": {"coins": -item["price"]}, "$push": {"inventory": item["name"]}})
    if item.get("role_id"):
        role = interaction.guild.get_role(int(item["role_id"]))
        if role:
            try: await interaction.user.add_roles(role)
            except: pass
    await interaction.followup.send(f"✅ **{item['name']}** gekauft!")

@bot.tree.command(name="eco-rep", description="Reputation geben.")
async def rep_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    if user.id == interaction.user.id:
        await interaction.followup.send("❌ Du kannst dir selbst keine Rep geben!"); return
    giver = await hole_eco(interaction.guild_id, interaction.user.id)
    now = datetime.utcnow()
    last_rep = giver.get("last_rep")
    if last_rep:
        diff = now - (last_rep if isinstance(last_rep, datetime) else datetime.fromisoformat(str(last_rep)))
        if diff < timedelta(hours=24):
            warte = timedelta(hours=24) - diff
            h, r = divmod(int(warte.total_seconds()), 3600)
            await interaction.followup.send(f"⏰ Warte noch **{h}h {r//60}m**!"); return
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": user.id}, {"$inc": {"rep": 1}}, upsert=True)
    await economy_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$set": {"last_rep": now}})
    await interaction.followup.send(f"⭐ {user.mention} hat eine Reputation erhalten!")

# ══════════════════════════════════════════════════════════════
# GIVEAWAYS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="giveaway-start", description="[Admin] Giveaway starten.")
@is_admin()
async def giveaway_start_cmd(interaction: discord.Interaction, preis: str, dauer: str, gewinner: int = 1, rolle: discord.Role = None):
    await interaction.response.defer()
    match = re.match(r'(\d+)(m|h|d)', dauer.lower())
    if not match: await interaction.followup.send("❌ Format: 10m, 2h, 1d"); return
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
    ends_at = datetime.utcnow() + delta
    e = discord.Embed(title="🎉 GIVEAWAY", description=f"**Preis:** {preis}\n**Gewinner:** {gewinner}\n**Endet:** <t:{int(ends_at.timestamp())}:R>\n\nReagiere mit 🎉 um teilzunehmen!", color=discord.Color.gold())
    if rolle: e.add_field(name="Benötigte Rolle", value=rolle.mention)
    msg = await interaction.channel.send(embed=e)
    await msg.add_reaction("🎉")
    await giveaway_col.insert_one({"guild_id": interaction.guild_id, "channel_id": interaction.channel_id, "message_id": msg.id, "preis": preis, "gewinner": gewinner, "rolle_id": rolle.id if rolle else None, "ends_at": ends_at, "active": True})
    await interaction.followup.send("✅ Giveaway gestartet!", ephemeral=True)

@bot.tree.command(name="giveaway-reroll", description="[Admin] Neuen Gewinner ziehen.")
@is_admin()
async def giveaway_reroll_cmd(interaction: discord.Interaction, message_id: str):
    await interaction.response.defer()
    gw = await giveaway_col.find_one({"message_id": int(message_id)})
    if not gw: await interaction.followup.send("❌ Giveaway nicht gefunden."); return
    ch = interaction.guild.get_channel(gw["channel_id"])
    msg = await ch.fetch_message(gw["message_id"])
    reaction = discord.utils.get(msg.reactions, emoji="🎉")
    users = [u async for u in reaction.users() if not u.bot]
    if not users: await interaction.followup.send("❌ Keine Teilnehmer."); return
    winner = random.choice(users)
    await interaction.followup.send(f"🎉 Neuer Gewinner: {winner.mention} gewinnt **{gw['preis']}**!")

@tasks.loop(minutes=1)
async def giveaway_loop():
    active = await giveaway_col.find({"active": True, "ends_at": {"$lte": datetime.utcnow()}}).to_list(20)
    for gw in active:
        try:
            guild = bot.get_guild(gw["guild_id"])
            ch = guild.get_channel(gw["channel_id"])
            msg = await ch.fetch_message(gw["message_id"])
            reaction = discord.utils.get(msg.reactions, emoji="🎉")
            users = [u async for u in reaction.users() if not u.bot]
            if gw.get("rolle_id"):
                rolle = guild.get_role(gw["rolle_id"])
                if rolle: users = [u for u in users if rolle in guild.get_member(u.id).roles]
            winners = random.sample(users, min(gw["gewinner"], len(users))) if users else []
            e = discord.Embed(title="🎉 Giveaway Beendet!", description=f"**Preis:** {gw['preis']}\n**Gewinner:** {', '.join(w.mention for w in winners) if winners else 'Niemand'}", color=discord.Color.green())
            await msg.edit(embed=e)
            if winners: await ch.send(f"🎉 Glückwunsch {', '.join(w.mention for w in winners)}! Ihr gewinnt **{gw['preis']}**!")
            await giveaway_col.update_one({"_id": gw["_id"]}, {"$set": {"active": False}})
        except Exception as ex:
            print(f"❌ Giveaway Fehler: {ex}")

# ══════════════════════════════════════════════════════════════
# SUGGESTIONS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="suggest", description="Vorschlag einreichen.")
async def suggest_cmd(interaction: discord.Interaction, vorschlag: str):
    await interaction.response.defer(ephemeral=True)
    cfg = await hole_config(interaction.guild_id)
    ch_id = cfg.get("suggest_channel")
    if not ch_id: await interaction.followup.send("❌ Suggest-Kanal nicht konfiguriert!"); return
    ch = interaction.guild.get_channel(int(ch_id))
    e = discord.Embed(title="💡 Neuer Vorschlag", description=vorschlag, color=discord.Color.blurple())
    e.set_footer(text=f"von {interaction.user.display_name}")
    msg = await ch.send(embed=e)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    await suggest_col.insert_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id, "vorschlag": vorschlag, "message_id": msg.id, "status": "offen", "ts": datetime.utcnow()})
    await interaction.followup.send("✅ Vorschlag eingereicht!")

@bot.tree.command(name="suggest-accept", description="[Admin] Vorschlag annehmen.")
@is_admin()
async def suggest_accept_cmd(interaction: discord.Interaction, message_id: str, grund: str = ""):
    await interaction.response.defer()
    sug = await suggest_col.find_one({"message_id": int(message_id)})
    if not sug: await interaction.followup.send("❌ Vorschlag nicht gefunden."); return
    cfg = await hole_config(interaction.guild_id)
    ch = interaction.guild.get_channel(int(cfg.get("suggest_channel", 0)))
    if ch:
        try:
            msg = await ch.fetch_message(int(message_id))
            e = discord.Embed(title="✅ Vorschlag angenommen", description=sug["vorschlag"], color=discord.Color.green())
            if grund: e.add_field(name="Grund", value=grund)
            await msg.edit(embed=e)
        except: pass
    await suggest_col.update_one({"_id": sug["_id"]}, {"$set": {"status": "angenommen"}})
    await interaction.followup.send("✅ Vorschlag angenommen!")

@bot.tree.command(name="suggest-deny", description="[Admin] Vorschlag ablehnen.")
@is_admin()
async def suggest_deny_cmd(interaction: discord.Interaction, message_id: str, grund: str = ""):
    await interaction.response.defer()
    sug = await suggest_col.find_one({"message_id": int(message_id)})
    if not sug: await interaction.followup.send("❌ Vorschlag nicht gefunden."); return
    cfg = await hole_config(interaction.guild_id)
    ch = interaction.guild.get_channel(int(cfg.get("suggest_channel", 0)))
    if ch:
        try:
            msg = await ch.fetch_message(int(message_id))
            e = discord.Embed(title="❌ Vorschlag abgelehnt", description=sug["vorschlag"], color=discord.Color.red())
            if grund: e.add_field(name="Grund", value=grund)
            await msg.edit(embed=e)
        except: pass
    await suggest_col.update_one({"_id": sug["_id"]}, {"$set": {"status": "abgelehnt"}})
    await interaction.followup.send("✅ Vorschlag abgelehnt!")

# ══════════════════════════════════════════════════════════════
# BIRTHDAY SYSTEM
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="geburtstag", description="Geburtstag eintragen.")
async def birthday_cmd(interaction: discord.Interaction, datum: str):
    try:
        datetime.strptime(datum, "%d.%m")
        await birthday_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$set": {"datum": datum}}, upsert=True)
        await interaction.response.send_message(f"🎂 Geburtstag eingetragen: **{datum}**", ephemeral=True)
    except: await interaction.response.send_message("❌ Format: DD.MM", ephemeral=True)

@tasks.loop(hours=24)
async def birthday_loop():
    today = datetime.utcnow().strftime("%d.%m")
    birthdays = await birthday_col.find({"datum": today}).to_list(100)
    for b in birthdays:
        guild = bot.get_guild(b["guild_id"])
        if not guild: continue
        cfg = await hole_config(b["guild_id"])
        ch_id = cfg.get("birthday_channel")
        if not ch_id: continue
        ch = guild.get_channel(int(ch_id))
        if not ch: continue
        member = guild.get_member(b["user_id"])
        if not member: continue
        e = discord.Embed(title="🎂 Herzlichen Glückwunsch!", description=f"{member.mention} hat heute Geburtstag! 🎉", color=discord.Color.pink())
        await ch.send(embed=e)

# ══════════════════════════════════════════════════════════════
# TICKET SYSTEM
# ══════════════════════════════════════════════════════════════
class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ticket erstellen", style=discord.ButtonStyle.primary, custom_id="create_ticket")
    async def create_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cfg = await hole_config(interaction.guild_id)
        existing = discord.utils.get(interaction.guild.channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing: await interaction.followup.send(f"Bereits offen: {existing.mention}", ephemeral=True); return
        cat = interaction.guild.get_channel(int(cfg["ticket_category"])) if cfg.get("ticket_category") else None
        overwrites = {interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)}
        if cfg.get("ticket_team_role"):
            r = interaction.guild.get_role(int(cfg["ticket_team_role"]))
            if r: overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        ch = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name.lower()}", category=cat, overwrites=overwrites)
        await tickets_col.insert_one({"guild_id": interaction.guild_id, "channel_id": ch.id, "user_id": interaction.user.id, "open": True, "created_at": datetime.utcnow()})
        e = discord.Embed(title="🎫 Ticket geöffnet", description=f"Hallo {interaction.user.mention}! Schreib dein Anliegen.", color=discord.Color.green())
        await ch.send(embed=e, view=CloseTicketView())
        await interaction.followup.send(f"✅ {ch.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Schließen", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await tickets_col.update_one({"channel_id": interaction.channel_id}, {"$set": {"open": False}})
        await interaction.channel.send("🔒 Wird in 5s gelöscht...")
        await asyncio.sleep(5)
        await interaction.channel.delete()

@bot.tree.command(name="ticket-setup", description="[Admin] Ticket-Panel erstellen.")
@is_admin()
async def ticket_setup_cmd(interaction: discord.Interaction, titel: str = "Support", beschreibung: str = "Klicke um ein Ticket zu öffnen."):
    e = discord.Embed(title=f"🎫 {titel}", description=beschreibung, color=discord.Color.blurple())
    await interaction.channel.send(embed=e, view=TicketView())
    await interaction.response.send_message("✅ Ticket-Panel erstellt!", ephemeral=True)

# ══════════════════════════════════════════════════════════════
# VERIFY
# ══════════════════════════════════════════════════════════════
class VerifyView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="✅ Verifizieren", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await hole_config(interaction.guild_id)
        role = interaction.guild.get_role(int(cfg.get("verify_role", 0)))
        if not role: await interaction.response.send_message("❌ Keine Rolle!", ephemeral=True); return
        if role in interaction.user.roles: await interaction.response.send_message("✅ Bereits verifiziert!", ephemeral=True); return
        await interaction.user.add_roles(role)
        await interaction.response.send_message("✅ Verifiziert!", ephemeral=True)

@bot.tree.command(name="verify-setup", description="[Admin] Verifizierungs-Panel.")
@is_admin()
async def verify_setup_cmd(interaction: discord.Interaction, rolle: discord.Role):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"verify_role": rolle.id}}, upsert=True)
    e = discord.Embed(title="✅ Verifizierung", description="Klicke den Button um dich zu verifizieren.", color=discord.Color.green())
    await interaction.channel.send(embed=e, view=VerifyView())
    await interaction.response.send_message("✅ Panel erstellt!", ephemeral=True)

# ══════════════════════════════════════════════════════════════
# TEAM & BEWERBUNGEN
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="team-add", description="[Admin] User zum Team hinzufügen.")
@is_admin()
async def team_add_cmd(interaction: discord.Interaction, user: discord.Member, rolle: str = "Moderator"):
    await team_col.update_one({"guild_id": interaction.guild_id, "user_id": user.id}, {"$set": {"guild_id": interaction.guild_id, "user_id": user.id, "rolle": rolle, "joined": datetime.utcnow(), "aktiv": True}}, upsert=True)
    await interaction.response.send_message(f"✅ {user.mention} → **{rolle}**")

@bot.tree.command(name="team-remove", description="[Admin] User aus Team entfernen.")
@is_admin()
async def team_remove_cmd(interaction: discord.Interaction, user: discord.Member):
    await team_col.delete_one({"guild_id": interaction.guild_id, "user_id": user.id})
    await interaction.response.send_message(f"✅ {user.mention} entfernt.")

@bot.tree.command(name="team", description="Team anzeigen.")
async def team_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    members = await team_col.find({"guild_id": interaction.guild_id, "aktiv": True}).to_list(50)
    e = discord.Embed(title="👥 Team", color=discord.Color.blurple())
    if not members: e.description = "Kein Team."
    else:
        for m in members:
            user = interaction.guild.get_member(m["user_id"])
            e.add_field(name=m.get("rolle", "Mitglied"), value=user.mention if user else str(m["user_id"]), inline=True)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="abmelden", description="Abwesenheit eintragen.")
async def abmelden_cmd(interaction: discord.Interaction, von: str, bis: str, grund: str = "Kein Grund"):
    m = await team_col.find_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id})
    if not m: await interaction.response.send_message("❌ Du bist kein Team-Mitglied!", ephemeral=True); return
    await team_col.update_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id}, {"$push": {"abmeldungen": {"von": von, "bis": bis, "grund": grund, "ts": datetime.utcnow()}}})
    await interaction.response.send_message(f"✅ Abmeldung: **{von}** bis **{bis}** – {grund}", ephemeral=True)

@bot.tree.command(name="bewerben", description="Fürs Team bewerben.")
async def bewerben_cmd(interaction: discord.Interaction, alter: str, erfahrung: str, warum: str, verfuegbarkeit: str):
    await interaction.response.defer(ephemeral=True)
    existing = await apps_col.find_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id, "status": "offen"})
    if existing: await interaction.followup.send("❌ Du hast bereits eine offene Bewerbung!"); return
    await apps_col.insert_one({"guild_id": interaction.guild_id, "user_id": interaction.user.id, "alter": alter, "erfahrung": erfahrung, "warum": warum, "verfuegbarkeit": verfuegbarkeit, "status": "offen", "ts": datetime.utcnow()})
    cfg = await hole_config(interaction.guild_id)
    if cfg.get("mod_log"):
        ch = interaction.guild.get_channel(int(cfg["mod_log"]))
        if ch:
            e = discord.Embed(title="📝 Neue Bewerbung", color=discord.Color.blurple())
            e.add_field(name="User", value=interaction.user.mention)
            e.add_field(name="Alter", value=alter)
            e.add_field(name="Erfahrung", value=erfahrung, inline=False)
            e.add_field(name="Warum", value=warum, inline=False)
            e.add_field(name="Verfügbarkeit", value=verfuegbarkeit)
            await ch.send(embed=e)
    await interaction.followup.send("✅ Bewerbung eingereicht!")

@bot.tree.command(name="bewerbungen", description="[Admin] Bewerbungen anzeigen.")
@is_admin()
async def bewerbungen_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    apps = await apps_col.find({"guild_id": interaction.guild_id, "status": "offen"}).to_list(20)
    if not apps: await interaction.followup.send("Keine offenen Bewerbungen."); return
    e = discord.Embed(title="📝 Bewerbungen", color=discord.Color.blurple())
    for a in apps:
        user = interaction.guild.get_member(a["user_id"])
        e.add_field(name=str(user) if user else str(a["user_id"]), value=f"Alter: {a['alter']}\nVerfügbar: {a['verfuegbarkeit']}", inline=True)
    await interaction.followup.send(embed=e)

@bot.tree.command(name="bewerbung-accept", description="[Admin] Bewerbung annehmen.")
@is_admin()
async def bewerbung_accept_cmd(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    app = await apps_col.find_one({"guild_id": interaction.guild_id, "user_id": user.id, "status": "offen"})
    if not app: await interaction.followup.send("❌ Keine offene Bewerbung."); return
    await apps_col.update_one({"_id": app["_id"]}, {"$set": {"status": "angenommen"}})
    try: await user.send(f"🎉 Deine Bewerbung auf **{interaction.guild.name}** wurde angenommen!")
    except: pass
    await interaction.followup.send(f"✅ Bewerbung von {user.mention} angenommen!")

@bot.tree.command(name="bewerbung-deny", description="[Admin] Bewerbung ablehnen.")
@is_admin()
async def bewerbung_deny_cmd(interaction: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
    await interaction.response.defer()
    app = await apps_col.find_one({"guild_id": interaction.guild_id, "user_id": user.id, "status": "offen"})
    if not app: await interaction.followup.send("❌ Keine offene Bewerbung."); return
    await apps_col.update_one({"_id": app["_id"]}, {"$set": {"status": "abgelehnt"}})
    try: await user.send(f"❌ Deine Bewerbung auf **{interaction.guild.name}** wurde abgelehnt.\nGrund: {grund}")
    except: pass
    await interaction.followup.send(f"✅ Bewerbung abgelehnt.")

# ══════════════════════════════════════════════════════════════
# RL TEAMS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="rl-team-erstellen", description="RL Team erstellen.")
async def rl_team_create_cmd(interaction: discord.Interaction, name: str, format: str = "3v3"):
    await interaction.response.defer()
    existing = await rl_teams_col.find_one({"guild_id": interaction.guild_id, "captain_id": interaction.user.id})
    if existing: await interaction.followup.send("❌ Du hast bereits ein Team!"); return
    await rl_teams_col.insert_one({"guild_id": interaction.guild_id, "name": name, "format": format, "captain_id": interaction.user.id, "members": [interaction.user.id], "wins": 0, "losses": 0, "created": datetime.utcnow()})
    await interaction.followup.send(f"✅ Team **{name}** ({format}) erstellt!")

@bot.tree.command(name="rl-team-join", description="RL Team beitreten.")
async def rl_team_join_cmd(interaction: discord.Interaction, team_name: str):
    await interaction.response.defer()
    team = await rl_teams_col.find_one({"guild_id": interaction.guild_id, "name": team_name})
    if not team: await interaction.followup.send("❌ Team nicht gefunden."); return
    if interaction.user.id in team["members"]: await interaction.followup.send("❌ Du bist bereits im Team!"); return
    await rl_teams_col.update_one({"_id": team["_id"]}, {"$push": {"members": interaction.user.id}})
    await interaction.followup.send(f"✅ Team **{team_name}** beigetreten!")

@bot.tree.command(name="rl-teams", description="Alle RL Teams anzeigen.")
async def rl_teams_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    teams = await rl_teams_col.find({"guild_id": interaction.guild_id}).to_list(20)
    if not teams: await interaction.followup.send("Keine Teams."); return
    e = discord.Embed(title="🚗 RL Teams", color=discord.Color.orange())
    for t in teams:
        captain = interaction.guild.get_member(t["captain_id"])
        e.add_field(name=f"{t['name']} ({t['format']})", value=f"Captain: {captain.mention if captain else '?'}\nMember: {len(t['members'])} | W/L: {t['wins']}/{t['losses']}", inline=False)
    await interaction.followup.send(embed=e)

# ══════════════════════════════════════════════════════════════
# CUSTOM COMMANDS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="cmd-add", description="[Admin] Custom Command erstellen.")
@is_admin()
async def cmd_add(interaction: discord.Interaction, trigger: str, antwort: str):
    await custom_cmd_col.update_one({"guild_id": interaction.guild_id, "trigger": trigger.lower()}, {"$set": {"response": antwort}}, upsert=True)
    await interaction.response.send_message(f"✅ Command `{trigger}` erstellt!")

@bot.tree.command(name="cmd-remove", description="[Admin] Custom Command entfernen.")
@is_admin()
async def cmd_remove(interaction: discord.Interaction, trigger: str):
    await custom_cmd_col.delete_one({"guild_id": interaction.guild_id, "trigger": trigger.lower()})
    await interaction.response.send_message(f"✅ Command `{trigger}` entfernt!")

@bot.tree.command(name="cmd-list", description="Alle Custom Commands anzeigen.")
async def cmd_list(interaction: discord.Interaction):
    await interaction.response.defer()
    cmds = await custom_cmd_col.find({"guild_id": interaction.guild_id}).to_list(50)
    if not cmds: await interaction.followup.send("Keine Custom Commands."); return
    e = discord.Embed(title="⚙️ Custom Commands", color=discord.Color.blurple())
    e.description = "\n".join(f"`{c['trigger']}` → {c['response'][:50]}" for c in cmds)
    await interaction.followup.send(embed=e)

# ══════════════════════════════════════════════════════════════
# RSS SYSTEM
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="rss-add", description="[Admin] RSS Feed hinzufügen.")
@is_admin()
async def rss_add_cmd(interaction: discord.Interaction, name: str, url: str, kanal: discord.TextChannel):
    await interaction.response.defer()
    import feedparser
    parsed = feedparser.parse(url)
    if not parsed.entries: await interaction.followup.send("❌ Ungültiger RSS Feed!"); return
    await rss_col.insert_one({"guild_id": interaction.guild_id, "name": name, "url": url, "channel_id": kanal.id, "aktiv": True, "added": datetime.utcnow()})
    await interaction.followup.send(f"✅ RSS **{name}** → {kanal.mention}")

@bot.tree.command(name="rss-remove", description="[Admin] RSS Feed entfernen.")
@is_admin()
async def rss_remove_cmd(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    r = await rss_col.delete_one({"guild_id": interaction.guild_id, "name": name})
    await interaction.followup.send(f"✅ Feed **{name}** entfernt." if r.deleted_count else "❌ Nicht gefunden.")

@bot.tree.command(name="rss-list", description="RSS Feeds anzeigen.")
async def rss_list_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    feeds = await rss_col.find({"guild_id": interaction.guild_id}).to_list(20)
    if not feeds: await interaction.followup.send("Keine Feeds."); return
    e = discord.Embed(title="📰 RSS Feeds", color=discord.Color.blurple())
    for f in feeds:
        ch = interaction.guild.get_channel(f["channel_id"])
        e.add_field(name=f"{'✅' if f.get('aktiv') else '⏸️'} {f['name']}", value=f"Kanal: {ch.mention if ch else '?'}", inline=False)
    await interaction.followup.send(embed=e)

@tasks.loop(minutes=10)
async def rss_check_loop():
    import feedparser
    feeds = await rss_col.find({"aktiv": True}).to_list(50)
    for feed in feeds:
        try:
            parsed = feedparser.parse(feed["url"])
            guild = bot.get_guild(feed["guild_id"])
            if not guild: continue
            ch = guild.get_channel(feed["channel_id"])
            if not ch: continue
            for entry in parsed.entries[:3]:
                link = entry.get("link", "")
                if not link: continue
                if await rss_seen_col.find_one({"feed_id": str(feed["_id"]), "link": link}): continue
                e = discord.Embed(title=entry.get("title", "")[:250], url=link, description=entry.get("summary", "")[:300], color=discord.Color.blurple())
                e.set_footer(text=f"📰 {feed.get('name', 'RSS')}")
                await ch.send(embed=e)
                await rss_seen_col.insert_one({"feed_id": str(feed["_id"]), "link": link, "ts": datetime.utcnow()})
        except Exception as ex:
            print(f"❌ RSS Fehler: {ex}")

# ══════════════════════════════════════════════════════════════
# TWITCH / YOUTUBE NOTIFICATIONS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="notif-twitch", description="[Admin] Twitch Notification einrichten.")
@is_admin()
async def notif_twitch_cmd(interaction: discord.Interaction, streamer: str, kanal: discord.TextChannel, nachricht: str = "{streamer} ist jetzt live! 🎮"):
    await notif_col.update_one({"guild_id": interaction.guild_id, "type": "twitch", "name": streamer.lower()}, {"$set": {"channel_id": kanal.id, "message": nachricht, "live": False}}, upsert=True)
    await interaction.response.send_message(f"✅ Twitch Notification für **{streamer}** → {kanal.mention}")

@bot.tree.command(name="notif-youtube", description="[Admin] YouTube Notification einrichten.")
@is_admin()
async def notif_youtube_cmd(interaction: discord.Interaction, channel_id: str, kanal: discord.TextChannel):
    await notif_col.update_one({"guild_id": interaction.guild_id, "type": "youtube", "name": channel_id}, {"$set": {"channel_id": kanal.id}}, upsert=True)
    await interaction.response.send_message(f"✅ YouTube Notification eingerichtet → {kanal.mention}")

@tasks.loop(minutes=5)
async def twitch_check_loop():
    client_id = os.getenv("TWITCH_CLIENT_ID")
    client_secret = os.getenv("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret: return
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://id.twitch.tv/oauth2/token", params={"client_id": client_id, "client_secret": client_secret, "grant_type": "client_credentials"}) as r:
                token_data = await r.json()
            token = token_data.get("access_token")
            if not token: return
            streamers = await notif_col.find({"type": "twitch"}).to_list(50)
            for streamer in streamers:
                async with s.get(f"https://api.twitch.tv/helix/streams?user_login={streamer['name']}", headers={"Client-ID": client_id, "Authorization": f"Bearer {token}"}) as r:
                    data = await r.json()
                is_live = len(data.get("data", [])) > 0
                was_live = streamer.get("live", False)
                if is_live and not was_live:
                    guild = bot.get_guild(streamer["guild_id"])
                    if guild:
                        ch = guild.get_channel(streamer["channel_id"])
                        if ch:
                            stream = data["data"][0]
                            msg = streamer.get("message", "{streamer} ist live!").replace("{streamer}", streamer["name"])
                            e = discord.Embed(title=stream.get("title", "Live!"), url=f"https://twitch.tv/{streamer['name']}", color=discord.Color.purple())
                            e.add_field(name="Spiel", value=stream.get("game_name", "?"))
                            e.add_field(name="Zuschauer", value=str(stream.get("viewer_count", 0)))
                            await ch.send(msg, embed=e)
                await notif_col.update_one({"_id": streamer["_id"]}, {"$set": {"live": is_live}})
    except Exception as ex:
        print(f"❌ Twitch Check Fehler: {ex}")

# ══════════════════════════════════════════════════════════════
# STAT CHANNELS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="stat-channel", description="[Admin] Statistik-Kanal einrichten.")
@is_admin()
async def stat_channel_cmd(interaction: discord.Interaction, kanal: discord.VoiceChannel, typ: str):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {f"stat_channels.{typ}": kanal.id}}, upsert=True)
    await interaction.response.send_message(f"✅ Stat-Kanal ({typ}) → {kanal.mention}")

@tasks.loop(minutes=10)
async def stat_channel_loop():
    configs = await config_col.find({"stat_channels": {"$exists": True, "$ne": {}}}).to_list(50)
    for cfg in configs:
        guild = bot.get_guild(cfg["guild_id"])
        if not guild: continue
        for typ, ch_id in cfg.get("stat_channels", {}).items():
            ch = guild.get_channel(int(ch_id))
            if not ch: continue
            try:
                if typ == "members": await ch.edit(name=f"👥 Member: {guild.member_count}")
                elif typ == "bots": await ch.edit(name=f"🤖 Bots: {sum(1 for m in guild.members if m.bot)}")
                elif typ == "roles": await ch.edit(name=f"🎭 Rollen: {len(guild.roles)}")
                elif typ == "channels": await ch.edit(name=f"💬 Kanäle: {len(guild.channels)}")
            except: pass

# ══════════════════════════════════════════════════════════════
# SETUP COMMANDS
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="setup-welcome", description="[Admin] Willkommen einrichten.")
@is_admin()
async def setup_welcome_cmd(interaction: discord.Interaction, kanal: discord.TextChannel, nachricht: str = "Willkommen {user} auf {server}! 🎉"):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"welcome_channel": kanal.id, "welcome_msg": nachricht}}, upsert=True)
    await interaction.response.send_message(f"✅ Willkommen → {kanal.mention}")

@bot.tree.command(name="setup-goodbye", description="[Admin] Abschied einrichten.")
@is_admin()
async def setup_goodbye_cmd(interaction: discord.Interaction, kanal: discord.TextChannel, nachricht: str = "{user} hat den Server verlassen."):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"goodbye_channel": kanal.id, "goodbye_msg": nachricht}}, upsert=True)
    await interaction.response.send_message(f"✅ Abschied → {kanal.mention}")

@bot.tree.command(name="setup-autorole", description="[Admin] Auto-Rolle einrichten.")
@is_admin()
async def setup_autorole_cmd(interaction: discord.Interaction, rolle: discord.Role):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"auto_role": rolle.id}}, upsert=True)
    await interaction.response.send_message(f"✅ Auto-Rolle: {rolle.mention}")

@bot.tree.command(name="setup-modlog", description="[Admin] Mod-Log Kanal.")
@is_admin()
async def setup_modlog_cmd(interaction: discord.Interaction, kanal: discord.TextChannel):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"mod_log": kanal.id}}, upsert=True)
    await interaction.response.send_message(f"✅ Mod-Log → {kanal.mention}")

@bot.tree.command(name="setup-automod", description="[Admin] Auto-Mod einrichten.")
@is_admin()
async def setup_automod_cmd(interaction: discord.Interaction, aktiviert: bool, spam: bool = True, links: bool = False, caps: bool = False, mention_limit: int = 5):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"automod": {"enabled": aktiviert, "spam": spam, "links": links, "caps": caps, "bad_words": [], "mention_limit": mention_limit}}}, upsert=True)
    await interaction.response.send_message(f"✅ Auto-Mod {'aktiviert' if aktiviert else 'deaktiviert'}.")

@bot.tree.command(name="setup-starboard", description="[Admin] Starboard einrichten.")
@is_admin()
async def setup_starboard_cmd(interaction: discord.Interaction, kanal: discord.TextChannel, min_sterne: int = 3):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"starboard_channel": kanal.id, "starboard_min": min_sterne}}, upsert=True)
    await interaction.response.send_message(f"✅ Starboard → {kanal.mention} (min. {min_sterne} ⭐)")

@bot.tree.command(name="setup-suggest", description="[Admin] Suggest-Kanal einrichten.")
@is_admin()
async def setup_suggest_cmd(interaction: discord.Interaction, kanal: discord.TextChannel):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"suggest_channel": kanal.id}}, upsert=True)
    await interaction.response.send_message(f"✅ Suggest-Kanal → {kanal.mention}")

@bot.tree.command(name="setup-birthday", description="[Admin] Geburtstags-Kanal einrichten.")
@is_admin()
async def setup_birthday_cmd(interaction: discord.Interaction, kanal: discord.TextChannel):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"birthday_channel": kanal.id}}, upsert=True)
    await interaction.response.send_message(f"✅ Geburtstags-Kanal → {kanal.mention}")

@bot.tree.command(name="setup-bot-status", description="[Admin] Bot Status setzen.")
@is_admin()
async def setup_bot_status_cmd(interaction: discord.Interaction, status: str):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$set": {"custom_bot_status": status}}, upsert=True)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
    await interaction.response.send_message(f"✅ Bot Status: **{status}**")

@bot.tree.command(name="badword-add", description="[Admin] Verbotenes Wort hinzufügen.")
@is_admin()
async def badword_add_cmd(interaction: discord.Interaction, wort: str):
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$addToSet": {"automod.bad_words": wort.lower()}}, upsert=True)
    await interaction.response.send_message(f"✅ `{wort}` zur Blacklist.", ephemeral=True)

@bot.tree.command(name="eco-shop-add", description="[Admin] Shop Item hinzufügen.")
@is_admin()
async def shop_add_cmd(interaction: discord.Interaction, name: str, preis: int, beschreibung: str = "", rolle: discord.Role = None):
    item = {"name": name, "price": preis, "description": beschreibung}
    if rolle: item["role_id"] = str(rolle.id)
    await config_col.update_one({"guild_id": interaction.guild_id}, {"$push": {"shop": item}}, upsert=True)
    await interaction.response.send_message(f"✅ **{name}** für {preis} Coins zum Shop hinzugefügt!")

# ══════════════════════════════════════════════════════════════
# PREFIX COMMANDS
# ══════════════════════════════════════════════════════════════
@bot.command(name="mute")
@commands.has_permissions(kick_members=True)
async def mute_prefix(ctx, user: discord.Member, minuten: int = 10, *, grund: str = "Kein Grund"):
    until = discord.utils.utcnow() + timedelta(minutes=minuten)
    if hasattr(user, 'timeout'):
        await user.timeout(until, reason=grund)
    await ctx.send(f"⏰ {user.mention} für **{minuten} Min** gemutet. Grund: {grund}")

@bot.command(name="unmute")
@commands.has_permissions(kick_members=True)
async def unmute_prefix(ctx, user: discord.Member):
    await user.timeout(None)
    await ctx.send(f"✅ {user.mention} entmutet.")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear_prefix(ctx, anzahl: int = 10):
    deleted = await ctx.channel.purge(limit=min(anzahl + 1, 101))
    await ctx.send(f"✅ {len(deleted)-1} Nachrichten gelöscht.", delete_after=3)

# ══════════════════════════════════════════════════════════════
# HELP
# ══════════════════════════════════════════════════════════════
@bot.tree.command(name="help", description="Alle Commands.")
async def help_cmd(interaction: discord.Interaction):
    e = discord.Embed(title="📖 RLD Main Bot", color=discord.Color.blurple())
    e.add_field(name="🛡️ Mod", value="`/ban` `/main-kick` `/main-timeout` `/main-warn` `/main-warns` `/main-clear` `/main-slowmode` `/main-lock` `/main-case` `/main-raid-mode`", inline=False)
    e.add_field(name="ℹ️ Info", value="`/userinfo` `/main-serverinfo` `/main-avatar` `/main-ping` `/main-timestamp`", inline=False)
    e.add_field(name="🎮 Fun", value="`/8ball` `/main-coinflip` `/main-würfel` `/main-rps` `/main-quote` `/main-fact` `/main-gif` `/main-poll` `/main-calc` `/main-meme`", inline=False)
    e.add_field(name="💰 Economy", value="`/eco-balance` `/eco-daily` `/eco-work` `/eco-fish` `/eco-mine` `/eco-gamble` `/eco-rob` `/eco-pay` `/eco-slots` `/eco-shop` `/eco-buy` `/eco-rep` `/eco-leaderboard`", inline=False)
    e.add_field(name="🎉 Giveaway", value="`/giveaway-start` `/giveaway-reroll`", inline=False)
    e.add_field(name="💡 Suggestions", value="`/suggest` `/main-suggest-accept` `/main-suggest-deny`", inline=False)
    e.add_field(name="🎂 Geburtstag", value="`/main-geburtstag`", inline=False)
    e.add_field(name="💤 AFK", value="`/afk` `/main-remindme`", inline=False)
    e.add_field(name="🎫 Ticket", value="`/ticket-setup`", inline=False)
    e.add_field(name="✅ Verify", value="`/verify-setup`", inline=False)
    e.add_field(name="👥 Team", value="`/team` `/team-add` `/team-remove` `/main-abmelden` `/main-bewerben` `/main-bewerbungen` `/main-bewerbung-accept` `/main-bewerbung-deny`", inline=False)
    e.add_field(name="🚗 RL Teams", value="`/rl-team-erstellen` `/rl-team-join` `/rl-teams`", inline=False)
    e.add_field(name="📰 RSS", value="`/rss-add` `/rss-remove` `/rss-list`", inline=False)
    e.add_field(name="📣 Notifications", value="`/notif-twitch` `/notif-youtube`", inline=False)
    e.add_field(name="⚙️ Setup", value="`/setup-welcome` `/setup-goodbye` `/setup-autorole` `/setup-modlog` `/setup-automod` `/setup-starboard` `/setup-suggest` `/setup-birthday` `/setup-bot-status` `/stat-channel` `/badword-add` `/eco-shop-add` `/cmd-add` `/cmd-remove`", inline=False)
    e.set_footer(text="RLD Main Bot • Made by Rezyel83 with AI")
    await interaction.response.send_message(embed=e)

# ══════════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════════
async def main():
    token = os.getenv("DISCORD_TOKEN")
    if not token: raise ValueError("DISCORD_TOKEN fehlt!")
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())
    bot.add_view(VerifyView())
    threading.Thread(target=starte_webserver, daemon=True).start()
    async with bot:
        await bot.start(token)

if __name__ == "__main__":
    asyncio.run(main())