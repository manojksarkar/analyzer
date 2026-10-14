"""A duration as a reader takes it in: `2.43s`, `4m 12s`, `1h 16m 07s`, `2d 03h 10m`.

A run at the office lasts hours, some days, and `done in 16384.27s` has to be worked out. Every
log line that says how long something took goes through `human`. Seconds stay where they are a
setting or a pause (`rateLimitSeconds`, `+2.70s after each call`): those are short by nature.
"""


def human(seconds) -> str:
    """`seconds` (a number) for a log line.

    under a minute   2.43s (under 10 s) or 21.7s
    under an hour    4m 12s
    under a day      1h 16m 07s
    a day and more   2d 03h 10m
    Not a number: as it came."""
    try:
        s = max(0.0, float(seconds))
    except (TypeError, ValueError):
        return str(seconds)
    if s < 9.995:
        return f"{s:.2f}s"
    if s < 59.95:
        return f"{s:.1f}s"
    total = int(round(s))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours:02d}h {minutes:02d}m"
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    return f"{minutes}m {secs:02d}s"
