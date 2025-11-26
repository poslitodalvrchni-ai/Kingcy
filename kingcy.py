import discord
from discord.ext import commands
import json
import random
import os
import asyncio
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
    # Render provides the port via the PORT environment variable
    port = int(os.environ.get('PORT', 5000))
    # Must bind to 0.0.0.0 to be accessible externally
    app.run(host='0.0.0.0', port=port)

# --- Configuration ---
# REPLACE THIS WITH YOUR BOT'S TOKEN
TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN_HERE') 
CURRENCY_NAME = "Kingcy"
CURRENCY_SYMBOL = "👑"
COMMAND_PREFIX = "!"
DATA_FILE = "users.json" # !!! WARNING: This data will be LOST on Render restarts. Use a database!
INITIAL_BALANCE = 500
DAILY_REWARD = 200
CHECKLIST_REWARD = 150
COOLDOWN_DAILY = 24 # hours
COOLDOWN_CHECKLIST = 24 # hours

# Intents are required for reading message content and members
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# --- Asynchronous Data Persistence using JSON file ---

async def load_data():
    """Asynchronously loads user data from the JSON file."""
    if not os.path.exists(DATA_FILE):
        return {}
    
    # Run file operation in an executor to prevent blocking the event loop
    def _read():
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    
    try:
        return await asyncio.to_thread(_read)
    except json.JSONDecodeError:
        print(f"Warning: {DATA_FILE} is corrupted or empty. Starting with empty data.")
        return {}
    except Exception as e:
        print(f"Error loading data: {e}")
        return {}

async def save_data(data):
    """Asynchronously saves user data to the JSON file."""
    # Run file operation in an executor to prevent blocking the event loop
    def _write():
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)
            
    try:
        await asyncio.to_thread(_write)
    except Exception as e:
        print(f"Error saving data: {e}")

async def ensure_user_data(user_id):
    """Ensures a user has an entry in the data file with default values."""
    user_id_str = str(user_id)
    data = await load_data()
    
    if user_id_str not in data:
        data[user_id_str] = {
            "balance": INITIAL_BALANCE,
            "daily_last_claimed": "0",
            "checklist_last_claimed": "0",
            "wins_flip": 0,
            "losses_flip": 0,
            "wins_slot": 0,
            "losses_slot": 0,
            "wins_bj": 0,
            "losses_bj": 0,
            "total_gambled": 0
        }
        await save_data(data)
    return data[user_id_str]

# --- Bot Events ---

@bot.event
async def on_ready():
    """Prints a message when the bot successfully connects."""
    print(f'{bot.user.name} is online and ready!')
    # Load all data when the bot starts
    global users_data
    users_data = await load_data()
    print(f"Loaded {len(users_data)} users.")

# --- Helper Functions for Time and Formatting ---

def format_currency(amount):
    """Formats the currency amount with the symbol."""
    return f"{amount:,} {CURRENCY_SYMBOL}"

def get_cooldown_message(last_claimed_timestamp, cooldown_hours):
    """Calculates the time remaining until the cooldown expires."""
    try:
        # Ensure we are using timezone-aware datetimes for comparison
        last_claimed = datetime.fromisoformat(last_claimed_timestamp)
        next_claim = last_claimed + timedelta(hours=cooldown_hours)
        now_utc = datetime.now(timezone.utc)

        if next_claim > now_utc:
            remaining = next_claim - now_utc
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            return f"You can claim this again in **{hours}h {minutes}m {seconds}s**."
        return None
    except:
        # Handle case where timestamp is "0" or invalid
        return None

# --- Core Economy Commands ---

@bot.command(name='balance', aliases=['bal'])
async def balance(ctx):
    """Shows the user's Kingcy balance."""
    user_id = str(ctx.author.id)
    # Ensure data is loaded/user exists
    data_for_user = await ensure_user_data(user_id)
    
    balance_amount = data_for_user["balance"]
    
    embed = discord.Embed(
        title=f"{ctx.author.name}'s Kingcy Balance",
        description=f"You currently have **{format_currency(balance_amount)}**.",
        color=0x00FF00 # Green color
    )
    embed.set_thumbnail(url=ctx.author.avatar.url if ctx.author.avatar else None)
    await ctx.send(embed=embed)


