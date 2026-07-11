import os, asyncio, threading, time, logging
from datetime import datetime, timedelta
from collections import deque, defaultdict
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN         = os.getenv("DISCORD_TOKEN", "")
DISCORD_CLIENT_ID     = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_BOT_TOKEN     = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_REDIRECT_URI  = os.getenv("DISCORD_REDIRECT_URI", "http://localhost:10000/callback")
MONGODB_URI           = os.getenv("MONGODB_URI", "")
MONGODB_DB            = os.getenv("MONGODB_DB", "rld_main")
SECRET_KEY            = os.getenv("SECRET_KEY", "")
RENDER_URL            = os.getenv("RENDER_EXTERNAL_URL", "")
PORT                  = int(os.getenv("PORT", "10000"))
TWITCH_ID             = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_SECRET         = os.getenv("TWITCH_CLIENT_SECRET", "")

for v, n in [(DISCORD_TOKEN, "DISCORD_TOKEN"), (MONGODB_URI, "MONGODB_URI"), (SECRET_KEY, "SECRET_KEY")]:
    if not v: raise RuntimeError(f"{n} env var missing!")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("rld")
log.setLevel(logging.INFO)

# ── Import shared utils ─────────────────────────────────────
from utils import (
    col, db, gcfg, ivcfg, heco, addcoins, logcase,
    _count, _find, _findone, _update, _delete,
    cdchk, is_mod, is_admin, _mlog
)

# ── Discord Bot ──────────────────────────────────────────────
import discord
from discord.ext import commands, tasks
from discord import app_commands

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
start_t = datetime.utcnow()
recent_joins: deque = deque(maxlen=20)
spam_tr: dict = defaultdict(list)
coin_cd: dict = {}

BOT_COGS = [
    "cogs.moderation",
    "cogs.economy",
    "cogs.fun",
    "cogs.info",
    "cogs.team",
    "cogs.giveaway",
    "cogs.tickets",
    "cogs.verify",
    "cogs.rss",
    "cogs.notifications",
    "cogs.rl_teams",
    "cogs.setup",
    "cogs.counting",
    "cogs.help",
]




@bot.event
async def on_ready():
    log.info(f"Bot: {bot.user}")
    for cog in BOT_COGS:
        try:
            await bot.load_extension(cog)
            log.info(f"Loaded cog: {cog}")
        except Exception as ex:
            log.error(f"Failed to load cog {cog}: {ex}")
    try:
        s = await bot.tree.sync()
        log.info(f"Synced {len(s)} cmds")
    except Exception as ex:
        log.error(ex)
    asyncio.ensure_future(kalive())
    cfgs = await col("config").find({}, {"custom_bot_status": 1}).to_list(50)
    for c in cfgs:
        if c.get("custom_bot_status"):
            await bot.change_presence(activity=discord.Activity(
                type=discord.ActivityType.watching, name=c["custom_bot_status"]))
            return
    tot = sum((g.member_count or 0) for g in bot.guilds)
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=f"{tot} Member | /help"))

@bot.event
async def on_member_join(m: discord.Member):
    cfg = await gcfg(m.guild.id)
    sm = cfg.get("slow_joiner_minutes", 0)
    if sm > 0:
        age = (datetime.utcnow() - m.created_at.replace(tzinfo=None)).total_seconds() / 60
        if age < sm:
            try:
                await m.send(f"Account zu neu. Komm in {sm} Min wieder.")
                await m.kick(reason="Slow Joiner")
            except: pass
            return
    if cfg.get("anti_raid"):
        now = time.time()
        recent_joins.append(now)
        if len([t for t in recent_joins if now - t < 10]) >= 10:
            try: await m.kick(reason="Anti-Raid")
            except: pass
            return
    if cfg.get("auto_role"):
        r = m.guild.get_role(int(cfg["auto_role"]))
        if r:
            try: await m.add_roles(r)
            except: pass
    if cfg.get("welcome_channel"):
        ch = m.guild.get_channel(int(cfg["welcome_channel"]))
        if ch:
            msg = cfg.get("welcome_msg", "Willkommen {user}!") \
                .replace("{user}", m.mention) \
                .replace("{server}", m.guild.name) \
                .replace("{count}", str(m.guild.member_count))
            e = discord.Embed(description=msg, color=discord.Color.green())
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)
    if cfg.get("welcome_dm"):
        try:
            await m.send(embed=discord.Embed(
                title=f"Willkommen auf {m.guild.name}!",
                description=cfg.get("welcome_msg", "").replace("{user}", m.display_name),
                color=discord.Color.blurple()))
        except: pass

