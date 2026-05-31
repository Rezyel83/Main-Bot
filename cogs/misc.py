import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, gcfg, is_admin

class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminder_loop.start()
        self.bday_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()
        self.bday_loop.cancel()

    # ── AFK ──────────────────────────────────────────────────
    @app_commands.command(name="afk", description="AFK setzen.")
    async def afk_cmd(self, i: discord.Interaction, grund: str = "AFK"):
        await i.response.defer()
        await col("afk").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$set": {"grund": grund, "ts": datetime.utcnow()}}, upsert=True
        )
        await i.followup.send(f"💤 AFK gesetzt: *{grund}*")

    @app_commands.command(name="afk-list", description="Alle AFK User anzeigen.")
    async def afk_list_cmd(self, i: discord.Interaction):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        al = await col("afk").find({"guild_id": i.guild_id}).to_list(30)
        e = discord.Embed(title="💤 AFK User", color=discord.Color.blurple())
        if not al:
            e.description = "Niemand ist AFK."
        else:
            for a in al:
                m = i.guild.get_member(a["user_id"])
                name = f"{m.display_name} ({a['user_id']})" if m else str(a["user_id"])
                e.add_field(name=name, value=a.get("grund", "AFK"), inline=True)
        await i.followup.send(embed=e)

    # ── REMINDER ─────────────────────────────────────────────
    @app_commands.command(name="remindme", description="Erinnerung setzen.")
    async def remind_cmd(self, i: discord.Interaction, zeit: str, nachricht: str):
        await i.response.defer(ephemeral=True)
        mt = re.match(r"(\d+)(m|h|d)", zeit.lower())
        if not mt: await i.followup.send("❌ Format: 10m, 2h, 1d", ephemeral=True); return
        a, u = int(mt.group(1)), mt.group(2)
        dl = {"m": timedelta(minutes=a), "h": timedelta(hours=a), "d": timedelta(days=a)}[u]
        await col("reminders").insert_one({
            "user_id": i.user.id, "channel_id": i.channel_id,
            "nachricht": nachricht, "remind_at": datetime.utcnow() + dl, "done": False
        })
        await i.followup.send(f"⏰ Erinnerung in **{zeit}**: *{nachricht}*", ephemeral=True)

    @tasks.loop(minutes=1)
    async def reminder_loop(self):
        due = await col("reminders").find(
            {"done": False, "remind_at": {"$lte": datetime.utcnow()}}
        ).to_list(30)
        for r in due:
            try:
                ch = self.bot.get_channel(r["channel_id"])
                u = await self.bot.fetch_user(r["user_id"])
                if ch: await ch.send(f"⏰ {u.mention} Erinnerung: **{r['nachricht']}**")
                await col("reminders").update_one({"_id": r["_id"]}, {"$set": {"done": True}})
            except: pass

    # ── BIRTHDAY ─────────────────────────────────────────────
    @app_commands.command(name="geburtstag", description="Geburtstag eintragen.")
    async def bday_cmd(self, i: discord.Interaction, datum: str):
        try:
            datetime.strptime(datum, "%d.%m")
            await col("birthdays").update_one(
                {"guild_id": i.guild_id, "user_id": i.user.id},
                {"$set": {"datum": datum, "username": str(i.user)}}, upsert=True
            )
            await i.response.send_message(f"🎂 Geburtstag eingetragen: **{datum}**", ephemeral=True)
        except:
            await i.response.send_message("❌ Format: DD.MM", ephemeral=True)

    @app_commands.command(name="geburtstag-liste", description="Alle Geburtstage anzeigen.")
    async def bday_list_cmd(self, i: discord.Interaction):
        await i.response.defer()
        bs = await col("birthdays").find({"guild_id": i.guild_id}).sort("datum", 1).to_list(50)
        e = discord.Embed(title="🎂 Geburtstage", color=discord.Color.pink())
        if not bs:
            e.description = "Keine Geburtstage eingetragen."
        else:
            for b in bs:
                m = i.guild.get_member(b["user_id"])
                name = f"{m.mention} ({b['user_id']})" if m else str(b["user_id"])
                e.add_field(name=b["datum"], value=name, inline=True)
        await i.followup.send(embed=e)

    @tasks.loop(hours=24)
    async def bday_loop(self):
        today = datetime.utcnow().strftime("%d.%m")
        bs = await col("birthdays").find({"datum": today}).to_list(100)
        for b in bs:
            g = self.bot.get_guild(b["guild_id"])
            if not g: continue
            cfg = await gcfg(b["guild_id"])
            cid = cfg.get("birthday_channel")
            if not cid: continue
            ch = g.get_channel(int(cid))
            if not ch: continue
            m = g.get_member(b["user_id"])
            if not m: continue
            e = discord.Embed(
                title="🎂 Herzlichen Glückwunsch!",
                description=f"{m.mention} hat heute Geburtstag! 🎉",
                color=discord.Color.pink()
            )
            await ch.send(embed=e)

    # ── SUGGEST ──────────────────────────────────────────────
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
        await msg.add_reaction("✅")
        await msg.add_reaction("❌")
        await col("suggestions").insert_one({
            "guild_id": i.guild_id, "user_id": i.user.id, "username": str(i.user),
            "vorschlag": vorschlag, "message_id": msg.id, "status": "offen", "ts": datetime.utcnow()
        })
        await i.followup.send("✅ Vorschlag eingereicht!")

    @app_commands.command(name="suggest-accept", description="[Admin] Vorschlag annehmen.")
    @is_admin()
    async def sugg_acc(self, i: discord.Interaction, message_id: str, grund: str = ""):
        await i.response.defer()
        sg = await col("suggestions").find_one({"message_id": int(message_id)})
        if not sg: await i.followup.send("❌ Nicht gefunden."); return
        cfg = await gcfg(i.guild_id)
        ch = i.guild.get_channel(int(cfg.get("suggest_channel", 0) or 0))
        if ch:
            try:
                msg = await ch.fetch_message(int(message_id))
                e = discord.Embed(title="✅ Angenommen", description=sg["vorschlag"], color=discord.Color.green())
                if grund: e.add_field(name="Begründung", value=grund)
                await msg.edit(embed=e)
            except: pass
        await col("suggestions").update_one({"_id": sg["_id"]}, {"$set": {"status": "angenommen"}})
        await i.followup.send("✅ Angenommen!")

    @app_commands.command(name="suggest-deny", description="[Admin] Vorschlag ablehnen.")
    @is_admin()
    async def sugg_deny(self, i: discord.Interaction, message_id: str, grund: str = ""):
        await i.response.defer()
        sg = await col("suggestions").find_one({"message_id": int(message_id)})
        if not sg: await i.followup.send("❌ Nicht gefunden."); return
        cfg = await gcfg(i.guild_id)
        ch = i.guild.get_channel(int(cfg.get("suggest_channel", 0) or 0))
        if ch:
            try:
                msg = await ch.fetch_message(int(message_id))
                e = discord.Embed(title="❌ Abgelehnt", description=sg["vorschlag"], color=discord.Color.red())
                if grund: e.add_field(name="Begründung", value=grund)
                await msg.edit(embed=e)
            except: pass
        await col("suggestions").update_one({"_id": sg["_id"]}, {"$set": {"status": "abgelehnt"}})
        await i.followup.send("✅ Abgelehnt.")

    # ── CUSTOM COMMANDS ───────────────────────────────────────
    @app_commands.command(name="cmd-add", description="[Admin] Custom Command erstellen.")
    @is_admin()
    async def cmdadd(self, i: discord.Interaction, trigger: str, antwort: str):
        await col("custom_commands").update_one(
            {"guild_id": i.guild_id, "trigger": trigger.lower()},
            {"$set": {"response": antwort}}, upsert=True
        )
        await i.response.send_message(f"✅ Command `{trigger}` erstellt!")

    @app_commands.command(name="cmd-remove", description="[Admin] Custom Command entfernen.")
    @is_admin()
    async def cmdremove(self, i: discord.Interaction, trigger: str):
        await col("custom_commands").delete_one({"guild_id": i.guild_id, "trigger": trigger.lower()})
        await i.response.send_message(f"✅ Command `{trigger}` entfernt!")

    @app_commands.command(name="cmd-list", description="Custom Commands anzeigen.")
    async def cmdlist(self, i: discord.Interaction):
        await i.response.defer()
        cs = await col("custom_commands").find({"guild_id": i.guild_id}).to_list(50)
        if not cs: await i.followup.send("Keine Custom Commands."); return
        e = discord.Embed(title="⚙️ Custom Commands", color=discord.Color.blurple())
        e.description = "\n".join(f"`{c['trigger']}` → {c['response'][:50]}" for c in cs)
        await i.followup.send(embed=e)

    @reminder_loop.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    @bday_loop.before_loop
    async def before_bday(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Misc(bot))