@bot.command(name='daily')
@commands.cooldown(1, 3600 * COOLDOWN_DAILY, commands.BucketType.user)
async def daily(ctx):
    """Claim your daily Kingcy reward."""
    user_id = str(ctx.author.id)
    data = await load_data()
    await ensure_user_data(user_id)
    user_data = data[user_id]

    last_claimed_timestamp = user_data["daily_last_claimed"]
    cooldown_msg = get_cooldown_message(last_claimed_timestamp, COOLDOWN_DAILY)

    if cooldown_msg:
        # Manually reset cooldown since the command logic handles the time check
        daily.reset_cooldown(ctx)
        await ctx.send(f"{ctx.author.mention}, you already claimed your daily reward! {cooldown_msg}")
        return

    # Update balance
    user_data["balance"] += DAILY_REWARD
    # Use timezone.utc for consistency
    user_data["daily_last_claimed"] = datetime.now(timezone.utc).isoformat()

    await save_data(data)
    
    embed = discord.Embed(
        title="👑 Daily Kingcy Claimed!",
        description=f"{ctx.author.mention}, you received **{format_currency(DAILY_REWARD)}**!",
        color=0xFFD700
    )
    embed.set_footer(text=f"Your new balance is {format_currency(user_data['balance'])}")
    await ctx.send(embed=embed)

# This handles the cooldown being triggered, in case the time check fails or is bypassed
@daily.error
async def daily_error(ctx, error):
    if isinstance(error, commands.CommandOnCooldown):
        # We handle this manually in the command for a custom message, so we just ignore the generic error here
        pass 
    else:
        print(f"Daily command error: {error}")

@bot.command(name='checklist', aliases=['check'])
@commands.cooldown(1, 3600 * COOLDOWN_CHECKLIST, commands.BucketType.user)
async def checklist(ctx):
    """Complete your daily checklist for bonus Kingcy."""
    user_id = str(ctx.author.id)
    data = await load_data()
    await ensure_user_data(user_id)
    user_data = data[user_id]

    last_claimed_timestamp = user_data["checklist_last_claimed"]
    cooldown_msg = get_cooldown_message(last_claimed_timestamp, COOLDOWN_CHECKLIST)

    if cooldown_msg:
        checklist.reset_cooldown(ctx)
        await ctx.send(f"{ctx.author.mention}, you've already completed your checklist today! {cooldown_msg}")
        return

    # Update balance
    user_data["balance"] += CHECKLIST_REWARD
    user_data["checklist_last_claimed"] = datetime.now(timezone.utc).isoformat()

    await save_data(data)
    
    embed = discord.Embed(
        title="✅ Checklist Complete!",
        description=(
            f"{ctx.author.mention}, you completed your daily tasks and earned **{format_currency(CHECKLIST_REWARD)}**!\n"
            f"**Tasks Completed:**\n"
            f"• Woke up on time (1/1)\n"
            f"• Had a sip of water (1/1)\n"
            f"• Booted up Discord (1/1)\n"
        ),
        color=0x4CAF50
    )
    embed.set_footer(text=f"Your new balance is {format_currency(user_data['balance'])}")
    await ctx.send(embed=embed)

# --- Gambling Games ---

async def check_bet_async(ctx, amount):
    """Asynchronous function to validate a bet amount."""
    user_id = str(ctx.author.id)
    data = await load_data() # Load data asynchronously
    
    balance = data.get(user_id, {}).get('balance', 0)
    
    if balance < amount:
        await ctx.send(
            f"{ctx.author.mention}, you don't have enough Kingcy. Your balance is {format_currency(balance)}."
        )
        return False
    if amount <= 0:
        await ctx.send(f"{ctx.author.mention}, please bet a positive amount.")
        return False
    return True

# Removed the redundant update_gambling_stats function as the individual commands handle it
# async def update_gambling_stats(user_id, bet_amount, win): 
#     ...

@bot.command(name='flip', aliases=['cf'])
async def coin_flip(ctx, choice: str = None, amount: int = None):
    """Flips a coin for a 2x payout (Heads or Tails)."""
    user_id = str(ctx.author.id)
    
    if choice is None or amount is None:
        return await ctx.send(f"Usage: `!flip <heads|tails> <amount>`. Example: `!flip heads 100`")

    choice = choice.lower()
    if choice not in ['heads', 'tails']:
        return await ctx.send(f"Invalid choice. Please choose `heads` or `tails`.")

    if not await check_bet_async(ctx, amount): return

    data = await load_data()
    user_data = data[user_id]
    
    result = random.choice(['heads', 'tails'])
    
    # Update stats BEFORE sending message (safety first)
    if choice == result:
        # Win amount is the bet amount (profit) + the original bet returned
        profit = amount 
        user_data["balance"] += profit
        user_data["wins_flip"] += 1
        message = f"It's **{result.upper()}**! 🎉 You won **{format_currency(profit)}**!"
        color = discord.Color.green()
    else:
        loss = amount
        user_data["balance"] -= loss
        user_data["losses_flip"] += 1
        message = f"It's **{result.upper()}**! 💔 You lost **{format_currency(loss)}**."
        color = discord.Color.red()
        
    user_data["total_gambled"] += amount
    await save_data(data)

    embed = discord.Embed(
        title="🪙 Coin Flip",
        description=message,
        color=color
    )
    embed.set_footer(text=f"Your new balance is {format_currency(user_data['balance'])}")
    await ctx.send(embed=embed)


