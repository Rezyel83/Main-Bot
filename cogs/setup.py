import discord
from discord.ext import commands, tasks
from discord import app_commands
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, gcfg, ivcfg, is_admin

class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.stat_loop.start()

    def cog_unload(self):
        self.stat_loop.cancel()

    async def cfgu(self, gid, fields):
        await col("config").update_one({"guild_id": gid}, {"$set": fields}, upsert=True)
        ivcfg(gid)

    @app_commands.command(name="setup-welcome", description="[Admin] Willkommen einrichten.")
    @is_admin()
    async def swelcome(self, i: discord.Interaction, kanal: discord.TextChannel,
                        nachricht: str = "Willkommen {user} auf {server}! 🎉"):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"welcome_channel": kanal.id, "welcome_msg": nachricht})
        await i.followup.send(f"✅ Willkommen → {kanal.mention}")

    @app_commands.command(name="setup-goodbye", description="[Admin] Abschied einrichten.")
    @is_admin()
    async def sgoodbye(self, i: discord.Interaction, kanal: discord.TextChannel,
                        nachricht: str = "{user} hat den Server verlassen."):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"goodbye_channel": kanal.id, "goodbye_msg": nachricht})
        await i.followup.send(f"✅ Abschied → {kanal.mention}")

    @app_commands.command(name="setup-autorole", description="[Admin] Auto-Rolle setzen.")
    @is_admin()
    async def sautorole(self, i: discord.Interaction, rolle: discord.Role):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"auto_role": rolle.id})
        await i.followup.send(f"✅ Auto-Rolle: {rolle.mention}")

    @app_commands.command(name="setup-modlog", description="[Admin] Mod-Log Kanal setzen.")
    @is_admin()
    async def smodlog(self, i: discord.Interaction, kanal: discord.TextChannel):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"mod_log": kanal.id, "log_channels.mod_log": kanal.id})
        await i.followup.send(f"✅ Mod-Log → {kanal.mention}")

    @app_commands.command(name="setup-logs", description="[Admin] Log-Kanäle einrichten.")
    @is_admin()
    async def slogs(self, i: discord.Interaction,
                     mod_log: discord.TextChannel = None,
                     ticket_log: discord.TextChannel = None,
                     automod_log: discord.TextChannel = None,
                     server_log: discord.TextChannel = None,
                     member_log: discord.TextChannel = None,
                     join_leave_log: discord.TextChannel = None):
        await i.response.defer()
        upd = {}
        if mod_log: upd["log_channels.mod_log"] = mod_log.id
        if ticket_log: upd["log_channels.ticket_log"] = ticket_log.id
        if automod_log: upd["log_channels.automod_log"] = automod_log.id
        if server_log: upd["log_channels.server_log"] = server_log.id
        if member_log: upd["log_channels.member_log"] = member_log.id
        if join_leave_log: upd["log_channels.join_leave_log"] = join_leave_log.id
        if not upd: await i.followup.send("❌ Kein Kanal angegeben."); return
        await self.cfgu(i.guild_id, upd)
        await i.followup.send("✅ Log-Kanäle gespeichert!")

    @app_commands.command(name="setup-automod", description="[Admin] Auto-Mod konfigurieren.")
    @is_admin()
    async def sautomod(self, i: discord.Interaction, aktiviert: bool, spam: bool = True,
                        links: bool = False, caps: bool = False, mention_limit: int = 5):
        await i.response.defer()
        await self.cfgu(i.guild_id, {
            "automod": {"enabled": aktiviert, "spam": spam, "links": links,
                        "caps": caps, "bad_words": [], "mention_limit": mention_limit}
        })
        await i.followup.send(f"✅ Auto-Mod {'aktiviert' if aktiviert else 'deaktiviert'}.")

    @app_commands.command(name="setup-starboard", description="[Admin] Starboard einrichten.")
    @is_admin()
    async def sstarboard(self, i: discord.Interaction, kanal: discord.TextChannel, min_sterne: int = 3):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"starboard_channel": kanal.id, "starboard_min": min_sterne})
        await i.followup.send(f"✅ Starboard → {kanal.mention} (min. {min_sterne} ⭐)")

    @app_commands.command(name="setup-suggest", description="[Admin] Suggest-Kanal setzen.")
    @is_admin()
    async def ssuggest(self, i: discord.Interaction, kanal: discord.TextChannel):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"suggest_channel": kanal.id})
        await i.followup.send(f"✅ Suggest → {kanal.mention}")

    @app_commands.command(name="setup-birthday", description="[Admin] Geburtstags-Kanal setzen.")
    @is_admin()
    async def sbday(self, i: discord.Interaction, kanal: discord.TextChannel):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"birthday_channel": kanal.id})
        await i.followup.send(f"✅ Geburtstag → {kanal.mention}")

    @app_commands.command(name="setup-slowjoiner", description="[Admin] Slow Joiner Schutz.")
    @is_admin()
    async def sslowjoin(self, i: discord.Interaction, minuten: int):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"slow_joiner_minutes": minuten})
        await i.followup.send(f"✅ Slow Joiner: **{minuten} Min**")

    @app_commands.command(name="setup-welcomedm", description="[Admin] Welcome DM an/aus.")
    @is_admin()
    async def swelcomedm(self, i: discord.Interaction, aktiv: bool):
        await i.response.defer()
        await self.cfgu(i.guild_id, {"welcome_dm": aktiv})
        await i.followup.send(f"✅ Welcome DM: {'an' if aktiv else 'aus'}")

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
        await col("config").update_one(
            {"guild_id": i.guild_id},
            {"$addToSet": {"automod.bad_words": wort.lower()}}, upsert=True
        )
        ivcfg(i.guild_id)
        await i.response.send_message(f"✅ `{wort}` zur Blacklist hinzugefügt.", ephemeral=True)

    @app_commands.command(name="badword-remove", description="[Admin] Verbotenes Wort entfernen.")
    @is_admin()
    async def bwremove(self, i: discord.Interaction, wort: str):
        await col("config").update_one(
            {"guild_id": i.guild_id},
            {"$pull": {"automod.bad_words": wort.lower()}}, upsert=True
        )
        ivcfg(i.guild_id)
        await i.response.send_message(f"✅ `{wort}` entfernt.", ephemeral=True)

    @app_commands.command(name="stat-channel", description="[Admin] Statistik-Kanal einrichten.")
    @is_admin()
    async def statch_cmd(self, i: discord.Interaction, kanal: discord.VoiceChannel, typ: str):
        await i.response.defer()
        valid = ["members", "bots", "roles", "channels"]
        if typ not in valid:
            await i.followup.send(f"❌ Typ muss einer von: {', '.join(valid)} sein."); return
        await col("config").update_one(
            {"guild_id": i.guild_id},
            {"$set": {f"stat_channels.{typ}": kanal.id}}, upsert=True
        )
        ivcfg(i.guild_id)
        await i.followup.send(f"✅ Stat-Kanal ({typ}) → {kanal.mention}")

    @tasks.loop(minutes=10)
    async def stat_loop(self):
        cfgs = await col("config").find(
            {"stat_channels": {"$exists": True, "$ne": {}}},
            {"guild_id": 1, "stat_channels": 1, "member_count_role": 1}
        ).to_list(50)
        for cfg in cfgs:
            g = self.bot.get_guild(cfg["guild_id"])
            if not g: continue
            for typ, cid in cfg.get("stat_channels", {}).items():
                ch = g.get_channel(int(cid))
                if not ch: continue
                try:
                    if typ == "members":
                        role_id = cfg.get("member_count_role")
                        if role_id:
                            r = g.get_role(int(role_id))
                            count = len(r.members) if r else g.member_count
                        else:
                            count = g.member_count
                        await ch.edit(name=f"👥 Member: {count}")
                    elif typ == "bots":
                        await ch.edit(name=f"🤖 Bots: {sum(1 for m in g.members if m.bot)}")
                    elif typ == "roles":
                        await ch.edit(name=f"🎭 Rollen: {len(g.roles)}")
                    elif typ == "channels":
                        await ch.edit(name=f"💬 Kanäle: {len(g.channels)}")
                except: pass

    @stat_loop.before_loop
    async def before_stat(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Setup(bot))