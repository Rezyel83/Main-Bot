import discord
from discord.ext import commands
from discord import app_commands
from utils import col, gcfg, is_admin

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="✅ Verifizieren", style=discord.ButtonStyle.success, custom_id="verify_button")
    async def verify(self, i: discord.Interaction, b: discord.ui.Button):
        cfg = await gcfg(i.guild_id)
        rid = cfg.get("verify_role")
        if not rid: await i.response.send_message("❌ Keine Rolle konfiguriert!", ephemeral=True); return
        r = i.guild.get_role(int(rid))
        if not r: await i.response.send_message("❌ Rolle nicht gefunden!", ephemeral=True); return
        if r in i.user.roles: await i.response.send_message("✅ Bereits verifiziert!", ephemeral=True); return
        await i.user.add_roles(r)
        await i.response.send_message("✅ Erfolgreich verifiziert!", ephemeral=True)

class Verify(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(VerifyView())

    @app_commands.command(name="verify-setup", description="[Admin] Verifizierungs-Panel erstellen.")
    @is_admin()
    async def vsetup_cmd(self, i: discord.Interaction, rolle: discord.Role,
                          titel: str = "Verifizierung",
                          text: str = "Klicke den Button um dich zu verifizieren."):
        await col("config").update_one(
            {"guild_id": i.guild_id}, {"$set": {"verify_role": rolle.id}}, upsert=True
        )
        from utils import ivcfg
        ivcfg(i.guild_id)
        e = discord.Embed(title=f"✅ {titel}", description=text, color=discord.Color.green())
        await i.channel.send(embed=e, view=VerifyView())
        await i.response.send_message("✅ Verify-Panel erstellt!", ephemeral=True)

    @app_commands.command(name="verify-role", description="[Admin] Verify-Rolle ändern.")
    @is_admin()
    async def vrole_cmd(self, i: discord.Interaction, rolle: discord.Role):
        await i.response.defer()
        await col("config").update_one(
            {"guild_id": i.guild_id}, {"$set": {"verify_role": rolle.id}}, upsert=True
        )
        from utils import ivcfg
        ivcfg(i.guild_id)
        await i.followup.send(f"✅ Verify-Rolle: {rolle.mention}")

async def setup(bot):
    await bot.add_cog(Verify(bot))
