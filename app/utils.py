def progress_bar(percent: float, length: int = 10) -> str:
    filled = int(percent / 100 * length)
    empty = length - filled
    return "▓" * filled + "░" * empty


def format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}д {hours}ч"
    elif hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"


def fmt_mb(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.1f}GB"
    return f"{mb:.0f}MB"
