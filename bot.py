import asyncio
import json
import logging
import logging.handlers
import os
import pathlib
import sys

import discord
from discord.ext import commands

CONFIG_FILENAME = "config.json"
current_working_dir = pathlib.Path(__file__).parent
config_path = current_working_dir / CONFIG_FILENAME

with open(config_path) as fp:
    config = json.load(fp)

# Logging Credit: Fretgfr

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

if config.get("testing"):
    HANDLER = sh
else:
    HANDLER = rfh

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(HANDLER)

_logger = logging.getLogger(__name__)


class Spork(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=",",
            intents=discord.Intents(),
            case_insensitive=True,
        )

    async def setup_hook(self):
        os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
        os.environ["JISHAKU_NO_DM_TRACEBACK"] = "True"

        await self.load_extension("jishaku")
        _logger.info("Extension: Loaded jishaku")

    async def on_message_edit(self, before, after):
        await self.process_commands(after)


async def main():
    bot = Spork()
    await bot.start(config.get("token"), reconnect=True)


if __name__ == "__main__":
    asyncio.run(main())
