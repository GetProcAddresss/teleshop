import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import aiohttp

from bot.misc.env import EnvKeys

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.nowpayments.io/v1"
_SANDBOX_URL = "https://api-sandbox.nowpayments.io/v1"


class NowPaymentsAPIError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"NowPayments Error [{code}]: {message}")


class _CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._state = "closed"

    @property
    def is_open(self) -> bool:
        if self._state == "open":
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = "closed"
                self._failure_count = 0
                return False
            return True
        return False

    def record_success(self):
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"


_nowpayments_circuit_breaker = _CircuitBreaker(failure_threshold=5, recovery_timeout=60)


class NowPaymentsAPI:
    """
    Async client for NowPayments.io API.
    Supports payment creation, status polling, and IPN signature verification.
    """

    _timeout = aiohttp.ClientTimeout(total=30)
    _session: Optional[aiohttp.ClientSession] = None

    def __init__(self):
        self.api_key = EnvKeys.NOWPAYMENTS_API_KEY
        self.ipn_secret = EnvKeys.NOWPAYMENTS_IPN_SECRET
        self.base_url = _BASE_URL
        self.circuit_breaker = _nowpayments_circuit_breaker

    @classmethod
    def _get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession(timeout=cls._timeout)
        return cls._session

    @classmethod
    async def close_session(cls):
        if cls._session and not cls._session.closed:
            await cls._session.close()
            cls._session = None

    @property
    def _headers(self) -> dict:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, payload: dict = None, params: dict = None) -> dict:
        if self.circuit_breaker.is_open:
            raise NowPaymentsAPIError(503, "NowPayments API temporarily unavailable")

        url = f"{self.base_url}/{path.lstrip('/')}"
        session = self._get_session()

        try:
            if method.upper() == "GET":
                async with session.get(url, headers=self._headers, params=params) as resp:
                    text = await resp.text()
                    data = json.loads(text)
                    if resp.status >= 400:
                        msg = data.get("message") or data.get("error") or text[:200]
                        self.circuit_breaker.record_failure()
                        raise NowPaymentsAPIError(resp.status, msg)
            else:
                async with session.post(url, headers=self._headers, json=payload) as resp:
                    text = await resp.text()
                    data = json.loads(text)
                    if resp.status >= 400:
                        msg = data.get("message") or data.get("error") or text[:200]
                        self.circuit_breaker.record_failure()
                        raise NowPaymentsAPIError(resp.status, msg)
        except NowPaymentsAPIError:
            raise
        except Exception as e:
            self.circuit_breaker.record_failure()
            raise NowPaymentsAPIError(0, str(e))

        self.circuit_breaker.record_success()
        return data

    async def get_status(self) -> bool:
        """Returns True if NowPayments API is reachable and operational."""
        try:
            data = await self._request("GET", "/status")
            return data.get("message") == "OK"
        except Exception:
            return False

    async def get_minimum_payment_amount(self, currency_from: str, currency_to: str = "usdttrc20") -> float:
        """Fetch the minimum allowed payment amount for a currency pair (in pay currency units)."""
        data = await self._request("GET", "/min-amount", params={
            "currency_from": currency_from.lower(),
            "currency_to": currency_to.lower(),
        })
        return float(data.get("min_amount", 0))

    async def get_estimate(self, amount: float, currency_from: str, currency_to: str) -> float:
        """Estimate how much `currency_to` you receive for `amount` of `currency_from`."""
        data = await self._request("GET", "/estimate", params={
            "amount": amount,
            "currency_from": currency_from.lower(),
            "currency_to": currency_to.lower(),
        })
        return float(data.get("estimated_amount", 0))

    async def get_minimum_fiat_amount(self, fiat_currency: str, pay_currency: str = "usdttrc20", safety: float = 1.05) -> float:
        """
        Compute the minimum required FIAT amount such that the resulting crypto
        amount is at least the API's minimum. Adds a small safety margin for
        rate fluctuations between request and payment creation.
        """
        min_crypto = await self.get_minimum_payment_amount(fiat_currency, pay_currency)
        if min_crypto <= 0:
            return 0.0
        # Use a probe amount to derive the fiat-to-crypto exchange rate.
        probe_fiat = max(10.0, min_crypto)
        probe_crypto = await self.get_estimate(probe_fiat, fiat_currency, pay_currency)
        if probe_crypto <= 0:
            return min_crypto * safety  # 1:1 fallback (works for USD↔USDT)
        rate = probe_crypto / probe_fiat  # crypto per 1 fiat
        return (min_crypto / rate) * safety

    async def create_payment(
        self,
        price_amount: float,
        price_currency: str,
        pay_currency: str,
        order_id: str,
        order_description: str,
        ipn_callback_url: str,
    ) -> dict:
        """
        Create a NowPayments payment.
        Returns payment object with payment_id, pay_address, pay_amount, etc.
        """
        payload = {
            "price_amount": price_amount,
            "price_currency": price_currency.lower(),
            "pay_currency": pay_currency.lower(),
            "order_id": order_id,
            "order_description": order_description,
            "ipn_callback_url": ipn_callback_url,
            "is_fixed_rate": False,
            "is_fee_paid_by_user": False,
        }
        return await self._request("POST", "/payment", payload=payload)

    async def get_payment_status(self, payment_id: str) -> dict:
        """Fetch current payment status by payment_id."""
        return await self._request("GET", f"/payment/{payment_id}")

    async def get_currencies(self) -> list[str]:
        """Return list of available pay currencies."""
        data = await self._request("GET", "/currencies")
        return data.get("currencies", [])

    def verify_ipn_signature(self, raw_body: bytes, received_sig: str) -> bool:
        """
        Verify NowPayments IPN HMAC-SHA512 signature.
        The signature is computed over the sorted JSON body using HMAC-SHA512
        with the IPN secret as the key.
        """
        if not self.ipn_secret:
            logger.warning("NowPayments IPN secret not configured — skipping signature check")
            return False
        try:
            body_dict = json.loads(raw_body)
            sorted_body = json.dumps(body_dict, sort_keys=True, separators=(",", ":"))
            expected = hmac.new(
                self.ipn_secret.encode(),
                sorted_body.encode(),
                hashlib.sha512,
            ).hexdigest()
            return hmac.compare_digest(expected, received_sig.lower())
        except Exception as e:
            logger.error(f"NowPayments IPN signature verification error: {e}")
            return False
