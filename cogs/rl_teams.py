import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
from typing import Optional
from utils import col, is_admin

class RLTeams(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="rl-team-erstellen", description="RL Team erstellen.")
    async def rlcreate_cmd(self, i: discord.Interaction, name: str, format: str = "3v3"):
        await i.response.defer()
        if await col("rl_teams").find_one({"guild_id": i.guild_id, "captain_id": i.user.id}):
            await i.followup.send("❌ Du hast bereits ein Team! Löse es zuerst auf."); return
        await col("rl_teams").insert_one({
            "guild_id": i.guild_id, "name": name, "format": format,
            "captain_id": i.user.id, "captain_name": str(i.user),
            "members": [{"user_id": i.user.id, "username": str(i.user), "epic": "", "rolle": "Captain"}],
            "trainers": [],
            "wins": 0, "losses": 0, "created": datetime.utcnow(),
            "bild": None
        })
        await i.followup.send(f"✅ Team **{name}** ({format}) erstellt!")

    @app_commands.command(name="rl-team-einladen", description="Spieler einladen.")
    async def rlinvite_cmd(self, i: discord.Interaction, user: discord.Member, rolle: str = "Spieler"):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "captain_id": i.user.id})
        if not t: await i.followup.send("❌ Du hast kein Team."); return
        if any(m["user_id"] == user.id for m in t["members"]):
            await i.followup.send("❌ Bereits im Team!"); return
        if rolle.lower() == "trainer":
            if len(t.get("trainers", [])) >= 2:
                await i.followup.send("❌ Maximal 2 Trainer erlaubt!"); return
            await col("rl_teams").update_one(
                {"_id": t["_id"]},
                {"$push": {"trainers": {"user_id": user.id, "username": str(user), "epic": ""}}}
            )
        else:
            await col("rl_teams").update_one(
                {"_id": t["_id"]},
                {"$push": {"members": {"user_id": user.id, "username": str(user), "epic": "", "rolle": rolle}}}
            )
        try: await user.send(f"🚗 Du wurdest von **{i.user.display_name}** in das RL Team **{t['name']}** eingeladen!")
        except: pass
        await i.followup.send(f"✅ {user.mention} ({user.id}) als **{rolle}** eingeladen!")

    @app_commands.command(name="rl-team-join", description="RL Team beitreten.")
    async def rljoin_cmd(self, i: discord.Interaction, team_name: str):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "name": team_name})
        if not t: await i.followup.send("❌ Team nicht gefunden."); return
        if any(m["user_id"] == i.user.id for m in t["members"]):
            await i.followup.send("❌ Bereits im Team!"); return
        await col("rl_teams").update_one(
            {"_id": t["_id"]},
            {"$push": {"members": {"user_id": i.user.id, "username": str(i.user), "epic": "", "rolle": "Spieler"}}}
        )
        await i.followup.send(f"✅ Team **{team_name}** beigetreten!")

    @app_commands.command(name="rl-team-leave", description="RL Team verlassen.")
    async def rlleave_cmd(self, i: discord.Interaction):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "members.user_id": i.user.id})
        if not t: await i.followup.send("❌ Du bist in keinem Team."); return
        if t["captain_id"] == i.user.id:
            await i.followup.send("❌ Captain kann nicht verlassen. Nutze /rl-team-disband."); return
        await col("rl_teams").update_one({"_id": t["_id"]}, {"$pull": {"members": {"user_id": i.user.id}}})
        await i.followup.send("✅ Team verlassen.")

    @app_commands.command(name="rl-team-disband", description="RL Team auflösen.")
    async def rldisband_cmd(self, i: discord.Interaction):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "captain_id": i.user.id})
        if not t: await i.followup.send("❌ Du hast kein Team."); return
        await col("rl_teams").delete_one({"_id": t["_id"]})
        await i.followup.send(f"✅ Team **{t['name']}** aufgelöst.")

    @app_commands.command(name="rl-teams", description="Alle RL Teams anzeigen.")
    async def rlteams_cmd(self, i: discord.Interaction):
        await i.response.defer()
        ts = await col("rl_teams").find({"guild_id": i.guild_id}).to_list(20)
        if not ts: await i.followup.send("Keine Teams vorhanden."); return
        e = discord.Embed(title="🚗 RL Teams", color=discord.Color.orange())
        for t in ts:
            cap = i.guild.get_member(t["captain_id"])
            cap_str = f"{cap.display_name} ({t['captain_id']})" if cap else str(t["captain_id"])
            e.add_field(
                name=f"{t['name']} ({t['format']})",
                value=f"Captain: {cap_str}\nSpieler: {len(t['members'])} | Trainer: {len(t.get('trainers',[]))}\nW/L: {t['wins']}/{t['losses']}",
                inline=False
            )
        await i.followup.send(embed=e)

    @app_commands.command(name="rl-team-info", description="Team Details anzeigen.")
    async def rlinfo_cmd(self, i: discord.Interaction, team_name: str):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "name": team_name})
        if not t: await i.followup.send("❌ Team nicht gefunden."); return
        e = discord.Embed(title=f"🚗 {t['name']}", color=discord.Color.orange())
        e.add_field(name="Format", value=t.get("format", "?"))
        e.add_field(name="W/L", value=f"{t['wins']}/{t['losses']}")
        members_str = "\n".join(
            f"• {m.get('username','?')} ({m['user_id']}) — {m.get('rolle','Spieler')}" +
            (f" | Epic: {m['epic']}" if m.get('epic') else "")
            for m in t["members"]
        )
        trainers_str = "\n".join(
            f"• {tr.get('username','?')} ({tr['user_id']})" +
            (f" | Epic: {tr['epic']}" if tr.get('epic') else "")
            for tr in t.get("trainers", [])
        ) or "Keine"
        e.add_field(name="Spieler", value=members_str or "–", inline=False)
        e.add_field(name="Trainer", value=trainers_str, inline=False)
        await i.followup.send(embed=e)

    @app_commands.command(name="rl-team-epic", description="Deinen Epic Games Namen setzen.")
    async def rlepic_cmd(self, i: discord.Interaction, epic_name: str):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "members.user_id": i.user.id})
        if not t: await i.followup.send("❌ Du bist in keinem Team."); return
        await col("rl_teams").update_one(
            {"_id": t["_id"], "members.user_id": i.user.id},
            {"$set": {"members.$.epic": epic_name}}
        )
        await i.followup.send(f"✅ Epic Name gesetzt: **{epic_name}**")

    @app_commands.command(name="rl-team-result", description="[Admin] Ergebnis eintragen.")
    @is_admin()
    async def rlresult_cmd(self, i: discord.Interaction, team_name: str, gewonnen: bool):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "name": team_name})
        if not t: await i.followup.send("❌ Team nicht gefunden."); return
        field = "wins" if gewonnen else "losses"
        await col("rl_teams").update_one({"_id": t["_id"]}, {"$inc": {field: 1}})
        await i.followup.send(f"✅ {'Sieg' if gewonnen else 'Niederlage'} für **{team_name}** eingetragen.")

    @is_admin()
    async def rlrole_cmd(self, i: discord.Interaction, team_name: str, rolle: discord.Role):
        await i.response.defer()
        t = await col("rl_teams").find_one({"guild_id": i.guild_id, "name": team_name})
        if not t: await i.followup.send("❌ Team nicht gefunden."); return
        for m in t["members"]:
            member = i.guild.get_member(m["user_id"])
            if member:
                try: await member.add_roles(rolle)
                except: pass
        await i.followup.send(f"✅ Rolle {rolle.mention} an alle Mitglieder von **{team_name}** vergeben.")

async def setup(bot):
    await bot.add_cog(RLTeams(bot))