@bot.event
async def on_member_remove(m: discord.Member):
    cfg = await gcfg(m.guild.id)
    if cfg.get("goodbye_channel"):
        ch = m.guild.get_channel(int(cfg["goodbye_channel"]))
        if ch:
            msg = cfg.get("goodbye_msg", "{user} hat den Server verlassen.") \
                .replace("{user}", str(m)).replace("{server}", m.guild.name)
            e = discord.Embed(description=msg, color=discord.Color.red())
            e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

@bot.event
async def on_message(msg: discord.Message):
    if msg.author.bot or not msg.guild: return
    cfg = await gcfg(msg.guild.id)
    afk = await col("afk").find_one({"guild_id": msg.guild.id, "user_id": msg.author.id})
    if afk:
        await col("afk").delete_one({"_id": afk["_id"]})
        try: await msg.channel.send(f"👋 Willkommen zurück {msg.author.mention}!", delete_after=5)
        except: pass
    for mn in msg.mentions[:3]:
        au = await col("afk").find_one({"guild_id": msg.guild.id, "user_id": mn.id})
        if au:
            try: await msg.channel.send(f"💤 **{mn.display_name}** ist AFK: {au.get('grund','–')}", delete_after=10)
            except: pass
    tr = msg.content.lower().split()[0] if msg.content else ""
    if tr:
        cc = await col("custom_commands").find_one({"guild_id": msg.guild.id, "trigger": tr})
        if cc: await msg.channel.send(cc["response"])
    ck = (msg.guild.id, msg.author.id)
    now = time.monotonic()
    if now - coin_cd.get(ck, 0) >= 30:
        coin_cd[ck] = now
        await addcoins(msg.guild.id, msg.author.id, 1)
        if len(coin_cd) > 2000:
            del coin_cd[min(coin_cd, key=coin_cd.get)]
    am = cfg.get("automod", {})
    if am.get("enabled") and not msg.author.guild_permissions.manage_messages:
        for w in am.get("bad_words", []):
            if w.lower() in msg.content.lower():
                try:
                    await msg.delete()
                    await msg.channel.send(f"{msg.author.mention} Verbotenes Wort!", delete_after=5)
                except: pass
                return
        if am.get("caps") and len(msg.content) > 10 and sum(1 for c in msg.content if c.isupper()) / len(msg.content) > 0.7:
            try:
                await msg.delete()
                await msg.channel.send(f"{msg.author.mention} Keine Großbuchstaben!", delete_after=5)
            except: pass
            return
        if am.get("links") and __import__("re").search(r"https?://|discord\.gg/", msg.content):
            try:
                await msg.delete()
                await msg.channel.send(f"{msg.author.mention} Links nicht erlaubt!", delete_after=5)
            except: pass
            return
        if len(msg.mentions) >= am.get("mention_limit", 5):
            try:
                await msg.delete()
                await msg.author.timeout(discord.utils.utcnow() + timedelta(minutes=5), reason="Mention Spam")
                await msg.channel.send(f"{msg.author.mention} Mention Spam! 5 Min Timeout.", delete_after=5)
            except: pass
            return
        key = f"{msg.guild.id}:{msg.author.id}"
        tn = time.time()
        spam_tr[key] = [t for t in spam_tr[key] if tn - t < 5]
        spam_tr[key].append(tn)
        if len(spam_tr[key]) >= 5:
            try:
                await msg.author.timeout(discord.utils.utcnow() + timedelta(minutes=2), reason="Spam")
                await msg.channel.send(f"{msg.author.mention} Spam! 2 Min Timeout.", delete_after=5)
            except: pass
    await bot.process_commands(msg)

