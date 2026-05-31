import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, is_admin, is_mod
import logging
log = logging.getLogger("rld")

TWITCH_ID     = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")

class Notifications(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.twitch_loop.start()

    def cog_unload(self):
        self.twitch_loop.cancel()

    @app_commands.command(name="notif-twitch", description="[Admin] Twitch Notification einrichten.")
    @is_admin()
    async def ntwitch(self, i: discord.Interaction, streamer: str, kanal: discord.TextChannel,
                      ping_rolle: Optional[discord.Role] = None,
                      nachricht: str = "{streamer} ist jetzt live! 🎮"):
        await col("notifications").update_one(
            {"guild_id": i.guild_id, "type": "twitch", "name": streamer.lower()},
            {"$set": {
                "channel_id": kanal.id,
                "ping_role_id": ping_rolle.id if ping_rolle else None,
                "message": nachricht, "live": False
            }},
            upsert=True
        )
        await i.response.send_message(
            f"✅ Twitch: **{streamer}** → {kanal.mention}" +
            (f" | Ping: {ping_rolle.mention}" if ping_rolle else "")
        )

    @app_commands.command(name="notif-remove", description="[Admin] Notification entfernen.")
    @is_admin()
    async def nremove(self, i: discord.Interaction, name: str):
        r = await col("notifications").delete_one({"guild_id": i.guild_id, "name": name.lower()})
        await i.response.send_message("✅ Entfernt." if r.deleted_count else "❌ Nicht gefunden.")

    @app_commands.command(name="notif-list", description="Notifications anzeigen.")
    @is_mod()
    async def nlist(self, i: discord.Interaction):
        await i.response.defer()
        ns = await col("notifications").find({"guild_id": i.guild_id}).to_list(20)
        if not ns: await i.followup.send("Keine Notifications konfiguriert."); return
        e = discord.Embed(title="🔔 Notifications", color=discord.Color.purple())
        for n in ns:
            ch = i.guild.get_channel(n["channel_id"])
            status = "🟢 Live" if n.get("live") else "⚫ Offline"
            ping = ""
            if n.get("ping_role_id"):
                r = i.guild.get_role(n["ping_role_id"])
                ping = f" | Ping: {r.mention}" if r else ""
            e.add_field(
                name=f"{n['type'].title()}: {n['name']} {status}",
                value=f"Kanal: {ch.mention if ch else '?'}{ping}",
                inline=True
            )
        await i.followup.send(embed=e)

    @tasks.loop(minutes=5)
    async def twitch_loop(self):
        if not TWITCH_ID or not TWITCH_SECRET: return
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    "https://id.twitch.tv/oauth2/token",
                    params={"client_id": TWITCH_ID, "client_secret": TWITCH_SECRET, "grant_type": "client_credentials"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    td = await r.json()
                token = td.get("access_token")
                if not token: return
                streamers = await col("notifications").find({"type": "twitch"}).to_list(50)
                for sr in streamers:
                    async with s.get(
                        f"https://api.twitch.tv/helix/streams?user_login={sr['name']}",
                        headers={"Client-ID": TWITCH_ID, "Authorization": f"Bearer {token}"},
                        timeout=aiohttp.ClientTimeout(total=8)
                    ) as r:
                        d = await r.json()
                    is_live = bool(d.get("data"))
                    was_live = sr.get("live", False)
                    if is_live and not was_live:
                        g = self.bot.get_guild(sr["guild_id"])
                        if g:
                            ch = g.get_channel(sr["channel_id"])
                            if ch:
                                stream = d["data"][0]
                                msg = sr.get("message", "{streamer} ist live!").replace("{streamer}", sr["name"])
                                ping_str = ""
                                if sr.get("ping_role_id"):
                                    rl = g.get_role(sr["ping_role_id"])
                                    if rl: ping_str = rl.mention
                                e = discord.Embed(
                                    title=stream.get("title", "Live!"),
                                    url=f"https://twitch.tv/{sr['name']}",
                                    color=discord.Color.purple()
                                )
                                e.add_field(name="Spiel", value=stream.get("game_name", "?"))
                                e.add_field(name="Zuschauer", value=str(stream.get("viewer_count", 0)))
                                e.set_footer(text=f"twitch.tv/{sr['name']}")
                                await ch.send(content=f"{ping_str} {msg}" if ping_str else msg, embed=e)
                    await col("notifications").update_one({"_id": sr["_id"]}, {"$set": {"live": is_live}})
        except Exception as ex:
            log.error(f"Twitch loop: {ex}")

    @twitch_loop.before_loop
    async def before_twitch(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(Notifications(bot))