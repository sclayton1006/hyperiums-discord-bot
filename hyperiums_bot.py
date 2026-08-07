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
bot = commands.Bot(command_prefix="!", intents=intents)
bot.remove_command("help")

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
# BOT COMMANDS
# ==============================================================================
@bot.command(name="r")
async def rank_check(ctx, *players: str):
    """
    Queries hyp-legacy API for player rank stats.
    Supports multi-player arguments: !r shamp fifi
    """
    if not players:
        await ctx.send("⚠️ Please specify at least one player name: !r <player1> [player2] ...")
        return

    # Pass all captured player arguments into the URI
    # Option A: Single request if passing as separate query args (e.g. arg1=shamp&arg2=fifi)
    query_args = "&".join([f"arg{i+1}={urllib.parse.quote(p.strip())}" for i, p in enumerate(players)])
    url = f"https://www.hyp-legacy.com/data/hypbot/get.php?command=rank&{query_args}&source={BOT_SOURCE_TAG}&game={GAME_NAME}"

    try:
        session = requests.Session()
        session.mount('https://', LegacySSLAdapter())
        session.mount('http://', LegacySSLAdapter())

        response = session.get(url, timeout=10, verify=False)
        if response.status_code != 200:
            await ctx.send(f"❌ Error reaching hyp-legacy API (HTTP {response.status_code}).")
            return

        raw_data = response.text.strip()
        if not raw_data or "not found" in raw_data.lower():
            await ctx.send(f"❌ Player(s) not found.")
            return

        # Parse the raw multiline response into Discord ANSI formatting
        formatted_msg = clean_mirc_tags_to_ansi(raw_data)
        
        # Output inside an ANSI code block wrapper
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
async def slap_user(ctx, target: typing.Union[discord.Member, str] = None):
    """
    Classic mIRC slap command. 
    Tags the member if an @mention is used, otherwise uses plain text.
    
    Usage: 
      !slap Shamp    -> Plain text (no ping)
      !slap @Shamp   -> Discord mention (pings user)
    """
    if not target:
        await ctx.send("Who do you want to slap? Usage: `!slap <name or @user>`")
        return

    if isinstance(target, discord.Member):
        target_display = target.mention
    else:
        target_display = target.lstrip("@").strip()

    await ctx.send(f"*{ctx.author.display_name} slaps {target_display} around a bit with a large trout!* 🐟")


@bot.command(name="help")
async def help_command(ctx):
    """Posts public help information in channel."""
    help_text = (
        "**🤖 Hyperiums Bot Commands**\n"
        "-------------------------------------\n"
        "`!r [player1] [player2] [player3] ...` - Check player rank, influence, and daily coloured delta.\n"
        "`!p [planet]` - Check planet stats (civ level, gov, race, coloured activity delta).\n"
        "`!ptop10` - Shows the top 10 planets in the game by activity.\n"
	"`!slap [player/@user]` - Send a classic trout slap.\n"
    )
    await ctx.send(help_text)

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
