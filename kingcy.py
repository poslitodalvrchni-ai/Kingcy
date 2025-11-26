import discord
from discord.ext import commands
import json
import random
import os
import asyncio
from datetime import datetime, timedelta, timezone
from flask import Flask
from threading import Thread

# --- Configuration ---
# REPLACE THIS WITH YOUR BOT'S TOKEN (or set DISCORD_TOKEN environment variable)
TOKEN = os.getenv('DISCORD_TOKEN', 'YOUR_BOT_TOKEN_HERE') 
CURRENCY_NAME = "Kingcy"
CURRENCY_SYMBOL = "👑"
COMMAND_PREFIX = "!"
DATA_FILE = "users.json"
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
        # Use UTC time for consistency
        last_claimed = datetime.fromisoformat(last_claimed_timestamp.replace('Z', '+00:00'))
        next_claim = last_claimed + timedelta(hours=cooldown_hours)
        now_utc = datetime.now(timezone.utc)

        if next_claim > now_utc:
            remaining = next_claim - now_utc
            # Calculate hours, minutes, and seconds remaining
            total_seconds = int(remaining.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
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
    data = await load_data()
    user_data = await ensure_user_data(user_id)
    
    balance_amount = user_data["balance"]
    
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
    user_data = data[user_id] # Load again after ensuring data is present

    last_claimed_timestamp = user_data["daily_last_claimed"]
    cooldown_msg = get_cooldown_message(last_claimed_timestamp, COOLDOWN_DAILY)

    if cooldown_msg:
        # Manually reset cooldown and send the message
        daily.reset_cooldown(ctx)
        await ctx.send(f"{ctx.author.mention}, you already claimed your daily reward! {cooldown_msg}")
        return

    # Update balance
    user_data["balance"] += DAILY_REWARD
    # Store the current time in ISO format (with timezone info)
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
        # The built-in cooldown error is handled by the manual check above for a nicer message
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

async def check_bet(ctx, amount):
    """Asynchronously validates a bet amount and initial user data."""
    user_id = str(ctx.author.id)
    
    # Ensure user data exists before checking balance
    user_data = await ensure_user_data(user_id)
    
    if amount is None or not isinstance(amount, int):
        await ctx.send(f"{ctx.author.mention}, please enter a valid integer amount.")
        return False

    if amount <= 0:
        await ctx.send(f"{ctx.author.mention}, please bet a positive amount.")
        return False

    if user_data['balance'] < amount:
        await ctx.send(
            f"{ctx.author.mention}, you don't have enough Kingcy. Your balance is {format_currency(user_data['balance'])}."
        )
        return False
        
    return True


@bot.command(name='flip', aliases=['cf'])
async def coin_flip(ctx, choice: str = None, amount: int = None):
    """Flips a coin for a 2x payout (Heads or Tails)."""
    user_id = str(ctx.author.id)
    
    if choice is None or amount is None:
        return await ctx.send(f"Usage: `!flip <heads|tails> <amount>`. Example: `!flip heads 100`")

    choice = choice.lower()
    if choice not in ['heads', 'tails']:
        return await ctx.send(f"Invalid choice. Please choose `heads` or `tails`.")

    if not await check_bet(ctx, amount): return

    data = await load_data()
    user_data = data[user_id]
    
    result = random.choice(['heads', 'tails'])
    
    # Update stats BEFORE sending message (safety first)
    user_data["total_gambled"] += amount
    
    if choice == result:
        # WIN: Add the profit (2x total return - 1x bet = 1x profit)
        profit = amount
        user_data["balance"] += profit
        user_data["wins_flip"] += 1
        message = f"It's **{result.upper()}**! 🎉 You won **{format_currency(profit)}**!"
        color = discord.Color.green()
    else:
        # LOSS: Deduct the bet
        loss = -amount
        user_data["balance"] += loss
        user_data["losses_flip"] += 1
        message = f"It's **{result.upper()}**! 💔 You lost **{format_currency(amount)}**."
        color = discord.Color.red()
        
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

    if not await check_bet(ctx, amount): return

    data = await load_data()
    user_data = data[user_id]
    
    emojis = ['🍒', '🔔', '💎', '💰', '👑']
    # Spin the slots
    s1 = random.choice(emojis)
    s2 = random.choice(emojis)
    s3 = random.choice(emojis)
    
    result_line = f"| {s1} | {s2} | {s3} |"
    net_change = 0
    
    user_data["total_gambled"] += amount # Track bet amount
    
    if s1 == s2 == s3:
        multiplier = 10  # 3 of a kind: 10x payout (9x profit)
        net_change = amount * (multiplier - 1)
        user_data["balance"] += net_change 
        user_data["wins_slot"] += 1
        message = f"**{result_line}**\n\n🎉 TRIPLE MATCH! You won **{format_currency(net_change)}**!"
        color = discord.Color.gold()
    elif s1 == s2 or s2 == s3 or s1 == s3:
        multiplier = 2  # 2 of a kind: 2x payout (1x profit)
        net_change = amount * (multiplier - 1)
        user_data["balance"] += net_change 
        user_data["wins_slot"] += 1
        message = f"**{result_line}**\n\n✨ DOUBLE MATCH! You won **{format_currency(net_change)}**!"
        color = discord.Color.orange()
    else:
        # LOSS: Deduct the bet
        net_change = -amount
        user_data["balance"] -= amount
        user_data["losses_slot"] += 1
        message = f"**{result_line}**\n\n😭 No match. You lost **{format_currency(amount)}**."
        color = discord.Color.red()

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
    # Base value without considering Aces
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

    if not await check_bet(ctx, amount): return
    
    # Deduct bet immediately
    data = await load_data()
    user_data = data[user_id]
    user_data["balance"] -= amount # User pays the bet now
    await save_data(data)
    
    deck = create_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    def format_hand(hand, hide_second=False):
        """Formats the hand for display."""
        if hide_second:
            return f"`{hand[0]}` | `??`"
        return " | ".join(f"`{card}`" for card in hand)

    # Simplified, one-round Blackjack logic for example
    player_score = calculate_hand_value(player_hand)
    
    # Check for Player Blackjack
    if player_score == 21:
        dealer_score = calculate_hand_value(dealer_hand)
        if dealer_score == 21:
            result = "Push (Tie)"
            winnings = amount # Bet returned
            color = discord.Color.greyple()
        else:
            result = "Player Blackjack! (Win 1.5x bet)"
            winnings = amount + int(amount * 1.5)
            color = discord.Color.green()
    
    # Check for Player Bust
    elif player_score > 21:
        dealer_score = calculate_hand_value(dealer_hand) # Calculate just for display
        result = "Player Busts! (Dealer Wins)"
        winnings = 0
        color = discord.Color.red()
        
    # Player did not have immediate Blackjack or Bust, proceed with Dealer's turn
    else:
        dealer_score = calculate_hand_value(dealer_hand)
        # Dealer hits until 17 or more
        while dealer_score < 17:
            dealer_hand.append(deck.pop())
            dealer_score = calculate_hand_value(dealer_hand)

        # Determine standard outcome
        if dealer_score > 21:
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
    final_win_loss = winnings - amount # Net change (positive for win, negative for loss)
    data = await load_data()
    user_data = data[user_id]
    user_data["balance"] += winnings # Add back the total received amount (winnings, which includes the returned bet if any)
    
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
    # Dealer's hand is fully revealed after the game logic
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
            # Use member.display_name for a better experience, or member.name
            name = member.display_name if member else f"User#{user_id[:4]}"
        except:
            name = f"User#{user_id[:4]}"
            
        balance = format_currency(user_data['balance'])
        
        # Use markdown bolding for the name if the user is in the current guild
        display_name = f"**{name}**" if ctx.guild and ctx.guild.get_member(int(user_id)) else name
        
        leaderboard_text += f"**{i + 1}.** {display_name} - **{balance}**\n"
    
    embed = discord.Embed(
        title=f"👑 Top 10 Kingcy Leaders",
        description=leaderboard_text,
        color=0x4287f5 # Blue color
    )
    embed.set_footer(text="Keep gambling to reach the top!")
    await ctx.send(embed=embed)

# --- FLASK SERVER SETUP (For Web Service Hosting like Render) ---

# Create a Flask app instance
app = Flask(__name__)

# Define a simple route that responds to a health check (ping)
@app.route('/')
def home():
    """Simple route for the health check/ping."""
    return "Kingcy Bot is running!"

# Function to run the Flask server in a separate thread
def run_flask():
    """Runs the Flask server using the PORT environment variable."""
    # Render automatically sets the PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    # host='0.0.0.0' is required for Render deployment
    # Setting debug=False for production environment
    app.run(host='0.0.0.0', port=port, debug=False) 

# --- Bot Run Command (Consolidated Entry Point) ---

if __name__ == "__main__":
    # 1. Start the Flask server in a non-blocking thread FIRST
    # This keeps the web service alive to prevent the bot from sleeping
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    # 2. Check token and run the Discord bot in the main thread SECOND
    if TOKEN == 'YOUR_BOT_TOKEN_HERE':
        print("\n--- WARNING ---")
        print("Please replace 'YOUR_BOT_TOKEN_HERE' with your actual Discord Bot Token in the bot code or set the DISCORD_TOKEN environment variable.")
        print("The bot will not run until the token is updated.")
        print("--- WARNING ---\n")
    else:
        try:
            # bot.run() is a blocking call and must be the last line in the main thread
            bot.run(TOKEN)
        except discord.errors.LoginFailure:
            print("Error: Invalid bot token provided. Please check your TOKEN.")
        except Exception as e:
            print(f"An unexpected error occurred while running the bot: {e}")
