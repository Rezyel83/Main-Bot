import os,asyncio,threading,time,random,re,json,ast,operator,logging
from datetime import datetime,timedelta
from functools import wraps
from urllib.parse import quote
from collections import deque,defaultdict
from typing import Optional
from dotenv import load_dotenv
load_dotenv()

DISCORD_TOKEN        = os.getenv("DISCORD_TOKEN","")
DISCORD_CLIENT_ID    = os.getenv("DISCORD_CLIENT_ID","")
DISCORD_CLIENT_SECRET= os.getenv("DISCORD_CLIENT_SECRET","")
DISCORD_BOT_TOKEN    = os.getenv("DISCORD_BOT_TOKEN","")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI","http://localhost:10000/callback")
MONGODB_URI          = os.getenv("MONGODB_URI","")
MONGODB_DB           = os.getenv("MONGODB_DB","rld_main")
SECRET_KEY           = os.getenv("SECRET_KEY","")
RENDER_URL           = os.getenv("RENDER_EXTERNAL_URL","")
PORT                 = int(os.getenv("PORT","10000"))
TWITCH_ID            = os.getenv("TWITCH_CLIENT_ID","")
TWITCH_SECRET        = os.getenv("TWITCH_CLIENT_SECRET","")
for v,n in[(DISCORD_TOKEN,"DISCORD_TOKEN"),(MONGODB_URI,"MONGODB_URI"),(SECRET_KEY,"SECRET_KEY")]:
    if not v: raise RuntimeError(f"{n} env var missing!")

logging.basicConfig(level=logging.WARNING,format="%(levelname)s: %(message)s")
log=logging.getLogger("rld"); log.setLevel(logging.INFO)

# ── MongoDB ──────────────────────────────────────────────────
from motor.motor_asyncio import AsyncIOMotorClient
_mc:Optional[AsyncIOMotorClient]=None
def get_mongo():
    global _mc
    if not _mc: _mc=AsyncIOMotorClient(MONGODB_URI,maxPoolSize=5,minPoolSize=0,serverSelectionTimeoutMS=5000)
    return _mc
def db(): return get_mongo()[MONGODB_DB]
def col(n): return db()[n]

# Config cache 60s
_ccache:dict={}
_CTTL=60
async def gcfg(gid:Optional[int])->dict:
    if not gid: return {}
    now=time.monotonic()
    if gid in _ccache:
        d,ts=_ccache[gid]
        if now-ts<_CTTL: return d
    d=await col("config").find_one({"guild_id":gid})
    if not d:
        d=_dcfg(gid); await col("config").insert_one(d)
    if len(_ccache)>=50:
        del _ccache[min(_ccache,key=lambda k:_ccache[k][1])]
    _ccache[gid]=(d,now); return d
def ivcfg(gid:int): _ccache.pop(gid,None)
def _dcfg(gid:int)->dict:
    return{"guild_id":gid,"prefix":"!","mod_log":None,"welcome_channel":None,
           "welcome_msg":"Willkommen {user} auf {server}! 🎉","goodbye_channel":None,
           "goodbye_msg":"{user} hat den Server verlassen.","auto_role":None,"verify_role":None,
           "ticket_category":None,"ticket_team_role":None,"starboard_channel":None,"starboard_min":3,
           "suggest_channel":None,"birthday_channel":None,"bump_channel":None,
           "automod":{"enabled":False,"spam":True,"links":False,"caps":False,"bad_words":[],"mention_limit":5},
           "anti_raid":False,"welcome_dm":False,"stat_channels":{},"shop":[],"slow_joiner_minutes":0,
           "custom_bot_status":None,"afk_channel":None,"log_channel":None}

async def heco(gid,uid):
    d=await col("economy").find_one({"guild_id":gid,"user_id":uid})
    if not d:
        d={"guild_id":gid,"user_id":uid,"coins":0,"bank":0,"last_daily":None,"last_work":None,
           "last_fish":None,"last_mine":None,"streak":0,"inventory":[],"rep":0,"last_rep":None}
        await col("economy").insert_one(d)
    return d
async def addcoins(gid,uid,amt):
    await col("economy").update_one({"guild_id":gid,"user_id":uid},{"$inc":{"coins":amt}},upsert=True)
async def logcase(gid,mid,tid,act,grund)->int:
    n=await col("cases").count_documents({"guild_id":gid})+1
    now=datetime.utcnow()
    e={"guild_id":gid,"case":n,"mod_id":mid,"target_id":tid,"aktion":act,"grund":grund,"ts":now}
    await col("cases").insert_one(e); await col("logs").insert_one(e.copy()); return n

_OPS={ast.Add:operator.add,ast.Sub:operator.sub,ast.Mult:operator.mul,ast.Div:operator.truediv,
      ast.Pow:operator.pow,ast.Mod:operator.mod,ast.FloorDiv:operator.floordiv,
      ast.UAdd:operator.pos,ast.USub:operator.neg}
def sfeval(expr:str)->float:
    def _e(n):
        if isinstance(n,ast.Expression): return _e(n.body)
        if isinstance(n,ast.Constant) and isinstance(n.value,(int,float)): return n.value
        if isinstance(n,ast.BinOp):
            op=_OPS.get(type(n.op));
            if not op: raise ValueError()
            return op(_e(n.left),_e(n.right))
        if isinstance(n,ast.UnaryOp):
            op=_OPS.get(type(n.op));
            if not op: raise ValueError()
            return op(_e(n.operand))
        raise ValueError()
    return _e(ast.parse(expr,mode="eval"))

def cdchk(last,hours:float)->Optional[str]:
    if not last: return None
    if isinstance(last,str): last=datetime.fromisoformat(last)
    wait=timedelta(hours=hours)-(datetime.utcnow()-last)
    if wait.total_seconds()>0:
        h,r=divmod(int(wait.total_seconds()),3600); return f"{h}h {r//60}m"
    return None

# ── Discord Bot ──────────────────────────────────────────────
import discord
from discord.ext import commands,tasks
from discord import app_commands
intents=discord.Intents.all()
bot=commands.Bot(command_prefix="!",intents=intents,help_command=None)
start_t=datetime.utcnow()
recent_joins:deque=deque(maxlen=20)
spam_tr:dict=defaultdict(list)
coin_cd:dict={}

def is_mod():
    async def p(i): return i.user.guild_permissions.kick_members or i.user.guild_permissions.administrator
    return app_commands.check(p)
def is_admin():
    async def p(i): return i.user.guild_permissions.administrator
    return app_commands.check(p)
async def _mlog(g,e):
    cfg=await gcfg(g.id)
    if cfg.get("mod_log"):
        ch=g.get_channel(int(cfg["mod_log"]))
        if ch:
            try: await ch.send(embed=e)
            except: pass

@bot.event
async def on_ready():
    log.info(f"Bot: {bot.user}")
    try: s=await bot.tree.sync(); log.info(f"Synced {len(s)} cmds")
    except Exception as ex: log.error(ex)
    for lp in[reminder_loop,rss_loop,bday_loop,stat_loop,gw_loop,twitch_loop]: lp.start()
    asyncio.ensure_future(kalive())
    cfgs=await col("config").find({},{"custom_bot_status":1}).to_list(50)
    for c in cfgs:
        if c.get("custom_bot_status"):
            await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=c["custom_bot_status"])); return
    tot=sum((g.member_count or 0) for g in bot.guilds)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=f"{tot} Member | /help"))

@bot.event
async def on_member_join(m:discord.Member):
    cfg=await gcfg(m.guild.id)
    sm=cfg.get("slow_joiner_minutes",0)
    if sm>0:
        age=(datetime.utcnow()-m.created_at.replace(tzinfo=None)).total_seconds()/60
        if age<sm:
            try: await m.send(f"Account zu neu. Komm in {sm} Min wieder."); await m.kick(reason="Slow Joiner")
            except: pass
            return
    if cfg.get("anti_raid"):
        now=time.time(); recent_joins.append(now)
        if len([t for t in recent_joins if now-t<10])>=10:
            try: await m.kick(reason="Anti-Raid")
            except: pass
            return
    if cfg.get("auto_role"):
        r=m.guild.get_role(int(cfg["auto_role"]))
        if r:
            try: await m.add_roles(r)
            except: pass
    if cfg.get("welcome_channel"):
        ch=m.guild.get_channel(int(cfg["welcome_channel"]))
        if ch:
            msg=cfg.get("welcome_msg","Willkommen {user}!").replace("{user}",m.mention).replace("{server}",m.guild.name).replace("{count}",str(m.guild.member_count))
            e=discord.Embed(description=msg,color=discord.Color.green()); e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)
    if cfg.get("welcome_dm"):
        try: await m.send(embed=discord.Embed(title=f"Willkommen auf {m.guild.name}!",description=cfg.get("welcome_msg","").replace("{user}",m.display_name),color=discord.Color.blurple()))
        except: pass

@bot.event
async def on_member_remove(m:discord.Member):
    cfg=await gcfg(m.guild.id)
    if cfg.get("goodbye_channel"):
        ch=m.guild.get_channel(int(cfg["goodbye_channel"]))
        if ch:
            msg=cfg.get("goodbye_msg","{user} hat den Server verlassen.").replace("{user}",str(m)).replace("{server}",m.guild.name)
            e=discord.Embed(description=msg,color=discord.Color.red()); e.set_thumbnail(url=m.display_avatar.url)
            await ch.send(embed=e)

@bot.event
async def on_message(msg:discord.Message):
    if msg.author.bot or not msg.guild: return
    cfg=await gcfg(msg.guild.id)
    afk=await col("afk").find_one({"guild_id":msg.guild.id,"user_id":msg.author.id})
    if afk:
        await col("afk").delete_one({"_id":afk["_id"]})
        try: await msg.channel.send(f"👋 Willkommen zurück {msg.author.mention}!",delete_after=5)
        except: pass
    for mn in msg.mentions[:3]:
        au=await col("afk").find_one({"guild_id":msg.guild.id,"user_id":mn.id})
        if au:
            try: await msg.channel.send(f"💤 **{mn.display_name}** ist AFK: {au.get('grund','–')}",delete_after=10)
            except: pass
    tr=msg.content.lower().split()[0] if msg.content else ""
    if tr:
        cc=await col("custom_commands").find_one({"guild_id":msg.guild.id,"trigger":tr})
        if cc: await msg.channel.send(cc["response"])
    ck=(msg.guild.id,msg.author.id); now=time.monotonic()
    if now-coin_cd.get(ck,0)>=30:
        coin_cd[ck]=now; await addcoins(msg.guild.id,msg.author.id,1)
        if len(coin_cd)>2000: del coin_cd[min(coin_cd,key=coin_cd.get)]
    am=cfg.get("automod",{})
    if am.get("enabled") and not msg.author.guild_permissions.manage_messages:
        for w in am.get("bad_words",[]):
            if w.lower() in msg.content.lower():
                try: await msg.delete(); await msg.channel.send(f"{msg.author.mention} Verbotenes Wort!",delete_after=5)
                except: pass
                return
        if am.get("caps") and len(msg.content)>10 and sum(1 for c in msg.content if c.isupper())/len(msg.content)>0.7:
            try: await msg.delete(); await msg.channel.send(f"{msg.author.mention} Keine Großbuchstaben!",delete_after=5)
            except: pass
            return
        if am.get("links") and re.search(r"https?://|discord\.gg/",msg.content):
            try: await msg.delete(); await msg.channel.send(f"{msg.author.mention} Links nicht erlaubt!",delete_after=5)
            except: pass
            return
        if len(msg.mentions)>=am.get("mention_limit",5):
            try:
                await msg.delete()
                await msg.author.timeout(discord.utils.utcnow()+timedelta(minutes=5),reason="Mention Spam")
                await msg.channel.send(f"{msg.author.mention} Mention Spam! 5 Min Timeout.",delete_after=5)
            except: pass
            return
        key=f"{msg.guild.id}:{msg.author.id}"; tn=time.time()
        spam_tr[key]=[t for t in spam_tr[key] if tn-t<5]; spam_tr[key].append(tn)
        if len(spam_tr[key])>=5:
            try: await msg.author.timeout(discord.utils.utcnow()+timedelta(minutes=2),reason="Spam"); await msg.channel.send(f"{msg.author.mention} Spam! 2 Min Timeout.",delete_after=5)
            except: pass
    await bot.process_commands(msg)

@bot.event
async def on_reaction_add(rx:discord.Reaction,u:discord.User):
    if u.bot or not rx.message.guild: return
    cfg=await gcfg(rx.message.guild.id)
    sid=cfg.get("starboard_channel")
    if sid and str(rx.emoji)=="⭐" and rx.count>=cfg.get("starboard_min",3):
        sc=rx.message.guild.get_channel(int(sid))
        if sc and not await col("starboard").find_one({"message_id":rx.message.id}):
            e=discord.Embed(description=rx.message.content,color=discord.Color.gold())
            e.set_author(name=rx.message.author.display_name,icon_url=rx.message.author.display_avatar.url)
            e.add_field(name="Original",value=f"[Springe]({rx.message.jump_url})")
            if rx.message.attachments: e.set_image(url=rx.message.attachments[0].url)
            sm=await sc.send(f"⭐ **{rx.count}** | {rx.message.channel.mention}",embed=e)
            await col("starboard").insert_one({"message_id":rx.message.id,"sb_id":sm.id})

@bot.event
async def on_voice_state_update(m:discord.Member,b:discord.VoiceState,a:discord.VoiceState):
    if a.channel and not b.channel:
        await col("voice_stats").update_one({"guild_id":m.guild.id,"user_id":m.id},{"$set":{"join_time":time.time()}},upsert=True)
    elif not a.channel and b.channel:
        d=await col("voice_stats").find_one({"guild_id":m.guild.id,"user_id":m.id})
        if d and d.get("join_time"):
            mins=(time.time()-d["join_time"])/60
            await col("voice_stats").update_one({"guild_id":m.guild.id,"user_id":m.id},{"$inc":{"total_minutes":mins},"$unset":{"join_time":""}})
            await addcoins(m.guild.id,m.id,int(mins*2))

@bot.event
async def on_command_error(ctx,err):
    if isinstance(err,commands.CommandNotFound): return
    if isinstance(err,commands.MissingPermissions): await ctx.send("❌ Keine Berechtigung!")
    else: log.error(f"Cmd [{ctx.command}]: {err}")

@bot.tree.error
async def on_app_err(i:discord.Interaction,err:app_commands.AppCommandError):
    msg="❌ Keine Berechtigung!" if isinstance(err,app_commands.CheckFailure) else "❌ Fehler!"
    log.error(f"Slash [{i.command}]: {err}")
    try:
        if i.response.is_done(): await i.followup.send(msg,ephemeral=True)
        else: await i.response.send_message(msg,ephemeral=True)
    except: pass

