"""
Shared utilities for bot cogs and dashboard.
Import from here instead of bot.py to avoid circular imports.
"""
import os, time, ast, operator
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB  = os.getenv("MONGODB_DB", "rld_main")

# ── MongoDB ──────────────────────────────────────────────────
from motor.motor_asyncio import AsyncIOMotorClient

_mc: Optional[AsyncIOMotorClient] = None

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
        "log_channel": None, "member_count_role": None,
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

# ── Discord permission checks ─────────────────────────────────
from discord import app_commands

def is_mod():
    async def p(i): return i.user.guild_permissions.kick_members or i.user.guild_permissions.administrator
    return app_commands.check(p)

def is_admin():
    async def p(i): return i.user.guild_permissions.administrator
    return app_commands.check(p)

# ── Mod log helper ────────────────────────────────────────────
import discord

async def _mlog(g, e, bot=None):
    cfg = await gcfg(g.id)
    cid = cfg.get("log_channels", {}).get("mod_log") or cfg.get("mod_log")
    if cid:
        ch = g.get_channel(int(cid))
        if ch:
            try: await ch.send(embed=e)
            except: pass
