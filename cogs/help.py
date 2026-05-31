import discord
from discord.ext import commands
from discord import app_commands

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Alle Commands anzeigen.")
    async def help_cmd(self, i: discord.Interaction):
        e = discord.Embed(title="📖 RLD Main Bot – Commands", color=discord.Color.red())

        e.add_field(name="🛡️ Moderation",
            value="`/ban` `/unban` `/kick` `/timeout` `/untimeout` `/warn` `/warns` `/unwarn` `/clearwarns` `/case` `/clear` `/slowmode` `/lock` `/unlock` `/nick` `/purge-user` `/raid-mode` `/say` `/announce`",
            inline=False)

        e.add_field(name="ℹ️ Info",
            value="`/userinfo` `/serverinfo` `/avatar` `/ping` `/timestamp` `/botinfo`",
            inline=False)

        e.add_field(name="🎮 Fun",
            value="`/8ball` `/coinflip` `/wuerfel` `/rps` `/quote` `/poll` `/calc` `/meme`",
            inline=False)

        e.add_field(name="💤 AFK / ⏰ Reminder",
            value="`/afk` `/afk-list` `/remindme`",
            inline=False)

        e.add_field(name="💰 Economy",
            value="`/eco-balance` `/eco-deposit` `/eco-withdraw` `/eco-daily` `/eco-work` `/eco-fish` `/eco-mine` `/eco-gamble` `/eco-rob` `/eco-pay` `/eco-slots` `/eco-rep` `/eco-shop` `/eco-buy` `/eco-inventory` `/eco-leaderboard` `/eco-give` `/eco-shop-add` `/eco-shop-remove`",
            inline=False)

        e.add_field(name="🎉 Giveaway",
            value="`/giveaway-start` `/giveaway-end` `/giveaway-reroll` `/giveaway-list`",
            inline=False)

        e.add_field(name="💡 Vorschläge",
            value="`/suggest` `/suggest-accept` `/suggest-deny`",
            inline=False)

        e.add_field(name="🎂 Geburtstag",
            value="`/geburtstag` `/geburtstag-liste`",
            inline=False)

        e.add_field(name="🎫 Ticket",
            value="`/ticket-setup` `/ticket-team` `/ticket-list` `/ticket-add` `/ticket-remove`",
            inline=False)

        e.add_field(name="✅ Verify",
            value="`/verify-setup` `/verify-role`",
            inline=False)

        e.add_field(name="👥 Team & Bewerbungen",
            value="`/team` `/team-add` `/team-remove` `/team-warn` `/team-kick` `/abmelden` `/team-notiz` `/bewerben` `/bewerbungen` `/bewerbung-accept` `/bewerbung-deny`",
            inline=False)

        e.add_field(name="🚗 RL Teams",
            value="`/rl-team-erstellen` `/rl-team-einladen` `/rl-team-join` `/rl-team-leave` `/rl-team-disband` `/rl-teams` `/rl-team-info` `/rl-team-epic` `/rl-team-result` `/rl-team-rolle`",
            inline=False)

        e.add_field(name="📰 RSS",
            value="`/rss-add` `/rss-remove` `/rss-list` `/rss-toggle`",
            inline=False)

        e.add_field(name="🔔 Notifications",
            value="`/notif-twitch` `/notif-remove` `/notif-list`",
            inline=False)

        e.add_field(name="⚙️ Custom Commands",
            value="`/cmd-add` `/cmd-remove` `/cmd-list`",
            inline=False)

        e.add_field(name="🔧 Setup",
            value="`/setup-welcome` `/setup-goodbye` `/setup-autorole` `/setup-modlog` `/setup-logs` `/setup-automod` `/setup-starboard` `/setup-suggest` `/setup-birthday` `/setup-slowjoiner` `/setup-welcomedm` `/setup-bot-status` `/setup-member-role` `/stat-channel` `/badword-add` `/badword-remove` `/ticket-team` `/verify-role`",
            inline=False)

        e.set_footer(text="Made by Rezyel | RLD Dashboard verfügbar")
        await i.response.send_message(embed=e)

async def setup(bot):
    await bot.add_cog(Help(bot))