# ── MOD ──────────────────────────────────────────────────────
@bot.tree.command(name="ban",description="User bannen.")
@is_mod()
async def ban_cmd(i:discord.Interaction,user:discord.Member,grund:str="Kein Grund",del_days:int=0):
    await i.response.defer()
    if user.top_role>=i.user.top_role: await i.followup.send("❌ Höhere Rolle!"); return
    try: await user.send(f"Du wurdest von **{i.guild.name}** gebannt. Grund: {grund}")
    except: pass
    await i.guild.ban(user,reason=grund,delete_message_days=del_days)
    n=await logcase(i.guild_id,i.user.id,user.id,"ban",grund)
    e=discord.Embed(title=f"🔨 Ban | Case #{n}",color=discord.Color.red())
    e.add_field(name="User",value=f"{user} ({user.id})"); e.add_field(name="Mod",value=i.user.mention); e.add_field(name="Grund",value=grund,inline=False)
    await i.followup.send(embed=e); await _mlog(i.guild,e)

@bot.tree.command(name="unban",description="User entbannen.")
@is_mod()
async def unban_cmd(i:discord.Interaction,user_id:str,grund:str="Kein Grund"):
    await i.response.defer()
    try: u=await bot.fetch_user(int(user_id)); await i.guild.unban(u,reason=grund); await i.followup.send(f"✅ **{u}** entbannt.")
    except: await i.followup.send("❌ User nicht gefunden.")

@bot.tree.command(name="kick",description="User kicken.")
@is_mod()
async def kick_cmd(i:discord.Interaction,user:discord.Member,grund:str="Kein Grund"):
    await i.response.defer()
    if user.top_role>=i.user.top_role: await i.followup.send("❌ Höhere Rolle!"); return
    try: await user.send(f"Du wurdest von **{i.guild.name}** gekickt. Grund: {grund}")
    except: pass
    await user.kick(reason=grund)
    n=await logcase(i.guild_id,i.user.id,user.id,"kick",grund)
    e=discord.Embed(title=f"👢 Kick | Case #{n}",color=discord.Color.orange())
    e.add_field(name="User",value=str(user)); e.add_field(name="Mod",value=i.user.mention); e.add_field(name="Grund",value=grund,inline=False)
    await i.followup.send(embed=e); await _mlog(i.guild,e)

@bot.tree.command(name="timeout",description="User timeout.")
@is_mod()
async def timeout_cmd(i:discord.Interaction,user:discord.Member,minuten:int,grund:str="Kein Grund"):
    await i.response.defer()
    await user.timeout(discord.utils.utcnow()+timedelta(minutes=minuten),reason=grund)
    n=await logcase(i.guild_id,i.user.id,user.id,"timeout",grund)
    e=discord.Embed(title=f"⏰ Timeout | Case #{n}",color=discord.Color.yellow())
    e.add_field(name="User",value=user.mention); e.add_field(name="Dauer",value=f"{minuten} Min"); e.add_field(name="Grund",value=grund,inline=False)
    await i.followup.send(embed=e); await _mlog(i.guild,e)

@bot.tree.command(name="untimeout",description="Timeout aufheben.")
@is_mod()
async def untimeout_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer()
    await user.timeout(None); await i.followup.send(f"✅ Timeout von {user.mention} aufgehoben.")

@bot.tree.command(name="warn",description="User verwarnen.")
@is_mod()
async def warn_cmd(i:discord.Interaction,user:discord.Member,grund:str):
    await i.response.defer()
    await col("warns").insert_one({"guild_id":i.guild_id,"user_id":user.id,"mod_id":i.user.id,"grund":grund,"ts":datetime.utcnow()})
    cnt=await col("warns").count_documents({"guild_id":i.guild_id,"user_id":user.id})
    n=await logcase(i.guild_id,i.user.id,user.id,"warn",grund)
    try: await user.send(f"Verwarnung auf **{i.guild.name}** Grund: {grund} (#{cnt})")
    except: pass
    e=discord.Embed(title=f"⚠️ Warn | Case #{n}",color=discord.Color.yellow())
    e.add_field(name="User",value=user.mention); e.add_field(name="Anzahl",value=str(cnt)); e.add_field(name="Grund",value=grund,inline=False)
    await i.followup.send(embed=e); await _mlog(i.guild,e)

@bot.tree.command(name="warns",description="Verwarnungen anzeigen.")
@is_mod()
async def warns_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer()
    ws=await col("warns").find({"guild_id":i.guild_id,"user_id":user.id}).sort("ts",-1).to_list(20)
    e=discord.Embed(title=f"⚠️ Warns: {user.display_name}",color=discord.Color.yellow())
    if not ws: e.description="Keine Verwarnungen."
    else:
        for idx,w in enumerate(ws,1):
            md=i.guild.get_member(w["mod_id"])
            e.add_field(name=f"#{idx} – {w['ts'].strftime('%d.%m.%Y')}",value=f"{w['grund']}\nMod: {md.mention if md else '?'}",inline=False)
    await i.followup.send(embed=e)

@bot.tree.command(name="unwarn",description="Letzte Verwarnung entfernen.")
@is_mod()
async def unwarn_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer()
    l=await col("warns").find_one({"guild_id":i.guild_id,"user_id":user.id},sort=[("ts",-1)])
    if not l: await i.followup.send("❌ Keine Verwarnungen."); return
    await col("warns").delete_one({"_id":l["_id"]}); await i.followup.send(f"✅ Letzte Warn von {user.mention} entfernt.")

@bot.tree.command(name="clearwarns",description="[Admin] Alle Warns löschen.")
@is_admin()
async def clearwarns_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer()
    r=await col("warns").delete_many({"guild_id":i.guild_id,"user_id":user.id}); await i.followup.send(f"✅ {r.deleted_count} Warns gelöscht.")

@bot.tree.command(name="case",description="Case anzeigen.")
@is_mod()
async def case_cmd(i:discord.Interaction,nummer:int):
    await i.response.defer()
    c=await col("cases").find_one({"guild_id":i.guild_id,"case":nummer})
    if not c: await i.followup.send("❌ Case nicht gefunden."); return
    md=i.guild.get_member(c["mod_id"]); tg=i.guild.get_member(c["target_id"])
    e=discord.Embed(title=f"📋 Case #{nummer}",color=discord.Color.blurple())
    e.add_field(name="Aktion",value=c["aktion"]); e.add_field(name="User",value=str(tg) if tg else str(c["target_id"])); e.add_field(name="Mod",value=md.mention if md else str(c["mod_id"]))
    e.add_field(name="Grund",value=c["grund"],inline=False); e.add_field(name="Datum",value=c["ts"].strftime("%d.%m.%Y %H:%M"))
    await i.followup.send(embed=e)

@bot.tree.command(name="clear",description="Nachrichten löschen.")
@is_mod()
async def clear_cmd(i:discord.Interaction,anzahl:int,user:Optional[discord.Member]=None):
    await i.response.defer(ephemeral=True)
    chk=(lambda m:m.author==user) if user else None
    d=await i.channel.purge(limit=min(anzahl,100),check=chk)
    await i.followup.send(f"✅ {len(d)} Nachrichten gelöscht.",ephemeral=True)

@bot.tree.command(name="slowmode",description="Slowmode setzen.")
@is_mod()
async def slowmode_cmd(i:discord.Interaction,sekunden:int):
    await i.response.defer()
    await i.channel.edit(slowmode_delay=sekunden); await i.followup.send(f"✅ Slowmode: **{sekunden}s**")

@bot.tree.command(name="lock",description="Kanal sperren.")
@is_mod()
async def lock_cmd(i:discord.Interaction):
    await i.response.defer()
    await i.channel.set_permissions(i.guild.default_role,send_messages=False); await i.followup.send("🔒 Gesperrt.")

@bot.tree.command(name="unlock",description="Kanal entsperren.")
@is_mod()
async def unlock_cmd(i:discord.Interaction):
    await i.response.defer()
    await i.channel.set_permissions(i.guild.default_role,send_messages=True); await i.followup.send("🔓 Entsperrt.")

@bot.tree.command(name="nick",description="Nickname ändern.")
@is_mod()
async def nick_cmd(i:discord.Interaction,user:discord.Member,name:str=""):
    await i.response.defer()
    await user.edit(nick=name or None); await i.followup.send(f"✅ Nick von {user.mention} geändert.")

@bot.tree.command(name="raid-mode",description="[Admin] Raid Mode an/aus.")
@is_admin()
async def raidmode_cmd(i:discord.Interaction,aktiv:bool):
    await i.response.defer()
    await col("config").update_one({"guild_id":i.guild_id},{"$set":{"anti_raid":aktiv}},upsert=True)
    ivcfg(i.guild_id); await i.followup.send(f"{'🚨 Raid Mode AKTIV' if aktiv else '✅ Raid Mode aus'}")

@bot.tree.command(name="purge-user",description="Alle Nachrichten eines Users löschen.")
@is_mod()
async def purge_cmd(i:discord.Interaction,user:discord.Member,limit:int=100):
    await i.response.defer(ephemeral=True)
    d=await i.channel.purge(limit=min(limit,500),check=lambda m:m.author==user)
    await i.followup.send(f"✅ {len(d)} Nachrichten von {user.display_name} gelöscht.",ephemeral=True)

# ── INFO ──────────────────────────────────────────────────────
@bot.tree.command(name="userinfo",description="User Informationen.")
async def userinfo_cmd(i:discord.Interaction,user:discord.Member=None):
    await i.response.defer()
    u=user or i.user
    wc=await col("warns").count_documents({"guild_id":i.guild_id,"user_id":u.id})
    eco=await heco(i.guild_id,u.id)
    e=discord.Embed(title=f"👤 {u.display_name}",color=u.color); e.set_thumbnail(url=u.display_avatar.url)
    e.add_field(name="ID",value=str(u.id)); e.add_field(name="Erstellt",value=u.created_at.strftime("%d.%m.%Y"))
    e.add_field(name="Beigetreten",value=u.joined_at.strftime("%d.%m.%Y") if u.joined_at else "?")
    e.add_field(name="Rollen",value=" ".join(r.mention for r in u.roles[1:]) or "Keine",inline=False)
    e.add_field(name="⚠️ Warns",value=str(wc)); e.add_field(name="💰 Coins",value=str(eco.get("coins",0)))
    vd=await col("voice_stats").find_one({"guild_id":i.guild_id,"user_id":u.id})
    if vd: e.add_field(name="🎙️ Voice Min",value=str(round(vd.get("total_minutes",0))))
    await i.followup.send(embed=e)

@bot.tree.command(name="serverinfo",description="Server Informationen.")
async def serverinfo_cmd(i:discord.Interaction):
    await i.response.defer()
    g=i.guild; e=discord.Embed(title=f"🏠 {g.name}",color=discord.Color.blurple())
    if g.icon: e.set_thumbnail(url=g.icon.url)
    e.add_field(name="ID",value=str(g.id)); e.add_field(name="Owner",value=str(g.owner)); e.add_field(name="Erstellt",value=g.created_at.strftime("%d.%m.%Y"))
    e.add_field(name="👥 Member",value=str(g.member_count)); e.add_field(name="💬 Kanäle",value=str(len(g.channels))); e.add_field(name="🎭 Rollen",value=str(len(g.roles)))
    e.add_field(name="Boost",value=f"Level {g.premium_tier} ({g.premium_subscription_count}x)")
    await i.followup.send(embed=e)

@bot.tree.command(name="avatar",description="Avatar anzeigen.")
async def avatar_cmd(i:discord.Interaction,user:Optional[discord.Member]=None):
    u=user or i.user; e=discord.Embed(title=f"🖼️ {u.display_name}",color=discord.Color.blurple()); e.set_image(url=u.display_avatar.url)
    await i.response.send_message(embed=e)

@bot.tree.command(name="ping",description="Bot Latenz.")
async def ping_cmd(i:discord.Interaction):
    up=datetime.utcnow()-start_t; h,r=divmod(int(up.total_seconds()),3600); m,s=divmod(r,60)
    await i.response.send_message(f"🏓 **{round(bot.latency*1000)}ms** | Uptime: {h}h {m}m {s}s")

@bot.tree.command(name="timestamp",description="Discord Timestamp erstellen.")
async def ts_cmd(i:discord.Interaction,datum:str,uhrzeit:str="00:00"):
    try:
        dt=datetime.strptime(f"{datum} {uhrzeit}","%d.%m.%Y %H:%M"); ts=int(dt.timestamp())
        e=discord.Embed(title="🕐 Timestamp",color=discord.Color.blurple())
        for lb,fm in[("Kurze Zeit","t"),("Lange Zeit","T"),("Datum","d"),("Datum+Zeit","f"),("Relativ","R")]:
            e.add_field(name=lb,value=f"`<t:{ts}:{fm}>` → <t:{ts}:{fm}>",inline=False)
        await i.response.send_message(embed=e)
    except: await i.response.send_message("❌ Format: DD.MM.YYYY und HH:MM")

@bot.tree.command(name="botinfo",description="Bot Informationen.")
async def botinfo_cmd(i:discord.Interaction):
    e=discord.Embed(title="🤖 RLD Main Bot",color=discord.Color.red())
    e.add_field(name="Server",value=str(len(bot.guilds))); e.add_field(name="User",value=str(sum(g.member_count or 0 for g in bot.guilds)))
    e.add_field(name="Ping",value=f"{round(bot.latency*1000)}ms"); e.add_field(name="Prefix",value="/ (Slash Commands)")
    e.set_footer(text="Dashboard: Renthol")
    await i.response.send_message(embed=e)

# ── FUN ───────────────────────────────────────────────────────
@bot.tree.command(name="8ball",description="Stelle eine Frage!")
async def ball_cmd(i:discord.Interaction,frage:str):
    ans=["Ja!","Definitiv ja!","Sehr wahrscheinlich.","Vielleicht.","Eher nicht.","Definitiv nein!","Frag später.","Ohne Zweifel!","Unmöglich."]
    e=discord.Embed(title="🎱 8Ball",color=discord.Color.purple())
    e.add_field(name="❓ Frage",value=frage,inline=False); e.add_field(name="🎱 Antwort",value=random.choice(ans),inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="coinflip",description="Münze werfen.")
async def coinflip_cmd(i:discord.Interaction):
    await i.response.send_message(f"🪙 **{random.choice(['Kopf 👑','Zahl 🔢'])}**")

@bot.tree.command(name="wuerfel",description="Würfel werfen.")
async def wuerfel_cmd(i:discord.Interaction,anzahl:int=1,seiten:int=6):
    a=min(max(anzahl,1),10); res=[random.randint(1,max(seiten,2)) for _ in range(a)]
    e=discord.Embed(title="🎲 Würfel",color=discord.Color.green())
    e.add_field(name="Ergebnisse",value=" | ".join(str(r) for r in res)); e.add_field(name="Summe",value=str(sum(res)))
    await i.response.send_message(embed=e)

@bot.tree.command(name="rps",description="Schere Stein Papier.")
async def rps_cmd(i:discord.Interaction,wahl:str):
    opts=["schere","stein","papier"]; wahl=wahl.lower()
    if wahl not in opts: await i.response.send_message("❌ schere, stein oder papier!"); return
    bw=random.choice(opts); em={"schere":"✂️","stein":"🪨","papier":"📄"}
    wins={("schere","papier"),("stein","schere"),("papier","stein")}
    res="🎉 Du gewinnst!" if (wahl,bw) in wins else("🤝 Unentschieden!" if wahl==bw else "😔 Bot gewinnt!")
    e=discord.Embed(title="✂️🪨📄 RPS",color=discord.Color.blurple())
    e.add_field(name="Du",value=em[wahl]); e.add_field(name="Bot",value=em[bw]); e.add_field(name="Ergebnis",value=res,inline=False)
    await i.response.send_message(embed=e)

