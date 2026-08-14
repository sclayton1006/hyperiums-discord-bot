"""
==============================================================================
 Hyperiums Discord Bot
 Author:      Simon Clayton (Shamp) & Hyperiums Community
 Description: Discord bot for live player rankings, influence tracking, 
              planet lookup, and hyp-legacy API integration.

 NOTICE:
 This software is provided as-is. Unauthorized modification, tampering, 
 redistribution, or removal of author credits is strictly prohibited.
==============================================================================
"""

import os
import re
import ssl
import typing
import urllib.parse
import discord
from discord.ext import commands
import requests
from requests.adapters import HTTPAdapter
import urllib3

# Suppress insecure request warnings if SSL checks are bypassed
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================================================
# CONFIGURATION - UPDATE YOUR BOT TOKEN AND GAME NAME HERE
# ==============================================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
GAME_NAME = "Hyperiums17"                       # Game universe name (e.g. Hyperiums17, Hyperiums18)
BOT_SOURCE_TAG = "mybot"                        # Source identifier sent to Markus's API

# ==============================================================================
# CUSTOM SSL ADAPTER FOR LEGACY TLS/OPENSSL HANDSHAKES
# ==============================================================================
class LegacySSLAdapter(HTTPAdapter):
    """
    Forces OpenSSL in Linux/WSL environments to allow legacy security levels
    and DH key sizes (SECLEVEL=1) so requests to old endpoints do not fail.
    """
    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers('DEFAULT@SECLEVEL=1')
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)

# ==============================================================================
# BOT SETUP & INTENTS
# ==============================================================================
intents = discord.Intents.default()
intents.message_content = True  # Requires 'Message Content Intent' enabled in Discord Developer Portal
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

# ==============================================================================
# DATA DICTIONARY
# ==============================================================================

# Civilization Level Investment Values
CIV_LEVELS = {
    1: 0.0,
    2: 125000.00,
    3: 281250.00,
    4: 476562.50,
    5: 720703.13,
    6: 1025878.91,
    7: 1407348.63,
    8: 1884185.79,
    9: 2480232.24,
    10: 3225290.30,
    11: 4156612.87,
    12: 5320766.09,
    13: 6775957.61,
    14: 8594947.02,
    15: 10868683.77,
    16: 13710854.72,
    17: 17263568.39,
    18: 21704460.49,
    19: 27255575.62,
    20: 34194469.52,
    21: 42868086.90,
    22: 53710108.62,
    23: 67262635.78,
    24: 84203294.73,
    25: 105379118.41,
    26: 131848898.01,
    27: 164936122.51,
    28: 206295153.14,
    29: 257993941.42,
    30: 322617426.78,
    31: 403396783.47,
    32: 504370979.34,
    33: 630588724.18,
    34: 788360905.22,
    35: 985576131.53,
    36: 1232095164.41,
    37: 1540243955.51,
    38: 1925429944.39,
    39: 2406912430.48,
    40: 3008765538.11,
}

# ==============================================================================
# HELPER: MIRC TAG PARSERS
# ==============================================================================
def clean_mirc_tags_for_discord(text: str) -> str:
    """
    Translates hyp-legacy custom mIRC tags into clean Discord Markdown (used for !r).
    """
    text = re.sub(r'%MESSAGE%', '', text, flags=re.IGNORECASE)
    text = re.sub(r'%/color%', '', text)
    text = re.sub(r'%color%', '', text)
    text = re.sub(r'%green%', '', text)
    text = re.sub(r'%red%', '', text)
    
    # Convert %bold% wrappers to Discord **bold** Markdown
    text = text.replace('%bold%', '**').replace('%/bold%', '**')
    
    # Strip double spaces created by removed tags
    return re.sub(r' +', ' ', text).strip()


