"""Admin approve/reject for Binance UID transfers."""
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import select, update

from bot.database import Database
from bot.database.models.main import Payments
from bot.database.methods.transactions import process_payment_with_referral
from bot.database.methods.audit import log_audit
from bot.misc.env import EnvKeys
from bot.misc.services.notifications import notify_new_deposit
from bot.logger_mesh import logger

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id == int(EnvKeys.OWNER_ID)


@router.callback_query(F.data.startswith("binance_ok:"))
async def approve_binance(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer("Not authorized", show_alert=True)
        return
    try:
        payment_id = int(call.data.split(":", 1)[1])
    except Exception:
        await call.answer("Invalid payload", show_alert=True)
        return

    async with Database().session() as s:
        p = (await s.execute(
            select(Payments).where(Payments.id == payment_id).with_for_update()
        )).scalars().first()
        if not p:
            await call.answer("Payment not found", show_alert=True)
            return
        if p.status != "pending":
            await call.answer(f"Already {p.status}", show_alert=True)
            return
        # Claim with id in external_id to keep uniqueness if anyone retries
        try:
            await s.execute(
                update(Payments).where(Payments.id == payment_id).values(status="processing")
            )
            await s.commit()
        except Exception as e:
            await s.rollback()
            await call.answer(f"DB error: {e}", show_alert=True)
            return
        user_id = p.user_id
        amount = Decimal(p.amount)
        external_id = p.external_id

    ok, msg = await process_payment_with_referral(
        user_id=user_id,
        amount=amount,
        provider="binance_uid",
        external_id=external_id,
        referral_percent=int(EnvKeys.REFERRAL_PERCENT or 0),
    )
    if not ok:
        async with Database().session() as s:
            await s.execute(update(Payments).where(Payments.id == payment_id).values(status="pending"))
            await s.commit()
        await call.answer(f"Credit failed: {msg}", show_alert=True)
        return

    await log_audit(
        "binance_uid_approved",
        user_id=user_id,
        resource_type="Payment",
        resource_id=external_id,
        details=f"approved_by={call.from_user.id}, amount={amount}",
    )

    try:
        user_chat = await call.bot.get_chat(user_id)
        user_name = user_chat.first_name or user_chat.username or "user"
    except Exception:
        user_name = "user"
    await notify_new_deposit(call.bot, float(amount), "binance_uid", user_name, user_id)

    try:
        await call.bot.send_message(
            user_id,
            f"✅ <b>Binance transfer approved!</b>\n\n"
            f"💰 <b>Amount:</b> {amount} {EnvKeys.PAY_CURRENCY}\n\n"
            f"Your balance has been credited.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Binance approval DM failed: {e}")

    await call.message.edit_text(
        (call.message.html_text or "") + f"\n\n✅ <b>APPROVED</b> by {call.from_user.first_name}",
        parse_mode="HTML",
    )
    await call.answer("Approved")


@router.callback_query(F.data.startswith("binance_no:"))
async def reject_binance(call: CallbackQuery):
    if not _is_admin(call.from_user.id):
        await call.answer("Not authorized", show_alert=True)
        return
    try:
        payment_id = int(call.data.split(":", 1)[1])
    except Exception:
        await call.answer("Invalid payload", show_alert=True)
        return

    async with Database().session() as s:
        p = (await s.execute(
            select(Payments).where(Payments.id == payment_id).with_for_update()
        )).scalars().first()
        if not p:
            await call.answer("Not found", show_alert=True)
            return
        if p.status != "pending":
            await call.answer(f"Already {p.status}", show_alert=True)
            return
        await s.execute(update(Payments).where(Payments.id == payment_id).values(status="rejected"))
        await s.commit()
        user_id = p.user_id
        external_id = p.external_id

    await log_audit(
        "binance_uid_rejected",
        user_id=user_id,
        resource_type="Payment",
        resource_id=external_id,
        details=f"rejected_by={call.from_user.id}",
    )

    try:
        await call.bot.send_message(
            user_id,
            f"❌ <b>Binance transfer rejected</b>\n\n"
            f"Order ID: <code>{(external_id or '').replace('binance_uid:', '')}</code>\n\n"
            f"If you believe this is a mistake, please contact support.",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.warning(f"Binance rejection DM failed: {e}")

    await call.message.edit_text(
        (call.message.html_text or "") + f"\n\n❌ <b>REJECTED</b> by {call.from_user.first_name}",
        parse_mode="HTML",
    )
    await call.answer("Rejected")
