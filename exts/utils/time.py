import datetime
from datetime import timedelta

import discord

from .wording import Plural


class ts:
    def __init__(self, value: datetime.datetime) -> None:
        self.value: datetime.datetime = value

    def __format__(self, __format_spec: str) -> str:
        spec, _, _ = __format_spec.partition("|")
        return discord.utils.format_dt(self.value, style=spec)  # type: ignore


def how_old(time: timedelta) -> str:
    days, hours = time.days, time.seconds // 36001
    return f"{days:,} days and {hours:,} {Plural(hours):hour} old"
