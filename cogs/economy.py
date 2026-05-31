import discord
from discord.ext import commands
from discord import app_commands
from datetime import datetime, timedelta
from typing import Optional
import random, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import col, heco, addcoins, gcfg, cdchk, is_mod, is_admin

class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="eco-balance", description="Kontostand anzeigen.")
    async def bal_cmd(self, i: discord.Interaction, user: Optional[discord.Member] = None):
        await i.response.defer()
        z = user or i.user
        eco = await heco(i.guild_id, z.id)
        e = discord.Embed(title=f"💰 {z.display_name}", color=discord.Color.gold())
        e.add_field(name="👛 Wallet", value=f"{eco.get('coins', 0)} Coins")
        e.add_field(name="🏦 Bank", value=f"{eco.get('bank', 0)} Coins")
        e.add_field(name="💎 Gesamt", value=f"{eco.get('coins', 0) + eco.get('bank', 0)} Coins")
        e.add_field(name="⭐ Rep", value=str(eco.get("rep", 0)))
        await i.followup.send(embed=e)

    @app_commands.command(name="eco-deposit", description="Coins in die Bank einzahlen.")
    async def deposit_cmd(self, i: discord.Interaction, menge: int):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        if menge <= 0 or eco.get("coins", 0) < menge:
            await i.followup.send("❌ Ungültiger Betrag!"); return
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": -menge, "bank": menge}}
        )
        await i.followup.send(f"🏦 **{menge} Coins** eingezahlt.")

    @app_commands.command(name="eco-withdraw", description="Coins aus der Bank abheben.")
    async def withdraw_cmd(self, i: discord.Interaction, menge: int):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        if menge <= 0 or eco.get("bank", 0) < menge:
            await i.followup.send("❌ Ungültiger Betrag!"); return
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": menge, "bank": -menge}}
        )
        await i.followup.send(f"💳 **{menge} Coins** abgehoben.")

    @app_commands.command(name="eco-daily", description="Tägliche Coins.")
    async def daily_cmd(self, i: discord.Interaction):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        wt = cdchk(eco.get("last_daily"), 20)
        if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
        last = eco.get("last_daily")
        st = eco.get("streak", 0)
        if last:
            diff = datetime.utcnow() - (last if isinstance(last, datetime) else datetime.fromisoformat(str(last)))
            st = st + 1 if diff < timedelta(hours=48) else 1
        else:
            st = 1
        amt = 200 + st * 10
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": amt}, "$set": {"last_daily": datetime.utcnow(), "streak": st}}
        )
        await i.followup.send(embed=discord.Embed(
            title="💰 Daily!", description=f"+**{amt} Coins** | 🔥 Streak: **{st}**",
            color=discord.Color.gold()
        ))

    @app_commands.command(name="eco-work", description="Arbeiten gehen.")
    async def work_cmd(self, i: discord.Interaction):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        wt = cdchk(eco.get("last_work"), 4)
        if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
        jobs = ["Pizza geliefert 🍕", "Code geschrieben 💻", "Rocket League gespielt 🚗", "Stream moderiert 🎮", "Designs erstellt 🎨"]
        amt = random.randint(50, 150)
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": amt}, "$set": {"last_work": datetime.utcnow()}}
        )
        await i.followup.send(f"💼 {random.choice(jobs)} → **+{amt} Coins**")

    @app_commands.command(name="eco-fish", description="Angeln.")
    async def fish_cmd(self, i: discord.Interaction):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        wt = cdchk(eco.get("last_fish"), 2)
        if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
        fi = [("🦐 Garnele", 10), ("🐟 Fisch", 30), ("🐠 Tropenfisch", 50), ("🐡 Kugelfisch", 70), ("🦈 Hai", 200), ("👢 Stiefel", 0), ("🗑️ Müll", 0)]
        f, v = random.choice(fi)
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": v}, "$set": {"last_fish": datetime.utcnow()}}
        )
        await i.followup.send(f"🎣 Du hast **{f}** gefangen!" + (f" → **+{v} Coins**" if v else " → Nichts wert."))

    @app_commands.command(name="eco-mine", description="Schürfen.")
    async def mine_cmd(self, i: discord.Interaction):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        wt = cdchk(eco.get("last_mine"), 2)
        if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
        mi = [("🪨 Stein", 5), ("⛏️ Kohle", 20), ("🪙 Kupfer", 40), ("🔩 Eisen", 60), ("🥇 Gold", 150), ("💎 Diamant", 300)]
        m, v = random.choice(mi)
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": v}, "$set": {"last_mine": datetime.utcnow()}}
        )
        await i.followup.send(f"⛏️ Du hast **{m}** gefunden! → **+{v} Coins**")

    @app_commands.command(name="eco-gamble", description="Coins setzen.")
    async def gamble_cmd(self, i: discord.Interaction, menge: int):
        await i.response.defer()
        if menge <= 0: await i.followup.send("❌ Ungültig!"); return
        eco = await heco(i.guild_id, i.user.id)
        if eco.get("coins", 0) < menge: await i.followup.send("❌ Nicht genug Coins!"); return
        if random.random() > 0.5:
            await addcoins(i.guild_id, i.user.id, menge)
            await i.followup.send(f"🎰 Gewonnen! **+{menge} Coins**")
        else:
            await addcoins(i.guild_id, i.user.id, -menge)
            await i.followup.send(f"🎰 Verloren! **-{menge} Coins**")

    @app_commands.command(name="eco-rob", description="Coins stehlen.")
    async def rob_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        if user.id == i.user.id: await i.followup.send("❌ Nicht möglich!"); return
        v = await heco(i.guild_id, user.id)
        if v.get("coins", 0) < 100: await i.followup.send("❌ Opfer hat zu wenig!"); return
        if random.random() > 0.4:
            st = random.randint(50, min(500, v["coins"]))
            await addcoins(i.guild_id, user.id, -st)
            await addcoins(i.guild_id, i.user.id, st)
            await i.followup.send(f"🦹 **{st} Coins** von {user.display_name} gestohlen!")
        else:
            fn = random.randint(100, 300)
            await addcoins(i.guild_id, i.user.id, -fn)
            await i.followup.send(f"👮 Erwischt! **-{fn} Coins**")

    @app_commands.command(name="eco-pay", description="Coins transferieren.")
    async def pay_cmd(self, i: discord.Interaction, user: discord.Member, menge: int):
        await i.response.defer()
        if menge <= 0: await i.followup.send("❌ Ungültig!"); return
        eco = await heco(i.guild_id, i.user.id)
        if eco.get("coins", 0) < menge: await i.followup.send("❌ Nicht genug!"); return
        await addcoins(i.guild_id, i.user.id, -menge)
        await addcoins(i.guild_id, user.id, menge)
        await i.followup.send(f"✅ **{menge} Coins** an {user.mention} ({user.id})!")

    @app_commands.command(name="eco-leaderboard", description="Reichste User.")
    async def lb_cmd(self, i: discord.Interaction):
        await i.response.defer()
        if not i.guild: await i.followup.send("❌ Guild nicht gefunden"); return
        top = await col("economy").find({"guild_id": i.guild_id}).sort("coins", -1).limit(10).to_list(10)
        e = discord.Embed(title="💰 Reichste User", color=discord.Color.gold())
        md = ["🥇", "🥈", "🥉"]
        lines = []
        for idx, u in enumerate(top):
            mb = i.guild.get_member(u["user_id"])
            nm = f"{mb.display_name} ({u['user_id']})" if mb else f"User {u['user_id']}"
            lines.append(f"{md[idx] if idx < 3 else f'**{idx+1}.**'} {nm} — {u.get('coins', 0)} Coins")
        e.description = "\n".join(lines) or "Keine Daten."
        await i.followup.send(embed=e)

    @app_commands.command(name="eco-slots", description="Slot Machine.")
    async def slots_cmd(self, i: discord.Interaction, einsatz: int):
        await i.response.defer()
        if einsatz <= 0: await i.followup.send("❌ Ungültig!"); return
        eco = await heco(i.guild_id, i.user.id)
        if eco.get("coins", 0) < einsatz: await i.followup.send("❌ Nicht genug!"); return
        sym = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"]
        res = [random.choice(sym) for _ in range(3)]
        if res[0] == res[1] == res[2]:
            mt = {"💎": 10, "7️⃣": 7, "⭐": 5}.get(res[0], 3)
            gw = einsatz * mt
            await addcoins(i.guild_id, i.user.id, gw)
            msg = f"🎰 {''.join(res)}\n🎉 JACKPOT! **+{gw} Coins**"
        elif res[0] == res[1] or res[1] == res[2]:
            await addcoins(i.guild_id, i.user.id, einsatz)
            msg = f"🎰 {''.join(res)}\n✅ Zwei gleiche! **+{einsatz} Coins**"
        else:
            await addcoins(i.guild_id, i.user.id, -einsatz)
            msg = f"🎰 {''.join(res)}\n❌ **-{einsatz} Coins**"
        await i.followup.send(msg)

    @app_commands.command(name="eco-rep", description="Rep geben.")
    async def rep_cmd(self, i: discord.Interaction, user: discord.Member):
        await i.response.defer()
        if user.id == i.user.id: await i.followup.send("❌ Keine Selbst-Rep!"); return
        eco = await heco(i.guild_id, i.user.id)
        wt = cdchk(eco.get("last_rep"), 24)
        if wt: await i.followup.send(f"⏰ Warte noch **{wt}**!"); return
        await col("economy").update_one({"guild_id": i.guild_id, "user_id": user.id}, {"$inc": {"rep": 1}}, upsert=True)
        await col("economy").update_one({"guild_id": i.guild_id, "user_id": i.user.id}, {"$set": {"last_rep": datetime.utcnow()}})
        await i.followup.send(f"⭐ {user.mention} ({user.id}) +1 Rep!")

    @app_commands.command(name="eco-shop", description="Shop anzeigen.")
    async def shop_cmd(self, i: discord.Interaction):
        await i.response.defer()
        cfg = await gcfg(i.guild_id)
        items = cfg.get("shop", [])
        if not items: await i.followup.send("❌ Shop leer."); return
        e = discord.Embed(title="🛒 Shop", color=discord.Color.green())
        for it in items:
            e.add_field(name=f"{it['name']} – {it['price']} Coins", value=it.get("description", "–"), inline=False)
        await i.followup.send(embed=e)

    @app_commands.command(name="eco-buy", description="Item kaufen.")
    async def buy_cmd(self, i: discord.Interaction, item_name: str):
        await i.response.defer()
        cfg = await gcfg(i.guild_id)
        it = next((x for x in cfg.get("shop", []) if x["name"].lower() == item_name.lower()), None)
        if not it: await i.followup.send("❌ Item nicht gefunden."); return
        eco = await heco(i.guild_id, i.user.id)
        if eco.get("coins", 0) < it["price"]: await i.followup.send("❌ Nicht genug Coins!"); return
        await col("economy").update_one(
            {"guild_id": i.guild_id, "user_id": i.user.id},
            {"$inc": {"coins": -it["price"]}, "$push": {"inventory": it["name"]}}
        )
        if it.get("role_id"):
            r = i.guild.get_role(int(it["role_id"]))
            if r:
                try: await i.user.add_roles(r)
                except: pass
        await i.followup.send(f"✅ **{it['name']}** gekauft!")

    @app_commands.command(name="eco-inventory", description="Inventar anzeigen.")
    async def inv_cmd(self, i: discord.Interaction):
        await i.response.defer()
        eco = await heco(i.guild_id, i.user.id)
        inv = eco.get("inventory", [])
        e = discord.Embed(title=f"🎒 Inventar von {i.user.display_name}", color=discord.Color.blurple())
        e.description = "\n".join(inv) if inv else "Leer."
        await i.followup.send(embed=e)

    @app_commands.command(name="eco-give", description="[Admin] Coins geben/abziehen.")
    @is_admin()
    async def give_cmd(self, i: discord.Interaction, user: discord.Member, menge: int):
        await i.response.defer()
        await addcoins(i.guild_id, user.id, menge)
        action = "gegeben" if menge > 0 else "abgezogen"
        await i.followup.send(f"✅ **{abs(menge)} Coins** {action} → {user.mention} ({user.id})")

    @app_commands.command(name="eco-shop-add", description="[Admin] Shop Item hinzufügen.")
    @is_admin()
    async def shopadd(self, i: discord.Interaction, name: str, preis: int, beschreibung: str = "", rolle: discord.Role = None):
        it = {"name": name, "price": preis, "description": beschreibung}
        if rolle: it["role_id"] = str(rolle.id)
        await col("config").update_one({"guild_id": i.guild_id}, {"$push": {"shop": it}}, upsert=True)
        from bot import ivcfg
        ivcfg(i.guild_id)
        await i.response.send_message(f"✅ **{name}** für {preis} Coins hinzugefügt!")

    @app_commands.command(name="eco-shop-remove", description="[Admin] Shop Item entfernen.")
    @is_admin()
    async def shopremove(self, i: discord.Interaction, name: str):
        await col("config").update_one({"guild_id": i.guild_id}, {"$pull": {"shop": {"name": name}}})
        from bot import ivcfg
        ivcfg(i.guild_id)
        await i.response.send_message(f"✅ **{name}** entfernt.")

async def setup(bot):
    await bot.add_cog(Economy(bot))