import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, gcfg, is_admin, is_mod

class CloseTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Schließen", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        tk = await col("tickets").find_one({"channel_id": i.channel_id})
        if tk:
            # Save transcript
            msgs = []
            async for msg in i.channel.history(limit=200, oldest_first=True):
                msgs.append({
                    "author": str(msg.author),
                    "author_id": msg.author.id,
                    "content": msg.content,
                    "ts": msg.created_at
                })
            await col("tickets").update_one(
                {"channel_id": i.channel_id},
                {"$set": {"open": False, "closed_at": datetime.utcnow(), "transcript": msgs}}
            )
            # Send log
            cfg = await gcfg(i.guild_id)
            log_cid = cfg.get("log_channels", {}).get("ticket_log") or cfg.get("ticket_log")
            if log_cid:
                lch = i.guild.get_channel(int(log_cid))
                if lch:
                    user = i.guild.get_member(tk["user_id"])
                    e = discord.Embed(title="🎫 Ticket geschlossen", color=discord.Color.red())
                    e.add_field(name="User", value=f"{user} ({tk['user_id']})" if user else str(tk["user_id"]))
                    e.add_field(name="Kanal", value=i.channel.name)
                    e.add_field(name="Nachrichten", value=str(len(msgs)))
                    e.add_field(name="Geschlossen von", value=f"{i.user} ({i.user.id})")
                    await lch.send(embed=e)
        await i.channel.send("🔒 Ticket wird in 5s gelöscht...")
        import asyncio
        await asyncio.sleep(5)
        await i.channel.delete()

class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎫 Ticket erstellen", style=discord.ButtonStyle.primary, custom_id="create_ticket")
    async def create(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer(ephemeral=True)
        cfg = await gcfg(i.guild_id)
        ex = discord.utils.get(i.guild.channels, name=f"ticket-{i.user.name.lower()}")
        if ex: await i.followup.send(f"Du hast bereits ein offenes Ticket: {ex.mention}", ephemeral=True); return
        cat = i.guild.get_channel(int(cfg["ticket_category"])) if cfg.get("ticket_category") else None
        ow = {
            i.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            i.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        if cfg.get("ticket_team_role"):
            r = i.guild.get_role(int(cfg["ticket_team_role"]))
            if r: ow[r] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        ch = await i.guild.create_text_channel(f"ticket-{i.user.name.lower()}", category=cat, overwrites=ow)
        await col("tickets").insert_one({
            "guild_id": i.guild_id, "channel_id": ch.id,
            "user_id": i.user.id, "username": str(i.user),
            "open": True, "created_at": datetime.utcnow()
        })
        e = discord.Embed(title="🎫 Ticket", description=f"Hallo {i.user.mention}! Beschreibe dein Anliegen.", color=discord.Color.green())
        e.set_footer(text=f"User ID: {i.user.id}")
        await ch.send(embed=e, view=CloseTicketView())
        await i.followup.send(f"✅ Ticket erstellt: {ch.mention}", ephemeral=True)

class Tickets(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        bot.add_view(TicketView())
        bot.add_view(CloseTicketView())

    @app_commands.command(name="ticket-setup", description="[Admin] Ticket-Panel erstellen.")
    @is_admin()
    async def tsetup_cmd(self, i: discord.Interaction, titel: str = "Support",
                          beschreibung: str = "Klicke den Button um ein Ticket zu öffnen."):
        e = discord.Embed(title=f"🎫 {titel}", description=beschreibung, color=discord.Color.blurple())
        await i.channel.send(embed=e, view=TicketView())
        await i.response.send_message("✅ Ticket-Panel erstellt!", ephemeral=True)

    @app_commands.command(name="ticket-team", description="[Admin] Ticket Team-Rolle & Kategorie setzen.")
    @is_admin()
    async def tteam_cmd(self, i: discord.Interaction, rolle: discord.Role,
                         kategorie: discord.CategoryChannel = None):
        await i.response.defer()
        upd = {"ticket_team_role": rolle.id}
        if kategorie: upd["ticket_category"] = kategorie.id
        await col("config").update_one({"guild_id": i.guild_id}, {"$set": upd}, upsert=True)
        from bot import ivcfg
        ivcfg(i.guild_id)
        await i.followup.send(f"✅ Ticket Team: {rolle.mention}")

    @app_commands.command(name="ticket-list", description="[Mod] Offene Tickets anzeigen.")
    @is_mod()
    async def tlist_cmd(self, i: discord.Interaction):
        await i.response.defer()
        ts = await col("tickets").find({"guild_id": i.guild_id, "open": True}).to_list(20)
        e = discord.Embed(title="🎫 Offene Tickets", color=discord.Color.blurple())
        if not ts:
            e.description = "Keine offenen Tickets."
        else:
            for t in ts:
                m = i.guild.get_member(t["user_id"])
                ch = i.guild.get_channel(t["channel_id"])
                name = f"{m.display_name} ({t['user_id']})" if m else str(t["user_id"])
                e.add_field(name=ch.name if ch else str(t["channel_id"]), value=name, inline=True)
        await i.followup.send(embed=e)

    @app_commands.command(name="ticket-add", description="[Mod] User zu Ticket hinzufügen.")
    @is_mod()
    async def tadd_user_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        if not i.channel or not hasattr(i.channel, "set_permissions"):
            await i.followup.send("❌ Nur in Ticket-Kanälen möglich."); return
        await i.channel.set_permissions(user, read_messages=True, send_messages=True)
        await i.followup.send(f"✅ {user.mention} ({user.id}) zum Ticket hinzugefügt.")

    @app_commands.command(name="ticket-remove", description="[Mod] User aus Ticket entfernen.")
    @is_mod()
    async def tremove_user_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        if not i.channel or not hasattr(i.channel, "set_permissions"):
            await i.followup.send("❌ Nur in Ticket-Kanälen möglich."); return
        await i.channel.set_permissions(user, read_messages=False, send_messages=False)
        await i.followup.send(f"✅ {user.mention} ({user.id}) aus Ticket entfernt.")

async def setup(bot):
    await bot.add_cog(Tickets(bot))