import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import random, re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, is_admin

class Giveaway(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.gw_loop.start()

    def cog_unload(self):
        self.gw_loop.cancel()

    @app_commands.command(name="giveaway-start", description="[Admin] Giveaway starten.")
    @is_admin()
    async def gw_cmd(self, i: discord.Interaction, preis: str, dauer: str, gewinner: int = 1,
                     rolle: Optional[discord.Role] = None, kanal: Optional[discord.TextChannel] = None):
        await i.response.defer()
        mt = re.match(r"(\d+)(m|h|d)", dauer.lower())
        if not mt: await i.followup.send("❌ Format: 10m, 2h, 1d"); return
        a, u = int(mt.group(1)), mt.group(2)
        dl = {"m": timedelta(minutes=a), "h": timedelta(hours=a), "d": timedelta(days=a)}[u]
        ea = datetime.utcnow() + dl
        ziel = kanal or i.channel
        e = discord.Embed(title="🎉 GIVEAWAY", color=discord.Color.gold())
        e.description = (
            f"**Preis:** {preis}\n"
            f"**Gewinner:** {gewinner}\n"
            f"**Endet:** <t:{int(ea.timestamp())}:R>\n\n"
            f"Reagiere mit 🎉 um teilzunehmen!"
        )
        if rolle: e.add_field(name="Benötigte Rolle", value=rolle.mention)
        e.set_footer(text=f"Gestartet von {i.user.display_name}")
        msg = await ziel.send(embed=e)
        await msg.add_reaction("🎉")
        await col("giveaways").insert_one({
            "guild_id": i.guild_id, "channel_id": ziel.id, "message_id": msg.id,
            "preis": preis, "gewinner": gewinner,
            "rolle_id": rolle.id if rolle else None,
            "ends_at": ea, "active": True,
            "gestartet_von": i.user.id
        })
        await i.followup.send(f"✅ Giveaway in {ziel.mention} gestartet!", ephemeral=True)

    @app_commands.command(name="giveaway-end", description="[Admin] Giveaway sofort beenden.")
    @is_admin()
    async def gw_end_cmd(self, i: discord.Interaction, message_id: str):
        await i.response.defer()
        gw = await col("giveaways").find_one({"message_id": int(message_id), "guild_id": i.guild_id})
        if not gw: await i.followup.send("❌ Giveaway nicht gefunden."); return
        if not gw.get("active"): await i.followup.send("❌ Giveaway bereits beendet."); return
        await self._end_giveaway(gw)
        await i.followup.send("✅ Giveaway beendet.")

    @app_commands.command(name="giveaway-reroll", description="[Admin] Neuen Gewinner auswählen.")
    @is_admin()
    async def gwreroll_cmd(self, i: discord.Interaction, message_id: str):
        await i.response.defer()
        gw = await col("giveaways").find_one({"message_id": int(message_id)})
        if not gw: await i.followup.send("❌ Nicht gefunden."); return
        try:
            ch = i.guild.get_channel(gw["channel_id"])
            msg = await ch.fetch_message(gw["message_id"])
            rx = discord.utils.get(msg.reactions, emoji="🎉")
            us = [u async for u in rx.users() if not u.bot]
            if not us: await i.followup.send("❌ Keine Teilnehmer."); return
            w = random.choice(us)
            await i.followup.send(f"🎉 Neuer Gewinner: {w.mention} ({w.id})!")
        except Exception as ex:
            await i.followup.send(f"❌ Fehler: {ex}")

    @app_commands.command(name="giveaway-list", description="Aktive Giveaways anzeigen.")
    @is_admin()
    async def gw_list_cmd(self, i: discord.Interaction):
        await i.response.defer()
        gws = await col("giveaways").find({"guild_id": i.guild_id, "active": True}).to_list(20)
        if not gws: await i.followup.send("Keine aktiven Giveaways."); return
        e = discord.Embed(title="🎉 Aktive Giveaways", color=discord.Color.gold())
        for gw in gws:
            ch = i.guild.get_channel(gw["channel_id"])
            e.add_field(
                name=gw["preis"],
                value=f"Kanal: {ch.mention if ch else '?'}\nEndet: <t:{int(gw['ends_at'].timestamp())}:R>\nGewinner: {gw['gewinner']}",
                inline=False
            )
        await i.followup.send(embed=e)

    async def _end_giveaway(self, gw: dict):
        try:
            g = self.bot.get_guild(gw["guild_id"])
            if not g: return
            ch = g.get_channel(gw["channel_id"])
            if not ch: return
            msg = await ch.fetch_message(gw["message_id"])
            rx = discord.utils.get(msg.reactions, emoji="🎉")
            us = [u async for u in rx.users() if not u.bot]
            if gw.get("rolle_id"):
                rl = g.get_role(gw["rolle_id"])
                if rl:
                    us = [u for u in us if rl in (g.get_member(u.id).roles if g.get_member(u.id) else [])]
            ws = random.sample(us, min(gw["gewinner"], len(us))) if us else []
            e = discord.Embed(title="🎉 Giveaway Beendet!", color=discord.Color.green())
            e.description = (
                f"**Preis:** {gw['preis']}\n"
                f"**Gewinner:** {', '.join(f'{w.mention} ({w.id})' for w in ws) if ws else 'Niemand'}"
            )
            await msg.edit(embed=e)
            if ws:
                await ch.send(f"🎉 Herzlichen Glückwunsch {', '.join(w.mention for w in ws)}! Ihr gewinnt **{gw['preis']}**!")
            await col("giveaways").update_one({"_id": gw["_id"]}, {"$set": {"active": False}})
        except Exception as ex:
            import logging
            logging.getLogger("rld").error(f"GW end: {ex}")

    @tasks.loop(minutes=1)
    async def gw_loop(self):
        ac = await col("giveaways").find({"active": True, "ends_at": {"$lte": datetime.utcnow()}}).to_list(10)
        for gw in ac:
            await self._end_giveaway(gw)

    @gw_loop.before_loop
    async def before_gw(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Giveaway(bot))