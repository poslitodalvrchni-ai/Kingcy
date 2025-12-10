import discord
from discord.ext import commands
import json
import random
import os
import asyncio
import re
from datetime import datetime, timedelta, timezone

# --- Web Server Imports (FOR RENDER HEALTH CHECK) ---
from flask import Flask
from threading import Thread

# --- Flask Web Server Setup ---
app = Flask(__name__)

@app.route('/')
def home():
    """Simple route for Render health check and Uptime Robot ping."""
    return "Kingcy Bot is running and online!", 200

def run_flask_server():
    """Starts the Flask web server."""
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

# --- Configuration ---
TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN_HERE') 
CURRENCY_NAME = "Kingcy"
CURRENCY_SYMBOL = "👑"

# Prefix is now "king " (with a space)
COMMAND_PREFIX = "king " 

DATA_FILE = "users.json"
INITIAL_BALANCE = 500
DAILY_REWARD = 200
PRAY_REWARD_BASE = 50
EXCLUDED_ROLE_ID = 1448198628085727294 # Role hidden from leaderboard & allowed to use 'claim'

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Remove default help to use our custom one
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

# --- Helper Functions ---

def format_currency(amount):
    """Formats the currency amount with short suffixes (k, M, B)."""
    try:
        amount = float(amount)
    except:
        return f"0 {CURRENCY_SYMBOL}"

    if amount >= 1_000_000_000:
        val = f"{amount / 1_000_000_000:.1f}B"
    elif amount >= 1_000_000:
        val = f"{amount / 1_000_000:.1f}M"
    elif amount >= 1_000:
        val = f"{amount / 1_000:.1f}k"
    else:
        val = f"{int(amount)}"
    
    return f"{val} {CURRENCY_SYMBOL}"

# --- Data Persistence ---

async def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    def _read():
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    try:
        return await asyncio.to_thread(_read)
    except:
        return {}

async def save_data(data):
    def _write():
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
    try:
        await asyncio.to_thread(_write)
    except Exception as e:
        print(f"Error saving data: {e}")

async def ensure_user_data(user_id):
    user_id_str = str(user_id)
    data = await load_data()
    
    if user_id_str not in data:
        data[user_id_str] = {
            "balance": INITIAL_BALANCE,
            "daily_last_claimed": "0",
            "wins_flip": 0, "losses_flip": 0,
            "wins_slot": 0, "losses_slot": 0,
            "wins_bj": 0, "losses_bj": 0,
            "total_gambled": 0,
            "pray_streak": 0,
            "last_pray_date": "0",
            "prays_today": 0
        }
        await save_data(data)
    else:
        # Migration for existing users (add missing fields)
        defaults = {
            "pray_streak": 0,
            "last_pray_date": "0",
            "prays_today": 0
        }
        changed = False
        for key, val in defaults.items():
            if key not in data[user_id_str]:
                data[user_id_str][key] = val
                changed = True
        if changed:
            await save_data(data)
            
    return data[user_id_str]

# --- Events ---

@bot.event
async def on_ready():
    print(f'{bot.user.name} is online!')
    await bot.change_presence(activity=discord.Game(name="king help | Gambling"))

# --- Commands ---

@bot.command(name='help')
async def help_command(ctx):
    """Lists all available commands."""
    embed = discord.Embed(title="👑 Kingcy Bot Commands", color=0xFFD700)
    
    embed.add_field(name="💰 Economy", value=(
        "`king balance` - Check your funds\n"
        "`king daily` - Claim daily reward\n"
        "`king gift @user <amount>` - Give money to someone\n"
        "`king claim <amount>` - (Admin/Special Role Only)"
    ), inline=False)
    
    embed.add_field(name="🙏 Prayer & Luck", value=(
        "`king pray` - Pray for luck (3x/day). Streaks give bonuses!\n"
        "`king remind <time> <msg>` - Set a reminder (e.g., `king remind 4h Pray`)"
    ), inline=False)
    
    embed.add_field(name="🎰 Gambling", value=(
        "`king flip <heads/tails> <amt>` - Coin flip (2x)\n"
        "`king slot <amt>` - Slot machine (Animated!)\n"
        "`king blackjack <amt>` - Play 21"
    ), inline=False)
    
    embed.add_field(name="🏆 Social", value=(
        "`king leaderboard` - See who has the most Kingcy"
    ), inline=False)
    
    embed.set_footer(text="Prefix: king (e.g., 'king daily')")
    await ctx.send(embed=embed)

# --- Economy ---

