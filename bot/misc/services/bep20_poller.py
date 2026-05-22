"""
BEP20 (USDT on BSC) deposit poller.

Strategy
--------
Direct on-chain deposits without a payment gateway:
- Admin sets BEP20_WALLET_ADDRESS (their receiving wallet) + BSCSCAN_API_KEY.
- When a user starts a top-up, we generate a per-payment unique "fingerprint"
  amount (e.g. 5.0137 instead of 5) and stash a pending `Payments` row with
  external_id = "bep20:<expected_amount>:<nonce>".
- This poller periodically queries BscScan token-tx history for the wallet,
  filters incoming USDT transfers, and tries to match each pending payment by
  the exact fingerprint amount.
- On match, the payment is credited via `process_payment_with_referral` and
  the pending row's external_id is updated to the actual tx hash, so the
  unique (provider, external_id) constraint blocks double-crediting.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import aiohttp
from sqlalchemy import select, update

from bot.database import Database
from bot.database.models.main import Payments
from bot.misc.env import EnvKeys

logger = logging.getLogger(__name__)

USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"
USDT_DECIMALS = 18
MATCH_TOLERANCE = Decimal("0.0001")
BSC_CHAIN_ID = 56
ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"


def parse_bep20_external_id(external_id: str) -> tuple[Decimal, str] | None:
    """Returns (expected_amount, nonce) or None if not a pending BEP20 ext_id."""
    if not external_id or not external_id.startswith("bep20:"):
        return None
    parts = external_id.split(":")
    if len(parts) < 3:
        return None
    try:
        return Decimal(parts[1]), parts[2]
    except Exception:
        return None


class Bep20Poller:
    """Periodic poller for incoming USDT BEP20 deposits."""

    def __init__(self, bot):
        self.bot = bot
        self.running = False
        self._task: asyncio.Task | None = None
        self._wallet = (EnvKeys.BEP20_WALLET_ADDRESS or "").strip().lower()
        self._api_key = (EnvKeys.BSCSCAN_API_KEY or "").strip()
        self._interval = max(20, int(EnvKeys.BEP20_POLL_INTERVAL or 45))
        self._ttl = max(300, int(EnvKeys.BEP20_DEPOSIT_TTL or 3600))

    async def start(self):
        if not self._wallet or not self._api_key:
            logger.info("BEP20 poller disabled (BEP20_WALLET_ADDRESS or BSCSCAN_API_KEY not set)")
            return
        logger.info(
            f"Starting BEP20 poller: wallet={self._wallet[:10]}..., interval={self._interval}s"
        )
        self.running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("BEP20 poller stopped")

    async def _loop(self):
        while self.running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"BEP20 poller tick failed: {e}")
            await asyncio.sleep(self._interval)

    async def _fetch_recent_txs(self) -> list[dict]:
        """Fetch last ~100 USDT-BEP20 transfers involving the receiving wallet."""
        params = {
            "chainid": str(BSC_CHAIN_ID),
            "module": "account",
            "action": "tokentx",
            "contractaddress": USDT_BEP20_CONTRACT,
            "address": self._wallet,
            "page": "1",
            "offset": "100",
            "sort": "desc",
            "apikey": self._api_key,
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(ETHERSCAN_V2_URL, params=params) as resp:
                data = await resp.json(content_type=None)
        if str(data.get("status")) != "1":
            msg = (data.get("message") or "").lower()
            if "no transactions" in msg:
                return []
            logger.debug(f"BscScan returned non-OK: {data}")
            return []
        return data.get("result") or []

    async def _tick(self):
        async with Database().session() as s:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._ttl)
            result = await s.execute(
                select(Payments).where(
                    Payments.provider == "bep20",
                    Payments.status == "pending",
                    Payments.created_at >= cutoff,
                )
            )
            pending = list(result.scalars())
        if not pending:
            return

        try:
            txs = await self._fetch_recent_txs()
        except Exception as e:
            logger.warning(f"BscScan fetch failed: {e}")
            return
        if not txs:
            return

        # Only incoming transfers to our wallet that succeeded
        incoming = [
            tx for tx in txs
            if (tx.get("to") or "").lower() == self._wallet
        ]

        # Index by Decimal value for fast match
        for payment in pending:
            parsed = parse_bep20_external_id(payment.external_id or "")
            if not parsed:
                continue
            expected, _nonce = parsed
            for tx in incoming:
                try:
                    raw_value = Decimal(tx.get("value") or "0")
                    actual = raw_value / Decimal(10**USDT_DECIMALS)
                except Exception:
                    continue
                if abs(actual - expected) > MATCH_TOLERANCE:
                    continue
                tx_hash = tx.get("hash") or ""
                if not tx_hash:
                    continue
                # Guard against re-crediting the same tx (unique constraint helps too)
                async with Database().session() as s:
                    dup = (await s.execute(
                        select(Payments).where(
                            Payments.provider == "bep20",
                            Payments.external_id == tx_hash,
                        )
                    )).scalars().first()
                if dup:
                    continue
                await self._credit(payment, tx_hash, actual)
                break

    async def _credit(self, payment: Payments, tx_hash: str, actual_amount: Decimal):
        """Credit user balance and finalize the payment."""
        from bot.database.methods.transactions import process_payment_with_referral
        from bot.misc.services.notifications import notify_new_deposit
        from bot.database.methods.audit import log_audit

        user_id = payment.user_id
        if user_id is None:
            return

        # Bind external_id to tx_hash first (idempotent claim).
        async with Database().session() as s:
            try:
                upd = await s.execute(
                    update(Payments)
                    .where(
                        Payments.id == payment.id,
                        Payments.status == "pending",
                    )
                    .values(external_id=tx_hash, amount=actual_amount.quantize(Decimal("0.01")))
                )
                await s.commit()
                if upd.rowcount == 0:
                    return
            except Exception as e:
                await s.rollback()
                logger.warning(f"BEP20 claim failed for payment={payment.id}: {e}")
                return

        ok, msg = await process_payment_with_referral(
            user_id=user_id,
            amount=actual_amount.quantize(Decimal("0.01")),
            provider="bep20",
            external_id=tx_hash,
            referral_percent=int(EnvKeys.REFERRAL_PERCENT or 0),
        )
        if not ok:
            logger.warning(f"BEP20 credit failed ({msg}) for user={user_id} tx={tx_hash}")
            return

        await log_audit(
            "bep20_deposit_credited",
            user_id=user_id,
            resource_type="Payment",
            resource_id=tx_hash,
            details=f"amount={actual_amount} USDT",
        )

        # Notifications
        try:
            user_name = "user"
            try:
                chat = await self.bot.get_chat(user_id)
                user_name = chat.first_name or chat.username or "user"
            except Exception:
                pass
            await notify_new_deposit(self.bot, float(actual_amount), "bep20", user_name, user_id)
            try:
                await self.bot.send_message(
                    user_id,
                    f"✅ <b>BEP20 deposit received!</b>\n\n"
                    f"💰 <b>Amount:</b> {actual_amount} USDT\n"
                    f"🔗 <b>TX:</b> <code>{tx_hash}</code>\n\n"
                    f"Your balance has been credited.",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"BEP20 deposit notification failed: {e}")
