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

# ── MongoDB ──────────────────────────────────────────────────
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional as Opt

_mc: Opt[AsyncIOMotorClient] = None

def get_mongo():
    global _mc
    if not _mc:
        _mc = AsyncIOMotorClient(MONGODB_URI, maxPoolSize=5, minPoolSize=0, serverSelectionTimeoutMS=5000)
    return _mc

def db():
    return get_mongo()[MONGODB_DB]

def col(n):
    return db()[n]

# Config cache
_ccache: dict = {}
_CTTL = 60

async def gcfg(gid: Optional[int]) -> dict:
    if not gid: return {}
    now = time.monotonic()
    if gid in _ccache:
        d, ts = _ccache[gid]
        if now - ts < _CTTL: return d
    d = await col("config").find_one({"guild_id": gid})
    if not d:
        d = _dcfg(gid)
        await col("config").insert_one(d)
    if len(_ccache) >= 50:
        del _ccache[min(_ccache, key=lambda k: _ccache[k][1])]
    _ccache[gid] = (d, now)
    return d

def ivcfg(gid: int):
    _ccache.pop(gid, None)

def _dcfg(gid: int) -> dict:
    return {
        "guild_id": gid, "prefix": "!", "mod_log": None,
        "welcome_channel": None, "welcome_msg": "Willkommen {user} auf {server}! 🎉",
        "goodbye_channel": None, "goodbye_msg": "{user} hat den Server verlassen.",
        "auto_role": None, "verify_role": None, "ticket_category": None,
        "ticket_team_role": None, "starboard_channel": None, "starboard_min": 3,
        "suggest_channel": None, "birthday_channel": None, "bump_channel": None,
        "automod": {"enabled": False, "spam": True, "links": False, "caps": False, "bad_words": [], "mention_limit": 5},
        "anti_raid": False, "welcome_dm": False, "stat_channels": {}, "shop": [],
        "slow_joiner_minutes": 0, "custom_bot_status": None, "afk_channel": None,
        "log_channel": None, "member_count_role": None, "rss_feeds": [],
        "welcome_bg": None, "goodbye_bg": None,
        "log_channels": {
            "ticket_log": None, "mod_log": None, "automod_log": None,
            "server_log": None, "member_log": None, "join_leave_log": None
        },
        "channel_presets": []
    }

async def heco(gid, uid):
    d = await col("economy").find_one({"guild_id": gid, "user_id": uid})
    if not d:
        d = {
            "guild_id": gid, "user_id": uid, "coins": 0, "bank": 0,
            "last_daily": None, "last_work": None, "last_fish": None,
            "last_mine": None, "streak": 0, "inventory": [], "rep": 0, "last_rep": None
        }
        await col("economy").insert_one(d)
    return d

async def addcoins(gid, uid, amt):
    await col("economy").update_one(
        {"guild_id": gid, "user_id": uid},
        {"$inc": {"coins": amt}}, upsert=True
    )

async def logcase(gid, mid, tid, act, grund) -> int:
    n = await col("cases").count_documents({"guild_id": gid}) + 1
    now = datetime.utcnow()
    e = {"guild_id": gid, "case": n, "mod_id": mid, "target_id": tid, "aktion": act, "grund": grund, "ts": now}
    await col("cases").insert_one(e)
    await col("logs").insert_one(e.copy())
    return n

async def _count(c, q): return await c.count_documents(q)
async def _find(c, q, sort=None, limit=50):
    cur = c.find(q)
    if sort: cur = cur.sort(*sort)
    return await cur.to_list(limit)
async def _findone(c, q): return await c.find_one(q)
async def _update(c, q, u, upsert=False): return await c.update_one(q, u, upsert=upsert)
async def _delete(c, q): return await c.delete_one(q)

def cdchk(last, hours: float) -> Optional[str]:
    if not last: return None
    if isinstance(last, str): last = datetime.fromisoformat(last)
    wait = timedelta(hours=hours) - (datetime.utcnow() - last)
    if wait.total_seconds() > 0:
        h, r = divmod(int(wait.total_seconds()), 3600)
        return f"{h}h {r//60}m"
    return None

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
    "cogs.misc",
    "cogs.help",
]

def is_mod():
    async def p(i): return i.user.guild_permissions.kick_members or i.user.guild_permissions.administrator
    return app_commands.check(p)

def is_admin():
    async def p(i): return i.user.guild_permissions.administrator
    return app_commands.check(p)

async def _mlog(g, e):
    cfg = await gcfg(g.id)
    cid = cfg.get("log_channels", {}).get("mod_log") or cfg.get("mod_log")
    if cid:
        ch = g.get_channel(int(cid))
        if ch:
            try: await ch.send(embed=e)
            except: pass

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
    from dashboard import create_app
    app = create_app(bot)
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)

async def main():
    threading.Thread(target=run_dashboard, daemon=True).start()
    log.info(f"Dashboard starting on port {PORT}")
    async with bot:
        await bot.start(DISCORD_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())