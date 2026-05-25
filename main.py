"""
Renthol – Combined Bot + Dashboard
Single-process: Flask (WSGI thread) + discord.py (asyncio)
Resource priority: minimal DB connections, aggressive caching, no polling waste
"""

import os, asyncio, threading, time, random, re, json, ast, operator
import logging
from datetime import datetime, timedelta
from functools import wraps, lru_cache
from urllib.parse import quote
from collections import deque, defaultdict
from typing import Optional

# ── Env ───────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN        = os.getenv("DISCORD_TOKEN", "")
DISCORD_CLIENT_ID    = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET= os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_BOT_TOKEN    = os.getenv("DISCORD_BOT_TOKEN", "")          # same token, used by dashboard API calls
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:5000/callback")
MONGODB_URI          = os.getenv("MONGODB_URI", "")
MONGODB_DB           = os.getenv("MONGODB_DB", "rld_main")
SECRET_KEY           = os.getenv("SECRET_KEY", "")
RENDER_URL           = os.getenv("RENDER_EXTERNAL_URL", "")
PORT                 = int(os.getenv("PORT", "10000"))

TWITCH_CLIENT_ID     = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY env var must be set!")
if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN env var must be set!")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI env var must be set!")

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("renthol")
log.setLevel(logging.INFO)

# ═════════════════════════════════════════════════════════════
# MONGODB  (motor – async, single shared client)
# ═════════════════════════════════════════════════════════════
from motor.motor_asyncio import AsyncIOMotorClient

_mongo_client: Optional[AsyncIOMotorClient] = None

def get_mongo() -> AsyncIOMotorClient:
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(
            MONGODB_URI,
            maxPoolSize=5,          # keep pool tiny for free tier
            minPoolSize=0,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )
    return _mongo_client

def db():
    return get_mongo()[MONGODB_DB]

# Collection shortcuts
def col(name: str):
    return db()[name]

# ── Config Cache (TTL 60 s, max 50 guilds in memory) ─────────
_config_cache: dict[int, tuple[dict, float]] = {}
_CONFIG_TTL = 60  # seconds

async def hole_config(gid: Optional[int]) -> dict:
    if not gid:
        return {}
    now = time.monotonic()
    if gid in _config_cache:
        doc, ts = _config_cache[gid]
        if now - ts < _CONFIG_TTL:
            return doc
    document = await col("config").find_one({"guild_id": gid})
    if not document:
        document = _default_config(gid)
        await col("config").insert_one(document)
    # evict oldest if cache too big
    if len(_config_cache) >= 50:
        oldest = min(_config_cache, key=lambda k: _config_cache[k][1])
        del _config_cache[oldest]
    _config_cache[gid] = (document, now)
    return document

def invalidate_config(gid: int):
    _config_cache.pop(gid, None)

def _default_config(gid: int) -> dict:
    return {
        "guild_id": gid, "prefix": "!",
        "mod_log": None, "welcome_channel": None,
        "welcome_msg": "Willkommen {user} auf {server}! 🎉",
        "goodbye_channel": None, "goodbye_msg": "{user} hat den Server verlassen.",
        "auto_role": None, "verify_role": None,
        "ticket_category": None, "ticket_log": None, "ticket_team_role": None,
        "starboard_channel": None, "starboard_min": 3,
        "suggest_channel": None,
        "bump_channel": None, "birthday_channel": None,
        "automod": {
            "enabled": False, "spam": True, "links": False,
            "caps": False, "bad_words": [], "mention_limit": 5,
        },
        "anti_raid": False, "welcome_dm": False,
        "stat_channels": {}, "coin_multiplier_roles": {},
        "shop": [], "perm_presets": {},
        "custom_bot_status": None, "slow_joiner_minutes": 0,
    }

# ── Economy helpers ───────────────────────────────────────────
async def hole_eco(gid: int, uid: int) -> dict:
    doc = await col("economy").find_one({"guild_id": gid, "user_id": uid})
    if not doc:
        doc = {
            "guild_id": gid, "user_id": uid,
            "coins": 0, "bank": 0,
            "last_daily": None, "last_work": None,
            "last_fish": None, "last_mine": None,
            "streak": 0, "inventory": [], "rep": 0, "last_rep": None,
        }
        await col("economy").insert_one(doc)
    return doc

async def add_coins(gid: int, uid: int, amount: int):
    await col("economy").update_one(
        {"guild_id": gid, "user_id": uid},
        {"$inc": {"coins": amount}},
        upsert=True,
    )

# ── Mod-log helper ────────────────────────────────────────────
async def log_aktion(guild_id, mod_id, target_id, aktion, grund) -> int:
    case_num = await col("cases").count_documents({"guild_id": guild_id}) + 1
    now = datetime.utcnow()
    entry = {
        "guild_id": guild_id, "case": case_num,
        "mod_id": mod_id, "target_id": target_id,
        "aktion": aktion, "grund": grund, "ts": now,
    }
    await col("cases").insert_one(entry)
    await col("logs").insert_one(entry.copy())
    return case_num

# Safe math eval (no exec/import abuse)
_SAFE_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.UAdd: operator.pos, ast.USub: operator.neg,
}

def safe_eval(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Unsupported")
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op:
                raise ValueError("Unsupported op")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op:
                raise ValueError("Unsupported op")
            return op(_eval(node.operand))
        raise ValueError("Unsupported node")
    return _eval(tree)

# ═════════════════════════════════════════════════════════════
# DISCORD BOT
# ═════════════════════════════════════════════════════════════
import discord
from discord.ext import commands, tasks
from discord import app_commands

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
start_time = datetime.utcnow()

# Anti-raid: thread-safe deque
recent_joins: deque = deque(maxlen=20)
# Spam tracker: {guild:user -> [timestamps]}
spam_tracker: dict = defaultdict(list)
# Coin cooldown per-message: {guild:user -> last_coin_ts}
coin_cooldown: dict = {}

# ── Permission checks ─────────────────────────────────────────
def is_mod():
    async def pred(i: discord.Interaction):
        return i.user.guild_permissions.kick_members or i.user.guild_permissions.administrator
    return app_commands.check(pred)

def is_admin():
    async def pred(i: discord.Interaction):
        return i.user.guild_permissions.administrator
    return app_commands.check(pred)

async def _mod_log(guild: discord.Guild, embed: discord.Embed):
    cfg = await hole_config(guild.id)
    if cfg.get("mod_log"):
        ch = guild.get_channel(int(cfg["mod_log"]))
        if ch:
            try:
                await ch.send(embed=embed)
            except Exception:
                pass

# ── Events ────────────────────────────────────────────────────
@bot.event
async def on_ready():
    log.info(f"Bot online: {bot.user}")
    try:
        synced = await bot.tree.sync()
        log.info(f"Synced {len(synced)} slash commands")
    except Exception as e:
        log.error(f"Sync error: {e}")
    # Start loops
    reminder_loop.start()
    rss_check_loop.start()
    birthday_loop.start()
    stat_channel_loop.start()
    giveaway_loop.start()
    twitch_check_loop.start()
    asyncio.ensure_future(keep_alive_loop())
    # Set presence
    cfg_all = await col("config").find({}, {"custom_bot_status": 1}).to_list(50)
    for cfg in cfg_all:
        if cfg.get("custom_bot_status"):
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name=cfg["custom_bot_status"],
                )
            )
            return
    total = sum((g.member_count or 0) for g in bot.guilds)
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{total} Member | /help",
        )
    )

@bot.event
async def on_member_join(member: discord.Member):
    cfg = await hole_config(member.guild.id)
    # Slow joiner
    slow_min = cfg.get("slow_joiner_minutes", 0)
    if slow_min > 0:
        age_min = (datetime.utcnow() - member.created_at.replace(tzinfo=None)).total_seconds() / 60
        if age_min < slow_min:
            try:
                await member.send(f"Dein Account ist zu neu. Komm in {slow_min} Minuten wieder.")
                await member.kick(reason="Account zu neu (Slow Joiner)")
            except Exception:
                pass
            return
    # Anti-raid
    if cfg.get("anti_raid"):
        now = time.time()
        recent_joins.append(now)
        window = [t for t in recent_joins if now - t < 10]
        if len(window) >= 10:
            try:
                await member.kick(reason="Anti-Raid")
            except Exception:
                pass
            return
    # Auto-role
    if cfg.get("auto_role"):
        role = member.guild.get_role(int(cfg["auto_role"]))
        if role:
            try:
                await member.add_roles(role)
            except Exception:
                pass
    # Welcome
    if cfg.get("welcome_channel"):
        ch = member.guild.get_channel(int(cfg["welcome_channel"]))
        if ch:
            msg = (
                cfg.get("welcome_msg", "Willkommen {user}!")
                .replace("{user}", member.mention)
                .replace("{server}", member.guild.name)
                .replace("{count}", str(member.guild.member_count))
            )
            e = discord.Embed(description=msg, color=discord.Color.green())
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)
    # Welcome DM
    if cfg.get("welcome_dm"):
        try:
            await member.send(
                embed=discord.Embed(
                    title=f"Willkommen auf {member.guild.name}!",
                    description=cfg.get("welcome_msg", "").replace("{user}", member.display_name),
                    color=discord.Color.blurple(),
                )
            )
        except Exception:
            pass

@bot.event
async def on_member_remove(member: discord.Member):
    cfg = await hole_config(member.guild.id)
    if cfg.get("goodbye_channel"):
        ch = member.guild.get_channel(int(cfg["goodbye_channel"]))
        if ch:
            msg = (
                cfg.get("goodbye_msg", "{user} hat den Server verlassen.")
                .replace("{user}", str(member))
                .replace("{server}", member.guild.name)
            )
            e = discord.Embed(description=msg, color=discord.Color.red())
            e.set_thumbnail(url=member.display_avatar.url)
            await ch.send(embed=e)

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or not msg.guild:
        return
    cfg = await hole_config(msg.guild.id)

    # AFK removal
    afk = await col("afk").find_one({"guild_id": msg.guild.id, "user_id": msg.author.id})
    if afk:
        await col("afk").delete_one({"_id": afk["_id"]})
        try:
            await msg.channel.send(f"👋 Willkommen zurück {msg.author.mention}!", delete_after=5)
        except Exception:
            pass

    # Mention → AFK info
    for mention in msg.mentions[:3]:  # cap at 3 to avoid spam
        afk_user = await col("afk").find_one({"guild_id": msg.guild.id, "user_id": mention.id})
        if afk_user:
            try:
                await msg.channel.send(
                    f"💤 **{mention.display_name}** ist AFK: {afk_user.get('grund','Kein Grund')}",
                    delete_after=10,
                )
            except Exception:
                pass

    # Custom commands
    trigger = msg.content.lower().split()[0] if msg.content else ""
    if trigger:
        custom = await col("custom_commands").find_one({"guild_id": msg.guild.id, "trigger": trigger})
        if custom:
            await msg.channel.send(custom["response"])

    # Coins per message – 30 s cooldown to prevent farming
    ck = (msg.guild.id, msg.author.id)
    now = time.monotonic()
    if now - coin_cooldown.get(ck, 0) >= 30:
        coin_cooldown[ck] = now
        await add_coins(msg.guild.id, msg.author.id, 1)
        # evict old cooldown entries periodically
        if len(coin_cooldown) > 2000:
            oldest = min(coin_cooldown, key=coin_cooldown.get)
            del coin_cooldown[oldest]

    # AutoMod
    automod = cfg.get("automod", {})
    if automod.get("enabled") and not msg.author.guild_permissions.manage_messages:
        # Bad words
        for word in automod.get("bad_words", []):
            if word.lower() in msg.content.lower():
                try:
                    await msg.delete()
                    await msg.channel.send(f"{msg.author.mention} Verbotenes Wort!", delete_after=5)
                except Exception:
                    pass
                return
        # ALL-CAPS
        if automod.get("caps") and len(msg.content) > 10:
            upper = sum(1 for c in msg.content if c.isupper())
            if upper / len(msg.content) > 0.7:
                try:
                    await msg.delete()
                    await msg.channel.send(f"{msg.author.mention} Bitte keine Großbuchstaben!", delete_after=5)
                except Exception:
                    pass
                return
        # Links
        if automod.get("links") and re.search(r"https?://|discord\.gg/", msg.content):
            try:
                await msg.delete()
                await msg.channel.send(f"{msg.author.mention} Links nicht erlaubt!", delete_after=5)
            except Exception:
                pass
            return
        # Mention spam
        if len(msg.mentions) >= automod.get("mention_limit", 5):
            try:
                await msg.delete()
                if hasattr(msg.author, "timeout"):
                    await msg.author.timeout(
                        discord.utils.utcnow() + timedelta(minutes=5), reason="Mention Spam"
                    )
                await msg.channel.send(f"{msg.author.mention} Mention Spam! 5 Min Timeout.", delete_after=5)
            except Exception:
                pass
            return
        # Spam detection
        key = f"{msg.guild.id}:{msg.author.id}"
        t_now = time.time()
        spam_tracker[key] = [t for t in spam_tracker[key] if t_now - t < 5]
        spam_tracker[key].append(t_now)
        if len(spam_tracker[key]) >= 5:
            try:
                if hasattr(msg.author, "timeout"):
                    await msg.author.timeout(
                        discord.utils.utcnow() + timedelta(minutes=2), reason="Spam"
                    )
                await msg.channel.send(f"{msg.author.mention} Spam! 2 Min Timeout.", delete_after=5)
            except Exception:
                pass

    await bot.process_commands(msg)

