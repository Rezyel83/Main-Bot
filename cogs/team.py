import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, is_admin, is_mod

class Team(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="team-add", description="[Admin] User zum Team hinzufügen.")
    @is_admin()
    async def tadd_cmd(self, i: discord.Interaction, user: discord.Member, rolle: str = "Moderator"):
        await col("team").update_one(
            {"guild_id": i.guild_id, "user_id": user.id},
            {"$set": {"guild_id": i.guild_id, "user_id": user.id, "username": str(user),
                      "rolle": rolle, "joined": datetime.utcnow(), "aktiv": True,
                      "notizen": [], "abmeldungen": []}},
            upsert=True
        )
        await i.response.send_message(f"✅ {user.mention} ({user.id}) → **{rolle}**")

    @app_commands.command(name="team-remove", description="[Admin] User aus Team entfernen.")
    @is_admin()
    async def tremove_cmd(self, i: discord.Interaction, user: discord.Member):
        await col("team").delete_one({"guild_id": i.guild_id, "user_id": user.id})
        await i.response.send_message(f"✅ {user.mention} ({user.id}) entfernt.")

    @app_commands.command(name="team", description="Team anzeigen.")
    async def team_cmd(self, i: discord.Interaction):
        await i.response.defer()
        ms = await col("team").find({"guild_id": i.guild_id, "aktiv": True}).to_list(50)
        e = discord.Embed(title="👥 Team", color=discord.Color.blurple())
        if not ms:
            e.description = "Kein Team."
        else:
            for m in ms:
                u = i.guild.get_member(m["user_id"])
                name = f"{u.display_name} ({m['user_id']})" if u else str(m["user_id"])
                e.add_field(name=m.get("rolle", "Mitglied"), value=name, inline=True)
        await i.followup.send(embed=e)

    @app_commands.command(name="abmelden", description="Abwesenheit eintragen.")
    async def abmeld_cmd(self, i: discord.Interaction, von: str, bis: str, grund: str = "Kein Grund"):
        m = await col("team").find_one({"guild_id": i.guild_id, "user_id": i.user.id})
        if not m: await i.response.send_message("❌ Kein Team-Mitglied!", ephemeral=True); return
        await col("team").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$push": {"abmeldungen": {"von": von, "bis": bis, "grund": grund, "ts": datetime.utcnow()}}}
        )
        await i.response.send_message(f"✅ Abmeldung: **{von}** bis **{bis}**", ephemeral=True)

    @app_commands.command(name="team-notiz", description="Notiz hinzufügen (nur für dich selbst).")
    async def notiz_cmd(self, i: discord.Interaction, text: str):
        m = await col("team").find_one({"guild_id": i.guild_id, "user_id": i.user.id})
        if not m: await i.response.send_message("❌ Kein Team-Mitglied!", ephemeral=True); return
        await col("team").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$push": {"notizen": {"text": text, "ts": datetime.utcnow()}}}
        )
        await i.response.send_message("✅ Notiz gespeichert!", ephemeral=True)

    @app_commands.command(name="team-warn", description="[Admin/Manager] Team-Mitglied verwarnen.")
    @is_mod()
    async def team_warn_cmd(self, i: discord.Interaction, user: discord.Member, grund: str):
        m = await col("team").find_one({"guild_id": i.guild_id, "user_id": user.id})
        if not m: await i.response.send_message("❌ Kein Team-Mitglied!", ephemeral=True); return
        await col("team").update_one(
            {"guild_id": i.guild_id, "user_id": user.id},
            {"$push": {"team_warns": {"mod_id": i.user.id, "grund": grund, "ts": datetime.utcnow()}}}
        )
        try: await user.send(f"⚠️ Team-Verwarnung auf **{i.guild.name}**: {grund}")
        except: pass
        await i.response.send_message(f"✅ Team-Warn an {user.mention} ({user.id}) gesendet.")

    @app_commands.command(name="team-kick", description="[Admin] Team-Mitglied kicken.")
    @is_admin()
    async def team_kick_cmd(self, i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
        await col("team").update_one(
            {"guild_id": i.guild_id, "user_id": user.id},
            {"$set": {"aktiv": False, "kicked_reason": grund, "kicked_at": datetime.utcnow()}}
        )
        try: await user.send(f"❌ Du wurdest aus dem Team von **{i.guild.name}** entfernt. Grund: {grund}")
        except: pass
        await i.response.send_message(f"✅ {user.mention} ({user.id}) aus dem Team entfernt.")

    @app_commands.command(name="bewerben", description="Fürs Team bewerben.")
    async def bewerb_cmd(self, i: discord.Interaction, alter: str, erfahrung: str, warum: str, verfuegbarkeit: str):
        await i.response.defer(ephemeral=True)
        ex = await col("applications").find_one({"guild_id": i.guild_id, "user_id": i.user.id, "status": "offen"})
        if ex: await i.followup.send("❌ Du hast bereits eine offene Bewerbung!"); return
        await col("applications").insert_one({
            "guild_id": i.guild_id, "user_id": i.user.id, "username": str(i.user),
            "alter": alter, "erfahrung": erfahrung, "warum": warum,
            "verfuegbarkeit": verfuegbarkeit, "status": "offen",
            "typ": "extern", "ts": datetime.utcnow()
        })
        from bot import gcfg
        cfg = await gcfg(i.guild_id)
        cid = cfg.get("log_channels", {}).get("mod_log") or cfg.get("mod_log")
        if cid:
            ch = i.guild.get_channel(int(cid))
            if ch:
                e = discord.Embed(title="📝 Neue Bewerbung", color=discord.Color.blurple())
                e.add_field(name="User", value=f"{i.user} ({i.user.id})")
                e.add_field(name="Alter", value=alter)
                e.add_field(name="Erfahrung", value=erfahrung, inline=False)
                e.add_field(name="Warum", value=warum, inline=False)
                e.add_field(name="Verfügbarkeit", value=verfuegbarkeit)
                await ch.send(embed=e)
        await i.followup.send("✅ Bewerbung eingereicht!")

    @app_commands.command(name="bewerbungen", description="[Admin] Bewerbungen anzeigen.")
    @is_admin()
    async def bewerbungen_cmd(self, i: discord.Interaction):
        await i.response.defer()
        apps = await col("applications").find({"guild_id": i.guild_id, "status": "offen"}).to_list(20)
        if not apps: await i.followup.send("Keine offenen Bewerbungen."); return
        e = discord.Embed(title="📝 Bewerbungen", color=discord.Color.blurple())
        for a in apps:
            u = i.guild.get_member(a["user_id"])
            name = f"{u} ({a['user_id']})" if u else str(a["user_id"])
            e.add_field(name=name, value=f"Alter: {a['alter']}\n{a['verfuegbarkeit']}", inline=True)
        await i.followup.send(embed=e)

    @app_commands.command(name="bewerbung-accept", description="[Admin] Bewerbung annehmen.")
    @is_admin()
    async def bacc_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        ap = await col("applications").find_one({"guild_id": i.guild_id, "user_id": user.id, "status": "offen"})
        if not ap: await i.followup.send("❌ Keine offene Bewerbung."); return
        await col("applications").update_one({"_id": ap["_id"]}, {"$set": {"status": "angenommen"}})
        try: await user.send(f"🎉 Deine Bewerbung auf **{i.guild.name}** wurde angenommen!")
        except: pass
        await i.followup.send(f"✅ {user.mention} ({user.id}) angenommen!")

    @app_commands.command(name="bewerbung-deny", description="[Admin] Bewerbung ablehnen.")
    @is_admin()
    async def bdeny_cmd(self, i: discord.Interaction, user: discord.Member, grund: str = "Kein Grund"):
        await i.response.defer()
        ap = await col("applications").find_one({"guild_id": i.guild_id, "user_id": user.id, "status": "offen"})
        if not ap: await i.followup.send("❌ Keine offene Bewerbung."); return
        await col("applications").update_one({"_id": ap["_id"]}, {"$set": {"status": "abgelehnt"}})
        try: await user.send(f"❌ Deine Bewerbung auf **{i.guild.name}** wurde abgelehnt. Grund: {grund}")
        except: pass
        await i.followup.send("✅ Abgelehnt.")

async def setup(bot):
    await bot.add_cog(Team(bot))