@bot.command(name='balance', aliases=['bal'])
async def balance(ctx):
    user_id = str(ctx.author.id)
    data = await ensure_user_data(user_id) # ensure data exists but reload fresh below
    data = await load_data()
    bal = data[user_id]["balance"]
    
    embed = discord.Embed(
        description=f"💳 **{ctx.author.name}**, you have **{format_currency(bal)}**",
        color=0x00FF00
    )
    await ctx.send(embed=embed)

@bot.command(name='daily')
async def daily(ctx):
    user_id = str(ctx.author.id)
    await ensure_user_data(user_id)
    data = await load_data()
    user_data = data[user_id]
    
    last_claimed = user_data.get("daily_last_claimed", "0")
    
    # Check 24h cooldown
    now = datetime.now(timezone.utc)
    try:
        last_date = datetime.fromisoformat(last_claimed)
        if now < last_date + timedelta(hours=24):
            remaining = (last_date + timedelta(hours=24)) - now
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return await ctx.send(f"⏳ Come back in **{hours}h {minutes}m**.")
    except ValueError:
        pass # If format error or "0", proceed

    user_data["balance"] += DAILY_REWARD
    user_data["daily_last_claimed"] = now.isoformat()
    await save_data(data)
    
    await ctx.send(f"✅ **{ctx.author.name}**, you claimed your daily **{format_currency(DAILY_REWARD)}**!")

@bot.command(name='gift', aliases=['pay'])
async def gift(ctx, recipient: discord.Member, amount: str):
    """Transfer money to another user."""
    if recipient.bot:
        return await ctx.send("🤖 You can't give money to bots.")
    
    # Handle "all" or short numbers parsing if needed, but keeping it simple int for now
    try:
        amount = int(amount)
    except ValueError:
        return await ctx.send("Please enter a valid number.")

    if amount <= 0:
        return await ctx.send("You must gift a positive amount.")

    sender_id = str(ctx.author.id)
    receiver_id = str(recipient.id)
    
    await ensure_user_data(sender_id)
    await ensure_user_data(receiver_id)
    
    data = await load_data()
    
    if data[sender_id]["balance"] < amount:
        return await ctx.send(f"❌ You don't have enough Kingcy. Balance: {format_currency(data[sender_id]['balance'])}")
    
    data[sender_id]["balance"] -= amount
    data[receiver_id]["balance"] += amount
    
    await save_data(data)
    
    embed = discord.Embed(
        description=f"💸 **{ctx.author.name}** sent **{format_currency(amount)}** to **{recipient.name}**!",
        color=0x00FF00
    )
    await ctx.send(embed=embed)

@bot.command(name='claim', aliases=['inviteclaim'])
async def claim(ctx, amount: str):
    """Exclusive command for a specific role to generate money."""
    user_id = str(ctx.author.id)
    role = ctx.guild.get_role(EXCLUDED_ROLE_ID)
    
    if not role or role not in ctx.author.roles:
        return await ctx.send("🔒 This command is locked to a specific role.")

    try:
        amount = int(amount)
    except ValueError:
        return await ctx.send("❌ Please enter a valid number.")
        
    if amount <= 0:
        return await ctx.send("❌ Amount must be positive.")

    await ensure_user_data(user_id)
    data = await load_data()
    
    data[user_id]["balance"] += amount
    
    await save_data(data)
    await ctx.send(f"💎 **Exclusive Claim!** You generated **{format_currency(amount)}**!")

# --- Prayer System ---

@bot.command(name='pray')
async def pray(ctx):
    user_id = str(ctx.author.id)
    await ensure_user_data(user_id)
    data = await load_data()
    user = data[user_id]
    
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    
    last_pray_date = user.get("last_pray_date", "0").split("T")[0] # Just get the date part
    prays_today = user.get("prays_today", 0)
    streak = user.get("pray_streak", 0)

    # Check reset
    if last_pray_date != today_str:
        prays_today = 0
        # Streak logic: if missed yesterday, reset
        if last_pray_date != yesterday_str and last_pray_date != "0":
            streak = 0
            await ctx.send("💔 You missed a day! Your prayer streak has been reset.")

    if prays_today >= 3:
        return await ctx.send("🙏 You have prayed 3 times today. Rest now, my child.")

    # Calculate Reward (Base + Streak Bonus)
    bonus = streak * 10
    total_reward = PRAY_REWARD_BASE + bonus
    
    user["balance"] += total_reward
    user["prays_today"] = prays_today + 1
    user["last_pray_date"] = now.isoformat()
    
    # Increment streak only on the FIRST pray of the day
    if prays_today == 0:
        streak += 1
        user["pray_streak"] = streak
        streak_msg = f"🔥 **Streak: {streak} days!**"
    else:
        streak_msg = ""

    await save_data(data)
    
    embed = discord.Embed(
        description=f"🙏 **{ctx.author.name}** prayed.\nreceived **{format_currency(total_reward)}** (Luck Bonus: +{bonus})\n{streak_msg}",
        color=0xFFFFFF
    )
    await ctx.send(embed=embed)

