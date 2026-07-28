import asyncio
import logging
import logging.handlers
import signal
import sys
from pathlib import Path

import asyncpg
import discord
from aiohttp import ClientSession
from discord import Activity, ActivityType, Status
from discord.ext import commands

import config
from exts import EXTENSIONS
from exts.utils.settings import GuildSettings


def setup_logging() -> None:
    # Logging credit: Fretgfr

    log_fmt = logging.Formatter(
        fmt="%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(log_fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(sh)

    if not config.TESTING:
        Path("logs").mkdir(exist_ok=True)
        max_bytes = 4 * 1024 * 1024  # 4 MB
        rfh = logging.handlers.RotatingFileHandler("logs/superior-spork.log", maxBytes=max_bytes, backupCount=10)
        rfh.setLevel(logging.DEBUG)
        rfh.setFormatter(log_fmt)
        root_logger.addHandler(rfh)


_logger = logging.getLogger(__name__)


class Spork(commands.Bot):
    def __init__(self, pool: asyncpg.Pool, session: ClientSession) -> None:
        super().__init__(
            command_prefix=get_prefix,
            intents=discord.Intents(
                guilds=True,
                members=True,  # privileged: member lists, joined_at and mutual guilds in whois/serverinfo
                message_content=True,  # privileged: prefix commands and the cleanup prefix check
                messages=True,
                presences=True,  # privileged: spotify and status counts in whois/serverinfo
            ),
            status=Status.dnd,
            activity=Activity(type=ActivityType.watching, name=f"my bad code | {config.PREFIX}help"),
            case_insensitive=True,
        )
        self.start_time = discord.utils.utcnow()
        self.pool = pool
        self.session = session
        self.settings = GuildSettings(pool)

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext.name)
            _logger.info("Loaded %sextension: %s", "module " if ext.ispkg else "", ext.name)

        sql = await asyncio.to_thread(Path("./database/schema.sql").read_text)
        await self.pool.execute(sql)

        await self.load_extension("jishaku")
        _logger.info("Extension: jishaku loaded successfully")

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        # edits also fire when discord unfurls an embed; only re-run on real content changes
        if before.content != after.content:
            await self.process_commands(after)


async def get_prefix(bot: Spork, message: discord.Message) -> list[str]:
    prefix = config.PREFIX
    if message.guild:
        prefix = await bot.settings.get_prefix(message.guild.id) or config.PREFIX
    return commands.when_mentioned_or(prefix)(bot, message)


async def main() -> None:
    setup_logging()
    async with ClientSession() as session, asyncpg.create_pool(config.DB_URL, command_timeout=30) as pool:
        async with Spork(pool=pool, session=session) as bot:
            # docker stop sends SIGTERM, which Client.run/start does not handle
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.close()))
            await bot.start(config.TOKEN, reconnect=True)


if __name__ == "__main__":
    asyncio.run(main())