@bot.command(name='slot', aliases=['slots'])
async def slot_machine(ctx, amount: int = None):
    """Plays a slot machine for a chance at big Kingcy."""
    user_id = str(ctx.author.id)
    
    if amount is None:
        return await ctx.send(f"Usage: `!slot <amount>`. Example: `!slot 50`")

    if not await check_bet_async(ctx, amount): return

    data = await load_data()
    user_data = data[user_id]
    
    emojis = ['🍒', '🔔', '💎', '💰', '👑']
    # Spin the slots
    s1 = random.choice(emojis)
    s2 = random.choice(emojis)
    s3 = random.choice(emojis)
    
    result = f"| {s1} | {s2} | {s3} |"
    profit = 0
    
    if s1 == s2 == s3:
        multiplier = 10
        profit = amount * (multiplier - 1) # Bet is returned, so profit is (multiplier - 1) * amount
        message = f"**{result}**\n\n🎉 TRIPLE MATCH! You won **{format_currency(profit)}**!"
        color = discord.Color.gold()
        user_data["wins_slot"] += 1
    elif s1 == s2 or s2 == s3 or s1 == s3:
        multiplier = 2
        profit = amount * (multiplier - 1) # Profit is 1x the bet
        message = f"**{result}**\n\n✨ DOUBLE MATCH! You won **{format_currency(profit)}**!"
        color = discord.Color.orange()
        user_data["wins_slot"] += 1
    else:
        profit = -amount # Loss is the full bet amount
        message = f"**{result}**\n\n😭 No match. You lost **{format_currency(amount)}**."
        color = discord.Color.red()
        user_data["losses_slot"] += 1

    # Update balance and stats
    user_data["balance"] += profit
    user_data["total_gambled"] += amount
    await save_data(data)

    embed = discord.Embed(
        title="🎰 Slot Machine",
        description=message,
        color=color
    )
    embed.set_footer(text=f"Your new balance is {format_currency(user_data['balance'])}")
    await ctx.send(embed=embed)


# --- Blackjack Implementation ---

# Card definitions
CARD_VALUES = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
    '10': 10, 'J': 10, 'Q': 10, 'K': 10, 'A': 11
}
CARD_SUITS = ['♠️', '♥️', '♣️', '♦️']

def create_deck():
    """Creates and shuffles a standard 52-card deck."""
    deck = []
    for rank in CARD_VALUES.keys():
        for suit in CARD_SUITS:
            deck.append(f"{rank}{suit}")
    random.shuffle(deck)
    return deck

def calculate_hand_value(hand):
    """Calculates the best possible value of a Blackjack hand."""
    # Start with all non-Aces
    value = sum(CARD_VALUES[card[:-1]] for card in hand if card[:-1] != 'A')
    num_aces = sum(1 for card in hand if card[:-1] == 'A')

    # Add Aces, treating them as 11 first
    value += num_aces * 11
    
    # Adjust Aces from 11 to 1 if the total value exceeds 21
    while value > 21 and num_aces > 0:
        value -= 10
        num_aces -= 1
        
    return value