@bot.tree.command(name="poll",description="Abstimmung erstellen.")
async def poll_cmd(i:discord.Interaction,frage:str,option1:str,option2:str,option3:str=None,option4:str=None):
    opts=[o for o in[option1,option2,option3,option4] if o]; ems=["1️⃣","2️⃣","3️⃣","4️⃣"]
    e=discord.Embed(title=f"📊 {frage}",description="\n".join(f"{ems[n]} {o}" for n,o in enumerate(opts)),color=discord.Color.blurple())
    e.set_footer(text=f"von {i.user.display_name}")
    await i.response.send_message(embed=e); msg=await i.original_response()
    for n in range(len(opts)): await msg.add_reaction(ems[n])

@bot.tree.command(name="calc",description="Rechnung ausführen.")
async def calc_cmd(i:discord.Interaction,rechnung:str):
    try: r=sfeval(rechnung.replace("^","**")); await i.response.send_message(f"🧮 `{rechnung}` = **{r}**")
    except: await i.response.send_message("❌ Ungültig! Erlaubt: + - * / ** % //")

@bot.tree.command(name="quote",description="Inspirierendes Zitat.")
async def quote_cmd(i:discord.Interaction):
    await i.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://zenquotes.io/api/random",timeout=aiohttp.ClientTimeout(total=8)) as r: d=await r.json()
        await i.followup.send(embed=discord.Embed(description=f'*"{d[0]["q"]}"*\n\n— **{d[0]["a"]}**',color=discord.Color.gold()))
    except: await i.followup.send("❌ Fehler.")

@bot.tree.command(name="meme",description="Zufälliges Meme.")
async def meme_cmd(i:discord.Interaction):
    await i.response.defer()
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://meme-api.com/gimme",timeout=aiohttp.ClientTimeout(total=8)) as r: d=await r.json()
        e=discord.Embed(title=d.get("title","Meme")[:250],color=discord.Color.random()); e.set_image(url=d.get("url")); e.set_footer(text=f"r/{d.get('subreddit','?')}")
        await i.followup.send(embed=e)
    except: await i.followup.send("❌ Fehler.")

# ── AFK ───────────────────────────────────────────────────────
@bot.tree.command(name="afk",description="AFK setzen.")
async def afk_cmd(i:discord.Interaction,grund:str="AFK"):
    await i.response.defer()
    await col("afk").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$set":{"grund":grund,"ts":datetime.utcnow()}},upsert=True)
    await i.followup.send(f"💤 AFK gesetzt: *{grund}*")

@bot.tree.command(name="afk-list",description="Alle AFK User anzeigen.")
async def afk_list_cmd(i:discord.Interaction):
    await i.response.defer()
    al=await col("afk").find({"guild_id":i.guild_id}).to_list(30)
    e=discord.Embed(title="💤 AFK User",color=discord.Color.blurple())
    if not al: e.description="Niemand ist AFK."
    else:
        for a in al:
            m=i.guild.get_member(a["user_id"]); e.add_field(name=m.display_name if m else str(a["user_id"]),value=a.get("grund","AFK"),inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="remindme",description="Erinnerung setzen.")
async def remind_cmd(i:discord.Interaction,zeit:str,nachricht:str):
    await i.response.defer(ephemeral=True)
    mt=re.match(r"(\d+)(m|h|d)",zeit.lower())
    if not mt: await i.followup.send("❌ Format: 10m, 2h, 1d",ephemeral=True); return
    a,u=int(mt.group(1)),mt.group(2)
    dl={"m":timedelta(minutes=a),"h":timedelta(hours=a),"d":timedelta(days=a)}[u]
    await col("reminders").insert_one({"user_id":i.user.id,"channel_id":i.channel_id,"nachricht":nachricht,"remind_at":datetime.utcnow()+dl,"done":False})
    await i.followup.send(f"⏰ Erinnerung in **{zeit}**: *{nachricht}*",ephemeral=True)

@tasks.loop(minutes=1)
async def reminder_loop():
    due=await col("reminders").find({"done":False,"remind_at":{"$lte":datetime.utcnow()}}).to_list(30)
    for r in due:
        try:
            ch=bot.get_channel(r["channel_id"]); u=await bot.fetch_user(r["user_id"])
            if ch: await ch.send(f"⏰ {u.mention} Erinnerung: **{r['nachricht']}**")
            await col("reminders").update_one({"_id":r["_id"]},{"$set":{"done":True}})
        except: pass

# ── ECONOMY ───────────────────────────────────────────────────
@bot.tree.command(name="eco-balance",description="Kontostand anzeigen.")
async def bal_cmd(i:discord.Interaction,user:discord.Member=None):
    await i.response.defer(); z=user or i.user; eco=await heco(i.guild_id,z.id)
    e=discord.Embed(title=f"💰 {z.display_name}",color=discord.Color.gold())
    e.add_field(name="👛 Wallet",value=f"{eco.get('coins',0)} Coins"); e.add_field(name="🏦 Bank",value=f"{eco.get('bank',0)} Coins")
    e.add_field(name="💎 Gesamt",value=f"{eco.get('coins',0)+eco.get('bank',0)} Coins"); e.add_field(name="⭐ Rep",value=str(eco.get("rep",0)))
    await i.followup.send(embed=e)

@bot.tree.command(name="eco-deposit",description="Coins in die Bank einzahlen.")
async def deposit_cmd(i:discord.Interaction,menge:int):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    if menge<=0 or eco.get("coins",0)<menge: await i.followup.send("❌ Ungültiger Betrag!"); return
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":-menge,"bank":menge}})
    await i.followup.send(f"🏦 **{menge} Coins** eingezahlt.")

@bot.tree.command(name="eco-withdraw",description="Coins aus der Bank abheben.")
async def withdraw_cmd(i:discord.Interaction,menge:int):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    if menge<=0 or eco.get("bank",0)<menge: await i.followup.send("❌ Ungültiger Betrag!"); return
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":menge,"bank":-menge}})
    await i.followup.send(f"💳 **{menge} Coins** abgehoben.")

@bot.tree.command(name="eco-daily",description="Tägliche Coins.")
async def daily_cmd(i:discord.Interaction):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    wt=cdchk(eco.get("last_daily"),20)
    if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
    last=eco.get("last_daily"); st=eco.get("streak",0)
    if last:
        diff=datetime.utcnow()-(last if isinstance(last,datetime) else datetime.fromisoformat(str(last)))
        st=st+1 if diff<timedelta(hours=48) else 1
    else: st=1
    amt=200+st*10
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":amt},"$set":{"last_daily":datetime.utcnow(),"streak":st}})
    await i.followup.send(embed=discord.Embed(title="💰 Daily!",description=f"+**{amt} Coins** | 🔥 Streak: **{st}**",color=discord.Color.gold()))

@bot.tree.command(name="eco-work",description="Arbeiten gehen.")
async def work_cmd(i:discord.Interaction):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    wt=cdchk(eco.get("last_work"),4)
    if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
    jobs=["Pizza geliefert 🍕","Code geschrieben 💻","Rocket League gespielt 🚗","Stream moderiert 🎮","Designs erstellt 🎨"]
    amt=random.randint(50,150)
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":amt},"$set":{"last_work":datetime.utcnow()}})
    await i.followup.send(f"💼 {random.choice(jobs)} → **+{amt} Coins**")

@bot.tree.command(name="eco-fish",description="Angeln.")
async def fish_cmd(i:discord.Interaction):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    wt=cdchk(eco.get("last_fish"),2)
    if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
    fi=[("🦐 Garnele",10),("🐟 Fisch",30),("🐠 Tropenfisch",50),("🐡 Kugelfisch",70),("🦈 Hai",200),("👢 Stiefel",0),("🗑️ Müll",0)]
    f,v=random.choice(fi)
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":v},"$set":{"last_fish":datetime.utcnow()}})
    await i.followup.send(f"🎣 Du hast **{f}** gefangen!"+( f" → **+{v} Coins**" if v else " → Nichts wert."))

@bot.tree.command(name="eco-mine",description="Schürfen.")
async def mine_cmd(i:discord.Interaction):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    wt=cdchk(eco.get("last_mine"),2)
    if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
    mi=[("🪨 Stein",5),("⛏️ Kohle",20),("🪙 Kupfer",40),("🔩 Eisen",60),("🥇 Gold",150),("💎 Diamant",300)]
    m,v=random.choice(mi)
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":v},"$set":{"last_mine":datetime.utcnow()}})
    await i.followup.send(f"⛏️ Du hast **{m}** gefunden! → **+{v} Coins**")

@bot.tree.command(name="eco-gamble",description="Coins setzen.")
async def gamble_cmd(i:discord.Interaction,menge:int):
    await i.response.defer()
    if menge<=0: await i.followup.send("❌ Ungültig!"); return
    eco=await heco(i.guild_id,i.user.id)
    if eco.get("coins",0)<menge: await i.followup.send("❌ Nicht genug Coins!"); return
    if random.random()>0.5: await addcoins(i.guild_id,i.user.id,menge); await i.followup.send(f"🎰 Gewonnen! **+{menge} Coins**")
    else: await addcoins(i.guild_id,i.user.id,-menge); await i.followup.send(f"🎰 Verloren! **-{menge} Coins**")

@bot.tree.command(name="eco-rob",description="Coins stehlen.")
async def rob_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer()
    if user.id==i.user.id: await i.followup.send("❌ Nicht möglich!"); return
    v=await heco(i.guild_id,user.id)
    if v.get("coins",0)<100: await i.followup.send("❌ Opfer hat zu wenig!"); return
    if random.random()>0.4:
        st=random.randint(50,min(500,v["coins"])); await addcoins(i.guild_id,user.id,-st); await addcoins(i.guild_id,i.user.id,st)
        await i.followup.send(f"🦹 **{st} Coins** gestohlen!")
    else:
        fn=random.randint(100,300); await addcoins(i.guild_id,i.user.id,-fn); await i.followup.send(f"👮 Erwischt! **-{fn} Coins**")

@bot.tree.command(name="eco-pay",description="Coins transferieren.")
async def pay_cmd(i:discord.Interaction,user:discord.Member,menge:int):
    await i.response.defer()
    if menge<=0: await i.followup.send("❌ Ungültig!"); return
    eco=await heco(i.guild_id,i.user.id)
    if eco.get("coins",0)<menge: await i.followup.send("❌ Nicht genug!"); return
    await addcoins(i.guild_id,i.user.id,-menge); await addcoins(i.guild_id,user.id,menge)
    await i.followup.send(f"✅ **{menge} Coins** an {user.mention}!")

@bot.tree.command(name="eco-leaderboard",description="Reichste User.")
async def lb_cmd(i:discord.Interaction):
    await i.response.defer(); top=await col("economy").find({"guild_id":i.guild_id}).sort("coins",-1).limit(10).to_list(10)
    e=discord.Embed(title="💰 Reichste User",color=discord.Color.gold()); md=["🥇","🥈","🥉"]
    lines=[]
    for idx,u in enumerate(top):
        mb=i.guild.get_member(u["user_id"]); nm=mb.display_name if mb else f"User {u['user_id']}"
        lines.append(f"{md[idx] if idx<3 else f'**{idx+1}.**'} {nm} — {u.get('coins',0)} Coins")
    e.description="\n".join(lines) or "Keine Daten."; await i.followup.send(embed=e)

@bot.tree.command(name="eco-slots",description="Slot Machine.")
async def slots_cmd(i:discord.Interaction,einsatz:int):
    await i.response.defer()
    if einsatz<=0: await i.followup.send("❌ Ungültig!"); return
    eco=await heco(i.guild_id,i.user.id)
    if eco.get("coins",0)<einsatz: await i.followup.send("❌ Nicht genug!"); return
    sym=["🍒","🍋","🍊","🍇","⭐","💎","7️⃣"]; res=[random.choice(sym) for _ in range(3)]
    if res[0]==res[1]==res[2]:
        mt={"💎":10,"7️⃣":7,"⭐":5}.get(res[0],3); gw=einsatz*mt
        await addcoins(i.guild_id,i.user.id,gw); msg=f"🎰 {''.join(res)}\n🎉 JACKPOT! **+{gw} Coins**"
    elif res[0]==res[1] or res[1]==res[2]:
        await addcoins(i.guild_id,i.user.id,einsatz); msg=f"🎰 {''.join(res)}\n✅ Zwei gleiche! **+{einsatz} Coins**"
    else:
        await addcoins(i.guild_id,i.user.id,-einsatz); msg=f"🎰 {''.join(res)}\n❌ **-{einsatz} Coins**"
    await i.followup.send(msg)

@bot.tree.command(name="eco-rep",description="Rep geben.")
async def rep_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer()
    if user.id==i.user.id: await i.followup.send("❌ Keine Selbst-Rep!"); return
    eco=await heco(i.guild_id,i.user.id); wt=cdchk(eco.get("last_rep"),24)
    if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":user.id},{"$inc":{"rep":1}},upsert=True)
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$set":{"last_rep":datetime.utcnow()}})
    await i.followup.send(f"⭐ {user.mention} +1 Rep!")

@bot.tree.command(name="eco-shop",description="Shop anzeigen.")
async def shop_cmd(i:discord.Interaction):
    await i.response.defer(); cfg=await gcfg(i.guild_id); items=cfg.get("shop",[])
    if not items: await i.followup.send("❌ Shop leer."); return
    e=discord.Embed(title="🛒 Shop",color=discord.Color.green())
    for it in items: e.add_field(name=f"{it['name']} – {it['price']} Coins",value=it.get("description","–"),inline=False)
    await i.followup.send(embed=e)

@bot.tree.command(name="eco-buy",description="Item kaufen.")
async def buy_cmd(i:discord.Interaction,item_name:str):
    await i.response.defer(); cfg=await gcfg(i.guild_id)
    it=next((x for x in cfg.get("shop",[]) if x["name"].lower()==item_name.lower()),None)
    if not it: await i.followup.send("❌ Item nicht gefunden."); return
    eco=await heco(i.guild_id,i.user.id)
    if eco.get("coins",0)<it["price"]: await i.followup.send("❌ Nicht genug Coins!"); return
    await col("economy").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$inc":{"coins":-it["price"]},"$push":{"inventory":it["name"]}})
    if it.get("role_id"):
        r=i.guild.get_role(int(it["role_id"]))
        if r:
            try: await i.user.add_roles(r)
            except: pass
    await i.followup.send(f"✅ **{it['name']}** gekauft!")

@bot.tree.command(name="eco-inventory",description="Inventar anzeigen.")
async def inv_cmd(i:discord.Interaction):
    await i.response.defer(); eco=await heco(i.guild_id,i.user.id)
    inv=eco.get("inventory",[]); e=discord.Embed(title=f"🎒 Inventar von {i.user.display_name}",color=discord.Color.blurple())
    e.description="\n".join(inv) if inv else "Leer."; await i.followup.send(embed=e)