@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    if user.bot or not reaction.message.guild:
        return
    cfg = await hole_config(reaction.message.guild.id)
    sb_id = cfg.get("starboard_channel")
    if sb_id and str(reaction.emoji) == "⭐" and reaction.count >= cfg.get("starboard_min", 3):
        sb_ch = reaction.message.guild.get_channel(int(sb_id))
        if sb_ch:
            existing = await col("starboard").find_one({"message_id": reaction.message.id})
            if not existing:
                e = discord.Embed(description=reaction.message.content, color=discord.Color.gold())
                e.set_author(
                    name=reaction.message.author.display_name,
                    icon_url=reaction.message.author.display_avatar.url,
                )
                e.add_field(
                    name="Original",
                    value=f"[Springe zur Nachricht]({reaction.message.jump_url})",
                )
                if reaction.message.attachments:
                    e.set_image(url=reaction.message.attachments[0].url)
                sb_msg = await sb_ch.send(
                    f"⭐ **{reaction.count}** | {reaction.message.channel.mention}", embed=e
                )
                await col("starboard").insert_one(
                    {"message_id": reaction.message.id, "sb_message_id": sb_msg.id}
                )

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if after.channel and not before.channel:
        await col("voice_stats").update_one(
            {"guild_id": member.guild.id, "user_id": member.id},
            {"$set": {"join_time": time.time()}},
            upsert=True,
        )
    elif not after.channel and before.channel:
        doc = await col("voice_stats").find_one({"guild_id": member.guild.id, "user_id": member.id})
        if doc and doc.get("join_time"):
            minutes = (time.time() - doc["join_time"]) / 60
            await col("voice_stats").update_one(
                {"guild_id": member.guild.id, "user_id": member.id},
                {"$inc": {"total_minutes": minutes}, "$unset": {"join_time": ""}},
            )
            await add_coins(member.guild.id, member.id, int(minutes * 2))

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Keine Berechtigung!")
        return
    log.error(f"Command error [{ctx.command}]: {error}")

@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = "❌ Fehler!"
    if isinstance(error, app_commands.CheckFailure):
        msg = "❌ Keine Berechtigung!"
    log.error(f"Slash error [{interaction.command}]: {error}")
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass

# ═════════════════════════════════════════════════════════════
# MODERATION COMMANDS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="ban", description="Bannt einen User.")
@is_mod()
async def ban_cmd(i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund", delete_days: int = 0):
    await i.response.defer()
    if user.top_role >= i.user.top_role:
        await i.followup.send("❌ Du kannst diesen User nicht bannen!"); return
    try: await user.send(f"Du wurdest von **{i.guild.name}** gebannt.\nGrund: {grund}")
    except Exception: pass
    await i.guild.ban(user, reason=grund, delete_message_days=delete_days)
    case = await log_aktion(i.guild_id, i.user.id, user.id, "ban", grund)
    e = discord.Embed(title=f"🔨 Ban | Case #{case}", color=discord.Color.red())
    e.add_field(name="User", value=f"{user} ({user.id})", inline=True)
    e.add_field(name="Mod", value=i.user.mention, inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await i.followup.send(embed=e)
    await _mod_log(i.guild, e)

@bot.tree.command(name="unban", description="Entbannt einen User.")
@is_mod()
async def unban_cmd(i: discord.Interaction, user_id: str, grund: str = "Kein Grund"):
    await i.response.defer()
    try:
        user = await bot.fetch_user(int(user_id))
        await i.guild.unban(user, reason=grund)
        await i.followup.send(f"✅ **{user}** entbannt.")
    except Exception:
        await i.followup.send("❌ User nicht gefunden.")

@bot.tree.command(name="kick", description="Kickt einen User.")
@is_mod()
async def kick_cmd(i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
    await i.response.defer()
    if user.top_role >= i.user.top_role:
        await i.followup.send("❌ Du kannst diesen User nicht kicken!"); return
    try: await user.send(f"Du wurdest von **{i.guild.name}** gekickt.\nGrund: {grund}")
    except Exception: pass
    await user.kick(reason=grund)
    case = await log_aktion(i.guild_id, i.user.id, user.id, "kick", grund)
    e = discord.Embed(title=f"👢 Kick | Case #{case}", color=discord.Color.orange())
    e.add_field(name="User", value=str(user), inline=True)
    e.add_field(name="Mod", value=i.user.mention, inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await i.followup.send(embed=e)
    await _mod_log(i.guild, e)

@bot.tree.command(name="timeout", description="Timeout für einen User.")
@is_mod()
async def timeout_cmd(i: discord.Interaction, user: discord.Member, minuten: int, grund: str = "Kein Grund"):
    await i.response.defer()
    until = discord.utils.utcnow() + timedelta(minutes=minuten)
    await user.timeout(until, reason=grund)
    case = await log_aktion(i.guild_id, i.user.id, user.id, "timeout", grund)
    e = discord.Embed(title=f"⏰ Timeout | Case #{case}", color=discord.Color.yellow())
    e.add_field(name="User", value=user.mention, inline=True)
    e.add_field(name="Dauer", value=f"{minuten} Min", inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await i.followup.send(embed=e)
    await _mod_log(i.guild, e)

@bot.tree.command(name="untimeout", description="Timeout aufheben.")
@is_mod()
async def untimeout_cmd(i: discord.Interaction, user: discord.Member):
    await user.timeout(None)
    await i.response.send_message(f"✅ Timeout von {user.mention} aufgehoben.")

@bot.tree.command(name="warn", description="Verwarnt einen User.")
@is_mod()
async def warn_cmd(i: discord.Interaction, user: discord.Member, grund: str):
    await i.response.defer()
    await col("warns").insert_one({"guild_id": i.guild_id, "user_id": user.id, "mod_id": i.user.id, "grund": grund, "ts": datetime.utcnow()})
    count = await col("warns").count_documents({"guild_id": i.guild_id, "user_id": user.id})
    case = await log_aktion(i.guild_id, i.user.id, user.id, "warn", grund)
    try: await user.send(f"Verwarnung auf **{i.guild.name}**\nGrund: {grund}\nAnzahl: {count}")
    except Exception: pass
    e = discord.Embed(title=f"⚠️ Warn | Case #{case}", color=discord.Color.yellow())
    e.add_field(name="User", value=user.mention, inline=True)
    e.add_field(name="Anzahl", value=str(count), inline=True)
    e.add_field(name="Grund", value=grund, inline=False)
    await i.followup.send(embed=e)
    await _mod_log(i.guild, e)

@bot.tree.command(name="warns", description="Verwarnungen anzeigen.")
@is_mod()
async def warns_cmd(i: discord.Interaction, user: discord.Member):
    await i.response.defer()
    warns = await col("warns").find({"guild_id": i.guild_id, "user_id": user.id}).sort("ts", -1).to_list(20)
    e = discord.Embed(title=f"⚠️ Verwarnungen: {user.display_name}", color=discord.Color.yellow())
    if not warns:
        e.description = "Keine Verwarnungen."
    else:
        for idx, w in enumerate(warns, 1):
            mod = i.guild.get_member(w["mod_id"])
            e.add_field(
                name=f"#{idx} – {w['ts'].strftime('%d.%m.%Y')}",
                value=f"{w['grund']}\nMod: {mod.mention if mod else '?'}",
                inline=False,
            )
    await i.followup.send(embed=e)

@bot.tree.command(name="unwarn", description="Letzte Verwarnung entfernen.")
@is_mod()
async def unwarn_cmd(i: discord.Interaction, user: discord.Member):
    await i.response.defer()
    last = await col("warns").find_one({"guild_id": i.guild_id, "user_id": user.id}, sort=[("ts", -1)])
    if not last:
        await i.followup.send("❌ Keine Verwarnungen."); return
    await col("warns").delete_one({"_id": last["_id"]})
    await i.followup.send(f"✅ Letzte Verwarnung von {user.mention} entfernt.")

@bot.tree.command(name="clearwarns", description="[Admin] Alle Verwarnungen löschen.")
@is_admin()
async def clearwarns_cmd(i: discord.Interaction, user: discord.Member):
    await i.response.defer()
    r = await col("warns").delete_many({"guild_id": i.guild_id, "user_id": user.id})
    await i.followup.send(f"✅ {r.deleted_count} Verwarnungen gelöscht.")

@bot.tree.command(name="case", description="Case Details anzeigen.")
@is_mod()
async def case_cmd(i: discord.Interaction, nummer: int):
    await i.response.defer()
    case = await col("cases").find_one({"guild_id": i.guild_id, "case": nummer})
    if not case:
        await i.followup.send("❌ Case nicht gefunden."); return
    mod = i.guild.get_member(case["mod_id"])
    target = i.guild.get_member(case["target_id"])
    e = discord.Embed(title=f"📋 Case #{nummer}", color=discord.Color.blurple())
    e.add_field(name="Aktion", value=case["aktion"], inline=True)
    e.add_field(name="User", value=str(target) if target else str(case["target_id"]), inline=True)
    e.add_field(name="Mod", value=mod.mention if mod else str(case["mod_id"]), inline=True)
    e.add_field(name="Grund", value=case["grund"], inline=False)
    e.add_field(name="Datum", value=case["ts"].strftime("%d.%m.%Y %H:%M"), inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="clear", description="Nachrichten löschen.")
@is_mod()
async def clear_cmd(i: discord.Interaction, anzahl: int, user: Optional[discord.Member] = None):
    await i.response.defer(ephemeral=True)
    check = (lambda m: m.author == user) if user else None
    deleted = await i.channel.purge(limit=min(anzahl, 100), check=check)
    await i.followup.send(f"✅ {len(deleted)} Nachrichten gelöscht.", ephemeral=True)

@bot.tree.command(name="slowmode", description="Slowmode setzen.")
@is_mod()
async def slowmode_cmd(i: discord.Interaction, sekunden: int):
    await i.channel.edit(slowmode_delay=sekunden)
    await i.response.send_message(f"✅ Slowmode: **{sekunden}s**")

@bot.tree.command(name="lock", description="Kanal sperren.")
@is_mod()
async def lock_cmd(i: discord.Interaction):
    await i.channel.set_permissions(i.guild.default_role, send_messages=False)
    await i.response.send_message("🔒 Kanal gesperrt.")

@bot.tree.command(name="unlock", description="Kanal entsperren.")
@is_mod()
async def unlock_cmd(i: discord.Interaction):
    await i.channel.set_permissions(i.guild.default_role, send_messages=True)
    await i.response.send_message("🔓 Kanal entsperrt.")

@bot.tree.command(name="raid-mode", description="[Admin] Raid Mode an/aus.")
@is_admin()
async def raid_mode_cmd(i: discord.Interaction, aktiv: bool):
    await col("config").update_one({"guild_id": i.guild_id}, {"$set": {"anti_raid": aktiv}}, upsert=True)
    invalidate_config(i.guild_id)
    await i.response.send_message(f"{'🚨 Raid Mode AKTIVIERT' if aktiv else '✅ Raid Mode deaktiviert'}")

# ═════════════════════════════════════════════════════════════
# INFO COMMANDS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="userinfo", description="User Informationen.")
async def userinfo_cmd(i: discord.Interaction, user: discord.Member = None):
    await i.response.defer()
    u = user or i.user
    warns_count = await col("warns").count_documents({"guild_id": i.guild_id, "user_id": u.id})
    eco = await hole_eco(i.guild_id, u.id)
    e = discord.Embed(title=f"👤 {u.display_name}", color=u.color)
    e.set_thumbnail(url=u.display_avatar.url)
    e.add_field(name="ID", value=str(u.id), inline=True)
    e.add_field(name="Erstellt", value=u.created_at.strftime("%d.%m.%Y"), inline=True)
    e.add_field(name="Beigetreten", value=u.joined_at.strftime("%d.%m.%Y") if u.joined_at else "?", inline=True)
    e.add_field(name="Rollen", value=" ".join(r.mention for r in u.roles[1:]) or "Keine", inline=False)
    e.add_field(name="⚠️ Warns", value=str(warns_count), inline=True)
    e.add_field(name="💰 Coins", value=str(eco.get("coins", 0)), inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="serverinfo", description="Server Informationen.")
async def serverinfo_cmd(i: discord.Interaction):
    await i.response.defer()
    g = i.guild
    e = discord.Embed(title=f"🏠 {g.name}", color=discord.Color.blurple())
    if g.icon:
        e.set_thumbnail(url=g.icon.url)
    e.add_field(name="ID", value=str(g.id), inline=True)
    e.add_field(name="Owner", value=str(g.owner), inline=True)
    e.add_field(name="Erstellt", value=g.created_at.strftime("%d.%m.%Y"), inline=True)
    e.add_field(name="👥 Member", value=str(g.member_count), inline=True)
    e.add_field(name="💬 Kanäle", value=str(len(g.channels)), inline=True)
    e.add_field(name="🎭 Rollen", value=str(len(g.roles)), inline=True)
    e.add_field(name="Boost Level", value=str(g.premium_tier), inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="avatar", description="Avatar anzeigen.")
async def avatar_cmd(i: discord.Interaction, user: Optional[discord.Member] = None):
    u = user or i.user
    e = discord.Embed(title=f"🖼️ {u.display_name}", color=discord.Color.blurple())
    e.set_image(url=u.display_avatar.url)
    await i.response.send_message(embed=e)

@bot.tree.command(name="ping", description="Bot Latenz.")
async def ping_cmd(i: discord.Interaction):
    uptime = datetime.utcnow() - start_time
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    await i.response.send_message(f"🏓 **{round(bot.latency*1000)}ms** | Uptime: {h}h {m}m {s}s")

@bot.tree.command(name="timestamp", description="Discord Timestamp erstellen.")
async def timestamp_cmd(i: discord.Interaction, datum: str, uhrzeit: str = "00:00"):
    try:
        dt = datetime.strptime(f"{datum} {uhrzeit}", "%d.%m.%Y %H:%M")
        ts = int(dt.timestamp())
        e = discord.Embed(title="🕐 Timestamp", color=discord.Color.blurple())
        for label, fmt in [("Kurze Zeit","t"),("Lange Zeit","T"),("Datum","d"),("Datum+Zeit","f"),("Relativ","R")]:
            e.add_field(name=label, value=f"`<t:{ts}:{fmt}>` → <t:{ts}:{fmt}>", inline=False)
        await i.response.send_message(embed=e)
    except Exception:
        await i.response.send_message("❌ Format: DD.MM.YYYY und HH:MM")

# ═════════════════════════════════════════════════════════════
# FUN
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="8ball", description="Stelle eine Frage!")
async def ball_cmd(i: discord.Interaction, frage: str):
    answers = ["Ja!","Definitiv ja!","Sehr wahrscheinlich.","Vielleicht.","Eher nicht.","Definitiv nein!","Frag später nochmal.","Ohne Zweifel!","Unmöglich."]
    e = discord.Embed(title="🎱 8Ball", color=discord.Color.purple())
    e.add_field(name="❓ Frage", value=frage, inline=False)
    e.add_field(name="🎱 Antwort", value=random.choice(answers), inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="coinflip", description="Münze werfen.")
async def coinflip_cmd(i: discord.Interaction):
    await i.response.send_message(f"🪙 **{random.choice(['Kopf 👑', 'Zahl 🔢'])}**")

@bot.tree.command(name="wuerfel", description="Würfel werfen.")
async def wuerfel_cmd(i: discord.Interaction, anzahl: int = 1, seiten: int = 6):
    anzahl = min(max(anzahl, 1), 10)
    results = [random.randint(1, max(seiten, 2)) for _ in range(anzahl)]
    e = discord.Embed(title="🎲 Würfel", color=discord.Color.green())
    e.add_field(name="Ergebnisse", value=" | ".join(str(r) for r in results))
    e.add_field(name="Summe", value=str(sum(results)))
    await i.response.send_message(embed=e)

@bot.tree.command(name="rps", description="Schere Stein Papier.")
async def rps_cmd(i: discord.Interaction, wahl: str):
    opts = ["schere", "stein", "papier"]
    wahl = wahl.lower()
    if wahl not in opts:
        await i.response.send_message("❌ Wähle: schere, stein, papier!"); return
    bot_w = random.choice(opts)
    emojis = {"schere": "✂️", "stein": "🪨", "papier": "📄"}
    wins = {("schere","papier"),("stein","schere"),("papier","stein")}
    result = "🎉 Du gewinnst!" if (wahl,bot_w) in wins else ("🤝 Unentschieden!" if wahl==bot_w else "😔 Bot gewinnt!")
    e = discord.Embed(title="✂️🪨📄 RPS", color=discord.Color.blurple())
    e.add_field(name="Du", value=emojis[wahl], inline=True)
    e.add_field(name="Bot", value=emojis[bot_w], inline=True)
    e.add_field(name="Ergebnis", value=result, inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="poll", description="Abstimmung erstellen.")
async def poll_cmd(i: discord.Interaction, frage: str, option1: str, option2: str, option3: str = None, option4: str = None):
    opts = [o for o in [option1, option2, option3, option4] if o]
    emojis = ["1️⃣","2️⃣","3️⃣","4️⃣"]
    e = discord.Embed(title=f"📊 {frage}", description="\n".join(f"{emojis[n]} {o}" for n,o in enumerate(opts)), color=discord.Color.blurple())
    e.set_footer(text=f"von {i.user.display_name}")
    await i.response.send_message(embed=e)
    msg = await i.original_response()
    for n in range(len(opts)):
        await msg.add_reaction(emojis[n])

@bot.tree.command(name="calc", description="Rechnung ausführen.")
async def calc_cmd(i: discord.Interaction, rechnung: str):
    try:
        result = safe_eval(rechnung.replace("^", "**"))
        await i.response.send_message(f"🧮 `{rechnung}` = **{result}**")
    except Exception:
        await i.response.send_message("❌ Ungültige Rechnung! Erlaubt: + - * / ** % //")

@bot.tree.command(name="quote", description="Inspirierendes Zitat.")
async def quote_cmd(i: discord.Interaction):
    await i.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://zenquotes.io/api/random", timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
        e = discord.Embed(description=f'*"{data[0]["q"]}"*\n\n— **{data[0]["a"]}**', color=discord.Color.gold())
        await i.followup.send(embed=e)
    except Exception:
        await i.followup.send("❌ Fehler beim Laden.")

@bot.tree.command(name="meme", description="Zufälliges Meme.")
async def meme_cmd(i: discord.Interaction):
    await i.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme", timeout=aiohttp.ClientTimeout(total=8)) as r:
                data = await r.json()
        e = discord.Embed(title=data.get("title","Meme")[:250], color=discord.Color.random())
        e.set_image(url=data.get("url"))
        e.set_footer(text=f"r/{data.get('subreddit','?')}")
        await i.followup.send(embed=e)
    except Exception:
        await i.followup.send("❌ Kein Meme geladen.")

# ═════════════════════════════════════════════════════════════
# AFK
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="afk", description="AFK setzen.")
async def afk_cmd(i: discord.Interaction, grund: str = "AFK"):
    await col("afk").update_one(
        {"guild_id": i.guild_id, "user_id": i.user.id},
        {"$set": {"grund": grund, "ts": datetime.utcnow()}},
        upsert=True,
    )
    await i.response.send_message(f"💤 AFK gesetzt: *{grund}*")

# ═════════════════════════════════════════════════════════════
# REMINDERS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="remindme", description="Erinnerung setzen.")
async def remindme_cmd(i: discord.Interaction, zeit: str, nachricht: str):
    match = re.match(r"(\d+)(m|h|d)", zeit.lower())
    if not match:
        await i.response.send_message("❌ Format: 10m, 2h, 1d"); return
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
    await col("reminders").insert_one({
        "user_id": i.user.id, "channel_id": i.channel_id,
        "nachricht": nachricht, "remind_at": datetime.utcnow() + delta, "done": False,
    })
    await i.response.send_message(f"⏰ Erinnerung in **{zeit}**: *{nachricht}*", ephemeral=True)

@tasks.loop(minutes=1)
async def reminder_loop():
    due = await col("reminders").find({"done": False, "remind_at": {"$lte": datetime.utcnow()}}).to_list(30)
    for r in due:
        try:
            ch = bot.get_channel(r["channel_id"])
            user = await bot.fetch_user(r["user_id"])
            if ch:
                await ch.send(f"⏰ {user.mention} Erinnerung: **{r['nachricht']}**")
            await col("reminders").update_one({"_id": r["_id"]}, {"$set": {"done": True}})
        except Exception:
            pass

# ═════════════════════════════════════════════════════════════
# ECONOMY
# ═════════════════════════════════════════════════════════════
def _cooldown_check(last, hours: float) -> Optional[str]:
    """Returns wait string if on cooldown, else None."""
    if not last:
        return None
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    diff = datetime.utcnow() - last
    wait = timedelta(hours=hours) - diff
    if wait.total_seconds() > 0:
        h, rem = divmod(int(wait.total_seconds()), 3600)
        return f"{h}h {rem//60}m"
    return None

@bot.tree.command(name="eco-balance", description="Kontostand anzeigen.")
async def balance_cmd(i: discord.Interaction, user: discord.Member = None):
    await i.response.defer()
    ziel = user or i.user
    eco = await hole_eco(i.guild_id, ziel.id)
    e = discord.Embed(title=f"💰 {ziel.display_name}", color=discord.Color.gold())
    e.add_field(name="👛 Wallet", value=f"{eco.get('coins',0)} Coins", inline=True)
    e.add_field(name="🏦 Bank", value=f"{eco.get('bank',0)} Coins", inline=True)
    e.add_field(name="💎 Gesamt", value=f"{eco.get('coins',0)+eco.get('bank',0)} Coins", inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="eco-daily", description="Tägliche Coins abholen.")
async def daily_cmd(i: discord.Interaction):
    await i.response.defer()
    eco = await hole_eco(i.guild_id, i.user.id)
    wait = _cooldown_check(eco.get("last_daily"), 20)
    if wait:
        await i.followup.send(f"⏰ Warte noch **{wait}**!"); return
    last = eco.get("last_daily")
    streak = eco.get("streak", 0)
    if last:
        diff = datetime.utcnow() - (last if isinstance(last, datetime) else datetime.fromisoformat(str(last)))
        streak = streak + 1 if diff < timedelta(hours=48) else 1
    else:
        streak = 1
    amount = 200 + streak * 10
    await col("economy").update_one(
        {"guild_id": i.guild_id, "user_id": i.user.id},
        {"$inc": {"coins": amount}, "$set": {"last_daily": datetime.utcnow(), "streak": streak}},
    )
    e = discord.Embed(title="💰 Daily!", description=f"+**{amount} Coins** | 🔥 Streak: **{streak}**", color=discord.Color.gold())
    await i.followup.send(embed=e)

@bot.tree.command(name="eco-work", description="Arbeiten gehen.")
async def work_cmd(i: discord.Interaction):
    await i.response.defer()
    eco = await hole_eco(i.guild_id, i.user.id)
    wait = _cooldown_check(eco.get("last_work"), 4)
    if wait:
        await i.followup.send(f"⏰ Warte noch **{wait}**!"); return
    jobs = ["Pizza geliefert 🍕","Code geschrieben 💻","Rocket League gespielt 🚗","Stream moderiert 🎮","Designs erstellt 🎨"]
    amount = random.randint(50, 150)
    await col("economy").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$inc": {"coins": amount}, "$set": {"last_work": datetime.utcnow()}})
    await i.followup.send(f"💼 {random.choice(jobs)} → **+{amount} Coins**")

@bot.tree.command(name="eco-fish", description="Angeln gehen.")
async def fish_cmd(i: discord.Interaction):
    await i.response.defer()
    eco = await hole_eco(i.guild_id, i.user.id)
    wait = _cooldown_check(eco.get("last_fish"), 2)
    if wait:
        await i.followup.send(f"⏰ Warte noch **{wait}**!"); return
    fische = [("🦐 Garnele",10),("🐟 Fisch",30),("🐠 Tropenfisch",50),("🐡 Kugelfisch",70),("🦈 Hai",200),("👢 Stiefel",0),("🗑️ Müll",0)]
    fisch, wert = random.choice(fische)
    await col("economy").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$inc": {"coins": wert}, "$set": {"last_fish": datetime.utcnow()}})
    msg = f"🎣 Du hast **{fisch}** gefangen!" + (f" → **+{wert} Coins**" if wert > 0 else " → Nichts wert.")
    await i.followup.send(msg)

@bot.tree.command(name="eco-mine", description="Schürfen gehen.")
async def mine_cmd(i: discord.Interaction):
    await i.response.defer()
    eco = await hole_eco(i.guild_id, i.user.id)
    wait = _cooldown_check(eco.get("last_mine"), 2)
    if wait:
        await i.followup.send(f"⏰ Warte noch **{wait}**!"); return
    mineralien = [("🪨 Stein",5),("⛏️ Kohle",20),("🪙 Kupfer",40),("🔩 Eisen",60),("💎 Diamant",300),("🥇 Gold",150)]
    mineral, wert = random.choice(mineralien)
    await col("economy").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$inc": {"coins": wert}, "$set": {"last_mine": datetime.utcnow()}})
    await i.followup.send(f"⛏️ Du hast **{mineral}** gefunden! → **+{wert} Coins**")

@bot.tree.command(name="eco-gamble", description="Coins setzen.")
async def gamble_cmd(i: discord.Interaction, menge: int):
    await i.response.defer()
    if menge <= 0:
        await i.followup.send("❌ Ungültiger Betrag!"); return
    eco = await hole_eco(i.guild_id, i.user.id)
    if eco.get("coins", 0) < menge:
        await i.followup.send("❌ Nicht genug Coins!"); return
    if random.random() > 0.5:
        await add_coins(i.guild_id, i.user.id, menge)
        await i.followup.send(f"🎰 Gewonnen! **+{menge} Coins**")
    else:
        await add_coins(i.guild_id, i.user.id, -menge)
        await i.followup.send(f"🎰 Verloren! **-{menge} Coins**")

@bot.tree.command(name="eco-rob", description="Versuche Coins zu stehlen.")
async def rob_cmd(i: discord.Interaction, user: discord.Member):
    await i.response.defer()
    if user.id == i.user.id:
        await i.followup.send("❌ Du kannst dich nicht selbst ausrauben!"); return
    victim = await hole_eco(i.guild_id, user.id)
    if victim.get("coins", 0) < 100:
        await i.followup.send("❌ Das Opfer hat zu wenig Coins!"); return
    if random.random() > 0.4:
        steal = random.randint(50, min(500, victim["coins"]))
        await add_coins(i.guild_id, user.id, -steal)
        await add_coins(i.guild_id, i.user.id, steal)
        await i.followup.send(f"🦹 Erfolgreich! **{steal} Coins** von {user.mention} gestohlen!")
    else:
        fine = random.randint(100, 300)
        await add_coins(i.guild_id, i.user.id, -fine)
        await i.followup.send(f"👮 Erwischt! Du zahlst **{fine} Coins** Strafe.")

@bot.tree.command(name="eco-pay", description="Coins transferieren.")
async def pay_cmd(i: discord.Interaction, user: discord.Member, menge: int):
    await i.response.defer()
    if menge <= 0:
        await i.followup.send("❌ Ungültiger Betrag!"); return
    eco = await hole_eco(i.guild_id, i.user.id)
    if eco.get("coins", 0) < menge:
        await i.followup.send("❌ Nicht genug Coins!"); return
    await add_coins(i.guild_id, i.user.id, -menge)
    await add_coins(i.guild_id, user.id, menge)
    await i.followup.send(f"✅ **{menge} Coins** an {user.mention} überwiesen!")

@bot.tree.command(name="eco-leaderboard", description="Reichste User.")
async def eco_lb_cmd(i: discord.Interaction):
    await i.response.defer()
    top = await col("economy").find({"guild_id": i.guild_id}).sort("coins", -1).limit(10).to_list(10)
    medals = ["🥇","🥈","🥉"]
    e = discord.Embed(title="💰 Reichste User", color=discord.Color.gold())
    lines = []
    for idx, u in enumerate(top):
        member = i.guild.get_member(u["user_id"])  # no extra API call
        name = member.display_name if member else f"User {u['user_id']}"
        prefix = medals[idx] if idx < 3 else f"**{idx+1}.**"
        lines.append(f"{prefix} {name} — {u.get('coins',0)} Coins")
    e.description = "\n".join(lines) or "Keine Daten."
    await i.followup.send(embed=e)

@bot.tree.command(name="eco-slots", description="Slot Machine.")
async def slots_cmd(i: discord.Interaction, einsatz: int):
    await i.response.defer()
    if einsatz <= 0:
        await i.followup.send("❌ Ungültiger Einsatz!"); return
    eco = await hole_eco(i.guild_id, i.user.id)
    if eco.get("coins", 0) < einsatz:
        await i.followup.send("❌ Nicht genug Coins!"); return
    symbole = ["🍒","🍋","🍊","🍇","⭐","💎","7️⃣"]
    result = [random.choice(symbole) for _ in range(3)]
    if result[0] == result[1] == result[2]:
        mult = {" 💎":10,"7️⃣":7,"⭐":5}.get(result[0], 3)
        gewinn = einsatz * mult
        await add_coins(i.guild_id, i.user.id, gewinn)
        msg = f"🎰 {''.join(result)}\n🎉 JACKPOT! **+{gewinn} Coins**"
    elif result[0] == result[1] or result[1] == result[2]:
        await add_coins(i.guild_id, i.user.id, einsatz)
        msg = f"🎰 {''.join(result)}\n✅ Zwei gleiche! **+{einsatz} Coins**"
    else:
        await add_coins(i.guild_id, i.user.id, -einsatz)
        msg = f"🎰 {''.join(result)}\n❌ Verloren! **-{einsatz} Coins**"
    await i.followup.send(msg)

@bot.tree.command(name="eco-rep", description="Reputation geben.")
async def rep_cmd(i: discord.Interaction, user: discord.Member):
    await i.response.defer()
    if user.id == i.user.id:
        await i.followup.send("❌ Keine Selbst-Rep!"); return
    eco = await hole_eco(i.guild_id, i.user.id)
    wait = _cooldown_check(eco.get("last_rep"), 24)
    if wait:
        await i.followup.send(f"⏰ Warte noch **{wait}**!"); return
    await col("economy").update_one({"guild_id": i.guild_id, "user_id": user.id}, {"$inc": {"rep": 1}}, upsert=True)
    await col("economy").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$set": {"last_rep": datetime.utcnow()}})
    await i.followup.send(f"⭐ {user.mention} hat eine Reputation erhalten!")

@bot.tree.command(name="eco-shop", description="Shop anzeigen.")
async def shop_cmd(i: discord.Interaction):
    await i.response.defer()
    cfg = await hole_config(i.guild_id)
    items = cfg.get("shop", [])
    if not items:
        await i.followup.send("❌ Shop ist leer."); return
    e = discord.Embed(title="🛒 Shop", color=discord.Color.green())
    for item in items:
        e.add_field(name=f"{item['name']} – {item['price']} Coins", value=item.get("description","–"), inline=False)
    await i.followup.send(embed=e)

@bot.tree.command(name="eco-buy", description="Item kaufen.")
async def buy_cmd(i: discord.Interaction, item_name: str):
    await i.response.defer()
    cfg = await hole_config(i.guild_id)
    item = next((it for it in cfg.get("shop",[]) if it["name"].lower()==item_name.lower()), None)
    if not item:
        await i.followup.send("❌ Item nicht gefunden."); return
    eco = await hole_eco(i.guild_id, i.user.id)
    if eco.get("coins",0) < item["price"]:
        await i.followup.send("❌ Nicht genug Coins!"); return
    await col("economy").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$inc": {"coins": -item["price"]}, "$push": {"inventory": item["name"]}})
    if item.get("role_id"):
        role = i.guild.get_role(int(item["role_id"]))
        if role:
            try: await i.user.add_roles(role)
            except Exception: pass
    await i.followup.send(f"✅ **{item['name']}** gekauft!")

# ═════════════════════════════════════════════════════════════
# GIVEAWAYS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="giveaway-start", description="[Admin] Giveaway starten.")
@is_admin()
async def giveaway_start_cmd(i: discord.Interaction, preis: str, dauer: str, gewinner: int = 1, rolle: discord.Role = None):
    await i.response.defer()
    match = re.match(r"(\d+)(m|h|d)", dauer.lower())
    if not match:
        await i.followup.send("❌ Format: 10m, 2h, 1d"); return
    amount, unit = int(match.group(1)), match.group(2)
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
    ends_at = datetime.utcnow() + delta
    e = discord.Embed(title="🎉 GIVEAWAY", description=f"**Preis:** {preis}\n**Gewinner:** {gewinner}\n**Endet:** <t:{int(ends_at.timestamp())}:R>\n\nReagiere mit 🎉!", color=discord.Color.gold())
    if rolle:
        e.add_field(name="Benötigte Rolle", value=rolle.mention)
    msg = await i.channel.send(embed=e)
    await msg.add_reaction("🎉")
    await col("giveaways").insert_one({"guild_id": i.guild_id, "channel_id": i.channel_id, "message_id": msg.id, "preis": preis, "gewinner": gewinner, "rolle_id": rolle.id if rolle else None, "ends_at": ends_at, "active": True})
    await i.followup.send("✅ Giveaway gestartet!", ephemeral=True)

@tasks.loop(minutes=1)
async def giveaway_loop():
    active = await col("giveaways").find({"active": True, "ends_at": {"$lte": datetime.utcnow()}}).to_list(10)
    for gw in active:
        try:
            guild = bot.get_guild(gw["guild_id"])
            ch = guild.get_channel(gw["channel_id"])
            msg = await ch.fetch_message(gw["message_id"])
            reaction = discord.utils.get(msg.reactions, emoji="🎉")
            users = [u async for u in reaction.users() if not u.bot]
            if gw.get("rolle_id"):
                role = guild.get_role(gw["rolle_id"])
                if role:
                    users = [u for u in users if role in (guild.get_member(u.id).roles if guild.get_member(u.id) else [])]
            winners = random.sample(users, min(gw["gewinner"], len(users))) if users else []
            e = discord.Embed(title="🎉 Giveaway Beendet!", description=f"**Preis:** {gw['preis']}\n**Gewinner:** {', '.join(w.mention for w in winners) if winners else 'Niemand'}", color=discord.Color.green())
            await msg.edit(embed=e)
            if winners:
                await ch.send(f"🎉 {', '.join(w.mention for w in winners)} gewinnen **{gw['preis']}**!")
            await col("giveaways").update_one({"_id": gw["_id"]}, {"$set": {"active": False}})
        except Exception as ex:
            log.error(f"Giveaway loop: {ex}")

# ═════════════════════════════════════════════════════════════
# SUGGESTIONS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="suggest", description="Vorschlag einreichen.")
async def suggest_cmd(i: discord.Interaction, vorschlag: str):
    await i.response.defer(ephemeral=True)
    cfg = await hole_config(i.guild_id)
    ch_id = cfg.get("suggest_channel")
    if not ch_id:
        await i.followup.send("❌ Suggest-Kanal nicht konfiguriert!"); return
    ch = i.guild.get_channel(int(ch_id))
    e = discord.Embed(title="💡 Neuer Vorschlag", description=vorschlag, color=discord.Color.blurple())
    e.set_footer(text=f"von {i.user.display_name}")
    msg = await ch.send(embed=e)
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")
    await col("suggestions").insert_one({"guild_id": i.guild_id, "user_id": i.user.id, "vorschlag": vorschlag, "message_id": msg.id, "status": "offen", "ts": datetime.utcnow()})
    await i.followup.send("✅ Vorschlag eingereicht!")

@bot.tree.command(name="suggest-accept", description="[Admin] Vorschlag annehmen.")
@is_admin()
async def suggest_accept_cmd(i: discord.Interaction, message_id: str, grund: str = ""):
    await i.response.defer()
    sug = await col("suggestions").find_one({"message_id": int(message_id)})
    if not sug:
        await i.followup.send("❌ Vorschlag nicht gefunden."); return
    cfg = await hole_config(i.guild_id)
    ch = i.guild.get_channel(int(cfg.get("suggest_channel", 0) or 0))
    if ch:
        try:
            msg = await ch.fetch_message(int(message_id))
            e = discord.Embed(title="✅ Vorschlag angenommen", description=sug["vorschlag"], color=discord.Color.green())
            if grund: e.add_field(name="Grund", value=grund)
            await msg.edit(embed=e)
        except Exception: pass
    await col("suggestions").update_one({"_id": sug["_id"]}, {"$set": {"status": "angenommen"}})
    await i.followup.send("✅ Vorschlag angenommen!")

@bot.tree.command(name="suggest-deny", description="[Admin] Vorschlag ablehnen.")
@is_admin()
async def suggest_deny_cmd(i: discord.Interaction, message_id: str, grund: str = ""):
    await i.response.defer()
    sug = await col("suggestions").find_one({"message_id": int(message_id)})
    if not sug:
        await i.followup.send("❌ Vorschlag nicht gefunden."); return
    cfg = await hole_config(i.guild_id)
    ch = i.guild.get_channel(int(cfg.get("suggest_channel", 0) or 0))
    if ch:
        try:
            msg = await ch.fetch_message(int(message_id))
            e = discord.Embed(title="❌ Vorschlag abgelehnt", description=sug["vorschlag"], color=discord.Color.red())
            if grund: e.add_field(name="Grund", value=grund)
            await msg.edit(embed=e)
        except Exception: pass
    await col("suggestions").update_one({"_id": sug["_id"]}, {"$set": {"status": "abgelehnt"}})
    await i.followup.send("✅ Vorschlag abgelehnt!")

# ═════════════════════════════════════════════════════════════
# BIRTHDAYS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="geburtstag", description="Geburtstag eintragen.")
async def birthday_cmd(i: discord.Interaction, datum: str):
    try:
        datetime.strptime(datum, "%d.%m")
        await col("birthdays").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$set": {"datum": datum}}, upsert=True)
        await i.response.send_message(f"🎂 Geburtstag: **{datum}**", ephemeral=True)
    except Exception:
        await i.response.send_message("❌ Format: DD.MM", ephemeral=True)

@tasks.loop(hours=24)
async def birthday_loop():
    today = datetime.utcnow().strftime("%d.%m")
    bdays = await col("birthdays").find({"datum": today}).to_list(100)
    for b in bdays:
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

# ═════════════════════════════════════════════════════════════
# TICKET SYSTEM
# ═════════════════════════════════════════════════════════════
class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ticket erstellen", style=discord.ButtonStyle.primary, custom_id="create_ticket")
    async def create_ticket(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.defer(ephemeral=True)
        cfg = await hole_config(i.guild_id)
        existing = discord.utils.get(i.guild.channels, name=f"ticket-{i.user.name.lower()}")
        if existing:
            await i.followup.send(f"Bereits offen: {existing.mention}", ephemeral=True); return
        cat = i.guild.get_channel(int(cfg["ticket_category"])) if cfg.get("ticket_category") else None
        overwrites = {
            i.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            i.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if cfg.get("ticket_team_role"):
            r = i.guild.get_role(int(cfg["ticket_team_role"]))
            if r: overwrites[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        ch = await i.guild.create_text_channel(f"ticket-{i.user.name.lower()}", category=cat, overwrites=overwrites)
        await col("tickets").insert_one({"guild_id": i.guild_id, "channel_id": ch.id, "user_id": i.user.id, "open": True, "created_at": datetime.utcnow()})
        e = discord.Embed(title="🎫 Ticket", description=f"Hallo {i.user.mention}! Schreib dein Anliegen.", color=discord.Color.green())
        await ch.send(embed=e, view=CloseTicketView())
        await i.followup.send(f"✅ {ch.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Schließen", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_ticket(self, i: discord.Interaction, button: discord.ui.Button):
        await i.response.defer()
        await col("tickets").update_one({"channel_id": i.channel_id}, {"$set": {"open": False}})
        await i.channel.send("🔒 Wird in 5s gelöscht...")
        await asyncio.sleep(5)
        await i.channel.delete()

@bot.tree.command(name="ticket-setup", description="[Admin] Ticket-Panel erstellen.")
@is_admin()
async def ticket_setup_cmd(i: discord.Interaction, titel: str = "Support", beschreibung: str = "Klicke um ein Ticket zu öffnen."):
    e = discord.Embed(title=f"🎫 {titel}", description=beschreibung, color=discord.Color.blurple())
    await i.channel.send(embed=e, view=TicketView())
    await i.response.send_message("✅ Ticket-Panel erstellt!", ephemeral=True)

# ═════════════════════════════════════════════════════════════
# VERIFY
# ═════════════════════════════════════════════════════════════
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Verifizieren", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify(self, i: discord.Interaction, button: discord.ui.Button):
        cfg = await hole_config(i.guild_id)
        role_id = cfg.get("verify_role")
        if not role_id:
            await i.response.send_message("❌ Keine Rolle konfiguriert!", ephemeral=True); return
        role = i.guild.get_role(int(role_id))
        if not role:
            await i.response.send_message("❌ Rolle nicht gefunden!", ephemeral=True); return
        if role in i.user.roles:
            await i.response.send_message("✅ Bereits verifiziert!", ephemeral=True); return
        await i.user.add_roles(role)
        await i.response.send_message("✅ Verifiziert!", ephemeral=True)

@bot.tree.command(name="verify-setup", description="[Admin] Verifizierungs-Panel.")
@is_admin()
async def verify_setup_cmd(i: discord.Interaction, rolle: discord.Role):
    await col("config").update_one({"guild_id": i.guild_id}, {"$set": {"verify_role": rolle.id}}, upsert=True)
    invalidate_config(i.guild_id)
    e = discord.Embed(title="✅ Verifizierung", description="Klicke den Button um dich zu verifizieren.", color=discord.Color.green())
    await i.channel.send(embed=e, view=VerifyView())
    await i.response.send_message("✅ Panel erstellt!", ephemeral=True)

# ═════════════════════════════════════════════════════════════
# TEAM & BEWERBUNGEN
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="team-add", description="[Admin] User zum Team hinzufügen.")
@is_admin()
async def team_add_cmd(i: discord.Interaction, user: discord.Member, rolle: str = "Moderator"):
    await col("team").update_one({"guild_id": i.guild_id, "user_id": user.id}, {"$set": {"guild_id": i.guild_id, "user_id": user.id, "rolle": rolle, "joined": datetime.utcnow(), "aktiv": True}}, upsert=True)
    await i.response.send_message(f"✅ {user.mention} → **{rolle}**")

@bot.tree.command(name="team-remove", description="[Admin] User aus Team entfernen.")
@is_admin()
async def team_remove_cmd(i: discord.Interaction, user: discord.Member):
    await col("team").delete_one({"guild_id": i.guild_id, "user_id": user.id})
    await i.response.send_message(f"✅ {user.mention} entfernt.")

@bot.tree.command(name="team", description="Team anzeigen.")
async def team_cmd(i: discord.Interaction):
    await i.response.defer()
    members = await col("team").find({"guild_id": i.guild_id, "aktiv": True}).to_list(50)
    e = discord.Embed(title="👥 Team", color=discord.Color.blurple())
    if not members:
        e.description = "Kein Team."
    else:
        for m in members:
            user = i.guild.get_member(m["user_id"])
            e.add_field(name=m.get("rolle","Mitglied"), value=user.mention if user else str(m["user_id"]), inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="abmelden", description="Abwesenheit eintragen.")
async def abmelden_cmd(i: discord.Interaction, von: str, bis: str, grund: str = "Kein Grund"):
    m = await col("team").find_one({"guild_id": i.guild_id, "user_id": i.user.id})
    if not m:
        await i.response.send_message("❌ Du bist kein Team-Mitglied!", ephemeral=True); return
    await col("team").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$push": {"abmeldungen": {"von": von, "bis": bis, "grund": grund, "ts": datetime.utcnow()}}})
    await i.response.send_message(f"✅ Abmeldung: **{von}** bis **{bis}** – {grund}", ephemeral=True)

@bot.tree.command(name="bewerben", description="Fürs Team bewerben.")
async def bewerben_cmd(i: discord.Interaction, alter: str, erfahrung: str, warum: str, verfuegbarkeit: str):
    await i.response.defer(ephemeral=True)
    existing = await col("applications").find_one({"guild_id": i.guild_id, "user_id": i.user.id, "status": "offen"})
    if existing:
        await i.followup.send("❌ Du hast bereits eine offene Bewerbung!"); return
    await col("applications").insert_one({"guild_id": i.guild_id, "user_id": i.user.id, "alter": alter, "erfahrung": erfahrung, "warum": warum, "verfuegbarkeit": verfuegbarkeit, "status": "offen", "ts": datetime.utcnow()})
    cfg = await hole_config(i.guild_id)
    if cfg.get("mod_log"):
        ch = i.guild.get_channel(int(cfg["mod_log"]))
        if ch:
            e = discord.Embed(title="📝 Neue Bewerbung", color=discord.Color.blurple())
            e.add_field(name="User", value=i.user.mention)
            e.add_field(name="Alter", value=alter)
            e.add_field(name="Erfahrung", value=erfahrung, inline=False)
            e.add_field(name="Warum", value=warum, inline=False)
            e.add_field(name="Verfügbarkeit", value=verfuegbarkeit)
            await ch.send(embed=e)
    await i.followup.send("✅ Bewerbung eingereicht!")

@bot.tree.command(name="bewerbungen", description="[Admin] Bewerbungen anzeigen.")
@is_admin()
async def bewerbungen_cmd(i: discord.Interaction):
    await i.response.defer()
    apps = await col("applications").find({"guild_id": i.guild_id, "status": "offen"}).to_list(20)
    if not apps:
        await i.followup.send("Keine offenen Bewerbungen."); return
    e = discord.Embed(title="📝 Bewerbungen", color=discord.Color.blurple())
    for a in apps:
        user = i.guild.get_member(a["user_id"])
        e.add_field(name=str(user) if user else str(a["user_id"]), value=f"Alter: {a['alter']}\nVerfügbar: {a['verfuegbarkeit']}", inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="bewerbung-accept", description="[Admin] Bewerbung annehmen.")
@is_admin()
async def bewerbung_accept_cmd(i: discord.Interaction, user: discord.Member):
    await i.response.defer()
    app = await col("applications").find_one({"guild_id": i.guild_id, "user_id": user.id, "status": "offen"})
    if not app:
        await i.followup.send("❌ Keine offene Bewerbung."); return
    await col("applications").update_one({"_id": app["_id"]}, {"$set": {"status": "angenommen"}})
    try: await user.send(f"🎉 Deine Bewerbung auf **{i.guild.name}** wurde angenommen!")
    except Exception: pass
    await i.followup.send(f"✅ Bewerbung von {user.mention} angenommen!")

@bot.tree.command(name="bewerbung-deny", description="[Admin] Bewerbung ablehnen.")
@is_admin()
async def bewerbung_deny_cmd(i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
    await i.response.defer()
    app = await col("applications").find_one({"guild_id": i.guild_id, "user_id": user.id, "status": "offen"})
    if not app:
        await i.followup.send("❌ Keine offene Bewerbung."); return
    await col("applications").update_one({"_id": app["_id"]}, {"$set": {"status": "abgelehnt"}})
    try: await user.send(f"❌ Bewerbung auf **{i.guild.name}** abgelehnt.\nGrund: {grund}")
    except Exception: pass
    await i.followup.send("✅ Bewerbung abgelehnt.")

# ═════════════════════════════════════════════════════════════
# RL TEAMS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="rl-team-erstellen", description="RL Team erstellen.")
async def rl_team_create_cmd(i: discord.Interaction, name: str, format: str = "3v3"):
    await i.response.defer()
    existing = await col("rl_teams").find_one({"guild_id": i.guild_id, "captain_id": i.user.id})
    if existing:
        await i.followup.send("❌ Du hast bereits ein Team!"); return
    await col("rl_teams").insert_one({"guild_id": i.guild_id, "name": name, "format": format, "captain_id": i.user.id, "members": [i.user.id], "wins": 0, "losses": 0, "created": datetime.utcnow()})
    await i.followup.send(f"✅ Team **{name}** ({format}) erstellt!")

@bot.tree.command(name="rl-team-join", description="RL Team beitreten.")
async def rl_team_join_cmd(i: discord.Interaction, team_name: str):
    await i.response.defer()
    team = await col("rl_teams").find_one({"guild_id": i.guild_id, "name": team_name})
    if not team:
        await i.followup.send("❌ Team nicht gefunden."); return
    if i.user.id in team["members"]:
        await i.followup.send("❌ Du bist bereits im Team!"); return
    await col("rl_teams").update_one({"_id": team["_id"]}, {"$push": {"members": i.user.id}})
    await i.followup.send(f"✅ Team **{team_name}** beigetreten!")

@bot.tree.command(name="rl-teams", description="Alle RL Teams anzeigen.")
async def rl_teams_cmd(i: discord.Interaction):
    await i.response.defer()
    teams = await col("rl_teams").find({"guild_id": i.guild_id}).to_list(20)
    if not teams:
        await i.followup.send("Keine Teams."); return
    e = discord.Embed(title="🚗 RL Teams", color=discord.Color.orange())
    for t in teams:
        captain = i.guild.get_member(t["captain_id"])
        e.add_field(name=f"{t['name']} ({t['format']})", value=f"Captain: {captain.mention if captain else '?'}\nMember: {len(t['members'])} | W/L: {t['wins']}/{t['losses']}", inline=False)
    await i.followup.send(embed=e)

# ═════════════════════════════════════════════════════════════
# CUSTOM COMMANDS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="cmd-add", description="[Admin] Custom Command erstellen.")
@is_admin()
async def cmd_add(i: discord.Interaction, trigger: str, antwort: str):
    await col("custom_commands").update_one({"guild_id": i.guild_id, "trigger": trigger.lower()}, {"$set": {"response": antwort}}, upsert=True)
    await i.response.send_message(f"✅ Command `{trigger}` erstellt!")

@bot.tree.command(name="cmd-remove", description="[Admin] Custom Command entfernen.")
@is_admin()
async def cmd_remove(i: discord.Interaction, trigger: str):
    await col("custom_commands").delete_one({"guild_id": i.guild_id, "trigger": trigger.lower()})
    await i.response.send_message(f"✅ Command `{trigger}` entfernt!")

@bot.tree.command(name="cmd-list", description="Alle Custom Commands.")
async def cmd_list(i: discord.Interaction):
    await i.response.defer()
    cmds = await col("custom_commands").find({"guild_id": i.guild_id}).to_list(50)
    if not cmds:
        await i.followup.send("Keine Custom Commands."); return
    e = discord.Embed(title="⚙️ Custom Commands", color=discord.Color.blurple())
    e.description = "\n".join(f"`{c['trigger']}` → {c['response'][:50]}" for c in cmds)
    await i.followup.send(embed=e)

# ═════════════════════════════════════════════════════════════
# RSS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="rss-add", description="[Admin] RSS Feed hinzufügen.")
@is_admin()
async def rss_add_cmd(i: discord.Interaction, name: str, url: str, kanal: discord.TextChannel):
    await i.response.defer()
    import feedparser
    parsed = feedparser.parse(url)
    if not parsed.entries:
        await i.followup.send("❌ Ungültiger RSS Feed!"); return
    await col("rss_feeds").insert_one({"guild_id": i.guild_id, "name": name, "url": url, "channel_id": kanal.id, "aktiv": True, "added": datetime.utcnow()})
    await i.followup.send(f"✅ RSS **{name}** → {kanal.mention}")

@bot.tree.command(name="rss-remove", description="[Admin] RSS Feed entfernen.")
@is_admin()
async def rss_remove_cmd(i: discord.Interaction, name: str):
    r = await col("rss_feeds").delete_one({"guild_id": i.guild_id, "name": name})
    await i.response.send_message(f"✅ Feed **{name}** entfernt." if r.deleted_count else "❌ Nicht gefunden.")

@bot.tree.command(name="rss-list", description="RSS Feeds anzeigen.")
async def rss_list_cmd(i: discord.Interaction):
    await i.response.defer()
    feeds = await col("rss_feeds").find({"guild_id": i.guild_id}).to_list(20)
    if not feeds:
        await i.followup.send("Keine Feeds."); return
    e = discord.Embed(title="📰 RSS Feeds", color=discord.Color.blurple())
    for f in feeds:
        ch = i.guild.get_channel(f["channel_id"])
        e.add_field(name=f"{'✅' if f.get('aktiv') else '⏸️'} {f['name']}", value=ch.mention if ch else "?", inline=False)
    await i.followup.send(embed=e)

@tasks.loop(minutes=15)   # 15 min instead of 10 → less DB + HTTP load
async def rss_check_loop():
    import feedparser
    feeds = await col("rss_feeds").find({"aktiv": True}).to_list(30)
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
                if await col("rss_seen").find_one({"feed_id": str(feed["_id"]), "link": link}):
                    continue
                e = discord.Embed(title=entry.get("title","")[:250], url=link, description=entry.get("summary","")[:300], color=discord.Color.blurple())
                e.set_footer(text=f"📰 {feed.get('name','RSS')}")
                await ch.send(embed=e)
                await col("rss_seen").insert_one({"feed_id": str(feed["_id"]), "link": link, "ts": datetime.utcnow()})
        except Exception as ex:
            log.error(f"RSS: {ex}")

# ═════════════════════════════════════════════════════════════
# TWITCH NOTIFICATIONS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="notif-twitch", description="[Admin] Twitch Notification einrichten.")
@is_admin()
async def notif_twitch_cmd(i: discord.Interaction, streamer: str, kanal: discord.TextChannel, nachricht: str = "{streamer} ist jetzt live! 🎮"):
    await col("notifications").update_one({"guild_id": i.guild_id, "type": "twitch", "name": streamer.lower()}, {"$set": {"channel_id": kanal.id, "message": nachricht, "live": False}}, upsert=True)
    await i.response.send_message(f"✅ Twitch Notification für **{streamer}** → {kanal.mention}")

@tasks.loop(minutes=5)
async def twitch_check_loop():
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        return
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://id.twitch.tv/oauth2/token",
                params={"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                token_data = await r.json()
            token = token_data.get("access_token")
            if not token: return
            streamers = await col("notifications").find({"type": "twitch"}).to_list(50)
            for streamer in streamers:
                async with s.get(
                    f"https://api.twitch.tv/helix/streams?user_login={streamer['name']}",
                    headers={"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as r:
                    data = await r.json()
                is_live = bool(data.get("data"))
                was_live = streamer.get("live", False)
                if is_live and not was_live:
                    guild = bot.get_guild(streamer["guild_id"])
                    if guild:
                        ch = guild.get_channel(streamer["channel_id"])
                        if ch:
                            stream = data["data"][0]
                            msg = streamer.get("message", "{streamer} ist live!").replace("{streamer}", streamer["name"])
                            e = discord.Embed(title=stream.get("title","Live!"), url=f"https://twitch.tv/{streamer['name']}", color=discord.Color.purple())
                            e.add_field(name="Spiel", value=stream.get("game_name","?"))
                            e.add_field(name="Zuschauer", value=str(stream.get("viewer_count",0)))
                            await ch.send(msg, embed=e)
                await col("notifications").update_one({"_id": streamer["_id"]}, {"$set": {"live": is_live}})
    except Exception as ex:
        log.error(f"Twitch check: {ex}")

# ═════════════════════════════════════════════════════════════
# STAT CHANNELS
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="stat-channel", description="[Admin] Statistik-Kanal einrichten.")
@is_admin()
async def stat_channel_cmd(i: discord.Interaction, kanal: discord.VoiceChannel, typ: str):
    await col("config").update_one({"guild_id": i.guild_id}, {"$set": {f"stat_channels.{typ}": kanal.id}}, upsert=True)
    invalidate_config(i.guild_id)
    await i.response.send_message(f"✅ Stat-Kanal ({typ}) → {kanal.mention}")

@tasks.loop(minutes=10)
async def stat_channel_loop():
    configs = await col("config").find({"stat_channels": {"$exists": True, "$ne": {}}}, {"guild_id": 1, "stat_channels": 1}).to_list(50)
    for cfg in configs:
        guild = bot.get_guild(cfg["guild_id"])
        if not guild: continue
        for typ, ch_id in cfg.get("stat_channels", {}).items():
            ch = guild.get_channel(int(ch_id))
            if not ch: continue
            try:
                if typ == "members":   await ch.edit(name=f"👥 Member: {guild.member_count}")
                elif typ == "bots":    await ch.edit(name=f"🤖 Bots: {sum(1 for m in guild.members if m.bot)}")
                elif typ == "roles":   await ch.edit(name=f"🎭 Rollen: {len(guild.roles)}")
                elif typ == "channels":await ch.edit(name=f"💬 Kanäle: {len(guild.channels)}")
            except Exception: pass

# ═════════════════════════════════════════════════════════════
# SETUP COMMANDS
# ═════════════════════════════════════════════════════════════
async def _cfg_update(guild_id: int, fields: dict):
    await col("config").update_one({"guild_id": guild_id}, {"$set": fields}, upsert=True)
    invalidate_config(guild_id)

@bot.tree.command(name="setup-welcome", description="[Admin] Willkommen einrichten.")
@is_admin()
async def setup_welcome_cmd(i: discord.Interaction, kanal: discord.TextChannel, nachricht: str = "Willkommen {user} auf {server}! 🎉"):
    await _cfg_update(i.guild_id, {"welcome_channel": kanal.id, "welcome_msg": nachricht})
    await i.response.send_message(f"✅ Willkommen → {kanal.mention}")

@bot.tree.command(name="setup-goodbye", description="[Admin] Abschied einrichten.")
@is_admin()
async def setup_goodbye_cmd(i: discord.Interaction, kanal: discord.TextChannel, nachricht: str = "{user} hat den Server verlassen."):
    await _cfg_update(i.guild_id, {"goodbye_channel": kanal.id, "goodbye_msg": nachricht})
    await i.response.send_message(f"✅ Abschied → {kanal.mention}")

@bot.tree.command(name="setup-autorole", description="[Admin] Auto-Rolle einrichten.")
@is_admin()
async def setup_autorole_cmd(i: discord.Interaction, rolle: discord.Role):
    await _cfg_update(i.guild_id, {"auto_role": rolle.id})
    await i.response.send_message(f"✅ Auto-Rolle: {rolle.mention}")

@bot.tree.command(name="setup-modlog", description="[Admin] Mod-Log Kanal.")
@is_admin()
async def setup_modlog_cmd(i: discord.Interaction, kanal: discord.TextChannel):
    await _cfg_update(i.guild_id, {"mod_log": kanal.id})
    await i.response.send_message(f"✅ Mod-Log → {kanal.mention}")

@bot.tree.command(name="setup-automod", description="[Admin] Auto-Mod einrichten.")
@is_admin()
async def setup_automod_cmd(i: discord.Interaction, aktiviert: bool, spam: bool = True, links: bool = False, caps: bool = False, mention_limit: int = 5):
    await _cfg_update(i.guild_id, {"automod": {"enabled": aktiviert, "spam": spam, "links": links, "caps": caps, "bad_words": [], "mention_limit": mention_limit}})
    await i.response.send_message(f"✅ Auto-Mod {'aktiviert' if aktiviert else 'deaktiviert'}.")

@bot.tree.command(name="setup-starboard", description="[Admin] Starboard einrichten.")
@is_admin()
async def setup_starboard_cmd(i: discord.Interaction, kanal: discord.TextChannel, min_sterne: int = 3):
    await _cfg_update(i.guild_id, {"starboard_channel": kanal.id, "starboard_min": min_sterne})
    await i.response.send_message(f"✅ Starboard → {kanal.mention} (min. {min_sterne} ⭐)")

@bot.tree.command(name="setup-suggest", description="[Admin] Suggest-Kanal einrichten.")
@is_admin()
async def setup_suggest_cmd(i: discord.Interaction, kanal: discord.TextChannel):
    await _cfg_update(i.guild_id, {"suggest_channel": kanal.id})
    await i.response.send_message(f"✅ Suggest-Kanal → {kanal.mention}")

@bot.tree.command(name="setup-birthday", description="[Admin] Geburtstags-Kanal einrichten.")
@is_admin()
async def setup_birthday_cmd(i: discord.Interaction, kanal: discord.TextChannel):
    await _cfg_update(i.guild_id, {"birthday_channel": kanal.id})
    await i.response.send_message(f"✅ Geburtstags-Kanal → {kanal.mention}")

@bot.tree.command(name="setup-bot-status", description="[Admin] Bot Status setzen.")
@is_admin()
async def setup_bot_status_cmd(i: discord.Interaction, status: str):
    await _cfg_update(i.guild_id, {"custom_bot_status": status})
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
    await i.response.send_message(f"✅ Bot Status: **{status}**")

@bot.tree.command(name="badword-add", description="[Admin] Verbotenes Wort hinzufügen.")
@is_admin()
async def badword_add_cmd(i: discord.Interaction, wort: str):
    await col("config").update_one({"guild_id": i.guild_id}, {"$addToSet": {"automod.bad_words": wort.lower()}}, upsert=True)
    invalidate_config(i.guild_id)
    await i.response.send_message(f"✅ `{wort}` zur Blacklist.", ephemeral=True)

@bot.tree.command(name="eco-shop-add", description="[Admin] Shop Item hinzufügen.")
@is_admin()
async def shop_add_cmd(i: discord.Interaction, name: str, preis: int, beschreibung: str = "", rolle: discord.Role = None):
    item = {"name": name, "price": preis, "description": beschreibung}
    if rolle: item["role_id"] = str(rolle.id)
    await col("config").update_one({"guild_id": i.guild_id}, {"$push": {"shop": item}}, upsert=True)
    invalidate_config(i.guild_id)
    await i.response.send_message(f"✅ **{name}** für {preis} Coins im Shop!")

# ═════════════════════════════════════════════════════════════
# PREFIX COMMANDS
# ═════════════════════════════════════════════════════════════
@bot.command(name="mute")
@commands.has_permissions(kick_members=True)
async def mute_prefix(ctx, user: discord.Member, minuten: int = 10, *, grund: str = "Kein Grund"):
    until = discord.utils.utcnow() + timedelta(minutes=minuten)
    await user.timeout(until, reason=grund)
    await ctx.send(f"⏰ {user.mention} für **{minuten} Min** gemutet.")

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

# ═════════════════════════════════════════════════════════════
# HELP
# ═════════════════════════════════════════════════════════════
@bot.tree.command(name="help", description="Alle Commands.")
async def help_cmd(i: discord.Interaction):
    e = discord.Embed(title="📖 Renthol Bot", color=discord.Color.blurple())
    e.add_field(name="🛡️ Mod", value="`/ban` `/unban` `/kick` `/timeout` `/untimeout` `/warn` `/warns` `/unwarn` `/clearwarns` `/case` `/clear` `/slowmode` `/lock` `/unlock` `/raid-mode`", inline=False)
    e.add_field(name="ℹ️ Info", value="`/userinfo` `/serverinfo` `/avatar` `/ping` `/timestamp`", inline=False)
    e.add_field(name="🎮 Fun", value="`/8ball` `/coinflip` `/wuerfel` `/rps` `/quote` `/poll` `/calc` `/meme`", inline=False)
    e.add_field(name="💰 Economy", value="`/eco-balance` `/eco-daily` `/eco-work` `/eco-fish` `/eco-mine` `/eco-gamble` `/eco-rob` `/eco-pay` `/eco-slots` `/eco-shop` `/eco-buy` `/eco-rep` `/eco-leaderboard`", inline=False)
    e.add_field(name="🎉 Giveaway", value="`/giveaway-start`", inline=False)
    e.add_field(name="💡 Suggestions", value="`/suggest` `/suggest-accept` `/suggest-deny`", inline=False)
    e.add_field(name="🎂 Geburtstag", value="`/geburtstag`", inline=False)
    e.add_field(name="💤 AFK / ⏰ Remind", value="`/afk` `/remindme`", inline=False)
    e.add_field(name="🎫 Ticket / ✅ Verify", value="`/ticket-setup` `/verify-setup`", inline=False)
    e.add_field(name="👥 Team", value="`/team` `/team-add` `/team-remove` `/abmelden` `/bewerben` `/bewerbungen` `/bewerbung-accept` `/bewerbung-deny`", inline=False)
    e.add_field(name="🚗 RL", value="`/rl-team-erstellen` `/rl-team-join` `/rl-teams`", inline=False)
    e.add_field(name="📰 RSS / 📣 Notif", value="`/rss-add` `/rss-remove` `/rss-list` `/notif-twitch`", inline=False)
    e.add_field(name="⚙️ Setup", value="`/setup-welcome` `/setup-goodbye` `/setup-autorole` `/setup-modlog` `/setup-automod` `/setup-starboard` `/setup-suggest` `/setup-birthday` `/setup-bot-status` `/stat-channel` `/badword-add` `/eco-shop-add` `/cmd-add` `/cmd-remove`", inline=False)
    e.set_footer(text="Renthol Bot")
    await i.response.send_message(embed=e)

# ═════════════════════════════════════════════════════════════
# FLASK DASHBOARD
# ═════════════════════════════════════════════════════════════
from flask import (
    Flask, render_template_string, request,
    redirect, session, url_for, flash, jsonify,
)
import requests as http_req

flask_app = Flask(__name__)
flask_app.secret_key = SECRET_KEY
flask_app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

DISCORD_API = "https://discord.com/api/v10"

# ── Dashboard Discord API (sync, runs in Flask thread) ────────
def _d_get(endpoint: str, token: str = None, bot: bool = False):
    headers = {"User-Agent": "Renthol/1.0"}
    if bot:
        headers["Authorization"] = f"Bot {DISCORD_BOT_TOKEN}"
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        return None
    try:
        r = http_req.get(f"{DISCORD_API}{endpoint}", headers=headers, timeout=6)
        return r.json() if r.ok else None
    except Exception:
        return None

# Cache dashboard guild lists (60 s) to avoid repeated Discord API calls
_dash_guild_cache: dict[str, tuple[list, float]] = {}
_DASH_GUILD_TTL = 60

def _user_guilds(access_token: str) -> list:
    now = time.monotonic()
    if access_token in _dash_guild_cache:
        data, ts = _dash_guild_cache[access_token]
        if now - ts < _DASH_GUILD_TTL:
            return data
    data = _d_get("/users/@me/guilds", token=access_token) or []
    if len(_dash_guild_cache) > 100:
        oldest = min(_dash_guild_cache, key=lambda k: _dash_guild_cache[k][1])
        del _dash_guild_cache[oldest]
    _dash_guild_cache[access_token] = (data, now)
    return data

_bot_guilds_cache: tuple[list, float] = ([], 0.0)

def _bot_guilds() -> list:
    global _bot_guilds_cache
    now = time.monotonic()
    if now - _bot_guilds_cache[1] < _DASH_GUILD_TTL:
        return _bot_guilds_cache[0]
    data = _d_get("/users/@me/guilds", bot=True) or []
    _bot_guilds_cache = (data, now)
    return data

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def guild_access_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        guild_id = kwargs.get("guild_id")
        if not guild_id:
            return redirect(url_for("dashboard"))
        user_guilds = _user_guilds(session.get("access_token",""))
        bot_guild_ids = {g["id"] for g in _bot_guilds()}
        user_guild = next((g for g in user_guilds if g["id"] == guild_id), None)
        if not user_guild:
            flash("Kein Zugriff auf diesen Server.", "error")
            return redirect(url_for("dashboard"))
        if guild_id not in bot_guild_ids:
            flash("Bot ist nicht auf diesem Server.", "error")
            return redirect(url_for("dashboard"))
        perms = int(user_guild.get("permissions", 0))
        if not (perms & 0x8 or perms & 0x20):
            flash("Du benötigst Administrator- oder Manage-Server-Rechte.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

# ── Minimal CSS (dark, red accent – no external fonts for speed) ─
_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--r:#ef4444;--rd:#dc2626;--bg:#0f0f0f;--bg2:#1a1a1a;--bg3:#262626;--tx:#fff;--tx2:#a1a1aa;--bdr:#333}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;line-height:1.6}
a{color:inherit;text-decoration:none}
.nav{background:var(--bg2);border-bottom:1px solid var(--bdr);padding:.875rem 1.5rem;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}
.logo{font-size:1.25rem;font-weight:700;color:var(--r)}
.nav-right{display:flex;gap:.75rem;align-items:center;color:var(--tx2)}
.wrap{display:flex;min-height:calc(100vh - 53px)}
.side{width:240px;background:var(--bg2);border-right:1px solid var(--bdr);padding:1.25rem 1rem;flex-shrink:0}
.side-link{display:flex;align-items:center;gap:.625rem;padding:.625rem .875rem;color:var(--tx2);border-radius:6px;margin-bottom:.2rem;font-size:.9rem;transition:all .15s}
.side-link:hover,.side-link.active{background:rgba(239,68,68,.12);color:var(--r)}
.main{flex:1;padding:1.75rem;overflow-y:auto}
.page-title{font-size:1.75rem;font-weight:700;margin-bottom:.35rem}
.page-sub{color:var(--tx2);margin-bottom:1.5rem}
.card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:1.25rem;margin-bottom:1.25rem}
.card-title{font-size:1.05rem;font-weight:600;margin-bottom:1rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem;margin-bottom:1.5rem}
.stat{background:var(--bg2);border:1px solid var(--bdr);border-top:3px solid var(--r);border-radius:10px;padding:1.25rem}
.stat-val{font-size:2rem;font-weight:700}
.stat-lbl{color:var(--tx2);font-size:.85rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.55rem 1.1rem;border-radius:7px;font-size:.875rem;font-weight:500;border:none;cursor:pointer;transition:all .15s}
.btn-p{background:var(--r);color:#fff}.btn-p:hover{background:var(--rd)}
.btn-s{background:var(--bg3);color:var(--tx)}.btn-s:hover{background:var(--bdr)}
.btn-d{background:#7f1d1d;color:#fff}.btn-d:hover{background:#991b1b}
.btn-sm{padding:.35rem .75rem;font-size:.8rem}
.input,.select,.textarea{width:100%;padding:.65rem .9rem;background:var(--bg3);border:1px solid var(--bdr);border-radius:7px;color:var(--tx);font-size:.875rem;transition:border .15s}
.input:focus,.select:focus,.textarea:focus{outline:none;border-color:var(--r)}
.textarea{min-height:90px;resize:vertical}
.label{display:block;margin-bottom:.4rem;font-size:.875rem;color:var(--tx2)}
.fgroup{margin-bottom:1rem}
.table{width:100%;border-collapse:collapse}
.table th{text-align:left;padding:.75rem 1rem;color:var(--tx2);font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bdr)}
.table td{padding:.875rem 1rem;border-bottom:1px solid var(--bdr)}
.table tr:hover{background:rgba(255,255,255,.02)}
.badge{padding:.2rem .6rem;border-radius:20px;font-size:.75rem;font-weight:500}
.b-g{background:rgba(34,197,94,.15);color:#22c55e}
.b-r{background:rgba(220,38,38,.15);color:#f87171}
.b-b{background:rgba(59,130,246,.15);color:#60a5fa}
.alert{padding:.875rem 1.1rem;border-radius:7px;margin-bottom:1rem}
.a-ok{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);color:#22c55e}
.a-err{background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.25);color:#f87171}
.srv-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:1.25rem}
.srv-card{background:var(--bg2);border:1px solid var(--bdr);border-radius:12px;padding:1.25rem;transition:all .2s;position:relative}
.srv-card:hover{border-color:var(--r);transform:translateY(-2px)}
.srv-icon{width:56px;height:56px;border-radius:12px;background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:1.25rem;font-weight:700;margin-bottom:.875rem;border:1px solid var(--bdr)}
.srv-name{font-weight:600;margin-bottom:.25rem}
.srv-sub{color:var(--tx2);font-size:.85rem}
.login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0f0f0f,#1a0a0a)}
.login-card{background:var(--bg2);border:1px solid var(--bdr);border-radius:16px;padding:2.5rem;text-align:center;max-width:380px;width:90%}
.login-title{font-size:1.5rem;font-weight:700;margin-bottom:.35rem}
.login-sub{color:var(--tx2);margin-bottom:1.75rem}
.d-btn{background:#5865F2;color:#fff;width:100%;justify-content:center;padding:.875rem;border-radius:10px;font-size:.95rem}
.d-btn:hover{background:#4752c4}
@media(max-width:700px){.side{display:none}.main{padding:1rem}}
"""

_NAV = """
<nav class="nav">
  <div class="logo">🤖 Renthol</div>
  <div class="nav-right">
    <span>{{ session.username }}</span>
    <a href="{{ url_for('logout') }}" class="btn btn-s btn-sm">Abmelden</a>
  </div>
</nav>
"""

def _sidebar(guild_id: str, active: str) -> str:
    links = [
        ("📊","Übersicht","guild_dashboard"),
        ("🛡️","Moderation","moderation"),
        ("💰","Economy","economy"),
        ("🎁","Giveaways","giveaways"),
        ("💡","Vorschläge","suggestions"),
        ("👥","Team","team"),
        ("📝","Bewerbungen","applications"),
        ("📰","RSS","rss"),
        ("🚗","RL Teams","rl_teams"),
        ("🔔","Notifications","notifications"),
        ("📋","Mod Logs","modlogs"),
        ("⚙️","Einstellungen","settings"),
    ]
    items = ""
    for icon, label, ep in links:
        cls = " active" if ep == active else ""
        items += f'<a href="/{guild_id}/{ep.replace("_","-")}" class="side-link{cls}">{icon} {label}</a>\n'
    return f'<aside class="side">{items}</aside>'

def _alerts() -> str:
    msgs = session.get("_flashes", [])
    out = ""
    for cat, msg in msgs:
        cls = "a-ok" if cat == "success" else "a-err"
        out += f'<div class="alert {cls}">{msg}</div>'
    return out

BASE_HTML = """<!DOCTYPE html>
<html lang="de">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{% block title %}Renthol{% endblock %}</title>
<style>""" + _CSS + """</style></head>
<body>{% block body %}{% endblock %}</body></html>"""

# ── Routes ────────────────────────────────────────────────────
@flask_app.route("/")
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))

@flask_app.route("/login")
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    scope = "identify guilds"
    auth_url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={quote(DISCORD_REDIRECT_URI)}"
        f"&response_type=code"
        f"&scope={quote(scope)}"
    )
    tmpl = BASE_HTML.replace("{% block title %}Renthol{% endblock %}", "Login – Renthol")
    body = f"""
<div class="login-wrap">
  <div class="login-card">
    <div style="font-size:3rem;margin-bottom:1rem">🤖</div>
    <h1 class="login-title">Willkommen zurück</h1>
    <p class="login-sub">Mit Discord anmelden</p>
    {_alerts()}
    <a href="{auth_url}" class="btn d-btn">Mit Discord anmelden</a>
  </div>
</div>"""
    return tmpl.replace("{% block body %}{% endblock %}", body)

@flask_app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        flash("Authentifizierung fehlgeschlagen.", "error")
        return redirect(url_for("login"))
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": DISCORD_REDIRECT_URI,
    }
    try:
        r = http_req.post(f"{DISCORD_API}/oauth2/token", data=data, timeout=8)
        tokens = r.json()
    except Exception:
        flash("Discord API Fehler.", "error")
        return redirect(url_for("login"))
    if not r.ok:
        flash("Token-Austausch fehlgeschlagen.", "error")
        return redirect(url_for("login"))
    user = _d_get("/users/@me", token=tokens["access_token"])
    if not user:
        flash("Benutzerinfo konnte nicht abgerufen werden.", "error")
        return redirect(url_for("login"))
    session.permanent = True
    session.update({
        "user_id": user["id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
        "access_token": tokens["access_token"],
    })
    return redirect(url_for("dashboard"))

@flask_app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@flask_app.route("/dashboard")
@login_required
def dashboard():
    user_g = _user_guilds(session["access_token"])
    bot_ids = {g["id"] for g in _bot_guilds()}
    guilds = [g for g in user_g if g["id"] in bot_ids and (int(g.get("permissions",0)) & 0x8 or int(g.get("permissions",0)) & 0x20)]
    body = f"""
{_NAV}
<div class="wrap">
  <aside class="side"><div style="color:var(--tx2);font-size:.85rem;padding:.5rem">Wähle einen Server</div></aside>
  <main class="main">
    {_alerts()}
    <div class="page-title">Deine Server</div>
    <p class="page-sub">Wähle einen Server um das Dashboard zu öffnen</p>
    <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:1.5rem">
      <div class="stat"><div class="stat-val">{len(_bot_guilds())}</div><div class="stat-lbl">Server mit Bot</div></div>
      <div class="stat"><div class="stat-val">{len(guilds)}</div><div class="stat-lbl">Verwaltbar</div></div>
    </div>
    <div class="srv-grid">
      {"".join(f'<a href="/{g["id"]}/guild-dashboard" class="srv-card"><div class="srv-icon">{g["name"][:2]}</div><div class="srv-name">{g["name"]}</div><div class="srv-sub">Verwalten</div></a>' for g in guilds)}
      <a href="https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&permissions=8&scope=bot%20applications.commands" target="_blank" class="srv-card" style="opacity:.6;border-style:dashed">
        <div class="srv-icon" style="background:transparent;border-style:dashed">+</div>
        <div class="srv-name">Bot hinzufügen</div>
        <div class="srv-sub">Server einladen</div>
      </a>
    </div>
  </main>
</div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

def _guild_nav(guild_id: str, active: str):
    guild = _d_get(f"/guilds/{guild_id}", bot=True) or {"name": guild_id}
    name = guild.get("name", guild_id)
    nav = f"""
<nav class="nav">
  <div class="logo">🤖 {name}</div>
  <div class="nav-right">
    <a href="/dashboard" class="btn btn-s btn-sm">← Zurück</a>
    <span>{session.get("username","")}</span>
    <a href="/logout" class="btn btn-s btn-sm">Abmelden</a>
  </div>
</nav>"""
    return nav, _sidebar(guild_id, active), guild

@flask_app.route("/<guild_id>/guild-dashboard")
@login_required
@guild_access_required
def guild_dashboard(guild_id):
    nav, side, guild = _guild_nav(guild_id, "guild_dashboard")
    channels = _d_get(f"/guilds/{guild_id}/channels", bot=True) or []
    roles = _d_get(f"/guilds/{guild_id}/roles", bot=True) or []
    # Warn count via sync MongoDB call — run in executor so Flask thread doesn't block event loop
    import asyncio as _aio
    loop = bot.loop
    fut = _aio.run_coroutine_threadsafe(
        col("warns").count_documents({"guild_id": int(guild_id)}), loop
    )
    try:
        warns_count = fut.result(timeout=3)
    except Exception:
        warns_count = "?"
    g = guild
    mc = g.get("member_count","?")
    body = f"""
{nav}<div class="wrap">{side}<main class="main">
{_alerts()}
<div class="page-title">Übersicht</div>
<p class="page-sub">Statistiken für {g.get("name","")}</p>
<div class="grid">
  <div class="stat"><div class="stat-val">{mc}</div><div class="stat-lbl">Mitglieder</div></div>
  <div class="stat"><div class="stat-val">{len(channels)}</div><div class="stat-lbl">Channels</div></div>
  <div class="stat"><div class="stat-val">{len(roles)}</div><div class="stat-lbl">Rollen</div></div>
  <div class="stat"><div class="stat-val">{warns_count}</div><div class="stat-lbl">Verwarnungen</div></div>
</div>
<div class="card">
  <div class="card-title">Schnellzugriff</div>
  <div style="display:flex;gap:.75rem;flex-wrap:wrap">
    <a href="/{guild_id}/moderation" class="btn btn-p">Verwarnungen</a>
    <a href="/{guild_id}/economy" class="btn btn-p">Economy</a>
    <a href="/{guild_id}/settings" class="btn btn-s">Einstellungen</a>
  </div>
</div>
</main></div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

@flask_app.route("/<guild_id>/moderation", methods=["GET","POST"])
@login_required
@guild_access_required
def moderation(guild_id):
    nav, side, guild = _guild_nav(guild_id, "moderation")
    import asyncio as _aio
    loop = bot.loop
    search = request.args.get("search","")
    query = {"guild_id": int(guild_id)}
    if search:
        query["$or"] = [{"user_id": {"$regex": search}}, {"grund": {"$regex": search, "$options": "i"}}]
    fut = _aio.run_coroutine_threadsafe(
        col("warns").find(query).sort("ts",-1).to_list(50), loop
    )
    try:
        warns = fut.result(timeout=3)
    except Exception:
        warns = []
    rows = ""
    for w in warns:
        ts = w.get("ts","")
        if isinstance(ts, datetime):
            ts = ts.strftime("%d.%m.%Y %H:%M")
        rows += f"""<tr>
          <td>{w.get("user_id","")}</td>
          <td>{w.get("mod_id","")}</td>
          <td>{str(w.get("grund",""))[:60]}</td>
          <td>{ts}</td>
          <td><form method="POST" action="/{guild_id}/moderation/delete/{w['_id']}" style="display:inline">
            <button class="btn btn-d btn-sm" onclick="return confirm('Löschen?')">🗑️</button>
          </form></td>
        </tr>"""
    body = f"""
{nav}<div class="wrap">{side}<main class="main">
{_alerts()}
<div class="page-title">Moderation</div>
<p class="page-sub">Verwarnungen verwalten</p>
<div class="card">
  <form method="GET" style="display:flex;gap:.75rem">
    <input name="search" class="input" placeholder="User ID oder Grund..." value="{search}" style="max-width:340px">
    <button class="btn btn-p">Suchen</button>
  </form>
</div>
<div class="card">
  <div class="card-title">Verwarnungen</div>
  <table class="table"><thead><tr><th>User</th><th>Mod</th><th>Grund</th><th>Datum</th><th></th></tr></thead>
  <tbody>{rows or "<tr><td colspan='5' style='text-align:center;color:var(--tx2)'>Keine Verwarnungen</td></tr>"}</tbody></table>
</div>
</main></div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

@flask_app.route("/<guild_id>/moderation/delete/<warn_id>", methods=["POST"])
@login_required
@guild_access_required
def delete_warn(guild_id, warn_id):
    from bson import ObjectId
    import asyncio as _aio
    loop = bot.loop
    fut = _aio.run_coroutine_threadsafe(
        col("warns").delete_one({"_id": ObjectId(warn_id), "guild_id": int(guild_id)}), loop
    )
    try:
        fut.result(timeout=3)
    except Exception:
        pass
    flash("Verwarnung gelöscht!", "success")
    return redirect(f"/{guild_id}/moderation")

@flask_app.route("/<guild_id>/economy", methods=["GET","POST"])
@login_required
@guild_access_required
def economy(guild_id):
    nav, side, guild = _guild_nav(guild_id, "economy")
    import asyncio as _aio
    loop = bot.loop
    if request.method == "POST":
        uid = request.form.get("user_id","").strip()
        amount = request.form.get("amount","0")
        if uid.isdigit() and amount.lstrip("-").isdigit():
            fut = _aio.run_coroutine_threadsafe(
                col("economy").update_one(
                    {"guild_id": int(guild_id), "user_id": int(uid)},
                    {"$set": {"coins": int(amount)}},
                    upsert=True,
                ), loop
            )
            try:
                fut.result(timeout=3)
                flash("Coins aktualisiert!", "success")
            except Exception:
                flash("Fehler.", "error")
    fut2 = _aio.run_coroutine_threadsafe(
        col("economy").find({"guild_id": int(guild_id)}).sort("coins",-1).limit(30).to_list(30), loop
    )
    try:
        lb = fut2.result(timeout=3)
    except Exception:
        lb = []
    rows = ""
    for idx, u in enumerate(lb, 1):
        rows += f"<tr><td>#{idx}</td><td>{u.get('user_id','')}</td><td>{u.get('coins',0)} 💰</td><td>{u.get('bank',0)} 🏦</td><td>{u.get('rep',0)} ⭐</td></tr>"
    body = f"""
{nav}<div class="wrap">{side}<main class="main">
{_alerts()}
<div class="page-title">Economy</div>
<p class="page-sub">Leaderboard & Coins verwalten</p>
<div class="card">
  <div class="card-title">Coins bearbeiten</div>
  <form method="POST" style="display:grid;grid-template-columns:1fr 1fr auto;gap:.875rem;align-items:flex-end">
    <div class="fgroup" style="margin:0"><label class="label">User ID</label><input name="user_id" class="input" required></div>
    <div class="fgroup" style="margin:0"><label class="label">Betrag</label><input name="amount" type="number" class="input" required></div>
    <button class="btn btn-p">Speichern</button>
  </form>
</div>
<div class="card">
  <div class="card-title">Leaderboard</div>
  <table class="table"><thead><tr><th>#</th><th>User</th><th>Wallet</th><th>Bank</th><th>Rep</th></tr></thead>
  <tbody>{rows or "<tr><td colspan='5' style='text-align:center;color:var(--tx2)'>Keine Daten</td></tr>"}</tbody></table>
</div>
</main></div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

def _generic_page(guild_id, active, title, desc):
    nav, side, guild = _guild_nav(guild_id, active)
    body = f"""
{nav}<div class="wrap">{side}<main class="main">
{_alerts()}
<div class="page-title">{title}</div>
<p class="page-sub">{desc}</p>
<div class="card"><p style="color:var(--tx2)">Diese Funktion wird bald verfügbar sein.</p></div>
</main></div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

@flask_app.route("/<guild_id>/giveaways")
@login_required
@guild_access_required
def giveaways(guild_id):
    return _generic_page(guild_id, "giveaways", "Giveaways", "Giveaways verwalten")

@flask_app.route("/<guild_id>/suggestions")
@login_required
@guild_access_required
def suggestions(guild_id):
    return _generic_page(guild_id, "suggestions", "Vorschläge", "Community-Vorschläge")

@flask_app.route("/<guild_id>/team")
@login_required
@guild_access_required
def team(guild_id):
    return _generic_page(guild_id, "team", "Team", "Team verwalten")

@flask_app.route("/<guild_id>/applications")
@login_required
@guild_access_required
def applications(guild_id):
    return _generic_page(guild_id, "applications", "Bewerbungen", "Bewerbungen verwalten")

@flask_app.route("/<guild_id>/rss")
@login_required
@guild_access_required
def rss(guild_id):
    return _generic_page(guild_id, "rss", "RSS Feeds", "RSS Feeds verwalten")

@flask_app.route("/<guild_id>/rl-teams")
@login_required
@guild_access_required
def rl_teams(guild_id):
    return _generic_page(guild_id, "rl_teams", "RL Teams", "Rocket League Teams")

@flask_app.route("/<guild_id>/notifications")
@login_required
@guild_access_required
def notifications(guild_id):
    return _generic_page(guild_id, "notifications", "Notifications", "Twitch & YouTube")

@flask_app.route("/<guild_id>/modlogs")
@login_required
@guild_access_required
def modlogs(guild_id):
    import asyncio as _aio
    loop = bot.loop
    fut = _aio.run_coroutine_threadsafe(
        col("logs").find({"guild_id": int(guild_id)}).sort("ts",-1).limit(50).to_list(50), loop
    )
    try:
        logs = fut.result(timeout=3)
    except Exception:
        logs = []
    nav, side, guild = _guild_nav(guild_id, "modlogs")
    rows = ""
    for l in logs:
        ts = l.get("ts","")
        if isinstance(ts, datetime): ts = ts.strftime("%d.%m.%Y %H:%M")
        rows += f"<tr><td>{ts}</td><td>{l.get('mod_id','')}</td><td><span class='badge b-b'>{l.get('aktion','')}</span></td><td>{str(l.get('grund',''))[:60]}</td></tr>"
    body = f"""
{nav}<div class="wrap">{side}<main class="main">
{_alerts()}
<div class="page-title">Mod Logs</div>
<p class="page-sub">Letzte Mod-Aktionen</p>
<div class="card">
  <table class="table"><thead><tr><th>Zeit</th><th>Mod</th><th>Aktion</th><th>Grund</th></tr></thead>
  <tbody>{rows or "<tr><td colspan='4' style='text-align:center;color:var(--tx2)'>Keine Logs</td></tr>"}</tbody></table>
</div>
</main></div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

@flask_app.route("/<guild_id>/settings", methods=["GET","POST"])
@login_required
@guild_access_required
def settings(guild_id):
    import asyncio as _aio
    loop = bot.loop
    channels = _d_get(f"/guilds/{guild_id}/channels", bot=True) or []
    text_ch = [c for c in channels if c.get("type") == 0]
    if request.method == "POST":
        fields = {
            "prefix":          request.form.get("prefix","!") or "!",
            "welcome_channel": request.form.get("welcome_channel") or None,
            "welcome_msg":     request.form.get("welcome_msg",""),
            "goodbye_channel": request.form.get("goodbye_channel") or None,
            "goodbye_msg":     request.form.get("goodbye_msg",""),
            "mod_log":         request.form.get("modlog_channel") or None,
            "suggest_channel": request.form.get("suggest_channel") or None,
            "birthday_channel":request.form.get("birthday_channel") or None,
        }
        fut = _aio.run_coroutine_threadsafe(
            col("config").update_one({"guild_id": int(guild_id)}, {"$set": fields}, upsert=True), loop
        )
        try:
            fut.result(timeout=3)
            invalidate_config(int(guild_id))
            flash("Einstellungen gespeichert!", "success")
        except Exception:
            flash("Fehler beim Speichern.", "error")
    fut2 = _aio.run_coroutine_threadsafe(
        col("config").find_one({"guild_id": int(guild_id)}), loop
    )
    try:
        cfg = fut2.result(timeout=3) or {}
    except Exception:
        cfg = {}
    def ch_opts(sel):
        out = '<option value="">-- Deaktiviert --</option>'
        for c in text_ch:
            s = "selected" if str(sel) == c["id"] else ""
            out += f'<option value="{c["id"]}" {s}>#{c["name"]}</option>'
        return out
    nav, side, guild = _guild_nav(guild_id, "settings")
    body = f"""
{nav}<div class="wrap">{side}<main class="main">
{_alerts()}
<div class="page-title">Einstellungen</div>
<p class="page-sub">Bot-Konfiguration</p>
<form method="POST" class="card">
  <div class="card-title">Allgemein</div>
  <div class="fgroup"><label class="label">Prefix</label><input name="prefix" class="input" value="{cfg.get('prefix','!')}" maxlength="5" style="max-width:120px"></div>
  <div class="card-title" style="margin-top:1.25rem">Willkommen</div>
  <div class="fgroup"><label class="label">Kanal</label><select name="welcome_channel" class="select">{ch_opts(cfg.get('welcome_channel',''))}</select></div>
  <div class="fgroup"><label class="label">Nachricht</label><textarea name="welcome_msg" class="textarea">{cfg.get('welcome_msg','')}</textarea></div>
  <div class="card-title" style="margin-top:1.25rem">Abschied</div>
  <div class="fgroup"><label class="label">Kanal</label><select name="goodbye_channel" class="select">{ch_opts(cfg.get('goodbye_channel',''))}</select></div>
  <div class="fgroup"><label class="label">Nachricht</label><textarea name="goodbye_msg" class="textarea">{cfg.get('goodbye_msg','')}</textarea></div>
  <div class="card-title" style="margin-top:1.25rem">Logging</div>
  <div class="fgroup"><label class="label">Mod-Log Kanal</label><select name="modlog_channel" class="select">{ch_opts(cfg.get('mod_log',''))}</select></div>
  <div class="card-title" style="margin-top:1.25rem">Sonstiges</div>
  <div class="fgroup"><label class="label">Suggest Kanal</label><select name="suggest_channel" class="select">{ch_opts(cfg.get('suggest_channel',''))}</select></div>
  <div class="fgroup"><label class="label">Geburtstags-Kanal</label><select name="birthday_channel" class="select">{ch_opts(cfg.get('birthday_channel',''))}</select></div>
  <button type="submit" class="btn btn-p">💾 Speichern</button>
</form>
</main></div>"""
    return render_template_string(BASE_HTML.replace("{% block body %}{% endblock %}", body))

@flask_app.route("/ping")
def ping():
    return jsonify({"status": "alive", "time": datetime.utcnow().isoformat()})

@flask_app.route("/health")
def health():
    lat = round(bot.latency * 1000) if bot.is_ready() else -1
    return jsonify({"status": "ok", "ping_ms": lat})

# ═════════════════════════════════════════════════════════════
# KEEP-ALIVE (async, pings own /health every 9 min)
# ═════════════════════════════════════════════════════════════
async def keep_alive_loop():
    if not RENDER_URL:
        log.warning("RENDER_EXTERNAL_URL not set – keep-alive disabled")
        return
    await asyncio.sleep(60)
    import aiohttp
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{RENDER_URL}/health", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        log.info("Keep-alive OK")
        except Exception as ex:
            log.warning(f"Keep-alive failed: {ex}")
        await asyncio.sleep(540)  # 9 minutes

# ═════════════════════════════════════════════════════════════
# STARTUP
# ═════════════════════════════════════════════════════════════
def run_flask():
    """Run Flask in its own daemon thread."""
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)

async def main():
    # Register persistent views so buttons survive restarts
    bot.add_view(TicketView())
    bot.add_view(CloseTicketView())
    bot.add_view(VerifyView())
    # Start Flask in background thread
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    log.info(f"Flask dashboard started on port {PORT}")
    # Start Discord bot (blocks until disconnect)
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())