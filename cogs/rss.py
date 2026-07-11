import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime
from typing import Optional
from utils import col, is_admin, is_mod
import logging
log = logging.getLogger("rld")

class RSS(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.rss_loop.start()

    def cog_unload(self):
        self.rss_loop.cancel()

    @app_commands.command(name="rss-add", description="[Admin] RSS Feed hinzufügen (max 5).")
    @is_admin()
    async def rssadd(self, i: discord.Interaction, name: str, url: str,
                     kanal: discord.TextChannel, ping_rolle: Optional[discord.Role] = None):
        await i.response.defer()
        count = await col("rss_feeds").count_documents({"guild_id": i.guild_id})
        if count >= 5:
            await i.followup.send("❌ Maximal 5 RSS Feeds erlaubt! Entferne zuerst einen."); return
        import feedparser
        p = feedparser.parse(url)
        if not p.entries:
            await i.followup.send("❌ Ungültiger Feed oder keine Einträge!"); return
        existing = await col("rss_feeds").find_one({"guild_id": i.guild_id, "name": name})
        if existing:
            await i.followup.send("❌ Ein Feed mit diesem Namen existiert bereits."); return
        await col("rss_feeds").insert_one({
            "guild_id": i.guild_id, "name": name, "url": url,
            "channel_id": kanal.id,
            "ping_role_id": ping_rolle.id if ping_rolle else None,
            "aktiv": True, "added": datetime.utcnow()
        })
        await i.followup.send(f"✅ RSS **{name}** → {kanal.mention}" + (f" | Ping: {ping_rolle.mention}" if ping_rolle else ""))

    @app_commands.command(name="rss-remove", description="[Admin] RSS Feed entfernen.")
    @is_admin()
    async def rssremove(self, i: discord.Interaction, name: str):
        r = await col("rss_feeds").delete_one({"guild_id": i.guild_id, "name": name})
        await i.response.send_message("✅ Entfernt." if r.deleted_count else "❌ Nicht gefunden.")

    @app_commands.command(name="rss-list", description="RSS Feeds anzeigen.")
    async def rsslist(self, i: discord.Interaction):
        await i.response.defer()
        fs = await col("rss_feeds").find({"guild_id": i.guild_id}).to_list(5)
        if not fs: await i.followup.send("Keine RSS Feeds konfiguriert."); return
        e = discord.Embed(title="📰 RSS Feeds", color=discord.Color.blurple())
        for idx, f in enumerate(fs, 1):
            ch = i.guild.get_channel(f["channel_id"])
            ping = ""
            if f.get("ping_role_id"):
                r = i.guild.get_role(f["ping_role_id"])
                ping = f" | Ping: {r.mention}" if r else ""
            e.add_field(
                name=f"Slot {idx}: {'✅' if f.get('aktiv') else '⏸️'} {f['name']}",
                value=f"Kanal: {ch.mention if ch else '?'}{ping}\nURL: `{f['url'][:60]}...`",
                inline=False
            )
        e.set_footer(text=f"{len(fs)}/5 Slots belegt")
        await i.followup.send(embed=e)

    @app_commands.command(name="rss-toggle", description="[Admin] RSS Feed aktivieren/deaktivieren.")
    @is_admin()
    async def rss_toggle(self, i: discord.Interaction, name: str):
        f = await col("rss_feeds").find_one({"guild_id": i.guild_id, "name": name})
        if not f: await i.response.send_message("❌ Nicht gefunden."); return
        new = not f.get("aktiv", True)
        await col("rss_feeds").update_one({"_id": f["_id"]}, {"$set": {"aktiv": new}})
        await i.response.send_message(f"✅ **{name}** {'aktiviert' if new else 'deaktiviert'}.")

    @tasks.loop(minutes=15)
    async def rss_loop(self):
        import feedparser
        fs = await col("rss_feeds").find({"aktiv": True}).to_list(50)
        for feed in fs:
            try:
                p = feedparser.parse(feed["url"])
                g = self.bot.get_guild(feed["guild_id"])
                if not g: continue
                ch = g.get_channel(feed["channel_id"])
                if not ch: continue
                ping_str = ""
                if feed.get("ping_role_id"):
                    r = g.get_role(feed["ping_role_id"])
                    if r: ping_str = r.mention
                for entry in p.entries[:3]:
                    link = entry.get("link", "")
                    if not link: continue
                    if await col("rss_seen").find_one({"feed_id": str(feed["_id"]), "link": link}): continue
                    e = discord.Embed(
                        title=entry.get("title", "")[:250],
                        url=link,
                        description=entry.get("summary", "")[:300],
                        color=discord.Color.blurple()
                    )
                    e.set_footer(text=f"📰 {feed.get('name', 'RSS')}")
                    content = ping_str if ping_str else None
                    await ch.send(content=content, embed=e)
                    await col("rss_seen").insert_one({
                        "feed_id": str(feed["_id"]), "link": link, "ts": datetime.utcnow()
                    })
            except Exception as ex:
                log.error(f"RSS [{feed.get('name')}]: {ex}")

    @rss_loop.before_loop
    async def before_rss(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(RSS(bot))