# ── GIVEAWAY ──────────────────────────────────────────────────
@bot.tree.command(name="giveaway-start",description="[Admin] Giveaway starten.")
@is_admin()
async def gw_cmd(i:discord.Interaction,preis:str,dauer:str,gewinner:int=1,rolle:discord.Role=None):
    await i.response.defer()
    mt=re.match(r"(\d+)(m|h|d)",dauer.lower())
    if not mt: await i.followup.send("❌ Format: 10m, 2h, 1d"); return
    a,u=int(mt.group(1)),mt.group(2); dl={"m":timedelta(minutes=a),"h":timedelta(hours=a),"d":timedelta(days=a)}[u]
    ea=datetime.utcnow()+dl
    e=discord.Embed(title="🎉 GIVEAWAY",description=f"**Preis:** {preis}\n**Gewinner:** {gewinner}\n**Endet:** <t:{int(ea.timestamp())}:R>\n\nReagiere mit 🎉!",color=discord.Color.gold())
    if rolle: e.add_field(name="Rolle",value=rolle.mention)
    msg=await i.channel.send(embed=e); await msg.add_reaction("🎉")
    await col("giveaways").insert_one({"guild_id":i.guild_id,"channel_id":i.channel_id,"message_id":msg.id,"preis":preis,"gewinner":gewinner,"rolle_id":rolle.id if rolle else None,"ends_at":ea,"active":True})
    await i.followup.send("✅ Giveaway gestartet!",ephemeral=True)

@bot.tree.command(name="giveaway-reroll",description="[Admin] Neuen Gewinner.")
@is_admin()
async def gwreroll_cmd(i:discord.Interaction,message_id:str):
    await i.response.defer()
    gw=await col("giveaways").find_one({"message_id":int(message_id)})
    if not gw: await i.followup.send("❌ Nicht gefunden."); return
    ch=i.guild.get_channel(gw["channel_id"]); msg=await ch.fetch_message(gw["message_id"])
    rx=discord.utils.get(msg.reactions,emoji="🎉")
    us=[u async for u in rx.users() if not u.bot]
    if not us: await i.followup.send("❌ Keine Teilnehmer."); return
    w=random.choice(us); await i.followup.send(f"🎉 Neuer Gewinner: {w.mention}!")

@tasks.loop(minutes=1)
async def gw_loop():
    ac=await col("giveaways").find({"active":True,"ends_at":{"$lte":datetime.utcnow()}}).to_list(10)
    for gw in ac:
        try:
            g=bot.get_guild(gw["guild_id"]); ch=g.get_channel(gw["channel_id"]); msg=await ch.fetch_message(gw["message_id"])
            rx=discord.utils.get(msg.reactions,emoji="🎉"); us=[u async for u in rx.users() if not u.bot]
            if gw.get("rolle_id"):
                rl=g.get_role(gw["rolle_id"])
                if rl: us=[u for u in us if rl in (g.get_member(u.id).roles if g.get_member(u.id) else [])]
            ws=random.sample(us,min(gw["gewinner"],len(us))) if us else []
            e=discord.Embed(title="🎉 Giveaway Beendet!",description=f"**Preis:** {gw['preis']}\n**Gewinner:** {', '.join(w.mention for w in ws) if ws else 'Niemand'}",color=discord.Color.green())
            await msg.edit(embed=e)
            if ws: await ch.send(f"🎉 {', '.join(w.mention for w in ws)} gewinnen **{gw['preis']}**!")
            await col("giveaways").update_one({"_id":gw["_id"]},{"$set":{"active":False}})
        except Exception as ex: log.error(f"GW: {ex}")

# ── SUGGEST ───────────────────────────────────────────────────
@bot.tree.command(name="suggest",description="Vorschlag einreichen.")
async def suggest_cmd(i:discord.Interaction,vorschlag:str):
    await i.response.defer(ephemeral=True); cfg=await gcfg(i.guild_id); cid=cfg.get("suggest_channel")
    if not cid: await i.followup.send("❌ Suggest-Kanal nicht konfiguriert!"); return
    ch=i.guild.get_channel(int(cid))
    e=discord.Embed(title="💡 Vorschlag",description=vorschlag,color=discord.Color.blurple()); e.set_footer(text=f"von {i.user.display_name}")
    msg=await ch.send(embed=e); await msg.add_reaction("✅"); await msg.add_reaction("❌")
    await col("suggestions").insert_one({"guild_id":i.guild_id,"user_id":i.user.id,"vorschlag":vorschlag,"message_id":msg.id,"status":"offen","ts":datetime.utcnow()})
    await i.followup.send("✅ Vorschlag eingereicht!")

@bot.tree.command(name="suggest-accept",description="[Admin] Vorschlag annehmen.")
@is_admin()
async def sugg_acc(i:discord.Interaction,message_id:str,grund:str=""):
    await i.response.defer(); sg=await col("suggestions").find_one({"message_id":int(message_id)})
    if not sg: await i.followup.send("❌ Nicht gefunden."); return
    cfg=await gcfg(i.guild_id); ch=i.guild.get_channel(int(cfg.get("suggest_channel",0) or 0))
    if ch:
        try:
            msg=await ch.fetch_message(int(message_id))
            e=discord.Embed(title="✅ Angenommen",description=sg["vorschlag"],color=discord.Color.green())
            if grund: e.add_field(name="Grund",value=grund)
            await msg.edit(embed=e)
        except: pass
    await col("suggestions").update_one({"_id":sg["_id"]},{"$set":{"status":"angenommen"}}); await i.followup.send("✅ Angenommen!")

@bot.tree.command(name="suggest-deny",description="[Admin] Vorschlag ablehnen.")
@is_admin()
async def sugg_deny(i:discord.Interaction,message_id:str,grund:str=""):
    await i.response.defer(); sg=await col("suggestions").find_one({"message_id":int(message_id)})
    if not sg: await i.followup.send("❌ Nicht gefunden."); return
    cfg=await gcfg(i.guild_id); ch=i.guild.get_channel(int(cfg.get("suggest_channel",0) or 0))
    if ch:
        try:
            msg=await ch.fetch_message(int(message_id))
            e=discord.Embed(title="❌ Abgelehnt",description=sg["vorschlag"],color=discord.Color.red())
            if grund: e.add_field(name="Grund",value=grund)
            await msg.edit(embed=e)
        except: pass
    await col("suggestions").update_one({"_id":sg["_id"]},{"$set":{"status":"abgelehnt"}}); await i.followup.send("✅ Abgelehnt!")

# ── BIRTHDAY ──────────────────────────────────────────────────
@bot.tree.command(name="geburtstag",description="Geburtstag eintragen.")
async def bday_cmd(i:discord.Interaction,datum:str):
    try:
        datetime.strptime(datum,"%d.%m")
        await col("birthdays").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$set":{"datum":datum}},upsert=True)
        await i.response.send_message(f"🎂 Geburtstag: **{datum}**",ephemeral=True)
    except: await i.response.send_message("❌ Format: DD.MM",ephemeral=True)

@bot.tree.command(name="geburtstag-liste",description="Alle Geburtstage anzeigen.")
async def bday_list_cmd(i:discord.Interaction):
    await i.response.defer()
    bs=await col("birthdays").find({"guild_id":i.guild_id}).sort("datum",1).to_list(50)
    e=discord.Embed(title="🎂 Geburtstage",color=discord.Color.pink())
    if not bs: e.description="Keine eingetragen."
    else:
        for b in bs:
            m=i.guild.get_member(b["user_id"]); e.add_field(name=b["datum"],value=m.mention if m else str(b["user_id"]),inline=True)
    await i.followup.send(embed=e)

@tasks.loop(hours=24)
async def bday_loop():
    today=datetime.utcnow().strftime("%d.%m")
    bs=await col("birthdays").find({"datum":today}).to_list(100)
    for b in bs:
        g=bot.get_guild(b["guild_id"])
        if not g: continue
        cfg=await gcfg(b["guild_id"]); cid=cfg.get("birthday_channel")
        if not cid: continue
        ch=g.get_channel(int(cid));
        if not ch: continue
        m=g.get_member(b["user_id"])
        if not m: continue
        e=discord.Embed(title="🎂 Herzlichen Glückwunsch!",description=f"{m.mention} hat heute Geburtstag! 🎉",color=discord.Color.pink())
        await ch.send(embed=e)

# ── TICKET ────────────────────────────────────────────────────
class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎫 Ticket erstellen",style=discord.ButtonStyle.primary,custom_id="create_ticket")
    async def create(self,i:discord.Interaction,b:discord.ui.Button):
        await i.response.defer(ephemeral=True)
        cfg=await gcfg(i.guild_id)
        ex=discord.utils.get(i.guild.channels,name=f"ticket-{i.user.name.lower()}")
        if ex: await i.followup.send(f"Bereits offen: {ex.mention}",ephemeral=True); return
        cat=i.guild.get_channel(int(cfg["ticket_category"])) if cfg.get("ticket_category") else None
        ow={i.guild.default_role:discord.PermissionOverwrite(read_messages=False),i.user:discord.PermissionOverwrite(read_messages=True,send_messages=True)}
        if cfg.get("ticket_team_role"):
            r=i.guild.get_role(int(cfg["ticket_team_role"]))
            if r: ow[r]=discord.PermissionOverwrite(read_messages=True,send_messages=True)
        ch=await i.guild.create_text_channel(f"ticket-{i.user.name.lower()}",category=cat,overwrites=ow)
        await col("tickets").insert_one({"guild_id":i.guild_id,"channel_id":ch.id,"user_id":i.user.id,"open":True,"created_at":datetime.utcnow()})
        e=discord.Embed(title="🎫 Ticket",description=f"Hallo {i.user.mention}! Schreib dein Anliegen.",color=discord.Color.green())
        await ch.send(embed=e,view=CloseTicketView()); await i.followup.send(f"✅ {ch.mention}",ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🔒 Schließen",style=discord.ButtonStyle.danger,custom_id="close_ticket")
    async def close(self,i:discord.Interaction,b:discord.ui.Button):
        await i.response.defer()
        await col("tickets").update_one({"channel_id":i.channel_id},{"$set":{"open":False}})
        await i.channel.send("🔒 Wird in 5s gelöscht..."); await asyncio.sleep(5); await i.channel.delete()

@bot.tree.command(name="ticket-setup",description="[Admin] Ticket-Panel erstellen.")
@is_admin()
async def tsetup_cmd(i:discord.Interaction,titel:str="Support",beschreibung:str="Klicke um ein Ticket zu öffnen."):
    e=discord.Embed(title=f"🎫 {titel}",description=beschreibung,color=discord.Color.blurple())
    await i.channel.send(embed=e,view=TicketView()); await i.response.send_message("✅ Panel erstellt!",ephemeral=True)

@bot.tree.command(name="ticket-team",description="[Admin] Ticket Team-Rolle setzen.")
@is_admin()
async def tteam_cmd(i:discord.Interaction,rolle:discord.Role,kategorie:discord.CategoryChannel=None):
    await i.response.defer()
    upd={"ticket_team_role":rolle.id}
    if kategorie: upd["ticket_category"]=kategorie.id
    await col("config").update_one({"guild_id":i.guild_id},{"$set":upd},upsert=True); ivcfg(i.guild_id)
    await i.followup.send(f"✅ Ticket Team: {rolle.mention}")

@bot.tree.command(name="ticket-list",description="[Mod] Offene Tickets anzeigen.")
@is_mod()
async def tlist_cmd(i:discord.Interaction):
    await i.response.defer()
    ts=await col("tickets").find({"guild_id":i.guild_id,"open":True}).to_list(20)
    e=discord.Embed(title="🎫 Offene Tickets",color=discord.Color.blurple())
    if not ts: e.description="Keine offenen Tickets."
    else:
        for t in ts:
            m=i.guild.get_member(t["user_id"]); ch=i.guild.get_channel(t["channel_id"])
            e.add_field(name=ch.name if ch else str(t["channel_id"]),value=m.mention if m else str(t["user_id"]),inline=True)
    await i.followup.send(embed=e)

# ── VERIFY ────────────────────────────────────────────────────
class VerifyView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="✅ Verifizieren",style=discord.ButtonStyle.success,custom_id="verify_button")
    async def verify(self,i:discord.Interaction,b:discord.ui.Button):
        cfg=await gcfg(i.guild_id); rid=cfg.get("verify_role")
        if not rid: await i.response.send_message("❌ Keine Rolle konfiguriert!",ephemeral=True); return
        r=i.guild.get_role(int(rid))
        if not r: await i.response.send_message("❌ Rolle nicht gefunden!",ephemeral=True); return
        if r in i.user.roles: await i.response.send_message("✅ Bereits verifiziert!",ephemeral=True); return
        await i.user.add_roles(r); await i.response.send_message("✅ Verifiziert!",ephemeral=True)

@bot.tree.command(name="verify-setup",description="[Admin] Verifizierungs-Panel.")
@is_admin()
async def vsetup_cmd(i:discord.Interaction,rolle:discord.Role,titel:str="Verifizierung",text:str="Klicke den Button um dich zu verifizieren."):
    await col("config").update_one({"guild_id":i.guild_id},{"$set":{"verify_role":rolle.id}},upsert=True); ivcfg(i.guild_id)
    e=discord.Embed(title=f"✅ {titel}",description=text,color=discord.Color.green())
    await i.channel.send(embed=e,view=VerifyView()); await i.response.send_message("✅ Panel erstellt!",ephemeral=True)

@bot.tree.command(name="verify-role",description="[Admin] Verify-Rolle ändern.")
@is_admin()
async def vrole_cmd(i:discord.Interaction,rolle:discord.Role):
    await i.response.defer()
    await col("config").update_one({"guild_id":i.guild_id},{"$set":{"verify_role":rolle.id}},upsert=True); ivcfg(i.guild_id)
    await i.followup.send(f"✅ Verify-Rolle: {rolle.mention}")

# ── TEAM & BEWERBUNGEN ────────────────────────────────────────
@bot.tree.command(name="team-add",description="[Admin] User zum Team.")
@is_admin()
async def tadd_cmd(i:discord.Interaction,user:discord.Member,rolle:str="Moderator"):
    await col("team").update_one({"guild_id":i.guild_id,"user_id":user.id},{"$set":{"guild_id":i.guild_id,"user_id":user.id,"rolle":rolle,"joined":datetime.utcnow(),"aktiv":True}},upsert=True)
    await i.response.send_message(f"✅ {user.mention} → **{rolle}**")

@bot.tree.command(name="team-remove",description="[Admin] User aus Team entfernen.")
@is_admin()
async def tremove_cmd(i:discord.Interaction,user:discord.Member):
    await col("team").delete_one({"guild_id":i.guild_id,"user_id":user.id}); await i.response.send_message(f"✅ {user.mention} entfernt.")

@bot.tree.command(name="team",description="Team anzeigen.")
async def team_cmd(i:discord.Interaction):
    await i.response.defer()
    ms=await col("team").find({"guild_id":i.guild_id,"aktiv":True}).to_list(50)
    e=discord.Embed(title="👥 Team",color=discord.Color.blurple())
    if not ms: e.description="Kein Team."
    else:
        for m in ms:
            u=i.guild.get_member(m["user_id"]); e.add_field(name=m.get("rolle","Mitglied"),value=u.mention if u else str(m["user_id"]),inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="abmelden",description="Abwesenheit eintragen.")
