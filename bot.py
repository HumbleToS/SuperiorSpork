import asyncio
import logging
import logging.handlers
import sys
from pathlib import Path

import asyncpg
import discord
from aiohttp import ClientSession
from discord import Activity, ActivityType, Status
from discord.ext import commands

import config
from exts import EXTENSIONS


def setup_logging() -> None:
    # Logging credit: Fretgfr

    log_fmt = logging.Formatter(
        fmt="%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(log_fmt)

    max_bytes = 4 * 1024 * 1024  # 4 MB
    rfh = logging.handlers.RotatingFileHandler("logs/superior-spork.log", maxBytes=max_bytes, backupCount=10)
    rfh.setLevel(logging.DEBUG)
    rfh.setFormatter(log_fmt)

    HANDLER = sh if config.TESTING else rfh

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(HANDLER)


_logger = logging.getLogger(__name__)


class Spork(commands.Bot):
    def __init__(self, pool: asyncpg.Pool, session: ClientSession) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.PREFIX),
            intents=discord.Intents(
                emojis=True,
                guilds=True,
                invites=True,
                members=True,
                message_content=True,
                messages=True,
                presences=True,
                reactions=True,
                voice_states=True,
            ),
            status=Status.dnd,
            activity=Activity(type=ActivityType.watching, name=f"my bad code | {config.PREFIX}help"),
            case_insensitive=True,
        )
        self.start_time = discord.utils.utcnow()
        self.pool = pool
        self.session = session

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext.name)
            _logger.info("Loaded %sextension: %s", "module " if ext.ispkg else "", ext.name)

        with Path("./database/schema.sql").open() as file:
            sql = file.read()
            await self.pool.execute(sql)

        await self.load_extension("jishaku")
        _logger.info("Extension: jishaku loaded successfully")

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        await self.process_commands(after)


async def main() -> None:
    setup_logging()
    async with ClientSession() as session, asyncpg.create_pool(config.DB_URL, command_timeout=30) as pool:
        async with Spork(pool=pool, session=session) as bot:
            await bot.start(config.TOKEN, reconnect=True)


if __name__ == "__main__":
    asyncio.run(main())
