import logging
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.misc.env import EnvKeys

logger = logging.getLogger(__name__)


def _mask_username(username: str) -> str:
    """Mask username: show first char, stars, last char. e.g. 'hussein' → 'h****n'"""
    if not username:
        return "***"
    if len(username) <= 2:
        return username[0] + "*"
    return username[0] + "*" * (len(username) - 2) + username[-1]


def _open_app_keyboard() -> Optional[InlineKeyboardMarkup]:
    """Returns inline keyboard with Open App button if MINI_APP_URL is set."""
    url = EnvKeys.MINI_APP_URL
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛍️ Open App", url=url)
    ]])


async def _send_safe(bot: Bot, chat_id: str | int, text: str, keyboard: Optional[InlineKeyboardMarkup] = None):
    """Send a message silently, swallowing all errors so notifications never crash the bot."""
    try:
        await bot.send_message(
            chat_id=int(chat_id),
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_notification=True,
        )
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning(f"Notification send failed to {chat_id}: {e}")
    except Exception as e:
        logger.warning(f"Notification send error to {chat_id}: {e}")


async def notify_new_stock(
    bot: Bot,
    item_name: str,
    added_qty: int | str,
    price: float,
    category: str = "",
):
    """
    Send new-stock notification to NOTIFY_CHANNEL_ID.
    qty can be an int count or '∞' for infinite items.
    """
    channel_id = EnvKeys.NOTIFY_CHANNEL_ID
    if not channel_id:
        return

    qty_str = str(added_qty) if added_qty != 0 else "∞"
    price_str = f"{price:.2f}" if isinstance(price, float) else str(price)
    currency = EnvKeys.PAY_CURRENCY

    lines = [
        "🎁 <b>New Stock Available!</b>",
        f"🏷️ <b>Product:</b> {item_name}",
    ]
    if category:
        lines.append(f"📂 <b>Category:</b> {category}")
    lines += [
        f"📦 <b>Quantity:</b> {qty_str}",
        f"💰 <b>Price:</b> {price_str} {currency}",
    ]

    await _send_safe(bot, channel_id, "\n".join(lines), _open_app_keyboard())


async def notify_new_purchase(
    bot: Bot,
    item_name: str,
    price: float,
    buyer_name: str,
    buyer_id: int,
):
    """
    Send purchase notification to NOTIFY_GROUP_ID.
    Buyer name/id is masked for privacy.
    """
    group_id = EnvKeys.NOTIFY_GROUP_ID
    if not group_id:
        return

    masked = _mask_username(buyer_name)
    currency = EnvKeys.PAY_CURRENCY
    price_str = f"{price:.2f}" if isinstance(price, float) else str(price)

    lines = [
        "🛒 <b>New Purchase!</b>",
        f"🏷️ <b>Product:</b> {item_name}",
        f"💰 <b>Price:</b> {price_str} {currency}",
        f"👤 <b>Buyer:</b> {masked}",
    ]

    await _send_safe(bot, group_id, "\n".join(lines), _open_app_keyboard())


async def notify_new_deposit(
    bot: Bot,
    amount: float,
    method: str,
    user_name: str,
    user_id: int,
):
    """
    Send deposit notification to NOTIFY_GROUP_ID.
    User name is masked for privacy.
    """
    group_id = EnvKeys.NOTIFY_GROUP_ID
    if not group_id:
        return

    masked = _mask_username(user_name)
    currency = EnvKeys.PAY_CURRENCY
    amount_str = f"{amount:.2f}" if isinstance(amount, float) else str(amount)
    method_display = {
        "cryptopay": "💎 CryptoPay",
        "nowpayments": "🔗 NowPayments",
        "stars": "⭐ Telegram Stars",
        "telegram": "💸 Telegram Pay",
    }.get(method, method)

    lines = [
        "💳 <b>New Deposit!</b>",
        f"💰 <b>Amount:</b> {amount_str} {currency}",
        f"🏦 <b>Method:</b> {method_display}",
        f"👤 <b>User:</b> {masked}",
    ]

    await _send_safe(bot, group_id, "\n".join(lines), _open_app_keyboard())