async def abmeld_cmd(i:discord.Interaction,von:str,bis:str,grund:str="Kein Grund"):
    m=await col("team").find_one({"guild_id":i.guild_id,"user_id":i.user.id})
    if not m: await i.response.send_message("❌ Kein Team-Mitglied!",ephemeral=True); return
    await col("team").update_one({"guild_id":i.guild_id,"user_id":i.user.id},{"$push":{"abmeldungen":{"von":von,"bis":bis,"grund":grund,"ts":datetime.utcnow()}}})
    await i.response.send_message(f"✅ Abmeldung: **{von}** bis **{bis}**",ephemeral=True)

@bot.tree.command(name="bewerben",description="Fürs Team bewerben.")
async def bewerb_cmd(i:discord.Interaction,alter:str,erfahrung:str,warum:str,verfuegbarkeit:str):
    await i.response.defer(ephemeral=True)
    ex=await col("applications").find_one({"guild_id":i.guild_id,"user_id":i.user.id,"status":"offen"})
    if ex: await i.followup.send("❌ Offene Bewerbung vorhanden!"); return
    await col("applications").insert_one({"guild_id":i.guild_id,"user_id":i.user.id,"alter":alter,"erfahrung":erfahrung,"warum":warum,"verfuegbarkeit":verfuegbarkeit,"status":"offen","ts":datetime.utcnow()})
    cfg=await gcfg(i.guild_id)
    if cfg.get("mod_log"):
        ch=i.guild.get_channel(int(cfg["mod_log"]))
        if ch:
            e=discord.Embed(title="📝 Neue Bewerbung",color=discord.Color.blurple())
            e.add_field(name="User",value=i.user.mention); e.add_field(name="Alter",value=alter)
            e.add_field(name="Erfahrung",value=erfahrung,inline=False); e.add_field(name="Warum",value=warum,inline=False)
            e.add_field(name="Verfügbarkeit",value=verfuegbarkeit); await ch.send(embed=e)
    await i.followup.send("✅ Bewerbung eingereicht!")

@bot.tree.command(name="bewerbungen",description="[Admin] Bewerbungen anzeigen.")
@is_admin()
async def bewerbungen_cmd(i:discord.Interaction):
    await i.response.defer(); apps=await col("applications").find({"guild_id":i.guild_id,"status":"offen"}).to_list(20)
    if not apps: await i.followup.send("Keine offenen Bewerbungen."); return
    e=discord.Embed(title="📝 Bewerbungen",color=discord.Color.blurple())
    for a in apps:
        u=i.guild.get_member(a["user_id"]); e.add_field(name=str(u) if u else str(a["user_id"]),value=f"Alter: {a['alter']}\n{a['verfuegbarkeit']}",inline=True)
    await i.followup.send(embed=e)

@bot.tree.command(name="bewerbung-accept",description="[Admin] Bewerbung annehmen.")
@is_admin()
async def bacc_cmd(i:discord.Interaction,user:discord.Member):
    await i.response.defer(); ap=await col("applications").find_one({"guild_id":i.guild_id,"user_id":user.id,"status":"offen"})
    if not ap: await i.followup.send("❌ Keine offene Bewerbung."); return
    await col("applications").update_one({"_id":ap["_id"]},{"$set":{"status":"angenommen"}})
    try: await user.send(f"🎉 Bewerbung auf **{i.guild.name}** angenommen!")
    except: pass
    await i.followup.send(f"✅ {user.mention} angenommen!")

@bot.tree.command(name="bewerbung-deny",description="[Admin] Bewerbung ablehnen.")
@is_admin()
async def bdeny_cmd(i:discord.Interaction,user:discord.Member,grund:str="Kein Grund"):
    await i.response.defer(); ap=await col("applications").find_one({"guild_id":i.guild_id,"user_id":user.id,"status":"offen"})
    if not ap: await i.followup.send("❌ Keine offene Bewerbung."); return
    await col("applications").update_one({"_id":ap["_id"]},{"$set":{"status":"abgelehnt"}})
    try: await user.send(f"❌ Bewerbung auf **{i.guild.name}** abgelehnt. Grund: {grund}")
    except: pass
    await i.followup.send("✅ Abgelehnt.")

# ── RL TEAMS ──────────────────────────────────────────────────
@bot.tree.command(name="rl-team-erstellen",description="RL Team erstellen.")
async def rlcreate_cmd(i:discord.Interaction,name:str,format:str="3v3"):
    await i.response.defer()
    if await col("rl_teams").find_one({"guild_id":i.guild_id,"captain_id":i.user.id}): await i.followup.send("❌ Du hast bereits ein Team!"); return
    await col("rl_teams").insert_one({"guild_id":i.guild_id,"name":name,"format":format,"captain_id":i.user.id,"members":[i.user.id],"wins":0,"losses":0,"created":datetime.utcnow()})
    await i.followup.send(f"✅ Team **{name}** ({format}) erstellt!")

@bot.tree.command(name="rl-team-join",description="RL Team beitreten.")
async def rljoin_cmd(i:discord.Interaction,team_name:str):
    await i.response.defer(); t=await col("rl_teams").find_one({"guild_id":i.guild_id,"name":team_name})
    if not t: await i.followup.send("❌ Nicht gefunden."); return
    if i.user.id in t["members"]: await i.followup.send("❌ Bereits drin!"); return
    await col("rl_teams").update_one({"_id":t["_id"]},{"$push":{"members":i.user.id}}); await i.followup.send(f"✅ Team **{team_name}** beigetreten!")

@bot.tree.command(name="rl-team-leave",description="RL Team verlassen.")
async def rlleave_cmd(i:discord.Interaction):
    await i.response.defer(); t=await col("rl_teams").find_one({"guild_id":i.guild_id,"members":i.user.id})
    if not t: await i.followup.send("❌ Du bist in keinem Team."); return
    if t["captain_id"]==i.user.id: await i.followup.send("❌ Captain kann nicht verlassen. Nutze /rl-team-disband."); return
    await col("rl_teams").update_one({"_id":t["_id"]},{"$pull":{"members":i.user.id}}); await i.followup.send("✅ Team verlassen.")

@bot.tree.command(name="rl-team-disband",description="RL Team auflösen.")
async def rldisband_cmd(i:discord.Interaction):
    await i.response.defer(); t=await col("rl_teams").find_one({"guild_id":i.guild_id,"captain_id":i.user.id})
    if not t: await i.followup.send("❌ Du hast kein Team."); return
    await col("rl_teams").delete_one({"_id":t["_id"]}); await i.followup.send("✅ Team aufgelöst.")

@bot.tree.command(name="rl-teams",description="Alle RL Teams anzeigen.")
async def rlteams_cmd(i:discord.Interaction):
    await i.response.defer(); ts=await col("rl_teams").find({"guild_id":i.guild_id}).to_list(20)
    if not ts: await i.followup.send("Keine Teams."); return
    e=discord.Embed(title="🚗 RL Teams",color=discord.Color.orange())
    for t in ts:
        cap=i.guild.get_member(t["captain_id"]); e.add_field(name=f"{t['name']} ({t['format']})",value=f"Captain: {cap.mention if cap else '?'}\nMember: {len(t['members'])} | W/L: {t['wins']}/{t['losses']}",inline=False)
    await i.followup.send(embed=e)

@bot.tree.command(name="rl-team-result",description="[Admin] RL Team Ergebnis eintragen.")
@is_admin()
async def rlresult_cmd(i:discord.Interaction,team_name:str,gewonnen:bool):
    await i.response.defer(); t=await col("rl_teams").find_one({"guild_id":i.guild_id,"name":team_name})
    if not t: await i.followup.send("❌ Nicht gefunden."); return
    if gewonnen: await col("rl_teams").update_one({"_id":t["_id"]},{"$inc":{"wins":1}})
    else: await col("rl_teams").update_one({"_id":t["_id"]},{"$inc":{"losses":1}})
    await i.followup.send(f"✅ Ergebnis für **{team_name}** eingetragen.")

# ── CUSTOM CMDS ───────────────────────────────────────────────
@bot.tree.command(name="cmd-add",description="[Admin] Custom Command erstellen.")
@is_admin()
async def cmdadd(i:discord.Interaction,trigger:str,antwort:str):
    await col("custom_commands").update_one({"guild_id":i.guild_id,"trigger":trigger.lower()},{"$set":{"response":antwort}},upsert=True)
    await i.response.send_message(f"✅ `{trigger}` erstellt!")

@bot.tree.command(name="cmd-remove",description="[Admin] Custom Command entfernen.")
@is_admin()
async def cmdremove(i:discord.Interaction,trigger:str):
    await col("custom_commands").delete_one({"guild_id":i.guild_id,"trigger":trigger.lower()}); await i.response.send_message(f"✅ `{trigger}` entfernt!")

@bot.tree.command(name="cmd-list",description="Custom Commands anzeigen.")
async def cmdlist(i:discord.Interaction):
    await i.response.defer(); cs=await col("custom_commands").find({"guild_id":i.guild_id}).to_list(50)
    if not cs: await i.followup.send("Keine Commands."); return
    e=discord.Embed(title="⚙️ Custom Commands",color=discord.Color.blurple())
    e.description="\n".join(f"`{c['trigger']}` → {c['response'][:50]}" for c in cs); await i.followup.send(embed=e)

# ── RSS ───────────────────────────────────────────────────────
@bot.tree.command(name="rss-add",description="[Admin] RSS Feed hinzufügen.")
@is_admin()
async def rssadd(i:discord.Interaction,name:str,url:str,kanal:discord.TextChannel):
    await i.response.defer()
    import feedparser; p=feedparser.parse(url)
    if not p.entries: await i.followup.send("❌ Ungültiger Feed!"); return
    await col("rss_feeds").insert_one({"guild_id":i.guild_id,"name":name,"url":url,"channel_id":kanal.id,"aktiv":True,"added":datetime.utcnow()})
    await i.followup.send(f"✅ RSS **{name}** → {kanal.mention}")

@bot.tree.command(name="rss-remove",description="[Admin] RSS Feed entfernen.")
@is_admin()
async def rssremove(i:discord.Interaction,name:str):
    r=await col("rss_feeds").delete_one({"guild_id":i.guild_id,"name":name})
    await i.response.send_message("✅ Entfernt." if r.deleted_count else "❌ Nicht gefunden.")

@bot.tree.command(name="rss-list",description="RSS Feeds anzeigen.")
async def rsslist(i:discord.Interaction):
    await i.response.defer(); fs=await col("rss_feeds").find({"guild_id":i.guild_id}).to_list(20)
    if not fs: await i.followup.send("Keine Feeds."); return
    e=discord.Embed(title="📰 RSS Feeds",color=discord.Color.blurple())
    for f in fs:
        ch=i.guild.get_channel(f["channel_id"]); e.add_field(name=f"{'✅' if f.get('aktiv') else '⏸️'} {f['name']}",value=ch.mention if ch else "?",inline=False)
    await i.followup.send(embed=e)

@tasks.loop(minutes=15)
async def rss_loop():
    import feedparser; fs=await col("rss_feeds").find({"aktiv":True}).to_list(30)
    for feed in fs:
        try:
            p=feedparser.parse(feed["url"]); g=bot.get_guild(feed["guild_id"])
            if not g: continue
            ch=g.get_channel(feed["channel_id"])
            if not ch: continue
            for entry in p.entries[:3]:
                link=entry.get("link","")
                if not link or await col("rss_seen").find_one({"feed_id":str(feed["_id"]),"link":link}): continue
                e=discord.Embed(title=entry.get("title","")[:250],url=link,description=entry.get("summary","")[:300],color=discord.Color.blurple())
                e.set_footer(text=f"📰 {feed.get('name','RSS')}"); await ch.send(embed=e)
                await col("rss_seen").insert_one({"feed_id":str(feed["_id"]),"link":link,"ts":datetime.utcnow()})
        except Exception as ex: log.error(f"RSS: {ex}")

# ── NOTIFICATIONS ─────────────────────────────────────────────
@bot.tree.command(name="notif-twitch",description="[Admin] Twitch Notification.")
@is_admin()
async def ntwitch(i:discord.Interaction,streamer:str,kanal:discord.TextChannel,nachricht:str="{streamer} ist jetzt live! 🎮"):
    await col("notifications").update_one({"guild_id":i.guild_id,"type":"twitch","name":streamer.lower()},{"$set":{"channel_id":kanal.id,"message":nachricht,"live":False}},upsert=True)
    await i.response.send_message(f"✅ Twitch: **{streamer}** → {kanal.mention}")

@bot.tree.command(name="notif-list",description="Notifications anzeigen.")
@is_mod()
async def nlist(i:discord.Interaction):
    await i.response.defer(); ns=await col("notifications").find({"guild_id":i.guild_id}).to_list(20)
    if not ns: await i.followup.send("Keine Notifications."); return
    e=discord.Embed(title="🔔 Notifications",color=discord.Color.purple())
    for n in ns:
        ch=i.guild.get_channel(n["channel_id"]); e.add_field(name=f"{n['type']}: {n['name']}",value=ch.mention if ch else "?",inline=True)
    await i.followup.send(embed=e)

@tasks.loop(minutes=5)
async def twitch_loop():
    if not TWITCH_ID or not TWITCH_SECRET: return
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post("https://id.twitch.tv/oauth2/token",params={"client_id":TWITCH_ID,"client_secret":TWITCH_SECRET,"grant_type":"client_credentials"},timeout=aiohttp.ClientTimeout(total=10)) as r: td=await r.json()
            token=td.get("access_token")
            if not token: return
            st=await col("notifications").find({"type":"twitch"}).to_list(50)
            for sr in st:
                async with s.get(f"https://api.twitch.tv/helix/streams?user_login={sr['name']}",headers={"Client-ID":TWITCH_ID,"Authorization":f"Bearer {token}"},timeout=aiohttp.ClientTimeout(total=8)) as r: d=await r.json()
                il=bool(d.get("data")); wl=sr.get("live",False)
                if il and not wl:
                    g=bot.get_guild(sr["guild_id"])
                    if g:
                        ch=g.get_channel(sr["channel_id"])
                        if ch:
                            stream=d["data"][0]; msg=sr.get("message","{streamer} ist live!").replace("{streamer}",sr["name"])
                            e=discord.Embed(title=stream.get("title","Live!"),url=f"https://twitch.tv/{sr['name']}",color=discord.Color.purple())
                            e.add_field(name="Spiel",value=stream.get("game_name","?")); e.add_field(name="Zuschauer",value=str(stream.get("viewer_count",0)))
                            await ch.send(msg,embed=e)
                await col("notifications").update_one({"_id":sr["_id"]},{"$set":{"live":il}})
    except Exception as ex: log.error(f"Twitch: {ex}")

# ── STAT CHANNELS ─────────────────────────────────────────────
@bot.tree.command(name="stat-channel",description="[Admin] Statistik-Kanal.")
@is_admin()
async def statch_cmd(i:discord.Interaction,kanal:discord.VoiceChannel,typ:str):
    await col("config").update_one({"guild_id":i.guild_id},{"$set":{f"stat_channels.{typ}":kanal.id}},upsert=True); ivcfg(i.guild_id)
    await i.response.send_message(f"✅ Stat-Kanal ({typ}) → {kanal.mention}")