def clean_mirc_tags_to_ansi(text: str) -> str:
    """
    Translates hyp-legacy custom mIRC tags into Discord ANSI color codes (used for !p).
    Renders Green for positive changes (+X) and Red for negative changes (-X).
    """
    text = re.sub(r'%MESSAGE%', '', text, flags=re.IGNORECASE).strip()

    # Discord ANSI Code block escape sequences
    ANSI_BOLD   = "\u001b[1m"
    ANSI_GREEN  = "\u001b[1;32m"
    ANSI_RED    = "\u001b[1;31m"
    ANSI_RESET  = "\u001b[0m"

    # Replace mIRC color & bold tags with ANSI sequences
    text = text.replace("%color%%green%", ANSI_GREEN)
    text = text.replace("%color%%red%", ANSI_RED)
    text = text.replace("%/color%", ANSI_RESET)
    text = text.replace("%bold%", ANSI_BOLD)
    text = text.replace("%/bold%", ANSI_RESET)

    # Strip any unrecognized leftover tags
    text = re.sub(r'%/?[a-zA-Z0-9]+%', '', text)
    text = re.sub(r' +', ' ', text).strip()

    return text

# ==============================================================================
# HELP FILE
# ==============================================================================

@bot.command(name="help")
async def help_command(ctx):
    """Posts public help information in channel."""
    help_text = (
        "**🤖 Hyperiums Bot Commands**\n"
        "-------------------------------------\n"
		"`!slap [player/@user]` - Send a classic trout slap.\n"
        "`!r [player1] [player2] [player3] ...` - Check player rank, influence, and daily coloured delta.\n"
        "`!p [planet]` - Check planet stats (civ level, gov, race, coloured activity delta).\n"
		"`!d [planet1] [planet2]` - check the distance and flight time between two planets.\n"
        "`!ptop10` - Shows the top 10 planets in the game by activity.\n"
        "`!civ [x] [y]` - Shows the investment required to reach a specific civ level or to grow from one to the other. You can use a single value or two to calculate the difference.\n"
    )
    await ctx.send(help_text)

# ==============================================================================
# BOT COMMANDS
# ==============================================================================
@bot.command(name="r")
async def rank_check(ctx, *, raw_input: str = None):
    """
    Queries hyp-legacy API for live player rank stats.
    Takes only the first word from the input and strips everything else.
    
    Usage:
        !r Jacky (inactive ass)  -> Queries 'Jacky'
        !r Jacky                 -> Queries 'Jacky'
    """
    if not raw_input:
        await ctx.send("⚠️ Please specify a player name: `!r <playername>`")
        return

    # Extract ONLY the first full word and strip all surrounding whitespace
    target_player = raw_input.strip().split()[0]

    try:
        session = requests.Session()
        session.mount('https://', LegacySSLAdapter())
        session.mount('http://', LegacySSLAdapter())

        encoded_player = urllib.parse.quote(target_player)
        url = (
            f"https://www.hyp-legacy.com/data/hypbot/get.php"
            f"?command=rank&arg1={encoded_player}&source={BOT_SOURCE_TAG}&game={GAME_NAME}"
        )

        response = session.get(url, timeout=10, verify=False)

        if response.status_code != 200:
            await ctx.send(f"❌ Error fetching {target_player} (HTTP {response.status_code}).")
            return

        raw_data = response.text.strip()

        if not raw_data or "not found" in raw_data.lower():
            await ctx.send(f"❌ Player matching **{target_player}** was not found.")
            return

        # Clean mIRC tags to ANSI escape sequences
        formatted_msg = clean_mirc_tags_to_ansi(raw_data)
        await ctx.send(f"```ansi\n{formatted_msg}\n```")

    except Exception as e:
        await ctx.send(f"⚠️ Error fetching rank data: {e}")

