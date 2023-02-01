import asyncio
import json
import logging
import logging.handlers
import os
import pathlib
import sys

import discord
from discord import Activity, ActivityType, Status
from discord.ext import commands

CONFIG_FILENAME = "config.json"
current_working_dir = pathlib.Path(__file__).parent
config_path = current_working_dir / CONFIG_FILENAME

with open(config_path) as fp:
    config = json.load(fp)


def setup_logging():
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

    HANDLER = sh if config.get("testing") else rfh

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(HANDLER)


_logger = logging.getLogger(__name__)


class Spork(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=",,",
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
            activity=Activity(type=ActivityType.watching, name="my bad code | ,,help"),
            case_insensitive=True,
        )
        self.start_time = discord.utils.utcnow()

    async def setup_hook(self) -> None:
        # Loading Extensions credit: https://github.com/AbstractUmbra/
        for file in sorted(pathlib.Path("exts").glob("**/[!_]*.py")):
            if (file.is_dir() and file.name.startswith("util")) or (
                file.parent.is_dir() and file.parent.name.startswith("util")
            ):
                continue

            ext = ".".join(file.parts).removesuffix(".py")
            try:
                await self.load_extension(ext)
                _logger.info("Extension: %s loaded successfully", ext)
            except Exception as error:
                _logger.exception("Extension: %s failed to load\n%s", ext, error)

        os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
        os.environ["JISHAKU_NO_DM_TRACEBACK"] = "True"

        await self.load_extension("jishaku")
        _logger.info("Extension: jishaku loaded successfully")

    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        await self.process_commands(after)


async def main():
    setup_logging()
    bot = Spork()
    await bot.start(config.get("token"), reconnect=True)


if __name__ == "__main__":
    asyncio.run(main())