@tasks.loop(minutes=10)
async def stat_loop():
    cfgs=await col("config").find({"stat_channels":{"$exists":True,"$ne":{}}},{"guild_id":1,"stat_channels":1}).to_list(50)
    for cfg in cfgs:
        g=bot.get_guild(cfg["guild_id"])
        if not g: continue
        for typ,cid in cfg.get("stat_channels",{}).items():
            ch=g.get_channel(int(cid))
            if not ch: continue
            try:
                if typ=="members": await ch.edit(name=f"👥 Member: {g.member_count}")
                elif typ=="bots": await ch.edit(name=f"🤖 Bots: {sum(1 for m in g.members if m.bot)}")
                elif typ=="roles": await ch.edit(name=f"🎭 Rollen: {len(g.roles)}")
                elif typ=="channels": await ch.edit(name=f"💬 Kanäle: {len(g.channels)}")
            except: pass

# ── SETUP ─────────────────────────────────────────────────────
async def cfgu(gid,f): await col("config").update_one({"guild_id":gid},{"$set":f},upsert=True); ivcfg(gid)

@bot.tree.command(name="setup-welcome",description="[Admin] Willkommen einrichten.")
@is_admin()
async def swelcome(i:discord.Interaction,kanal:discord.TextChannel,nachricht:str="Willkommen {user} auf {server}! 🎉"):
    await i.response.defer(); await cfgu(i.guild_id,{"welcome_channel":kanal.id,"welcome_msg":nachricht}); await i.followup.send(f"✅ Willkommen → {kanal.mention}")

@bot.tree.command(name="setup-goodbye",description="[Admin] Abschied einrichten.")
@is_admin()
async def sgoodbye(i:discord.Interaction,kanal:discord.TextChannel,nachricht:str="{user} hat den Server verlassen."):
    await i.response.defer(); await cfgu(i.guild_id,{"goodbye_channel":kanal.id,"goodbye_msg":nachricht}); await i.followup.send(f"✅ Abschied → {kanal.mention}")

@bot.tree.command(name="setup-autorole",description="[Admin] Auto-Rolle.")
@is_admin()
async def sautorole(i:discord.Interaction,rolle:discord.Role):
    await i.response.defer(); await cfgu(i.guild_id,{"auto_role":rolle.id}); await i.followup.send(f"✅ Auto-Rolle: {rolle.mention}")

@bot.tree.command(name="setup-modlog",description="[Admin] Mod-Log Kanal.")
@is_admin()
async def smodlog(i:discord.Interaction,kanal:discord.TextChannel):
    await i.response.defer(); await cfgu(i.guild_id,{"mod_log":kanal.id}); await i.followup.send(f"✅ Mod-Log → {kanal.mention}")

@bot.tree.command(name="setup-automod",description="[Admin] Auto-Mod.")
@is_admin()
async def sautomod(i:discord.Interaction,aktiviert:bool,spam:bool=True,links:bool=False,caps:bool=False,mention_limit:int=5):
    await i.response.defer(); await cfgu(i.guild_id,{"automod":{"enabled":aktiviert,"spam":spam,"links":links,"caps":caps,"bad_words":[],"mention_limit":mention_limit}})
    await i.followup.send(f"✅ Auto-Mod {'an' if aktiviert else 'aus'}.")

@bot.tree.command(name="setup-starboard",description="[Admin] Starboard.")
@is_admin()
async def sstarboard(i:discord.Interaction,kanal:discord.TextChannel,min_sterne:int=3):
    await i.response.defer(); await cfgu(i.guild_id,{"starboard_channel":kanal.id,"starboard_min":min_sterne}); await i.followup.send(f"✅ Starboard → {kanal.mention}")

@bot.tree.command(name="setup-suggest",description="[Admin] Suggest-Kanal.")
@is_admin()
async def ssuggest(i:discord.Interaction,kanal:discord.TextChannel):
    await i.response.defer(); await cfgu(i.guild_id,{"suggest_channel":kanal.id}); await i.followup.send(f"✅ Suggest → {kanal.mention}")

@bot.tree.command(name="setup-birthday",description="[Admin] Geburtstags-Kanal.")
@is_admin()
async def sbday(i:discord.Interaction,kanal:discord.TextChannel):
    await i.response.defer(); await cfgu(i.guild_id,{"birthday_channel":kanal.id}); await i.followup.send(f"✅ Geburtstag → {kanal.mention}")

@bot.tree.command(name="setup-slowjoiner",description="[Admin] Slow Joiner Schutz.")
@is_admin()
async def sslowjoin(i:discord.Interaction,minuten:int):
    await i.response.defer(); await cfgu(i.guild_id,{"slow_joiner_minutes":minuten}); await i.followup.send(f"✅ Slow Joiner: **{minuten} Min**")

@bot.tree.command(name="setup-welcomedm",description="[Admin] Welcome DM an/aus.")
@is_admin()
async def swelcomedm(i:discord.Interaction,aktiv:bool):
    await i.response.defer(); await cfgu(i.guild_id,{"welcome_dm":aktiv}); await i.followup.send(f"✅ Welcome DM: {'an' if aktiv else 'aus'}")

@bot.tree.command(name="setup-bot-status",description="[Admin] Bot Status.")
@is_admin()
async def sbstatus(i:discord.Interaction,status:str):
    await i.response.defer(); await cfgu(i.guild_id,{"custom_bot_status":status})
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,name=status)); await i.followup.send(f"✅ Status: **{status}**")

@bot.tree.command(name="badword-add",description="[Admin] Verbotenes Wort.")
@is_admin()
async def bwadd(i:discord.Interaction,wort:str):
    await col("config").update_one({"guild_id":i.guild_id},{"$addToSet":{"automod.bad_words":wort.lower()}},upsert=True); ivcfg(i.guild_id)
    await i.response.send_message(f"✅ `{wort}` zur Blacklist.",ephemeral=True)

@bot.tree.command(name="badword-remove",description="[Admin] Verbotenes Wort entfernen.")
@is_admin()
async def bwremove(i:discord.Interaction,wort:str):
    await col("config").update_one({"guild_id":i.guild_id},{"$pull":{"automod.bad_words":wort.lower()}},upsert=True); ivcfg(i.guild_id)
    await i.response.send_message(f"✅ `{wort}` entfernt.",ephemeral=True)

@bot.tree.command(name="eco-shop-add",description="[Admin] Shop Item.")
@is_admin()
async def shopadd(i:discord.Interaction,name:str,preis:int,beschreibung:str="",rolle:discord.Role=None):
    it={"name":name,"price":preis,"description":beschreibung}
    if rolle: it["role_id"]=str(rolle.id)
    await col("config").update_one({"guild_id":i.guild_id},{"$push":{"shop":it}},upsert=True); ivcfg(i.guild_id)
    await i.response.send_message(f"✅ **{name}** für {preis} Coins!")

# ── PREFIX CMDS ───────────────────────────────────────────────
@bot.command(name="mute")
@commands.has_permissions(kick_members=True)
async def mute_p(ctx,user:discord.Member,minuten:int=10,*,grund:str="Kein Grund"):
    await user.timeout(discord.utils.utcnow()+timedelta(minutes=minuten),reason=grund); await ctx.send(f"⏰ {user.mention} für **{minuten} Min** gemutet.")

@bot.command(name="unmute")
@commands.has_permissions(kick_members=True)
async def unmute_p(ctx,user:discord.Member):
    await user.timeout(None); await ctx.send(f"✅ {user.mention} entmutet.")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear_p(ctx,anzahl:int=10):
    d=await ctx.channel.purge(limit=min(anzahl+1,101)); await ctx.send(f"✅ {len(d)-1} Nachrichten gelöscht.",delete_after=3)

# ── HELP ──────────────────────────────────────────────────────
@bot.tree.command(name="help",description="Alle Commands.")
async def help_cmd(i:discord.Interaction):
    e=discord.Embed(title="📖 RLD Main Bot – Commands",color=discord.Color.red())
    e.add_field(name="🛡️ Moderation",value="`/ban` `/unban` `/kick` `/timeout` `/untimeout` `/warn` `/warns` `/unwarn` `/clearwarns` `/case` `/clear` `/slowmode` `/lock` `/unlock` `/nick` `/purge-user` `/raid-mode`",inline=False)
    e.add_field(name="ℹ️ Info",value="`/userinfo` `/serverinfo` `/avatar` `/ping` `/timestamp` `/botinfo`",inline=False)
    e.add_field(name="🎮 Fun",value="`/8ball` `/coinflip` `/wuerfel` `/rps` `/quote` `/poll` `/calc` `/meme`",inline=False)
    e.add_field(name="💤 AFK / ⏰ Reminder",value="`/afk` `/afk-list` `/remindme`",inline=False)
    e.add_field(name="💰 Economy",value="`/eco-balance` `/eco-deposit` `/eco-withdraw` `/eco-daily` `/eco-work` `/eco-fish` `/eco-mine` `/eco-gamble` `/eco-rob` `/eco-pay` `/eco-slots` `/eco-rep` `/eco-shop` `/eco-buy` `/eco-inventory` `/eco-leaderboard`",inline=False)
    e.add_field(name="🎉 Giveaway",value="`/giveaway-start` `/giveaway-reroll`",inline=False)
    e.add_field(name="💡 Suggestions",value="`/suggest` `/suggest-accept` `/suggest-deny`",inline=False)
    e.add_field(name="🎂 Geburtstag",value="`/geburtstag` `/geburtstag-liste`",inline=False)
    e.add_field(name="🎫 Ticket",value="`/ticket-setup` `/ticket-team` `/ticket-list`",inline=False)
    e.add_field(name="✅ Verify",value="`/verify-setup` `/verify-role`",inline=False)
    e.add_field(name="👥 Team & Bewerbungen",value="`/team` `/team-add` `/team-remove` `/abmelden` `/bewerben` `/bewerbungen` `/bewerbung-accept` `/bewerbung-deny`",inline=False)
    e.add_field(name="🚗 RL Teams",value="`/rl-team-erstellen` `/rl-team-join` `/rl-team-leave` `/rl-team-disband` `/rl-teams` `/rl-team-result`",inline=False)
    e.add_field(name="📰 RSS / 🔔 Notifications",value="`/rss-add` `/rss-remove` `/rss-list` `/notif-twitch` `/notif-list`",inline=False)
    e.add_field(name="⚙️ Setup",value="`/setup-welcome` `/setup-goodbye` `/setup-autorole` `/setup-modlog` `/setup-automod` `/setup-starboard` `/setup-suggest` `/setup-birthday` `/setup-slowjoiner` `/setup-welcomedm` `/setup-bot-status` `/stat-channel` `/badword-add` `/badword-remove` `/eco-shop-add` `/cmd-add` `/cmd-remove` `/cmd-list` `/ticket-team` `/verify-role`",inline=False)
    await i.response.send_message(embed=e)