@bot.event
async def on_reaction_add(rx: discord.Reaction, u: discord.User):
    if u.bot or not rx.message.guild: return
    cfg = await gcfg(rx.message.guild.id)
    sid = cfg.get("starboard_channel")
    if sid and str(rx.emoji) == "⭐" and rx.count >= cfg.get("starboard_min", 3):
        sc = rx.message.guild.get_channel(int(sid))
        if sc and not await col("starboard").find_one({"message_id": rx.message.id}):
            e = discord.Embed(description=rx.message.content, color=discord.Color.gold())
            e.set_author(name=rx.message.author.display_name, icon_url=rx.message.author.display_avatar.url)
            e.add_field(name="Original", value=f"[Springe]({rx.message.jump_url})")
            if rx.message.attachments: e.set_image(url=rx.message.attachments[0].url)
            sm = await sc.send(f"⭐ **{rx.count}** | {rx.message.channel.mention}", embed=e)
            await col("starboard").insert_one({"message_id": rx.message.id, "sb_id": sm.id})

@bot.event
async def on_voice_state_update(m: discord.Member, b: discord.VoiceState, a: discord.VoiceState):
    if a.channel and not b.channel:
        await col("voice_stats").update_one(
            {"guild_id": m.guild.id, "user_id": m.id},
            {"$set": {"join_time": time.time()}}, upsert=True)
    elif not a.channel and b.channel:
        d = await col("voice_stats").find_one({"guild_id": m.guild.id, "user_id": m.id})
        if d and d.get("join_time"):
            mins = (time.time() - d["join_time"]) / 60
            await col("voice_stats").update_one(
                {"guild_id": m.guild.id, "user_id": m.id},
                {"$inc": {"total_minutes": mins}, "$unset": {"join_time": ""}})
            await addcoins(m.guild.id, m.id, int(mins * 2))

@bot.event
async def on_command_error(ctx, err):
    if isinstance(err, commands.CommandNotFound): return
    if isinstance(err, commands.MissingPermissions): await ctx.send("❌ Keine Berechtigung!")
    else: log.error(f"Cmd [{ctx.command}]: {err}")

@bot.tree.error
async def on_app_err(i: discord.Interaction, err: app_commands.AppCommandError):
    msg = "❌ Keine Berechtigung!" if isinstance(err, app_commands.CheckFailure) else "❌ Fehler!"
    log.error(f"Slash [{i.command}]: {err}")
    try:
        if i.response.is_done(): await i.followup.send(msg, ephemeral=True)
        else: await i.response.send_message(msg, ephemeral=True)
    except: pass

# ── Keep Alive ───────────────────────────────────────────────
async def kalive():
    if not RENDER_URL:
        log.warning("RENDER_EXTERNAL_URL not set")
        return
    await asyncio.sleep(60)
    import aiohttp
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{RENDER_URL}/health", timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200: log.info("Keep-alive OK")
        except Exception as ex:
            log.warning(f"Keep-alive: {ex}")
        await asyncio.sleep(540)

# ── Start ────────────────────────────────────────────────────
def run_dashboard():
    from app import create_app
    app = create_app(bot)
    log.info(f"Flask binding to port {PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)

async def main():
    # Start Flask FIRST so Render detects the port immediately
    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    # Give Flask a moment to bind the port
    await asyncio.sleep(2)
    log.info(f"Dashboard started on port {PORT}")
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
