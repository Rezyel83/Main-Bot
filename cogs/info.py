import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, heco, start_t

class Info(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="User Informationen.")
    async def userinfo_cmd(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        await i.response.defer()
        u = user or i.user
        wc = await col("warns").count_documents({"guild_id": i.guild_id, "user_id": u.id})
        eco = await heco(i.guild_id, u.id)
        e = discord.Embed(title=f"👤 {u.display_name}", color=u.color)
        e.set_thumbnail(url=u.display_avatar.url)
        e.add_field(name="Name", value=f"{u} ({u.id})")
        e.add_field(name="Erstellt", value=u.created_at.strftime("%d.%m.%Y"))
        e.add_field(name="Beigetreten", value=u.joined_at.strftime("%d.%m.%Y") if u.joined_at else "?")
        e.add_field(name="Rollen", value=" ".join(r.mention for r in u.roles[1:]) or "Keine", inline=False)
        e.add_field(name="⚠️ Warns", value=str(wc))
        e.add_field(name="💰 Coins", value=str(eco.get("coins", 0)))
        vd = await col("voice_stats").find_one({"guild_id": i.guild_id, "user_id": u.id})
        if vd: e.add_field(name="🎙️ Voice Min", value=str(round(vd.get("total_minutes", 0))))
        await i.followup.send(embed=e)

    @app_commands.command(name="serverinfo", description="Server Informationen.")
    async def serverinfo_cmd(self, i: discord.Interaction):
        await i.response.defer()
        g = i.guild
        if not g: await i.followup.send("❌ Guild nicht gefunden"); return
        e = discord.Embed(title=f"🏠 {g.name}", color=discord.Color.blurple())
        if g.icon: e.set_thumbnail(url=g.icon.url)
        e.add_field(name="ID", value=str(g.id))
        e.add_field(name="Owner", value=f"{g.owner} ({g.owner_id})")
        e.add_field(name="Erstellt", value=g.created_at.strftime("%d.%m.%Y"))
        e.add_field(name="👥 Member", value=str(g.member_count))
        e.add_field(name="💬 Kanäle", value=str(len(g.channels)))
        e.add_field(name="🎭 Rollen", value=str(len(g.roles)))
        e.add_field(name="Boost", value=f"Level {g.premium_tier} ({g.premium_subscription_count}x)")
        await i.followup.send(embed=e)

    @app_commands.command(name="avatar", description="Avatar anzeigen.")
    async def avatar_cmd(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        u = user or i.user
        e = discord.Embed(title=f"🖼️ {u.display_name} ({u.id})", color=discord.Color.blurple())
        e.set_image(url=u.display_avatar.url)
        await i.response.send_message(embed=e)

    @app_commands.command(name="ping", description="Bot Latenz.")
    async def ping_cmd(self, i: discord.Interaction):
        up = datetime.utcnow() - start_t
        h, r = divmod(int(up.total_seconds()), 3600)
        m, s = divmod(r, 60)
        await i.response.send_message(f"🏓 **{round(self.bot.latency*1000)}ms** | Uptime: {h}h {m}m {s}s")

    @app_commands.command(name="timestamp", description="Discord Timestamp erstellen.")
    async def ts_cmd(self, i: discord.Interaction, datum: str, uhrzeit: str = "00:00"):
        try:
            dt = datetime.strptime(f"{datum} {uhrzeit}", "%d.%m.%Y %H:%M")
            ts = int(dt.timestamp())
            e = discord.Embed(title="🕐 Timestamp", color=discord.Color.blurple())
            for lb, fm in [("Kurze Zeit", "t"), ("Lange Zeit", "T"), ("Datum", "d"), ("Datum+Zeit", "f"), ("Relativ", "R")]:
                e.add_field(name=lb, value=f"`<t:{ts}:{fm}>` → <t:{ts}:{fm}>", inline=False)
            await i.response.send_message(embed=e)
        except:
            await i.response.send_message("❌ Format: DD.MM.YYYY und HH:MM")

    @app_commands.command(name="botinfo", description="Bot Informationen.")
    async def botinfo_cmd(self, i: discord.Interaction):
        e = discord.Embed(title="🤖 RLD Main Bot", color=discord.Color.red())
        e.add_field(name="Server", value=str(len(self.bot.guilds)))
        e.add_field(name="User", value=str(sum(g.member_count or 0 for g in self.bot.guilds)))
        e.add_field(name="Ping", value=f"{round(self.bot.latency*1000)}ms")
        e.add_field(name="Prefix", value="/ (Slash Commands)")
        e.set_footer(text="Made by Rezyel")
        await i.response.send_message(embed=e)

async def setup(bot):
    await bot.add_cog(Info(bot))