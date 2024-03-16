from datetime import timedelta

from .wording import plural


def how_old(time: timedelta) -> str:
    days, hours = time.days, time.seconds // 3600
    return f"{days:,} days and {hours:,} {plural('hour', hours)} old"