@bot.command(name='remind')
async def remind(ctx, time_str: str, *, message: str="Something important!"):
    """Set a reminder. Usage: king remind 10m Check slots"""
    # Simple regex to parse 1h, 10m, 30s
    match = re.match(r"(\d+)([hms])", time_str)
    if not match:
        return await ctx.send("❌ Invalid time format. Use `1h`, `30m`, or `10s`.")
    
    amount = int(match.group(1))
    unit = match.group(2)
    
    seconds = 0
    if unit == 'h': seconds = amount * 3600
    elif unit == 'm': seconds = amount * 60
    elif unit == 's': seconds = amount
    
    if seconds > 86400: # Cap at 24h
        return await ctx.send("❌ Reminder cannot be longer than 24 hours.")

    await ctx.send(f"⏰ I will remind you to **\"{message}\"** in **{time_str}**.")
    
    await asyncio.sleep(seconds)
    
    await ctx.send(f"🔔 {ctx.author.mention}, Reminder: **{message}**")

# --- Gambling (Animated & Updated) ---

async def check_bet(ctx, amount):
    try:
        amount = int(amount)
    except:
        await ctx.send("Please enter a valid number.")
        return False, 0
    
    if amount <= 0:
        await ctx.send("Bet must be positive.")
        return False, 0
        
    user_id = str(ctx.author.id)
    data = await load_data()
    if user_id not in data or data[user_id]["balance"] < amount:
        await ctx.send("❌ Insufficient funds.")
        return False, 0
        
    return True, amount

@bot.command(name='slot', aliases=['slots'])
async def slot(ctx, amount: str):
    valid, bet = await check_bet(ctx, amount)
    if not valid: return

    # Deduct bet
    user_id = str(ctx.author.id)
    data = await load_data()
    data[user_id]["balance"] -= bet
    await save_data(data)

    emojis = ['🍒', '🔔', '💎', '💰', '👑']
    
    # Initial message
    embed = discord.Embed(title="🎰 Slot Machine", description="🔄 Spinning...\n\n| ❓ | ❓ | ❓ |", color=0x3498db)
    msg = await ctx.send(embed=embed)
    
    # Animation Loop
    for _ in range(3):
        await asyncio.sleep(0.7)
        s1, s2, s3 = random.choice(emojis), random.choice(emojis), random.choice(emojis)
        embed.description = f"🔄 Spinning...\n\n| {s1} | {s2} | {s3} |"
        await msg.edit(embed=embed)
    
    # Final Result
    await asyncio.sleep(0.5)
    s1, s2, s3 = random.choice(emojis), random.choice(emojis), random.choice(emojis)
    
    winnings = 0
    result_text = ""
    color = 0x000000
    
    if s1 == s2 == s3:
        winnings = bet * 10
        result_text = "🎉 **JACKPOT! (10x)**"
        color = 0xF1C40F # Gold
        data[user_id]["wins_slot"] += 1
    elif s1 == s2 or s2 == s3 or s1 == s3:
        winnings = bet * 2
        result_text = "✨ **Double Match! (2x)**"
        color = 0xE67E22 # Orange
        data[user_id]["wins_slot"] += 1
    else:
        result_text = "💸 **You Lost.**"
        color = 0xE74C3C # Red
        data[user_id]["losses_slot"] += 1

    data[user_id]["balance"] += winnings
    data[user_id]["total_gambled"] += bet
    await save_data(data)
    
    embed.title = "🎰 Slot Machine Result"
    embed.description = f"| {s1} | {s2} | {s3} |\n\n{result_text}\nWon: {format_currency(winnings)}"
    embed.color = color
    embed.set_footer(text=f"New Balance: {format_currency(data[user_id]['balance'])}")
    
    await msg.edit(embed=embed)

