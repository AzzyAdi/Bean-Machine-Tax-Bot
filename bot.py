import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import json
import asyncio
from datetime import datetime, timezone

# ---------------- LOAD ----------------
load_dotenv()
TOKEN = os.getenv("TOKEN")

with open("config.json", "r", encoding="utf-8") as f:
    config = json.load(f)

GUILD_ID = int(config["guild_id"])
OWNER_ID = int(config["owner_id"])
CHANNEL_ID = int(config["reminder_channel_id"])
FOOTER = config["footer"]

GUILD = discord.Object(id=GUILD_ID)

# ---------------- BOT ----------------
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- DATABASE (IN-MEMORY SIMPLE) ----------------
tax_data = {}  # user_id: {"status": str, "overdue": int, "last": str}

# ---------------- ROLES ----------------
TAX_ROLES = ["trainee", "waiter", "bartender", "kitchen head"]
EXEMPT_ROLES = ["owner", "manager", "assistant manager"]

# ---------------- EMBED ----------------
def embed(title, desc, color=discord.Color.gold()):
    e = discord.Embed(
        title=f"☕ {title}",
        description=desc,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    e.set_footer(text=f"{FOOTER} • Bean Machine Tax System")
    return e

# ---------------- ROLE CHECK ----------------
def is_tax_member(member):
    roles = [r.name.lower().strip() for r in member.roles]

    if any(r in roles for r in EXEMPT_ROLES):
        return False

    return any(r in roles for r in TAX_ROLES)

# ---------------- READY ----------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    synced = await bot.tree.sync(guild=GUILD)
    print(f"Synced commands: {len(synced)}")

    weekly_reminder.start()

# ---------------- SEND REMINDER ----------------
def get_overdue_level(overdue: int):
    if overdue == 0:
        return "OK", discord.Color.green()

    if overdue == 1:
        return "LOW", discord.Color.gold()

    if overdue == 2:
        return "MEDIUM", discord.Color.orange()

    return "CRITICAL", discord.Color.red()
async def send_reminder(channel, member):
    data = tax_data.get(member.id, {"overdue": 0})
    overdue = data["overdue"]

    level, color = get_overdue_level(overdue)

    if overdue == 0:
        desc = (
            f"👤 Employee: {member.mention}\n\n"
            "📌 Reason:\n"
            "This is your weekly tax reminder.\n\n"
            "💰 Action:\n"
            "Please pay your tax for this week.\n"
        )
        title = "☕ Weekly Tax Reminder"

    else:
        desc = (
            f"👤 Employee: {member.mention}\n\n"
            f"⚠️ Risk Level: {level}\n\n"
            "📌 Reason:\n"
            "You have unpaid tax from previous week(s).\n\n"
            f"📊 Overdue Periods: {overdue}\n\n"
            "💰 Action:\n"
            "Please pay your pending tax as soon as possible.\n"
        )

        if level == "CRITICAL":
            desc += "\n🚨 FINAL WARNING: Immediate payment required to avoid action."

        title = "⚠️ Tax Overdue Notice"

    await channel.send(embed=embed(title, desc, color))
    await asyncio.sleep(2)

# ---------------- WEEKLY SYSTEM ----------------
@tasks.loop(hours=24)
async def weekly_reminder():
    now = datetime.now(timezone.utc)

    if now.weekday() != 5:
        return

    guild = bot.get_guild(GUILD_ID)
    channel = bot.get_channel(CHANNEL_ID)

    if not guild or not channel:
        return

    await guild.chunk()

    for member in guild.members:
        if member.bot:
            continue

        if is_tax_member(member):
            await send_reminder(channel, member)

# ---------------- TEST ----------------
@bot.tree.command(name="test", guild=GUILD)
async def test(interaction: discord.Interaction):
    await interaction.response.send_message(
        embed=embed("System Check", "Bot is working perfectly")
    )

# ---------------- TAX LIST ----------------
@bot.tree.command(name="taxlist", guild=GUILD)
async def taxlist(interaction: discord.Interaction):

    members = [
        m.mention for m in interaction.guild.members
        if is_tax_member(m)
    ]

    await interaction.response.send_message(
        embed=embed("Tax Employees", "\n".join(members) or "None")
    )

# ---------------- TAX PAID ----------------
@bot.tree.command(name="taxpaid", guild=GUILD)
async def taxpaid(interaction: discord.Interaction, member: discord.Member):

    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("Owner only", ephemeral=True)

    tax_data[member.id] = {
        "status": "PAID",
        "overdue": 0,
        "last": str(datetime.now(timezone.utc))
    }

    await interaction.response.send_message(
        embed=embed("Payment Recorded", f"{member.mention} marked PAID", discord.Color.green())
    )

# ---------------- TAX UNPAID ----------------
@bot.tree.command(name="taxunpaid", guild=GUILD)
async def taxunpaid(interaction: discord.Interaction, member: discord.Member):

    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("Owner only", ephemeral=True)

    old = tax_data.get(member.id, {"overdue": 0})

    tax_data[member.id] = {
        "status": "UNPAID",
        "overdue": old["overdue"] + 1,
        "last": str(datetime.now(timezone.utc))
    }

    await interaction.response.send_message(
        embed=embed("Marked Unpaid", f"{member.mention} overdue increased")
    )

# ---------------- STATUS ----------------
@bot.tree.command(name="taxstatus", guild=GUILD)
async def taxstatus(interaction: discord.Interaction, member: discord.Member):

    data = tax_data.get(member.id, {"status": "UNKNOWN", "overdue": 0})

    await interaction.response.send_message(
        embed=embed(
            "Tax Status",
            f"{member.mention}\nStatus: {data['status']}\nOverdue: {data['overdue']}"
        )
    )

# ---------------- UNPAID LIST ----------------
@bot.tree.command(name="taxunpaidlist", guild=GUILD)
async def taxunpaidlist(interaction: discord.Interaction):

    text = ""

    for uid, data in tax_data.items():
        if data["status"] == "UNPAID":
            member = interaction.guild.get_member(uid)
            if member:
                text += f"{member.mention} - {data['overdue']}\n"

    await interaction.response.send_message(
        embed=embed("Unpaid Employees", text or "None")
    )

# ---------------- DASHBOARD ----------------
@bot.tree.command(name="taxdashboard", guild=GUILD)
async def taxdashboard(interaction: discord.Interaction):

    members = [m for m in interaction.guild.members if is_tax_member(m)]

    total = len(members)

    low = medium = critical = 0

    for m in members:
        overdue = tax_data.get(m.id, {"overdue": 0})["overdue"]

        level, _ = get_overdue_level(overdue)

        if level == "LOW":
            low += 1
        elif level == "MEDIUM":
            medium += 1
        elif level == "CRITICAL":
            critical += 1

    desc = (
        "☕ **Bean Machine Tax Dashboard**\n\n"
        f"👥 Total Employees: {total}\n\n"
        f"🟢 Low Risk: {low}\n"
        f"🟠 Medium Risk: {medium}\n"
        f"🔴 Critical Risk: {critical}\n\n"
        "📊 System Status: ACTIVE"
    )

    await interaction.response.send_message(
        embed=embed("📊 Tax Dashboard", desc, discord.Color.blurple())
    )
# ---------------- FORCE REMIND ----------------
@bot.tree.command(name="forceremind", guild=GUILD)
async def forceremind(interaction: discord.Interaction, member: discord.Member):

    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("Owner only", ephemeral=True)

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("Channel not found", ephemeral=True)

    data = tax_data.get(member.id, {"overdue": 0})
    overdue = data["overdue"]

    level, color = get_overdue_level(overdue)

    desc = (
        f"👤 Employee: {member.mention}\n\n"
        "📌 Reason:\n"
        "This is a manual reminder sent by management.\n\n"
        f"⚠️ Risk Level: {level}\n\n"
        "💰 Action:\n"
        "Please complete your tax payment.\n"
    )

    if overdue > 0:
        desc += (
            f"\n📊 Overdue Periods: {overdue}\n\n"
            "🚨 Please clear your previous dues as soon as possible."
        )

    await channel.send(embed=embed("☕ Manual Tax Reminder", desc, color))

    await interaction.response.send_message("Sent", ephemeral=True)

# ---------------- RUN ----------------
try:
    print("BOT STARTING...")
    print("TOKEN EXISTS:", bool(TOKEN))
    print("TOKEN LENGTH:", len(TOKEN) if TOKEN else 0)

    bot.run(TOKEN)

except Exception as e:
    print("BOT CRASH ERROR:", e)
