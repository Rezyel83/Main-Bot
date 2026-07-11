import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import re, sys, os
from utils import col, gcfg, ivcfg, is_admin

class SetupMisc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()
        self.bday_loop.start()
        self.stat_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()
        self.bday_loop.cancel()
        self.stat_loop.cancel()

    async def cfgu(self, gid, fields):
        await col("config").update_one({"guild_id": gid}, {"$set": fields}, upsert=True)
        ivcfg(gid)

    @is_admin()
    async def swelcome(self, i: discord.Interaction, kanal: discord.TextChannel, nachricht: str = "Willkommen {user} auf {server}! 🎉"):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"welcome_channel": kanal.id, "welcome_msg": nachricht})
        await i.followup.send(f"✅ Willkommen → {kanal.mention}")

    @is_admin()
    async def sgoodbye(self, i: discord.Interaction, kanal: discord.TextChannel, nachricht: str = "{user} hat den Server verlassen."):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"goodbye_channel": kanal.id, "goodbye_msg": nachricht})
        await i.followup.send(f"✅ Abschied → {kanal.mention}")

    @is_admin()
    async def sautorole(self, i: discord.Interaction, rolle: discord.Role):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"auto_role": rolle.id})
        await i.followup.send(f"✅ Auto-Rolle: {rolle.mention}")

    @is_admin()
    async def smodlog(self, i: discord.Interaction, kanal: discord.TextChannel):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"mod_log": kanal.id, "log_channels.mod_log": kanal.id})
        await i.followup.send(f"✅ Mod-Log → {kanal.mention}")

    @app_commands.command(name="setup-automod", description="[Admin] Auto-Mod konfigurieren.")
    @is_admin()
    async def sautomod(self, i: discord.Interaction, aktiviert: bool, spam: bool = True, links: bool = False, caps: bool = False, mention_limit: int = 5):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"automod": {"enabled": aktiviert, "spam": spam, "links": links, "caps": caps, "bad_words": [], "mention_limit": mention_limit}})
        await i.followup.send(f"✅ Auto-Mod {'aktiviert' if aktiviert else 'deaktiviert'}.")

    @app_commands.command(name="setup-bot-status", description="[Admin] Bot Status setzen.")
    @is_admin()
    async def sbstatus(self, i: discord.Interaction, status: str):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"custom_bot_status": status})
        await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
        await i.followup.send(f"✅ Status: **{status}**")

    @app_commands.command(name="setup-member-role", description="[Admin] Rolle für Member-Zähler.")
    @is_admin()
    async def smemberrole(self, i: discord.Interaction, rolle: discord.Role):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"member_count_role": rolle.id})
        await i.followup.send(f"✅ Member-Zähler Rolle: {rolle.mention}")

    @app_commands.command(name="badword-add", description="[Admin] Verbotenes Wort hinzufügen.")
    @is_admin()
    async def bwadd(self, i: discord.Interaction, wort: str):
        await col("config").update_one({"guild_id": i.guild_id}, {"$addToSet": {"automod.bad_words": wort.lower()}}, upsert=True)
        ivcfg(i.guild_id)
        await i.response.send_message(f"✅ `{wort}` zur Blacklist.", ephemeral=True)

    @app_commands.command(name="badword-remove", description="[Admin] Verbotenes Wort entfernen.")
    @is_admin()
    async def bwremove(self, i: discord.Interaction, wort: str):
        await col("config").update_one({"guild_id": i.guild_id}, {"$pull": {"automod.bad_words": wort.lower()}}, upsert=True)
        ivcfg(i.guild_id)
        await i.response.send_message(f"✅ `{wort}` entfernt.", ephemeral=True)

    @app_commands.command(name="stat-channel", description="[Admin] Statistik-Kanal einrichten.")
    @is_admin()
    async def statch_cmd(self, i: discord.Interaction, kanal: discord.VoiceChannel, typ: str):
        await i.response.defer()
        valid = ["members", "bots", "roles", "channels"]
        if typ not in valid:
            await i.followup.send(f"❌ Typ: {', '.join(valid)}"); return
        await col("config").update_one({"guild_id": i.guild_id}, {"$set": {f"stat_channels.{typ}": kanal.id}}, upsert=True)
        ivcfg(i.guild_id)
        await i.followup.send(f"✅ Stat-Kanal ({typ}) → {kanal.mention}")

    @app_commands.command(name="afk", description="AFK setzen.")
    async def afk_cmd(self, i: discord.Interaction, grund: str = "AFK"):
        await i.response.defer()
        await col("afk").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$set": {"grund": grund, "ts": datetime.utcnow()}}, upsert=True)
        await i.followup.send(f"💤 AFK gesetzt: *{grund}*")

    @app_commands.command(name="afk-list", description="Alle AFK User anzeigen.")
    async def afk_list_cmd(self, i: discord.Interaction):
        await i.response.defer()
        al = await col("afk").find({"guild_id": i.guild_id}).to_list(30)
        e = discord.Embed(title="💤 AFK User", color=discord.Color.blurple())
        if not al: e.description = "Niemand ist AFK."
        else:
            for a in al:
                m = i.guild.get_member(a["user_id"])
                name = f"{m.display_name} ({a['user_id']})" if m else str(a["user_id"])
                e.add_field(name=name, value=a.get("grund", "AFK"), inline=True)
        await i.followup.send(embed=e)

    @app_commands.command(name="remindme", description="Erinnerung setzen.")
    async def remind_cmd(self, i: discord.Interaction, zeit: str, nachricht: str):
        await i.response.defer(ephemeral=True)
        mt = re.match(r"(\d+)(m|h|d)", zeit.lower())
        if not mt: await i.followup.send("❌ Format: 10m, 2h, 1d", ephemeral=True); return
        a, u = int(mt.group(1)), mt.group(2)
        dl = {"m": timedelta(minutes=a), "h": timedelta(hours=a), "d": timedelta(days=a)}[u]
        await col("reminders").insert_one({"user_id": i.user.id, "channel_id": i.channel_id, "nachricht": nachricht, "remind_at": datetime.utcnow() + dl, "done": False})
        await i.followup.send(f"⏰ Erinnerung in **{zeit}**: *{nachricht}*", ephemeral=True)

    @app_commands.command(name="geburtstag", description="Geburtstag eintragen.")
    async def bday_cmd(self, i: discord.Interaction, datum: str):
        try:
            datetime.strptime(datum, "%d.%m")
            await col("birthdays").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$set": {"datum": datum, "username": str(i.user)}}, upsert=True)
            await i.response.send_message(f"🎂 Geburtstag: **{datum}**", ephemeral=True)
        except:
            await i.response.send_message("❌ Format: DD.MM", ephemeral=True)

    @app_commands.command(name="geburtstag-liste", description="Alle Geburtstage anzeigen.")
    async def bday_list_cmd(self, i: discord.Interaction):
        await i.response.defer()
        bs = await col("birthdays").find({"guild_id": i.guild_id}).sort("datum", 1).to_list(50)
        e = discord.Embed(title="🎂 Geburtstage", color=discord.Color.pink())
        if not bs: e.description = "Keine Geburtstage."
        else:
            for b in bs:
                m = i.guild.get_member(b["user_id"])
                name = f"{m.mention} ({b['user_id']})" if m else str(b["user_id"])
                e.add_field(name=b["datum"], value=name, inline=True)
        await i.followup.send(embed=e)

    @app_commands.command(name="suggest", description="Vorschlag einreichen.")
    async def suggest_cmd(self, i: discord.Interaction, vorschlag: str):
        await i.response.defer(ephemeral=True)
        cfg = await gcfg(i.guild_id)
        cid = cfg.get("suggest_channel")
        if not cid: await i.followup.send("❌ Suggest-Kanal nicht konfiguriert!"); return
        ch = i.guild.get_channel(int(cid))
        e = discord.Embed(title="💡 Vorschlag", description=vorschlag, color=discord.Color.blurple())
        e.set_footer(text=f"von {i.user.display_name} ({i.user.id})")
        msg = await ch.send(embed=e)
        await msg.add_reaction("✅"); await msg.add_reaction("❌")
        await col("suggestions").insert_one({"guild_id": i.guild_id, "user_id": i.user.id, "username": str(i.user), "vorschlag": vorschlag, "message_id": msg.id, "status": "offen", "ts": datetime.utcnow()})
        await i.followup.send("✅ Vorschlag eingereicht!")

    @app_commands.command(name="cmd-add", description="[Admin] Custom Command erstellen.")
    @is_admin()
    async def cmdadd(self, i: discord.Interaction, trigger: str, antwort: str):
        await col("custom_commands").update_one({"guild_id": i.guild_id, "trigger": trigger.lower()}, {"$set": {"response": antwort}}, upsert=True)
        await i.response.send_message(f"✅ `{trigger}` erstellt!")

    @app_commands.command(name="cmd-remove", description="[Admin] Custom Command entfernen.")
    @is_admin()
    async def cmdremove(self, i: discord.Interaction, trigger: str):
        await col("custom_commands").delete_one({"guild_id": i.guild_id, "trigger": trigger.lower()})
        await i.response.send_message(f"✅ `{trigger}` entfernt!")

    @app_commands.command(name="cmd-list", description="Custom Commands anzeigen.")
    async def cmdlist(self, i: discord.Interaction):
        await i.response.defer()
        cs = await col("custom_commands").find({"guild_id": i.guild_id}).to_list(50)
        if not cs: await i.followup.send("Keine Custom Commands."); return
        e = discord.Embed(title="⚙️ Custom Commands", color=discord.Color.blurple())
        e.description = "\n".join(f"`{c['trigger']}` → {c['response'][:50]}" for c in cs)
        await i.followup.send(embed=e)

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        due = await col("reminders").find({"done": False, "remind_at": {"$lte": datetime.utcnow()}}).to_list(30)
        for r in due:
            try:
                ch = self.bot.get_channel(r["channel_id"]); u = await self.bot.fetch_user(r["user_id"])
                if ch: await ch.send(f"⏰ {u.mention} Erinnerung: **{r['nachricht']}**")
                await col("reminders").update_one({"_id": r["_id"]}, {"$set": {"done": True}})
            except: pass

    @tasks.loop(hours=24)
    async def bday_loop(self):
        today = datetime.utcnow().strftime("%d.%m")
        bs = await col("birthdays").find({"datum": today}).to_list(100)
        for b in bs:
            g = self.bot.get_guild(b["guild_id"])
            if not g: continue
            cfg = await gcfg(b["guild_id"]); cid = cfg.get("birthday_channel")
            if not cid: continue
            ch = g.get_channel(int(cid))
            if not ch: continue
            m = g.get_member(b["user_id"])
            if not m: continue
            await ch.send(embed=discord.Embed(title="🎂 Herzlichen Glückwunsch!", description=f"{m.mention} hat heute Geburtstag! 🎉", color=discord.Color.pink()))

    @tasks.loop(minutes=10)
    async def stat_loop(self):
        cfgs = await col("config").find({"stat_channels": {"$exists": True, "$ne": {}}}, {"guild_id": 1, "stat_channels": 1, "member_count_role": 1}).to_list(50)
        for cfg in cfgs:
            g = self.bot.get_guild(cfg["guild_id"])
            if not g: continue
            for typ, cid in cfg.get("stat_channels", {}).items():
                ch = g.get_channel(int(cid))
                if not ch: continue
                try:
                    if typ == "members":
                        role_id = cfg.get("member_count_role")
                        r = g.get_role(int(role_id)) if role_id else None
                        count = len(r.members) if r else g.member_count
                        await ch.edit(name=f"👥 Member: {count}")
                    elif typ == "bots": await ch.edit(name=f"🤖 Bots: {sum(1 for m in g.members if m.bot)}")
                    elif typ == "roles": await ch.edit(name=f"🎭 Rollen: {len(g.roles)}")
                    elif typ == "channels": await ch.edit(name=f"💬 Kanäle: {len(g.channels)}")
                except: pass

    @reminder_loop.before_loop
    async def before_reminder(self): await self.bot.wait_until_ready()

    @bday_loop.before_loop
    async def before_bday(self): await self.bot.wait_until_ready()

    @stat_loop.before_loop
    async def before_stat(self): await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(SetupMisc(bot))
