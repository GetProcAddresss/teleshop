from typing import Optional

_bot = None


def set_bot(bot) -> None:
    global _bot
    _bot = bot


def get_bot() -> Optional[object]:
    return _bot