@bot.command(name="p", aliases=["planet"])
async def planet_check(ctx, *planets: str):
    """
    Queries hyp-legacy API for live planet stats.
    Supports single or multiple planet lookups.
    Usage: 
      !p planet1
      !p planet1 planet2 planet3
    """
    if not planets:
        await ctx.send("⚠️ Please specify at least one planet name: `!p <planet1> [planet2] ...`")
        return

    results = []

    try:
        session = requests.Session()
        session.mount('https://', LegacySSLAdapter())
        session.mount('http://', LegacySSLAdapter())

        for target_planet in planets:
            planet_clean = target_planet.strip()
            encoded_planet = urllib.parse.quote(planet_clean)

            url = (
                f"https://www.hyp-legacy.com/data/hypbot/get.php"
                f"?command=planet&arg1={encoded_planet}&source={BOT_SOURCE_TAG}&game={GAME_NAME}"
            )

            response = session.get(url, timeout=10, verify=False)

            if response.status_code != 200:
                results.append(f"❌ Error fetching {planet_clean} (HTTP {response.status_code}).")
                continue

            raw_data = response.text.strip()

            if not raw_data or "not found" in raw_data.lower():
                results.append(f"❌ Planet matching {planet_clean} was not found.")
                continue

            # Clean mIRC tags (returns raw ANSI text without code block wrappers)
            formatted_line = clean_mirc_tags_to_ansi(raw_data)
            results.append(formatted_line)

        # Join all planet outputs with newlines and wrap in a single ANSI block
        combined_output = "\n".join(results)
        await ctx.send(f"```ansi\n{combined_output}\n```")

    except Exception as e:
        await ctx.send(f"⚠️ Error fetching planet data: {e}")

@bot.command(name="slap")
async def slap_user(ctx, *, target: str = None):
    """
    Classic mIRC slap command.
    - Strictly permits ONLY a single word/player name (blocks spaces, tabs, etc.).
    - Tags the member if @mentioned or matched case-insensitively.
    
    Usage:
      !slap titiz     -> Tags @Titiz if they are in the server
      !slap @Shamp    -> Tags @Shamp
      !slap Unknown   -> Plain text slap if player is not in the server
    """
    # 1. Check if an argument was provided
    if not target:
        await ctx.send("⚠️ Who do you want to slap? Usage: `!slap <name or @user>`")
        return

    target_clean = target.strip()

    # 2. Strict single-word check: Reject any whitespace (spaces, tabs, newlines)
    # \s matches spaces, \t (tabs), \n, \r, and other unicode whitespace
    if re.search(r'\s', target_clean) or len(target_clean.split()) > 1:
        await ctx.send("❌ **Invalid name:** Player names must be a single word with no spaces, tabs, or extra text.")
        return

    # Strip any leading '@' if typed manually (e.g. '@titiz')
    search_name = target_clean.lstrip("@").lower()
    matched_member = None

    # 3. Check direct @mentions first
    if ctx.message.mentions:
        matched_member = ctx.message.mentions[0]
    elif ctx.guild:
        # Case-insensitive check across username, server nickname, and global display name
        for member in ctx.guild.members:
            if (
                member.name.lower() == search_name
                or member.display_name.lower() == search_name
                or (member.global_name and member.global_name.lower() == search_name)
            ):
                matched_member = member
                break

    # 4. Format output
    if matched_member:
        target_display = matched_member.mention
    else:
        target_display = discord.utils.escape_markdown(target_clean.lstrip("@"))

    await ctx.send(f"*{ctx.author.display_name} slaps {target_display} around a bit with a large trout!* 🐟")
	
@bot.command(name="ptop10")
async def top10_planets(ctx):
    """
    Fetches the top 10 activity planets from the game.
    Usage: !ptop10
    """
    url = (
        f"https://www.hyp-legacy.com/data/hypbot/get.php"
        f"?command=ptop10&source={BOT_SOURCE_TAG}&game={GAME_NAME}"
    )

    try:
        session = requests.Session()
        session.mount('https://', LegacySSLAdapter())
        session.mount('http://', LegacySSLAdapter())

        response = session.get(url, timeout=10, verify=False)

        if response.status_code != 200:
            await ctx.send(f"❌ Error reaching hyp-legacy API (HTTP {response.status_code}).")
            return

        raw_data = response.text.strip()

        if not raw_data:
            await ctx.send("❌ No data returned from the API.")
            return

        # Translate mIRC tags to ANSI colors and send in an ANSI block
        formatted_msg = clean_mirc_tags_to_ansi(raw_data)
        await ctx.send(f"```ansi\n{formatted_msg}\n```")

    except Exception as e:
        await ctx.send(f"⚠️ Error fetching top 10 planets: {e}")

