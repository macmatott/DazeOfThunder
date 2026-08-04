"""
Discord bot entrypoint.

Run with (from discord-bot/): python -m bot.main

Commands live in bot/commands/ and get registered here as they're built.
The bot reads from Supabase and posts to Discord — it does not calculate
points or standings itself. Nothing is wired up yet — this just confirms
the bot can connect.
"""

import logging

import discord
from discord.ext import commands

from config.settings import settings

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("formula_fantasy")

intents = discord.Intents.default()
intents.message_content = True  # needed to read attached CSV files on commands

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready() -> None:
    logger.info("Formula Fantasy bot connected as %s", bot.user)


def main() -> None:
    if not settings.discord_bot_token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN is not set. Copy .env.example to .env and fill it in."
        )
    bot.run(settings.discord_bot_token)


if __name__ == "__main__":
    main()
