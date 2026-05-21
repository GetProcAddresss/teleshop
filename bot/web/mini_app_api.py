import hashlib
import hmac
import json
import logging
import math
import time
import urllib.parse
from collections import defaultdict, deque
from decimal import Decimal
from functools import wraps

from sqlalchemy import select, func, case, and_
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from bot.database.main import Database
from bot.database.models.main import Categories, Goods, ItemValues, BoughtGoods, User
from bot.misc import EnvKeys
from bot.misc.bot_holder import get_bot

logger = logging.getLogger(__name__)


# ────────────────────────── Auth ──────────────────────────
def _validate_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        hash_val = parsed.pop("hash", "")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", EnvKeys.TOKEN.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, hash_val):
            return None
        auth_date = int(parsed.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            return None
        user_str = parsed.get("user", "{}")
        return json.loads(user_str)
    except Exception:
        return None


def _auth(request: Request) -> dict | None:
    return _validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))


# ────────────────────────── Rate limit ──────────────────────────
class _RateLimiter:
    """Simple in-memory sliding-window limiter. Per-key (user/ip) → deque of timestamps."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.time()
        dq = self._hits[key]
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self.limit:
            return False
        dq.append(now)
        return True


_buy_limiter = _RateLimiter(limit=10, window=60.0)        # 10 buys/min/user
_topup_limiter = _RateLimiter(limit=6, window=60.0)       # 6 invoices/min/user


def _client_key(request: Request, user: dict | None) -> str:
    if user and user.get("id"):
        return f"u:{user['id']}"
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")
    return f"ip:{ip}"


# ────────────────────────── Helpers ──────────────────────────
_JSON_HEADERS_SHORT = {"Cache-Control": "public, max-age=15, stale-while-revalidate=60"}
_JSON_HEADERS_NONE = {"Cache-Control": "no-store"}


def _etag_for(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return 'W/"' + hashlib.md5(raw).hexdigest() + '"'


def _maybe_304(request: Request, etag: str) -> Response | None:
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, **_JSON_HEADERS_SHORT})
    return None


# ────────────────────────── Routes ──────────────────────────
async def api_health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True, "ts": int(time.time())}, headers=_JSON_HEADERS_NONE)


async def api_categories(request: Request) -> Response:
    try:
        async with Database().session() as s:
            result = await s.execute(select(Categories.id, Categories.name).order_by(Categories.name))
            rows = result.all()
        payload = [{"id": r.id, "name": r.name} for r in rows]
        etag = _etag_for(payload)
        cached = _maybe_304(request, etag)
        if cached:
            return cached
        return JSONResponse(payload, headers={"ETag": etag, **_JSON_HEADERS_SHORT})
    except Exception as e:
        logger.error(f"api_categories error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500, headers=_JSON_HEADERS_NONE)


async def api_products(request: Request) -> Response:
    category_name = (request.query_params.get("category") or "").strip()[:120]
    search = (request.query_params.get("search") or "").strip()[:80]
    try:
        async with Database().session() as s:
            # Aggregate stock counts in one query (no N+1).
            inf_expr = func.coalesce(
                func.sum(case((ItemValues.is_infinity.is_(True), 1), else_=0)), 0
            ).label("inf_count")
            fin_expr = func.coalesce(
                func.sum(case((ItemValues.is_infinity.is_(False), 1), else_=0)), 0
            ).label("fin_count")

            stmt = (
                select(Goods, inf_expr, fin_expr)
                .outerjoin(ItemValues, ItemValues.item_id == Goods.id)
                .group_by(Goods.id)
                .order_by(Goods.name)
            )

            if category_name:
                stmt = stmt.join(Categories, Goods.category_id == Categories.id).where(
                    Categories.name == category_name
                )
            if search:
                stmt = stmt.where(Goods.name.ilike(f"%{search}%"))

            rows = (await s.execute(stmt)).all()

            products = []
            for g, inf_count, fin_count in rows:
                in_stock = (inf_count or 0) > 0 or (fin_count or 0) > 0
                products.append({
                    "id": g.id,
                    "name": g.name,
                    "description": g.description,
                    "price": float(g.price),
                    "custom_emoji_id": g.custom_emoji_id,
                    "in_stock": bool(in_stock),
                    "stock_count": None if (inf_count or 0) > 0 else int(fin_count or 0),
                })

        etag = _etag_for(products)
        cached = _maybe_304(request, etag)
        if cached:
            return cached
        return JSONResponse(products, headers={"ETag": etag, **_JSON_HEADERS_SHORT})
    except Exception as e:
        logger.error(f"api_products error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500, headers=_JSON_HEADERS_NONE)


async def api_user(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401, headers=_JSON_HEADERS_NONE)
    try:
        telegram_id = int(user.get("id", 0))
        async with Database().session() as s:
            result = await s.execute(select(User).where(User.telegram_id == telegram_id))
            db_user = result.scalars().first()
        if not db_user:
            return JSONResponse({"error": "User not found. Start the bot first."}, status_code=404,
                                headers=_JSON_HEADERS_NONE)
        return JSONResponse({
            "id": telegram_id,
            "first_name": user.get("first_name", ""),
            "username": user.get("username", ""),
            "balance": float(db_user.balance),
            "currency": EnvKeys.PAY_CURRENCY,
        }, headers=_JSON_HEADERS_NONE)
    except Exception as e:
        logger.error(f"api_user error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500, headers=_JSON_HEADERS_NONE)


async def api_orders(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401, headers=_JSON_HEADERS_NONE)
    try:
        telegram_id = int(user.get("id", 0))
        async with Database().session() as s:
            result = await s.execute(
                select(BoughtGoods)
                .where(BoughtGoods.buyer_id == telegram_id)
                .order_by(BoughtGoods.bought_datetime.desc())
                .limit(50)
            )
            orders = result.scalars().all()
        return JSONResponse([{
            "id": o.id,
            "item_name": o.item_name,
            "price": float(o.price),
            "bought_at": o.bought_datetime.isoformat() if o.bought_datetime else None,
            "value": o.value,
        } for o in orders], headers=_JSON_HEADERS_NONE)
    except Exception as e:
        logger.error(f"api_orders error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500, headers=_JSON_HEADERS_NONE)


async def api_topup(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401, headers=_JSON_HEADERS_NONE)

    if not _topup_limiter.allow(_client_key(request, user)):
        return JSONResponse({"error": "Too many requests. Wait a moment."}, status_code=429,
                            headers=_JSON_HEADERS_NONE)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400, headers=_JSON_HEADERS_NONE)

    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid amount"}, status_code=400, headers=_JSON_HEADERS_NONE)

    if amount < float(EnvKeys.MIN_AMOUNT):
        return JSONResponse({"error": f"Minimum amount is {EnvKeys.MIN_AMOUNT} {EnvKeys.PAY_CURRENCY}"},
                            status_code=400, headers=_JSON_HEADERS_NONE)
    if amount > float(EnvKeys.MAX_AMOUNT):
        return JSONResponse({"error": f"Maximum amount is {EnvKeys.MAX_AMOUNT} {EnvKeys.PAY_CURRENCY}"},
                            status_code=400, headers=_JSON_HEADERS_NONE)

    bot = get_bot()
    if not bot:
        return JSONResponse({"error": "Service unavailable"}, status_code=503, headers=_JSON_HEADERS_NONE)

    stars = int(math.ceil(amount * EnvKeys.STARS_PER_VALUE))
    if stars < 1:
        stars = 1

    try:
        from aiogram.types import LabeledPrice
        link = await bot.create_invoice_link(
            title="Balance Top-up",
            description=f"Add {int(amount)} {EnvKeys.PAY_CURRENCY} to your Evrest Market balance",
            payload=json.dumps({
                "op": "topup_balance_stars",
                "amount_rub": int(amount),
                "stars": stars,
                "telegram_id": user.get("id"),
            }),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Stars", amount=stars)],
        )
        return JSONResponse({"invoice_url": link, "stars": stars, "amount": amount},
                            headers=_JSON_HEADERS_NONE)
    except Exception as e:
        logger.error(f"api_topup create_invoice_link error: {e}")
        return JSONResponse({"error": "Failed to create invoice"}, status_code=500,
                            headers=_JSON_HEADERS_NONE)


async def api_buy(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401, headers=_JSON_HEADERS_NONE)

    if not _buy_limiter.allow(_client_key(request, user)):
        return JSONResponse({"error": "Too many purchase attempts. Wait a moment."}, status_code=429,
                            headers=_JSON_HEADERS_NONE)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400, headers=_JSON_HEADERS_NONE)

    item_name = (body.get("item_name") or "").strip()[:100]
    if not item_name:
        return JSONResponse({"error": "item_name required"}, status_code=400, headers=_JSON_HEADERS_NONE)

    try:
        telegram_id = int(user.get("id", 0))
        from bot.database.methods.transactions import buy_item
        success, reason, data = await buy_item(telegram_id, item_name)
        if success:
            return JSONResponse({"ok": True, "data": data}, headers=_JSON_HEADERS_NONE)
        error_map = {
            "insufficient_funds": ("Insufficient balance", 402),
            "out_of_stock": ("Item is out of stock", 409),
            "item_not_found": ("Item not found", 404),
            "user_not_found": ("User not found. Start the bot first.", 404),
        }
        msg, code = error_map.get(reason, (reason, 400))
        return JSONResponse({"error": msg, "reason": reason}, status_code=code,
                            headers=_JSON_HEADERS_NONE)
    except Exception as e:
        logger.error(f"api_buy error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500, headers=_JSON_HEADERS_NONE)


def get_mini_app_routes() -> list:
    return [
        Route("/mini/api/health", api_health, methods=["GET"]),
        Route("/mini/api/categories", api_categories, methods=["GET"]),
        Route("/mini/api/products", api_products, methods=["GET"]),
        Route("/mini/api/user", api_user, methods=["GET"]),
        Route("/mini/api/orders", api_orders, methods=["GET"]),
        Route("/mini/api/topup", api_topup, methods=["POST"]),
        Route("/mini/api/buy", api_buy, methods=["POST"]),
    ]
