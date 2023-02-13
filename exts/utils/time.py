from datetime import timedelta


def how_old(time: timedelta):
    days, hours = time.days, time.seconds // 3600
    return f"{days:,} days and {hours:,} hours old"
