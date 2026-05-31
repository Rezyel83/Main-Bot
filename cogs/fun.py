import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional
import random, ast, operator

def sfeval(expr: str) -> float:
    OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
           ast.FloorDiv: operator.floordiv, ast.UAdd: operator.pos, ast.USub: operator.neg}
    def _e(n):
        if isinstance(n, ast.Expression): return _e(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.BinOp):
            op = OPS.get(type(n.op))
            if not op: raise ValueError()
            return op(_e(n.left), _e(n.right))
        if isinstance(n, ast.UnaryOp):
            op = OPS.get(type(n.op))
            if not op: raise ValueError()
            return op(_e(n.operand))
        raise ValueError()
    return _e(ast.parse(expr, mode="eval"))

class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="8ball", description="Stelle eine Frage!")
    async def ball_cmd(self, i: discord.Interaction, frage: str):
        ans = ["Ja!", "Definitiv ja!", "Sehr wahrscheinlich.", "Vielleicht.", "Eher nicht.", "Definitiv nein!", "Frag später.", "Ohne Zweifel!", "Unmöglich."]
        e = discord.Embed(title="🎱 8Ball", color=discord.Color.purple())
        e.add_field(name="❓ Frage", value=frage, inline=False)
        e.add_field(name="🎱 Antwort", value=random.choice(ans), inline=False)
        await i.response.send_message(embed=e)

    @app_commands.command(name="coinflip", description="Münze werfen.")
    async def coinflip_cmd(self, i: discord.Interaction):
        await i.response.send_message(f"🪙 **{random.choice(['Kopf 👑', 'Zahl 🔢'])}**")

    @app_commands.command(name="wuerfel", description="Würfel werfen.")
    async def wuerfel_cmd(self, i: discord.Interaction, anzahl: int = 1, seiten: int = 6):
        a = min(max(anzahl, 1), 10)
        res = [random.randint(1, max(seiten, 2)) for _ in range(a)]
        e = discord.Embed(title="🎲 Würfel", color=discord.Color.green())
        e.add_field(name="Ergebnisse", value=" | ".join(str(r) for r in res))
        e.add_field(name="Summe", value=str(sum(res)))
        await i.response.send_message(embed=e)

    @app_commands.command(name="rps", description="Schere Stein Papier.")
    async def rps_cmd(self, i: discord.Interaction, wahl: str):
        opts = ["schere", "stein", "papier"]
        wahl = wahl.lower()
        if wahl not in opts: await i.response.send_message("❌ schere, stein oder papier!"); return
        bw = random.choice(opts)
        em = {"schere": "✂️", "stein": "🪨", "papier": "📄"}
        wins = {("schere", "papier"), ("stein", "schere"), ("papier", "stein")}
        res = "🎉 Du gewinnst!" if (wahl, bw) in wins else ("🤝 Unentschieden!" if wahl == bw else "😔 Bot gewinnt!")
        e = discord.Embed(title="✂️🪨📄 RPS", color=discord.Color.blurple())
        e.add_field(name="Du", value=em[wahl])
        e.add_field(name="Bot", value=em[bw])
        e.add_field(name="Ergebnis", value=res, inline=False)
        await i.response.send_message(embed=e)

    @app_commands.command(name="poll", description="Abstimmung erstellen.")
    async def poll_cmd(self, i: discord.Interaction, frage: str, option1: str, option2: str,
                       option3: Optional[str] = None, option4: Optional[str] = None):
        opts = [o for o in [option1, option2, option3, option4] if o]
        ems = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        e = discord.Embed(
            title=f"📊 {frage}",
            description="\n".join(f"{ems[n]} {o}" for n, o in enumerate(opts)),
            color=discord.Color.blurple()
        )
        e.set_footer(text=f"von {i.user.display_name}")
        await i.response.send_message(embed=e)
        msg = await i.original_response()
        for n in range(len(opts)): await msg.add_reaction(ems[n])

    @app_commands.command(name="calc", description="Rechnung ausführen.")
    async def calc_cmd(self, i: discord.Interaction, rechnung: str):
        try:
            r = sfeval(rechnung.replace("^", "**"))
            await i.response.send_message(f"🧮 `{rechnung}` = **{r}**")
        except:
            await i.response.send_message("❌ Ungültig! Erlaubt: + - * / ** % //")

    @app_commands.command(name="quote", description="Inspirierendes Zitat.")
    async def quote_cmd(self, i: discord.Interaction):
        await i.response.defer()
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://zenquotes.io/api/random", timeout=aiohttp.ClientTimeout(total=8)) as r:
                    d = await r.json()
            await i.followup.send(embed=discord.Embed(
                description=f'*"{d[0]["q"]}"*\n\n— **{d[0]["a"]}**', color=discord.Color.gold()
            ))
        except: await i.followup.send("❌ Fehler.")

    @app_commands.command(name="meme", description="Zufälliges Meme.")
    async def meme_cmd(self, i: discord.Interaction):
        await i.response.defer()
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://meme-api.com/gimme", timeout=aiohttp.ClientTimeout(total=8)) as r:
                    d = await r.json()
            e = discord.Embed(title=d.get("title", "Meme")[:250], color=discord.Color.random())
            e.set_image(url=d.get("url"))
            e.set_footer(text=f"r/{d.get('subreddit', '?')}")
            await i.followup.send(embed=e)
        except: await i.followup.send("❌ Fehler.")

async def setup(bot):
    await bot.add_cog(Fun(bot))