@bot.command(name='flip', aliases=['cf'])
async def flip(ctx, choice: str, amount: str):
    valid, bet = await check_bet(ctx, amount)
    if not valid: return
    
    choice = choice.lower()
    if choice not in ['heads', 'tails', 'h', 't']:
        return await ctx.send("Please pick `heads` or `tails`.")
        
    if choice == 'h': choice = 'heads'
    if choice == 't': choice = 'tails'

    user_id = str(ctx.author.id)
    data = await load_data()
    
    result = random.choice(['heads', 'tails'])
    
    if choice == result:
        winnings = bet # Profit
        data[user_id]["balance"] += winnings
        data[user_id]["wins_flip"] += 1
        msg = f"🎉 It's **{result.upper()}**! You won **{format_currency(winnings)}**!"
        col = 0x2ECC71
    else:
        data[user_id]["balance"] -= bet
        data[user_id]["losses_flip"] += 1
        msg = f"💀 It's **{result.upper()}**! You lost **{format_currency(bet)}**."
        col = 0xE74C3C
        
    data[user_id]["total_gambled"] += bet
    await save_data(data)
    
    embed = discord.Embed(title="🪙 Coin Flip", description=msg, color=col)
    embed.set_footer(text=f"New Balance: {format_currency(data[user_id]['balance'])}")
    await ctx.send(embed=embed)

@bot.command(name='blackjack', aliases=['bj'])
async def blackjack(ctx, amount: str):
    valid, bet = await check_bet(ctx, amount)
    if not valid: return

    user_id = str(ctx.author.id)
    data = await load_data()
    data[user_id]["balance"] -= bet
    await save_data(data)

    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    
    def score(hand):
        s = sum(hand)
        aces = hand.count(11)
        while s > 21 and aces:
            s -= 10
            aces -= 1
        return s

    p_score = score(player_hand)
    d_score = score(dealer_hand)
    
    # Instant Blackjack Check
    if p_score == 21:
        win = int(bet * 2.5) # 1.5x payout + bet back
        data[user_id]["balance"] += win
        data[user_id]["wins_bj"] += 1
        await save_data(data)
        return await ctx.send(embed=discord.Embed(title="🃏 Blackjack!", description=f"**Blackjack!** You won **{format_currency(win)}**!", color=0xF1C40F))

    # Simplified logic (No hit/stand interaction for simplicity in text command)
    # Dealer plays out immediately
    while d_score < 17:
        dealer_hand.append(deck.pop())
        d_score = score(dealer_hand)
        
    # Determine winner
    winnings = 0
    if p_score > 21:
        res = "Bust! You lose."
        col = 0xE74C3C
    elif d_score > 21:
        res = "Dealer Bust! You win!"
        winnings = bet * 2
        col = 0x2ECC71
    elif p_score > d_score:
        res = "You win!"
        winnings = bet * 2
        col = 0x2ECC71
    elif p_score == d_score:
        res = "Push (Tie)."
        winnings = bet
        col = 0x95A5A6
    else:
        res = "Dealer wins."
        col = 0xE74C3C
        
    data[user_id]["balance"] += winnings
    data[user_id]["total_gambled"] += bet
    if winnings > bet: data[user_id]["wins_bj"] += 1
    elif winnings < bet: data[user_id]["losses_bj"] += 1
    
    await save_data(data)

    embed = discord.Embed(title="🃏 Blackjack", color=col)
    embed.add_field(name="You", value=f"{player_hand} ({p_score})")
    embed.add_field(name="Dealer", value=f"{dealer_hand} ({d_score})")
    embed.add_field(name="Result", value=res, inline=False)
    embed.set_footer(text=f"Balance: {format_currency(data[user_id]['balance'])}")
    await ctx.send(embed=embed)

@bot.command(name='leaderboard', aliases=['lb'])
async def leaderboard(ctx):
    data = await load_data()
    sorted_users = sorted(
        [(uid, d) for uid, d in data.items() if d.get('balance', 0) > 0],
        key=lambda x: x[1]['balance'],
        reverse=True
    )

    lb_text = ""
    count = 0
    
    for uid, user_data in sorted_users:
        if count >= 10: break
        
        # Check for excluded role
        try:
            member = ctx.guild.get_member(int(uid))
            if member:
                # Check if member has the excluded role
                if any(r.id == EXCLUDED_ROLE_ID for r in member.roles):
                    continue # Skip this user
                name = member.name
            else:
                # If member left server, we show them (optional) or skip
                name = f"User#{uid[-4:]}"
        except:
            name = f"User#{uid[-4:]}"

        count += 1
        lb_text += f"**{count}.** {name} • **{format_currency(user_data['balance'])}**\n"

    if not lb_text:
        lb_text = "No one is on the leaderboard yet!"

    embed = discord.Embed(title="🏆 Server Leaderboard", description=lb_text, color=0xF1C40F)
    await ctx.send(embed=embed)

# --- Startup ---
if __name__ == "__main__":
    if TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("ERROR: Set DISCORD_TOKEN env variable.")
    else:
        Thread(target=run_flask_server, daemon=True).start()
        bot.run(TOKEN)
