import discord
from discord.ext import commands
from discord import app_commands
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils import col, gcfg, ivcfg, is_admin

class Counting(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, msg: discord.Message):
        if msg.author.bot or not msg.guild: return
        cfg = await gcfg(msg.guild.id)
        counting_ch = cfg.get("counting_channel")
        if not counting_ch or str(msg.channel.id) != str(counting_ch): return

        # Get current counting state
        state = await col("counting").find_one({"guild_id": msg.guild.id})
        if not state:
            state = {"guild_id": msg.guild.id, "count": 0, "last_user": None, "high_score": 0}
            await col("counting").insert_one(state)

        current = state.get("count", 0)
        last_user = state.get("last_user")
        high_score = state.get("high_score", 0)

        # Check if message is a valid number
        try:
            num = int(msg.content.strip())
        except ValueError:
            # Not a number - ignore (don't delete non-number messages)
            return

        # Check rules
        if num != current + 1:
            # Wrong number
            await msg.add_reaction("❌")
            await col("counting").update_one(
                {"guild_id": msg.guild.id},
                {"$set": {"count": 0, "last_user": None}}
            )
            ivcfg(msg.guild.id)
            await msg.channel.send(
                f"❌ {msg.author.mention} hat gezählt! Die richtige Zahl wäre **{current + 1}** gewesen.\n"
                f"Gestartet von vorne! Nächste Zahl: **1**\n"
                f"(Rekord: **{high_score}**)",
                delete_after=10
            )
            return

        if last_user and last_user == msg.author.id:
            # Same user twice in a row
            await msg.add_reaction("❌")
            await col("counting").update_one(
                {"guild_id": msg.guild.id},
                {"$set": {"count": 0, "last_user": None}}
            )
            ivcfg(msg.guild.id)
            await msg.channel.send(
                f"❌ {msg.author.mention} darf nicht zweimal hintereinander zählen!\n"
                f"Gestartet von vorne! Nächste Zahl: **1**\n"
                f"(Rekord: **{high_score}**)",
                delete_after=10
            )
            return

        # Correct!
        new_count = current + 1
        new_high = max(high_score, new_count)
        await col("counting").update_one(
            {"guild_id": msg.guild.id},
            {"$set": {"count": new_count, "last_user": msg.author.id, "high_score": new_high}}
        )
        ivcfg(msg.guild.id)
        await msg.add_reaction("✅")

        # Milestone reactions
        if new_count % 100 == 0:
            await msg.add_reaction("🎉")
            await msg.channel.send(f"🎉 **{new_count}** erreicht! Weiter so!", delete_after=5)
        elif new_count % 50 == 0:
            await msg.add_reaction("🔥")

        # New high score
        if new_count > high_score:
            await msg.add_reaction("🏆")

    @app_commands.command(name="counting-setup", description="[Admin] Counting Kanal einrichten.")
    @is_admin()
    async def counting_setup(self, i: discord.Interaction, kanal: discord.TextChannel):
        await i.response.defer()
        await col("config").update_one(
            {"guild_id": i.guild_id},
            {"$set": {"counting_channel": kanal.id}},
            upsert=True
        )
        ivcfg(i.guild_id)
        # Reset count
        await col("counting").update_one(
            {"guild_id": i.guild_id},
            {"$set": {"count": 0, "last_user": None, "high_score": 0}},
            upsert=True
        )
        e = discord.Embed(
            title="🔢 Counting eingerichtet!",
            description=f"Counting Kanal: {kanal.mention}\n\nRegeln:\n• Schreibe die nächste Zahl\n• Du darfst nicht zweimal hintereinander zählen\n• Falsche Zahl = Neustart von 1",
            color=discord.Color.green()
        )
        await i.followup.send(embed=e)
        await kanal.send(embed=discord.Embed(
            title="🔢 Counting gestartet!",
            description="Fang mit **1** an!\n\n**Regeln:**\n✅ Schreibe die nächste Zahl\n❌ Nicht zweimal hintereinander\n❌ Falsche Zahl = Neustart",
            color=discord.Color.blurple()
        ))

    @app_commands.command(name="counting-reset", description="[Admin] Counting zurücksetzen.")
    @is_admin()
    async def counting_reset(self, i: discord.Interaction):
        await i.response.defer()
        await col("counting").update_one(
            {"guild_id": i.guild_id},
            {"$set": {"count": 0, "last_user": None}},
            upsert=True
        )
        await i.followup.send("✅ Counting zurückgesetzt! Nächste Zahl: **1**")

    @app_commands.command(name="counting-score", description="Aktuellen Stand anzeigen.")
    async def counting_score(self, i: discord.Interaction):
        await i.response.defer()
        state = await col("counting").find_one({"guild_id": i.guild_id})
        if not state:
            await i.followup.send("❌ Counting nicht eingerichtet. Nutze /counting-setup")
            return
        e = discord.Embed(title="🔢 Counting Status", color=discord.Color.blurple())
        e.add_field(name="Aktueller Stand", value=str(state.get("count", 0)))
        e.add_field(name="🏆 Rekord", value=str(state.get("high_score", 0)))
        last = state.get("last_user")
        if last and i.guild:
            m = i.guild.get_member(last)
            e.add_field(name="Letzter", value=m.mention if m else str(last))
        await i.followup.send(embed=e)

async def setup(bot):
    await bot.add_cog(Counting(bot))