@bot.command(name="civ")
async def civ_calc(ctx, *args: int):
    """Calculates investment cost for civ levels.

    Usage:
        !civ 28      -> Cost to reach Civ 28
        !civ 10 15   -> Cost to go from Civ 10 to Civ 15
    """
    if not args or len(args) > 2:
        await ctx.send("⚠️ Usage: `!civ <level>` or `!civ <start_level> <target_level>`")
        return

    # Check that inputs fall within valid 1-40 range
    for level in args:
        if level not in CIV_LEVELS:
            await ctx.send("❌ Please enter a valid civ level between 1 and 40.")
            return

    # Case 1: Single Argument (!civ 28)
    if len(args) == 1:
        target = args[0]
        val = CIV_LEVELS[target]
        formatted_val = f"{val:,.2f}"
        await ctx.send(f"You need to invest **{formatted_val}** to reach civ **{target}**.")

    # Case 2: Two Arguments (!civ 10 15)
    elif len(args) == 2:
        start, end = args[0], args[1]
        
        if start >= end:
            await ctx.send("⚠️ The starting civ level must be smaller than the target level.")
            return

        diff = CIV_LEVELS[end] - CIV_LEVELS[start]
        formatted_diff = f"{diff:,.2f}"
        await ctx.send(f"You need **{formatted_diff}** to move from civ **{start}** to civ **{end}**.")

@bot.command(name="d", aliases=["distance"])
async def calculate_distance(ctx, planet1: str = None, planet2: str = None):
    """
    Calculates the distance and flight time between two planets.
    Usage:
        !d planet1 planet2
        !distance planet1 planet2
    """
    # 1. Validate that both planet names were supplied
    if not planet1 or not planet2:
        await ctx.send("⚠️ Please provide both planet names: `!d <planet1> <planet2>` or `!distance <planet1> <planet2>`")
        return

    # Clean and URL-encode inputs
    p1_clean = urllib.parse.quote(planet1.strip())
    p2_clean = urllib.parse.quote(planet2.strip())

    # 2. Build the hyp-legacy API endpoint URL
    url = (
        f"https://www.hyp-legacy.com/data/hypbot/get.php"
        f"?command=distance&arg1={p1_clean}&arg2={p2_clean}&source={BOT_SOURCE_TAG}&game={GAME_NAME}"
    )

    try:
        session = requests.Session()
        session.mount('https://', LegacySSLAdapter())
        session.mount('http://', LegacySSLAdapter())

        response = session.get(url, timeout=10, verify=False)

        if response.status_code != 200:
            await ctx.send(f"❌ Error reaching hyp-legacy API (HTTP {response.status_code}).")
            return

        raw_data = response.text.strip()

        # Handle empty responses or errors from the API
        if not raw_data:
            await ctx.send("❌ No data returned from the API.")
            return
        
        if "not found" in raw_data.lower() or "error" in raw_data.lower():
            await ctx.send(f"❌ Could not calculate distance: {raw_data.replace('%MESSAGE%', '').strip()}")
            return

        # 3. Clean mIRC tags to ANSI escape sequences and post wrapped in ANSI block
        formatted_msg = clean_mirc_tags_to_ansi(raw_data)
        await ctx.send(f"```ansi\n{formatted_msg}\n```")

    except Exception as e:
        await ctx.send(f"⚠️ Error fetching distance data: {e}")

# ==============================================================================
# BOT EVENTS & STARTUP
# ==============================================================================
@bot.event
async def on_ready():
    print(f"Logged in successfully as {bot.user.name} ({bot.user.id})")
    print(f"Active Game Universe: {GAME_NAME}")
    print("Ready to process !r and !p commands!")

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