@bot.command(name='blackjack', aliases=['bj'])
async def blackjack(ctx, amount: int = None):
    """Starts a simplified game of Blackjack."""
    user_id = str(ctx.author.id)

    if amount is None:
        return await ctx.send(f"Usage: `!blackjack <amount>`. Example: `!blackjack 250`")

    if not await check_bet_async(ctx, amount): return
    
    # Deduct bet immediately for game
    data = await load_data()
    user_data = data[user_id]
    user_data["balance"] -= amount
    await save_data(data)
    
    deck = create_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    def format_hand(hand):
        """Formats the hand for display."""
        return " | ".join(f"`{card}`" for card in hand)

    # Simplified, one-round Blackjack logic for example
    player_score = calculate_hand_value(player_hand)
    dealer_score = calculate_hand_value(dealer_hand)
    
    winnings = 0
    
    # Check for natural blackjack
    if player_score == 21:
        # Dealer flips the card
        while dealer_score < 17 and len(dealer_hand) < 5: # Dealer hits up to 5 cards max if under 17
            dealer_hand.append(deck.pop())
            dealer_score = calculate_hand_value(dealer_hand)
            
        if dealer_score == 21:
            result = "Push (Tie)"
            winnings = amount  # Bet returned
            color = discord.Color.greyple()
        else:
            result = "Player Blackjack! (Win 1.5x bet)"
            winnings = amount + int(amount * 1.5)
            color = discord.Color.green()
    else:
        # Dealer hits until 17 or more (simplified: no player hit/stand interaction)
        while dealer_score < 17 and len(dealer_hand) < 5: 
            dealer_hand.append(deck.pop())
            dealer_score = calculate_hand_value(dealer_hand)

        # Standard outcome logic
        if player_score > 21:
            result = "Player Busts! (Dealer Wins)"
            winnings = 0
            color = discord.Color.red()
        elif dealer_score > 21:
            result = "Dealer Busts! (Player Wins 1x bet)"
            winnings = amount * 2
            color = discord.Color.green()
        elif player_score > dealer_score:
            result = "Player Wins! (Win 1x bet)"
            winnings = amount * 2
            color = discord.Color.green()
        elif player_score < dealer_score:
            result = "Dealer Wins!"
            winnings = 0
            color = discord.Color.red()
        else: # player_score == dealer_score
            result = "Push (Tie)"
            winnings = amount
            color = discord.Color.greyple()

    # --- Update Balance and Stats ---
    final_win_loss = winnings - amount # Net change (profit/loss)
    data = await load_data()
    user_data = data[user_id]
    user_data["balance"] += winnings # Add back the total received amount (winnings)
    
    user_data["total_gambled"] += amount
    if final_win_loss > 0: user_data["wins_bj"] += 1
    elif final_win_loss < 0: user_data["losses_bj"] += 1

    await save_data(data)

    # --- Send Result Embed ---
    embed = discord.Embed(
        title="🃏 Blackjack Game Result",
        description=f"**Bet:** {format_currency(amount)}",
        color=color
    )
    embed.add_field(name="Your Hand", value=f"{format_hand(player_hand)}\nScore: {player_score}", inline=False)
    embed.add_field(name="Dealer's Hand", value=f"{format_hand(dealer_hand)}\nScore: {dealer_score}", inline=False)
    embed.add_field(name="Outcome", value=f"**{result}**", inline=True)
    embed.add_field(name="Net Change", value=f"{format_currency(final_win_loss)}", inline=True)
    embed.set_footer(text=f"Your new balance is {format_currency(user_data['balance'])}")
    await ctx.send(embed=embed)


# --- Leaderboards Command ---

@bot.command(name='leaderboard', aliases=['lb'])
async def leaderboard(ctx):
    """Displays the top 10 users by Kingcy balance."""
    data = await load_data()
    
    # Filter out users with no balance and sort by balance descending
    sorted_users = sorted(
        [(uid, user_data) for uid, user_data in data.items() if user_data.get('balance', 0) > 0],
        key=lambda x: x[1]['balance'],
        reverse=True
    )

    if not sorted_users:
        return await ctx.send("The leaderboard is currently empty. Start earning Kingcy!")

    # Build the leaderboard string
    leaderboard_text = ""
    for i, (user_id, user_data) in enumerate(sorted_users[:10]):
        # Try to fetch member object for name, otherwise use ID
        try:
            member = await bot.fetch_user(int(user_id))
            name = member.name
        except:
            name = f"User#{user_id[:4]}"
            
        balance = format_currency(user_data['balance'])
        
        leaderboard_text += f"**{i + 1}.** {name} - **{balance}**\n"
    
    embed = discord.Embed(
        title=f"👑 Top 10 Kingcy Leaders",
        description=leaderboard_text,
        color=0x4287f5 # Blue color
    )
    embed.set_footer(text="Keep gambling to reach the top!")
    await ctx.send(embed=embed)


# --- Bot Run Command ---

if __name__ == "__main__":
    
    if TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("\n--- CRITICAL ERROR ---")
        print("Please set the DISCORD_TOKEN environment variable or replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord Bot Token.")
        print("The bot will not run without a valid token.")
        print("--- CRITICAL ERROR ---\n")
    else:
        # 1. Start Flask server in a separate thread
        print("Starting Flask web server for health checks...")
        flask_thread = Thread(target=run_flask_server)
        flask_thread.daemon = True # Allows the bot to exit even if the thread is still running
        flask_thread.start()
        
        # 2. Run the Discord bot in the main thread (blocking call)
        try:
            print("Starting Discord Bot...")
            bot.run(TOKEN)
        except discord.errors.LoginFailure:
            print("Error: Invalid bot token provided. Please check your TOKEN/DISCORD_TOKEN.")
        except Exception as e:
            print(f"An unexpected error occurred during bot execution: {e}")
