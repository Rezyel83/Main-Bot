import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, logcase, gcfg, _mlog, is_mod, is_admin

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ban", description="User bannen.")
    @is_mod()
    async def ban_cmd(self, i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund", del_days: int = 0):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        if user.top_role >= i.user.top_role: await i.followup.send("❌ Höhere Rolle!"); return
        try: await user.send(f"Du wurdest von **{i.guild.name}** gebannt. Grund: {grund}")
        except: pass
        await i.guild.ban(user, reason=grund, delete_message_days=del_days)
        n = await logcase(i.guild_id, i.user.id, user.id, "ban", grund)
        e = discord.Embed(title=f"🔨 Ban | Case #{n}", color=discord.Color.red())
        e.add_field(name="User", value=f"{user} ({user.id})")
        e.add_field(name="Mod", value=f"{i.user} ({i.user.id})")
        e.add_field(name="Grund", value=grund, inline=False)
        await i.followup.send(embed=e)
        await _mlog(i.guild, e)

    @app_commands.command(name="unban", description="User entbannen.")
    @is_mod()
    async def unban_cmd(self, i: discord.Interaction, user_id: str, grund: str = "Kein Grund"):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        try:
            u = await self.bot.fetch_user(int(user_id))
            await i.guild.unban(u, reason=grund)
            await i.followup.send(f"✅ **{u}** ({u.id}) entbannt.")
        except: await i.followup.send("❌ User nicht gefunden.")

    @app_commands.command(name="kick", description="User kicken.")
    @is_mod()
    async def kick_cmd(self, i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        if user.top_role >= i.user.top_role: await i.followup.send("❌ Höhere Rolle!"); return
        try: await user.send(f"Du wurdest von **{i.guild.name}** gekickt. Grund: {grund}")
        except: pass
        await user.kick(reason=grund)
        n = await logcase(i.guild_id, i.user.id, user.id, "kick", grund)
        e = discord.Embed(title=f"👢 Kick | Case #{n}", color=discord.Color.orange())
        e.add_field(name="User", value=f"{user} ({user.id})")
        e.add_field(name="Mod", value=f"{i.user} ({i.user.id})")
        e.add_field(name="Grund", value=grund, inline=False)
        await i.followup.send(embed=e)
        await _mlog(i.guild, e)

    @app_commands.command(name="timeout", description="User timeout.")
    @is_mod()
    async def timeout_cmd(self, i: discord.Interaction, user: discord.Member, minuten: int, grund: str = "Kein Grund"):
        await i.response.defer()
        await user.timeout(discord.utils.utcnow() + timedelta(minutes=minuten), reason=grund)
        n = await logcase(i.guild_id, i.user.id, user.id, "timeout", grund)
        e = discord.Embed(title=f"⏰ Timeout | Case #{n}", color=discord.Color.yellow())
        e.add_field(name="User", value=f"{user} ({user.id})")
        e.add_field(name="Dauer", value=f"{minuten} Min")
        e.add_field(name="Grund", value=grund, inline=False)
        await i.followup.send(embed=e)
        await _mlog(i.guild, e)

    @app_commands.command(name="untimeout", description="Timeout aufheben.")
    @is_mod()
    async def untimeout_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        await user.timeout(None)
        await i.followup.send(f"✅ Timeout von {user.mention} ({user.id}) aufgehoben.")

    @app_commands.command(name="warn", description="User verwarnen.")
    @is_mod()
    async def warn_cmd(self, i: discord.Interaction, user: discord.Member, grund: str):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        await col("warns").insert_one({
            "guild_id": i.guild_id, "user_id": user.id, "mod_id": i.user.id,
            "grund": grund, "ts": datetime.utcnow()
        })
        cnt = await col("warns").count_documents({"guild_id": i.guild_id, "user_id": user.id})
        n = await logcase(i.guild_id, i.user.id, user.id, "warn", grund)
        try: await user.send(f"Verwarnung auf **{i.guild.name}**. Grund: {grund} (Warn #{cnt})")
        except: pass
        e = discord.Embed(title=f"⚠️ Warn | Case #{n}", color=discord.Color.yellow())
        e.add_field(name="User", value=f"{user} ({user.id})")
        e.add_field(name="Anzahl", value=str(cnt))
        e.add_field(name="Mod", value=f"{i.user} ({i.user.id})")
        e.add_field(name="Grund", value=grund, inline=False)
        await i.followup.send(embed=e)
        await _mlog(i.guild, e)

    @app_commands.command(name="warns", description="Verwarnungen anzeigen.")
    @is_mod()
    async def warns_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        ws = await col("warns").find({"guild_id": i.guild_id, "user_id": user.id}).sort("ts", -1).to_list(20)
        e = discord.Embed(title=f"⚠️ Warns: {user.display_name} ({user.id})", color=discord.Color.yellow())
        if not ws:
            e.description = "Keine Verwarnungen."
        else:
            for idx, w in enumerate(ws, 1):
                md = i.guild.get_member(w["mod_id"])
                mod_str = f"{md} ({md.id})" if md else str(w["mod_id"])
                e.add_field(
                    name=f"#{idx} – {w['ts'].strftime('%d.%m.%Y %H:%M')}",
                    value=f"{w['grund']}\nMod: {mod_str}", inline=False
                )
        await i.followup.send(embed=e)

    @app_commands.command(name="unwarn", description="Letzte Verwarnung entfernen.")
    @is_mod()
    async def unwarn_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        l = await col("warns").find_one({"guild_id": i.guild_id, "user_id": user.id}, sort=[("ts", -1)])
        if not l: await i.followup.send("❌ Keine Verwarnungen."); return
        await col("warns").delete_one({"_id": l["_id"]})
        await i.followup.send(f"✅ Letzte Warn von {user.mention} ({user.id}) entfernt.")

    @app_commands.command(name="clearwarns", description="[Admin] Alle Warns löschen.")
    @is_admin()
    async def clearwarns_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        r = await col("warns").delete_many({"guild_id": i.guild_id, "user_id": user.id})
        await i.followup.send(f"✅ {r.deleted_count} Warns von {user} ({user.id}) gelöscht.")

    @app_commands.command(name="case", description="Case anzeigen.")
    @is_mod()
    async def case_cmd(self, i: discord.Interaction, nummer: int):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        c = await col("cases").find_one({"guild_id": i.guild_id, "case": nummer})
        if not c: await i.followup.send("❌ Case nicht gefunden."); return
        md = i.guild.get_member(c["mod_id"])
        tg = i.guild.get_member(c["target_id"])
        e = discord.Embed(title=f"📋 Case #{nummer}", color=discord.Color.blurple())
        e.add_field(name="Aktion", value=c["aktion"])
        e.add_field(name="User", value=f"{tg} ({c['target_id']})" if tg else str(c["target_id"]))
        e.add_field(name="Mod", value=f"{md} ({c['mod_id']})" if md else str(c["mod_id"]))
        e.add_field(name="Grund", value=c["grund"], inline=False)
        e.add_field(name="Datum", value=c["ts"].strftime("%d.%m.%Y %H:%M"))
        await i.followup.send(embed=e)

    @app_commands.command(name="clear", description="Nachrichten löschen.")
    @is_mod()
    async def clear_cmd(self, i: discord.Interaction, anzahl: int, user: Optional[discord.Member] = None):
        await i.response.defer(ephemeral=True)
        if not i.channel or not hasattr(i.channel, "purge"):
            await i.followup.send("❌ Kanal nicht verfügbar", ephemeral=True); return
        chk = (lambda m: m.author == user) if user else None
        d = await i.channel.purge(limit=min(anzahl, 100), check=chk) if chk else await i.channel.purge(limit=min(anzahl, 100))
        await i.followup.send(f"✅ {len(d)} Nachrichten gelöscht.", ephemeral=True)

    @app_commands.command(name="slowmode", description="Slowmode setzen.")
    @is_mod()
    async def slowmode_cmd(self, i: discord.Interaction, sekunden: int):
        await i.response.defer()
        if not i.channel or not hasattr(i.channel, "edit"):
            await i.followup.send("❌ Kanal nicht verfügbar"); return
        await i.channel.edit(slowmode_delay=sekunden)
        await i.followup.send(f"✅ Slowmode: **{sekunden}s**")

    @app_commands.command(name="lock", description="Kanal sperren.")
    @is_mod()
    async def lock_cmd(self, i: discord.Interaction):
        await i.response.defer()
        if not i.guild or not i.channel or not hasattr(i.channel, "set_permissions"):
            await i.followup.send("❌ Nicht verfügbar"); return
        await i.channel.set_permissions(i.guild.default_role, send_messages=False)
        await i.followup.send("🔒 Kanal gesperrt.")

    @app_commands.command(name="unlock", description="Kanal entsperren.")
    @is_mod()
    async def unlock_cmd(self, i: discord.Interaction):
        await i.response.defer()
        if not i.guild or not i.channel or not hasattr(i.channel, "set_permissions"):
            await i.followup.send("❌ Nicht verfügbar"); return
        await i.channel.set_permissions(i.guild.default_role, send_messages=True)
        await i.followup.send("🔓 Kanal entsperrt.")

    @app_commands.command(name="nick", description="Nickname ändern.")
    @is_mod()
    async def nick_cmd(self, i: discord.Interaction, user: discord.Member, name: str = ""):
        await i.response.defer()
        await user.edit(nick=name or None)
        await i.followup.send(f"✅ Nick von {user.mention} ({user.id}) geändert.")

    @app_commands.command(name="raid-mode", description="[Admin] Raid Mode an/aus.")
    @is_admin()
    async def raidmode_cmd(self, i: discord.Interaction, aktiv: bool):
        await i.response.defer()
        if not i.guild_id: await i.followup.send("❌ Guild ID nicht gefunden"); return
        await col("config").update_one({"guild_id": i.guild_id}, {"$set": {"anti_raid": aktiv}}, upsert=True)
        await i.followup.send(f"{'🚨 Raid Mode AKTIV' if aktiv else '✅ Raid Mode deaktiviert'}")

    @app_commands.command(name="purge-user", description="Nachrichten eines Users löschen.")
    @is_mod()
    async def purge_cmd(self, i: discord.Interaction, user: discord.Member, limit: int = 100):
        await i.response.defer(ephemeral=True)
        if not i.channel or not hasattr(i.channel, "purge"):
            await i.followup.send("❌ Kanal nicht verfügbar", ephemeral=True); return
        d = await i.channel.purge(limit=min(limit, 500), check=lambda m: m.author == user)
        await i.followup.send(f"✅ {len(d)} Nachrichten von {user.display_name} ({user.id}) gelöscht.", ephemeral=True)

    @app_commands.command(name="say", description="[Admin] Bot sendet eine Nachricht.")
    @is_admin()
    async def say_cmd(self, i: discord.Interaction, kanal: discord.TextChannel, nachricht: str):
        await i.response.defer(ephemeral=True)
        await kanal.send(nachricht)
        await i.followup.send(f"✅ Nachricht in {kanal.mention} gesendet.", ephemeral=True)

    @app_commands.command(name="announce", description="[Admin] Ankündigung mit Embed senden.")
    @is_admin()
    async def announce_cmd(self, i: discord.Interaction, kanal: discord.TextChannel, titel: str, nachricht: str, farbe: str = "red"):
        await i.response.defer(ephemeral=True)
        farben = {"red": discord.Color.red(), "blue": discord.Color.blue(), "green": discord.Color.green(), "gold": discord.Color.gold()}
        e = discord.Embed(title=titel, description=nachricht, color=farben.get(farbe, discord.Color.red()))
        e.set_footer(text=i.guild.name if i.guild else "")
        await kanal.send(embed=e)
        await i.followup.send(f"✅ Ankündigung in {kanal.mention} gesendet.", ephemeral=True)

    @commands.command(name="mute")
    @commands.has_permissions(kick_members=True)
    async def mute_p(self, ctx, user: discord.Member, minuten: int = 10, *, grund: str = "Kein Grund"):
        await user.timeout(discord.utils.utcnow() + timedelta(minutes=minuten), reason=grund)
        await ctx.send(f"⏰ {user.mention} ({user.id}) für **{minuten} Min** gemutet.")

    @commands.command(name="unmute")
    @commands.has_permissions(kick_members=True)
    async def unmute_p(self, ctx, user: discord.Member):
        await user.timeout(None)
        await ctx.send(f"✅ {user.mention} ({user.id}) entmutet.")

    @commands.command(name="clear")
    @commands.has_permissions(manage_messages=True)
    async def clear_p(self, ctx, anzahl: int = 10):
        d = await ctx.channel.purge(limit=min(anzahl + 1, 101))
        await ctx.send(f"✅ {len(d)-1} Nachrichten gelöscht.", delete_after=3)

async def setup(bot):
    await bot.add_cog(Moderation(bot))