# ── FLASK DASHBOARD ───────────────────────────────────────────
from flask import Flask,render_template_string,request,redirect,session,url_for,flash,jsonify
import requests as hr
fa=Flask(__name__)
fa.secret_key=SECRET_KEY
fa.config.update(SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",PERMANENT_SESSION_LIFETIME=timedelta(hours=12))
DAPI="https://discord.com/api/v10"

def dget(ep,token=None,isbot=False):
    hd={"User-Agent":"RLD/1.0"}
    if isbot: hd["Authorization"]=f"Bot {DISCORD_BOT_TOKEN}"
    elif token: hd["Authorization"]=f"Bearer {token}"
    else: return None
    try: r=hr.get(f"{DAPI}{ep}",headers=hd,timeout=6); return r.json() if r.ok else None
    except: return None

_ugc:dict={}; _bgc:tuple=([], 0.0); _GTTL=60

def uguilds(tok)->list:
    now=time.monotonic()
    if tok in _ugc:
        d,ts=_ugc[tok]
        if now-ts<_GTTL: return d
    d=dget("/users/@me/guilds",token=tok) or []
    if len(_ugc)>100: del _ugc[min(_ugc,key=lambda k:_ugc[k][1])]
    _ugc[tok]=(d,now); return d

def bguilds()->list:
    global _bgc
    now=time.monotonic()
    if now-_bgc[1]<_GTTL: return _bgc[0]
    d=dget("/users/@me/guilds",isbot=True) or []; _bgc=(d,now); return d

def lreq(f):
    @wraps(f)
    def dec(*a,**kw):
        if "user_id" not in session: return redirect(url_for("dlogin"))
        return f(*a,**kw)
    return dec

def greq(f):
    @wraps(f)
    def dec(*a,**kw):
        gid=kw.get("gid")
        if not gid: return redirect(url_for("dash"))
        ug=uguilds(session.get("access_token",""))
        bg={g["id"] for g in bguilds()}
        # KEY FIX: check if bot is in guild using bot guild list
        ug2=next((g for g in ug if g["id"]==gid),None)
        if not ug2: flash("Kein Zugriff.","error"); return redirect(url_for("dash"))
        if gid not in bg: flash("Bot ist nicht auf diesem Server.","error"); return redirect(url_for("dash"))
        p=int(ug2.get("permissions",0))
        if not(p&0x8 or p&0x20): flash("Keine Rechte.","error"); return redirect(url_for("dash"))
        return f(*a,**kw)
    return dec

# CSS
_C="""*{margin:0;padding:0;box-sizing:border-box}
:root{--r:#ef4444;--rd:#dc2626;--bg:#0f0f0f;--bg2:#1a1a1a;--bg3:#262626;--tx:#fff;--tx2:#a1a1aa;--bdr:#333}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;line-height:1.6}a{color:inherit;text-decoration:none}
.nav{background:var(--bg2);border-bottom:1px solid var(--bdr);padding:.875rem 1.5rem;display:flex;justify-content:space-between;align-items:center;position:sticky;top:0;z-index:100}
.logo{font-size:1.1rem;font-weight:700;color:var(--r)}.nav-r{display:flex;gap:.75rem;align-items:center;color:var(--tx2)}
.wrap{display:flex;min-height:calc(100vh - 53px)}.side{width:220px;background:var(--bg2);border-right:1px solid var(--bdr);padding:1rem .75rem;flex-shrink:0}
.sl{display:flex;align-items:center;gap:.5rem;padding:.55rem .75rem;color:var(--tx2);border-radius:6px;margin-bottom:.2rem;font-size:.875rem;transition:all .15s}
.sl:hover,.sl.on{background:rgba(239,68,68,.12);color:var(--r)}.main{flex:1;padding:1.5rem;overflow-y:auto}
.pt{font-size:1.5rem;font-weight:700;margin-bottom:.25rem}.ps{color:var(--tx2);margin-bottom:1.25rem}
.card{background:var(--bg2);border:1px solid var(--bdr);border-radius:10px;padding:1.25rem;margin-bottom:1.25rem}
.ct{font-size:1rem;font-weight:600;margin-bottom:.875rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-bottom:1.25rem}
.stat{background:var(--bg2);border:1px solid var(--bdr);border-top:3px solid var(--r);border-radius:10px;padding:1.125rem}
.sv{font-size:1.75rem;font-weight:700}.sl2{color:var(--tx2);font-size:.8rem}
.btn{display:inline-flex;align-items:center;gap:.4rem;padding:.5rem 1rem;border-radius:7px;font-size:.85rem;font-weight:500;border:none;cursor:pointer;transition:all .15s}
.bp{background:var(--r);color:#fff}.bp:hover{background:var(--rd)}.bs{background:var(--bg3);color:var(--tx)}.bs:hover{background:var(--bdr)}
.bd{background:#7f1d1d;color:#fff}.bd:hover{background:#991b1b}.bsm{padding:.3rem .65rem;font-size:.78rem}
.inp,.sel,.ta{width:100%;padding:.6rem .85rem;background:var(--bg3);border:1px solid var(--bdr);border-radius:7px;color:var(--tx);font-size:.85rem;transition:border .15s}
.inp:focus,.sel:focus,.ta:focus{outline:none;border-color:var(--r)}.ta{min-height:80px;resize:vertical}
.lbl{display:block;margin-bottom:.35rem;font-size:.82rem;color:var(--tx2)}.fg{margin-bottom:.875rem}
.tbl{width:100%;border-collapse:collapse}.tbl th{text-align:left;padding:.65rem .875rem;color:var(--tx2);font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--bdr)}
.tbl td{padding:.8rem .875rem;border-bottom:1px solid var(--bdr)}.tbl tr:hover{background:rgba(255,255,255,.02)}
.bdg{padding:.18rem .55rem;border-radius:20px;font-size:.72rem;font-weight:500}
.bg{background:rgba(34,197,94,.15);color:#22c55e}.br{background:rgba(220,38,38,.15);color:#f87171}.bb{background:rgba(59,130,246,.15);color:#60a5fa}
.al{padding:.8rem 1rem;border-radius:7px;margin-bottom:.875rem}
.aok{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);color:#22c55e}.aer{background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.25);color:#f87171}
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1.1rem}
.sc{background:var(--bg2);border:1px solid var(--bdr);border-radius:12px;padding:1.1rem;transition:all .2s}
.sc:hover{border-color:var(--r);transform:translateY(-2px)}.si{width:50px;height:50px;border-radius:10px;background:var(--bg3);display:flex;align-items:center;justify-content:center;font-size:1.1rem;font-weight:700;margin-bottom:.75rem;border:1px solid var(--bdr)}
.sn{font-weight:600;margin-bottom:.2rem}.ss{color:var(--tx2);font-size:.82rem}
.lw{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0f0f0f,#1a0a0a)}
.lc{background:var(--bg2);border:1px solid var(--bdr);border-radius:16px;padding:2.25rem;text-align:center;max-width:360px;width:90%}
.lt{font-size:1.4rem;font-weight:700;margin-bottom:.3rem}.ls{color:var(--tx2);margin-bottom:1.5rem}
.db{background:#5865F2;color:#fff;width:100%;justify-content:center;padding:.8rem;border-radius:10px;font-size:.9rem}.db:hover{background:#4752c4}
.perm-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:.75rem;margin-top:.875rem}
.perm-item{background:var(--bg3);border:1px solid var(--bdr);border-radius:8px;padding:.875rem;display:flex;justify-content:space-between;align-items:center;font-size:.82rem}
.pbtns{display:flex;gap:.35rem}.pb{width:28px;height:28px;border:none;border-radius:5px;cursor:pointer;font-size:.7rem;transition:all .15s}
.pa{background:rgba(34,197,94,.2);color:#22c55e}.pa.on{background:#22c55e;color:#fff}
.pn{background:rgba(161,161,170,.2);color:var(--tx2)}.pn.on{background:var(--tx2);color:#000}
.pd{background:rgba(220,38,38,.2);color:#f87171}.pd.on{background:#ef4444;color:#fff}
.footer{text-align:center;padding:1rem;color:var(--tx2);font-size:.78rem;border-top:1px solid var(--bdr);margin-top:2rem}
@media(max-width:700px){.side{display:none}.main{padding:1rem}}"""

def _al():
    ms=session.get("_flashes",[])
    return "".join(f'<div class="al {"aok" if c=="success" else "aer"}">{m}</div>' for c,m in ms)

def _side(gid,active):
    ls=[("📊","Übersicht","ov"),("🛡️","Moderation","mod"),("💰","Economy","eco"),("🎁","Giveaways","gws"),
        ("💡","Vorschläge","sugg"),("👥","Team","team"),("📝","Bewerbungen","apps"),
        ("📰","RSS","rss"),("🚗","RL Teams","rl"),("🔔","Notifications","notif"),
        ("🔐","Channel-Rechte","chperms"),("📋","Mod Logs","mlogs"),("⚙️","Einstellungen","sett")]
    items="".join(f'<a href="/g/{gid}/{ep}" class="sl{" on" if ep==active else ""}">{ic} {lb}</a>' for ic,lb,ep in ls)
    return f'<aside class="side">{items}</aside>'

BH=f'<!DOCTYPE html><html lang="de"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RLD Dashboard</title><style>{_C}</style></head><body>{{body}}<div class="footer">RLD Dashboard &mdash; Made by Rezyel with AI &bull; &copy; 2025</div></body></html>'

def pg(body): return BH.replace("{body}",body)

def gnav(gid):
    g=dget(f"/guilds/{gid}",isbot=True) or {"name":gid}
    return f'<nav class="nav"><div class="logo">🤖 {g.get("name",gid)}</div><div class="nav-r"><a href="/dash" class="btn bs bsm">← Zurück</a><span>{session.get("username","")}</span><a href="/logout" class="btn bs bsm">Abmelden</a></div></nav>',g

def runasync(coro,timeout=4):
    import asyncio as _a
    fut=_a.run_coroutine_threadsafe(coro,bot.loop)
    try: return fut.result(timeout=timeout)
    except: return None

@fa.route("/")
def idx(): return redirect(url_for("dash") if "user_id" in session else url_for("dlogin"))

@fa.route("/login")
def dlogin():
    if "user_id" in session: return redirect(url_for("dash"))
    sc="identify guilds"
    au=f"https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&redirect_uri={quote(DISCORD_REDIRECT_URI)}&response_type=code&scope={quote(sc)}"
    body=f'<div class="lw"><div class="lc"><div style="font-size:2.5rem;margin-bottom:.875rem">🤖</div><h1 class="lt">RLD Dashboard</h1><p class="ls">Mit Discord anmelden</p>{_al()}<a href="{au}" class="btn db">Mit Discord anmelden</a></div></div>'
    return pg(body)

@fa.route("/callback")
def cb():
    code=request.args.get("code")
    if not code: flash("Fehler.","error"); return redirect(url_for("dlogin"))
    try:
        r=hr.post(f"{DAPI}/oauth2/token",data={"client_id":DISCORD_CLIENT_ID,"client_secret":DISCORD_CLIENT_SECRET,"grant_type":"authorization_code","code":code,"redirect_uri":DISCORD_REDIRECT_URI},timeout=8)
        tok=r.json()
    except: flash("API Fehler.","error"); return redirect(url_for("dlogin"))
    if not r.ok: flash("Token Fehler.","error"); return redirect(url_for("dlogin"))
    u=dget("/users/@me",token=tok["access_token"])
    if not u: flash("User Fehler.","error"); return redirect(url_for("dlogin"))
    session.permanent=True; session.update({"user_id":u["id"],"username":u["username"],"avatar":u.get("avatar"),"access_token":tok["access_token"]})
    return redirect(url_for("dash"))

@fa.route("/logout")
def logout(): session.clear(); return redirect(url_for("dlogin"))

@fa.route("/dash")
@lreq
def dash():
    ug=uguilds(session["access_token"]); bg={g["id"] for g in bguilds()}
    # Only show guilds where bot IS present AND user has manage perms
    gs=[g for g in ug if g["id"] in bg and(int(g.get("permissions",0))&0x8 or int(g.get("permissions",0))&0x20)]
    cards="".join(f'<a href="/g/{g["id"]}/ov" class="sc"><div class="si">{g["name"][:2]}</div><div class="sn">{g["name"]}</div><div class="ss">Verwalten →</div></a>' for g in gs)
    cards+=f'<a href="https://discord.com/api/oauth2/authorize?client_id={DISCORD_CLIENT_ID}&permissions=8&scope=bot%20applications.commands" target="_blank" class="sc" style="opacity:.55;border-style:dashed"><div class="si" style="border-style:dashed">+</div><div class="sn">Bot hinzufügen</div><div class="ss">Server einladen</div></a>'
    body=f'<nav class="nav"><div class="logo">🤖 RLD Dashboard</div><div class="nav-r"><span>{session.get("username","")}</span><a href="/logout" class="btn bs bsm">Abmelden</a></div></nav><div class="wrap"><aside class="side"><div style="color:var(--tx2);font-size:.82rem;padding:.5rem 0">Wähle einen Server</div></aside><main class="main">{_al()}<div class="pt">Deine Server</div><p class="ps">Wähle einen Server</p><div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));margin-bottom:1.25rem"><div class="stat"><div class="sv">{len(bguilds())}</div><div class="sl2">Server mit Bot</div></div><div class="stat"><div class="sv">{len(gs)}</div><div class="sl2">Verwaltbar</div></div></div><div class="sg">{cards}</div></main></div>'
    return pg(body)

@fa.route("/g/<gid>/ov")
@lreq
@greq
def gov(gid):
    nav,g=gnav(gid); chs=dget(f"/guilds/{gid}/channels",isbot=True) or []; rls=dget(f"/guilds/{gid}/roles",isbot=True) or []
    wc=runasync(col("warns").count_documents({"guild_id":int(gid)})) or "?"
    body=f'{nav}<div class="wrap">{_side(gid,"ov")}<main class="main">{_al()}<div class="pt">Übersicht</div><p class="ps">{g.get("name","")}</p><div class="grid"><div class="stat"><div class="sv">{g.get("member_count","?")}</div><div class="sl2">Mitglieder</div></div><div class="stat"><div class="sv">{len(chs)}</div><div class="sl2">Channels</div></div><div class="stat"><div class="sv">{len(rls)}</div><div class="sl2">Rollen</div></div><div class="stat"><div class="sv">{wc}</div><div class="sl2">Verwarnungen</div></div></div><div class="card"><div class="ct">Schnellzugriff</div><div style="display:flex;gap:.75rem;flex-wrap:wrap"><a href="/g/{gid}/mod" class="btn bp">Verwarnungen</a><a href="/g/{gid}/eco" class="btn bp">Economy</a><a href="/g/{gid}/chperms" class="btn bp">Channel-Rechte</a><a href="/g/{gid}/sett" class="btn bs">Einstellungen</a></div></div></main></div>'
    return pg(body)

@fa.route("/g/<gid>/mod",methods=["GET"])
@lreq
@greq
def gmod(gid):
    nav,g=gnav(gid); s=request.args.get("q","")
    q={"guild_id":int(gid)}
    if s: q["$or"]=[{"grund":{"$regex":s,"$options":"i"}}]
    ws=runasync(col("warns").find(q).sort("ts",-1).to_list(50)) or []
    rows="".join(f'<tr><td>{w.get("user_id","")}</td><td>{w.get("mod_id","")}</td><td>{str(w.get("grund",""))[:60]}</td><td>{w["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(w.get("ts"),datetime) else ""}</td><td><form method="POST" action="/g/{gid}/mod/del/{w["_id"]}" style="display:inline"><button class="btn bd bsm" onclick="return confirm(\'Löschen?\')">🗑️</button></form></td></tr>' for w in ws)
    body=f'{nav}<div class="wrap">{_side(gid,"mod")}<main class="main">{_al()}<div class="pt">Moderation</div><p class="ps">Verwarnungen</p><div class="card"><form method="GET" style="display:flex;gap:.75rem"><input name="q" class="inp" placeholder="Grund suchen..." value="{s}" style="max-width:300px"><button class="btn bp">Suchen</button></form></div><div class="card"><div class="ct">Verwarnungen</div><table class="tbl"><thead><tr><th>User</th><th>Mod</th><th>Grund</th><th>Datum</th><th></th></tr></thead><tbody>{rows or "<tr><td colspan=5 style=text-align:center;color:var(--tx2)>Keine Verwarnungen</td></tr>"}</tbody></table></div></main></div>'
    return pg(body)

@fa.route("/g/<gid>/mod/del/<wid>",methods=["POST"])
@lreq
@greq
def gdel(gid,wid):
    from bson import ObjectId
    runasync(col("warns").delete_one({"_id":ObjectId(wid),"guild_id":int(gid)}))
    flash("Verwarnung gelöscht!","success"); return redirect(f"/g/{gid}/mod")

@fa.route("/g/<gid>/eco",methods=["GET","POST"])
@lreq
@greq
def geco(gid):
    nav,g=gnav(gid)
    if request.method=="POST":
        uid=request.form.get("uid","").strip(); amt=request.form.get("amt","0")
        if uid.isdigit() and amt.lstrip("-").isdigit():
            runasync(col("economy").update_one({"guild_id":int(gid),"user_id":int(uid)},{"$set":{"coins":int(amt)}},upsert=True))
            flash("Aktualisiert!","success")
    lb=runasync(col("economy").find({"guild_id":int(gid)}).sort("coins",-1).limit(30).to_list(30)) or []
    rows="".join(f'<tr><td>#{i+1}</td><td>{u.get("user_id","")}</td><td>{u.get("coins",0)} 💰</td><td>{u.get("bank",0)} 🏦</td><td>{u.get("rep",0)} ⭐</td></tr>' for i,u in enumerate(lb))
    body=f'{nav}<div class="wrap">{_side(gid,"eco")}<main class="main">{_al()}<div class="pt">Economy</div><p class="ps">Leaderboard & Coins</p><div class="card"><div class="ct">Coins bearbeiten</div><form method="POST" style="display:grid;grid-template-columns:1fr 1fr auto;gap:.75rem;align-items:flex-end"><div class="fg" style="margin:0"><label class="lbl">User ID</label><input name="uid" class="inp" required></div><div class="fg" style="margin:0"><label class="lbl">Betrag</label><input name="amt" type="number" class="inp" required></div><button class="btn bp">Setzen</button></form></div><div class="card"><div class="ct">Leaderboard</div><table class="tbl"><thead><tr><th>#</th><th>User</th><th>Wallet</th><th>Bank</th><th>Rep</th></tr></thead><tbody>{rows or "<tr><td colspan=5 style=text-align:center;color:var(--tx2)>Keine Daten</td></tr>"}</tbody></table></div></main></div>'
    return pg(body)

def _gpg(gid,ep,title,desc):
    nav,g=gnav(gid)
    body=f'{nav}<div class="wrap">{_side(gid,ep)}<main class="main">{_al()}<div class="pt">{title}</div><p class="ps">{desc}</p><div class="card"><p style="color:var(--tx2)">Bald verfügbar.</p></div></main></div>'
    return pg(body)

@fa.route("/g/<gid>/gws")
@lreq
@greq
def ggws(gid): return _gpg(gid,"gws","Giveaways","Giveaways verwalten")

@fa.route("/g/<gid>/sugg")
@lreq
@greq
def gsugg(gid): return _gpg(gid,"sugg","Vorschläge","Community-Vorschläge")

@fa.route("/g/<gid>/team")
@lreq
@greq
def gteam(gid): return _gpg(gid,"team","Team","Team verwalten")

@fa.route("/g/<gid>/apps")
@lreq
@greq
def gapps(gid): return _gpg(gid,"apps","Bewerbungen","Bewerbungen verwalten")

@fa.route("/g/<gid>/rss")
@lreq
@greq
def grss(gid): return _gpg(gid,"rss","RSS Feeds","RSS verwalten")

@fa.route("/g/<gid>/rl")
@lreq
@greq
def grl(gid): return _gpg(gid,"rl","RL Teams","Rocket League Teams")

@fa.route("/g/<gid>/notif")
@lreq
@greq
def gnotif(gid): return _gpg(gid,"notif","Notifications","Twitch & YouTube")

@fa.route("/g/<gid>/mlogs")
@lreq
@greq
def gmlogs(gid):
    nav,g=gnav(gid)
    ls=runasync(col("logs").find({"guild_id":int(gid)}).sort("ts",-1).limit(50).to_list(50)) or []
    rows="".join(f'<tr><td>{l["ts"].strftime("%d.%m.%Y %H:%M") if isinstance(l.get("ts"),datetime) else ""}</td><td>{l.get("mod_id","")}</td><td><span class="bdg bb">{l.get("aktion","")}</span></td><td>{str(l.get("grund",""))[:60]}</td></tr>' for l in ls)
    body=f'{nav}<div class="wrap">{_side(gid,"mlogs")}<main class="main">{_al()}<div class="pt">Mod Logs</div><p class="ps">Letzte Aktionen</p><div class="card"><table class="tbl"><thead><tr><th>Zeit</th><th>Mod</th><th>Aktion</th><th>Grund</th></tr></thead><tbody>{rows or "<tr><td colspan=4 style=text-align:center;color:var(--tx2)>Keine Logs</td></tr>"}</tbody></table></div></main></div>'
    return pg(body)

# ── CHANNEL PERMISSIONS ───────────────────────────────────────
PBITS={"CREATE_INSTANT_INVITE":0x1,"KICK_MEMBERS":0x2,"BAN_MEMBERS":0x4,"ADMINISTRATOR":0x8,
       "MANAGE_CHANNELS":0x10,"MANAGE_GUILD":0x20,"ADD_REACTIONS":0x40,"VIEW_AUDIT_LOG":0x80,
       "VIEW_CHANNEL":0x400,"SEND_MESSAGES":0x800,"MANAGE_MESSAGES":0x2000,"EMBED_LINKS":0x4000,
       "ATTACH_FILES":0x8000,"READ_MESSAGE_HISTORY":0x10000,"MENTION_EVERYONE":0x20000,
       "USE_EXTERNAL_EMOJIS":0x40000,"CONNECT":0x100000,"SPEAK":0x200000,"MUTE_MEMBERS":0x400000,
       "DEAFEN_MEMBERS":0x800000,"MOVE_MEMBERS":0x1000000,"MANAGE_ROLES":0x10000000,
       "MANAGE_WEBHOOKS":0x20000000,"USE_APPLICATION_COMMANDS":0x80000000,"MANAGE_THREADS":0x400000000,
       "SEND_MESSAGES_IN_THREADS":0x4000000000,"MODERATE_MEMBERS":0x10000000000}

@fa.route("/g/<gid>/chperms",methods=["GET","POST"])
@lreq
@greq
def gchperms(gid):
    nav,g=gnav(gid)
    chs=dget(f"/guilds/{gid}/channels",isbot=True) or []
    rls=dget(f"/guilds/{gid}/roles",isbot=True) or []
    cats=[c for c in chs if c.get("type")==4]
    tchs=[c for c in chs if c.get("type") in[0,5]]
    vchs=[c for c in chs if c.get("type") in[2,13]]
    all_chs=sorted(tchs+vchs,key=lambda c:c.get("position",0))
    msg=""
    if request.method=="POST":
        cid2=request.form.get("channel_id"); rid=request.form.get("role_id"); pdata=request.form.get("perms","{}")
        if cid2 and rid:
            try:
                pd=json.loads(pdata); al=0; dn=0
                for pn,st in pd.items():
                    if pn in PBITS:
                        if st=="allow": al|=PBITS[pn]
                        elif st=="deny": dn|=PBITS[pn]
                r2=hr.put(f"{DAPI}/channels/{cid2}/permissions/{rid}",headers={"Authorization":f"Bot {DISCORD_BOT_TOKEN}","Content-Type":"application/json"},json={"allow":str(al),"deny":str(dn),"type":0},timeout=8)
                if r2.ok: flash("Berechtigungen gespeichert!","success")
                else: flash(f"Discord Fehler: {r2.status_code}","error")
            except Exception as ex: flash(f"Fehler: {ex}","error")
    cat_opts="<option value=''>Alle</option>"+"".join(f'<option value="{c["id"]}">{c["name"]}</option>' for c in cats)
    ch_opts="<option value=''>Channel wählen...</option>"+"".join(f'<option value="{c["id"]}" data-cat="{c.get("parent_id","")}">{("#" if c.get("type")==0 else "🔊 ")}{c["name"]}</option>' for c in all_chs)
    role_opts="<option value=''>Rolle wählen...</option>"+"".join(f'<option value="{r["id"]}">{r["name"]}</option>' for r in sorted(rls,key=lambda x:x.get("position",0),reverse=True))
    perm_items="".join(f'<div class="perm-item"><span>{pn.replace("_"," ").title()}</span><div class="pbtns" data-p="{pn}"><button type="button" class="pb pa" onclick="sp(\'{pn}\',\'allow\')">✓</button><button type="button" class="pb pn on" onclick="sp(\'{pn}\',\'neutral\')">−</button><button type="button" class="pb pd" onclick="sp(\'{pn}\',\'deny\')">✕</button></div></div>' for pn in PBITS)
    body=f'''{nav}<div class="wrap">{_side(gid,"chperms")}<main class="main">{_al()}<div class="pt">Channel-Rechte</div><p class="ps">Berechtigungen je Channel & Rolle bearbeiten</p>
<div class="card"><div class="ct">Channel & Rolle wählen</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:.75rem;margin-bottom:.875rem">
<div class="fg" style="margin:0"><label class="lbl">Kategorie</label><select class="sel" onchange="fc(this.value)">{cat_opts}</select></div>
<div class="fg" style="margin:0"><label class="lbl">Channel</label><select class="sel" id="chsel" onchange="lch(this.value)">{ch_opts}</select></div>
<div class="fg" style="margin:0"><label class="lbl">Rolle</label><select class="sel" id="rlsel" onchange="document.getElementById('perm-role-id').value=this.value">{role_opts}</select></div>
</div></div>
<form method="POST" id="pf"><input type="hidden" name="channel_id" id="perm-channel-id"><input type="hidden" name="role_id" id="perm-role-id"><input type="hidden" name="perms" id="perm-data">
<div class="card"><div class="ct">Berechtigungen</div><div class="perm-grid">{perm_items}</div>
<div style="display:flex;gap:.75rem;margin-top:1rem"><button type="submit" class="btn bp">💾 Speichern</button><button type="button" class="btn bs" onclick="rp()">🔄 Reset</button></div></div></form>
</main></div>
<script>
var ps={{}};
function sp(n,s){{ps[n]=s;var g=document.querySelector('[data-p="'+n+'"]');g.querySelectorAll('.pb').forEach(function(b){{b.classList.remove('on')}});g.querySelector('.p'+s[0]).classList.add('on');upd()}}
function upd(){{document.getElementById('perm-data').value=JSON.stringify(ps)}}
function rp(){{ps={{}};document.querySelectorAll('.pb').forEach(function(b){{b.classList.remove('on')}});document.querySelectorAll('.pn').forEach(function(b){{b.classList.add('on')}});upd()}}
function fc(cv){{var o=document.getElementById('chsel').querySelectorAll('option');o.forEach(function(op){{op.style.display=(!cv||op.dataset.cat==cv||!op.value)?'':'none'}})}}
function lch(v){{document.getElementById('perm-channel-id').value=v}}
rp();
</script>'''
    return pg(body)

@fa.route("/g/<gid>/sett",methods=["GET","POST"])
@lreq
@greq
def gsett(gid):
    nav,g=gnav(gid)
    chs=dget(f"/guilds/{gid}/channels",isbot=True) or []; rls=dget(f"/guilds/{gid}/roles",isbot=True) or []
    tch=[c for c in chs if c.get("type")==0]; vch=[c for c in chs if c.get("type") in[2,13]]
    if request.method=="POST":
        f2={k:request.form.get(k) or None for k in["prefix","welcome_channel","welcome_msg","goodbye_channel","goodbye_msg","mod_log","suggest_channel","birthday_channel","auto_role","verify_role","starboard_channel","ticket_category","ticket_team_role"]}
        if not f2["prefix"]: f2["prefix"]="!"
        for fi in["starboard_min","slow_joiner_minutes"]:
            v=request.form.get(fi,"0")
            f2[fi]=int(v) if v.isdigit() else 0
        f2["anti_raid"]=request.form.get("anti_raid")=="1"
        f2["welcome_dm"]=request.form.get("welcome_dm")=="1"
        runasync(col("config").update_one({"guild_id":int(gid)},{"$set":f2},upsert=True)); ivcfg(int(gid))
        flash("Gespeichert!","success")
    cfg=runasync(col("config").find_one({"guild_id":int(gid)})) or {}
    def co(sel,clist):
        o='<option value="">-- Deaktiviert --</option>'
        for c in clist:
            s=" selected" if str(sel)==c["id"] else ""; o+=f'<option value="{c["id"]}"{s}>#{c["name"]}</option>'
        return o
    def ro(sel):
        o='<option value="">-- Keine --</option>'
        for r in sorted(rls,key=lambda x:x.get("position",0),reverse=True):
            s=" selected" if str(sel)==r["id"] else ""; o+=f'<option value="{r["id"]}"{s}>@{r["name"]}</option>'
        return o
    ck=lambda k,v:"checked" if cfg.get(k)==v else ""
    body=f'''{nav}<div class="wrap">{_side(gid,"sett")}<main class="main">{_al()}<div class="pt">Einstellungen</div><p class="ps">Alle Bot-Einstellungen für {g.get("name","")}</p>
<form method="POST">
<div class="card"><div class="ct">🔧 Allgemein</div>
<div class="fg"><label class="lbl">Prefix</label><input name="prefix" class="inp" value="{cfg.get("prefix","!")}" maxlength="5" style="max-width:100px"></div>
<div class="fg"><label class="lbl">Anti-Raid</label><select name="anti_raid" class="sel" style="max-width:200px"><option value="0" {"selected" if not cfg.get("anti_raid") else ""}>Aus</option><option value="1" {"selected" if cfg.get("anti_raid") else ""}>An</option></select></div>
<div class="fg"><label class="lbl">Slow Joiner Schutz (Minuten, 0=aus)</label><input name="slow_joiner_minutes" type="number" class="inp" value="{cfg.get("slow_joiner_minutes",0)}" style="max-width:120px"></div>
<div class="fg"><label class="lbl">Welcome DM</label><select name="welcome_dm" class="sel" style="max-width:200px"><option value="0" {"selected" if not cfg.get("welcome_dm") else ""}>Aus</option><option value="1" {"selected" if cfg.get("welcome_dm") else ""}>An</option></select></div>
</div>
<div class="card"><div class="ct">👋 Willkommen & Abschied</div>
<div class="fg"><label class="lbl">Willkommen-Kanal</label><select name="welcome_channel" class="sel">{co(cfg.get("welcome_channel",""),tch)}</select></div>
<div class="fg"><label class="lbl">Willkommen-Nachricht</label><textarea name="welcome_msg" class="ta">{cfg.get("welcome_msg","")}</textarea></div>
<div class="fg"><label class="lbl">Abschied-Kanal</label><select name="goodbye_channel" class="sel">{co(cfg.get("goodbye_channel",""),tch)}</select></div>
<div class="fg"><label class="lbl">Abschied-Nachricht</label><textarea name="goodbye_msg" class="ta">{cfg.get("goodbye_msg","")}</textarea></div>
<div class="fg"><label class="lbl">Auto-Rolle</label><select name="auto_role" class="sel">{ro(cfg.get("auto_role",""))}</select></div>
</div>
<div class="card"><div class="ct">🔐 Verify & Rollen</div>
<div class="fg"><label class="lbl">Verify-Rolle</label><select name="verify_role" class="sel">{ro(cfg.get("verify_role",""))}</select></div>
</div>
<div class="card"><div class="ct">📋 Logging & Kanäle</div>
<div class="fg"><label class="lbl">Mod-Log Kanal</label><select name="mod_log" class="sel">{co(cfg.get("mod_log",""),tch)}</select></div>
<div class="fg"><label class="lbl">Suggest Kanal</label><select name="suggest_channel" class="sel">{co(cfg.get("suggest_channel",""),tch)}</select></div>
<div class="fg"><label class="lbl">Geburtstags-Kanal</label><select name="birthday_channel" class="sel">{co(cfg.get("birthday_channel",""),tch)}</select></div>
<div class="fg"><label class="lbl">Starboard Kanal</label><select name="starboard_channel" class="sel">{co(cfg.get("starboard_channel",""),tch)}</select></div>
<div class="fg"><label class="lbl">Starboard Min. Sterne</label><input name="starboard_min" type="number" class="inp" value="{cfg.get("starboard_min",3)}" style="max-width:100px"></div>
</div>
<div class="card"><div class="ct">🎫 Ticket</div>
<div class="fg"><label class="lbl">Ticket Kategorie</label><select name="ticket_category" class="sel"><option value="">-- Keine --</option>{"".join((f'<option value="{c["id"]}" ' + ('selected' if str(cfg.get("ticket_category",""))==c["id"] else '') + f'>{c["name"]}</option>') for c in chs if c.get("type")==4)}</select></div>
<div class="fg"><label class="lbl">Ticket Team-Rolle</label><select name="ticket_team_role" class="sel">{ro(cfg.get("ticket_team_role",""))}</select></div>
</div>
<button type="submit" class="btn bp">💾 Speichern</button>
</form></main></div>'''
    return pg(body)

@fa.route("/ping")
def ping(): return jsonify({"status":"alive","time":datetime.utcnow().isoformat()})

@fa.route("/health")
def health(): return jsonify({"status":"ok","ping_ms":round(bot.latency*1000) if bot.is_ready() else -1})

# ── KEEP ALIVE ────────────────────────────────────────────────
async def kalive():
    if not RENDER_URL: log.warning("RENDER_EXTERNAL_URL not set"); return
    await asyncio.sleep(60)
    import aiohttp
    while True:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{RENDER_URL}/health",timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status==200: log.info("Keep-alive OK")
        except Exception as ex: log.warning(f"Keep-alive: {ex}")
        await asyncio.sleep(540)

# ── MAIN ──────────────────────────────────────────────────────
def run_flask():
    fa.run(host="0.0.0.0",port=PORT,debug=False,use_reloader=False,threaded=True)

async def main():
    bot.add_view(TicketView()); bot.add_view(CloseTicketView()); bot.add_view(VerifyView())
    threading.Thread(target=run_flask,daemon=True).start()
    log.info(f"Flask on port {PORT}")
    async with bot: await bot.start(DISCORD_TOKEN)

if __name__=="__main__":
    asyncio.run(main())