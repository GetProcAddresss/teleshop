import hashlib
import hmac
import json
import logging
import math
import time
import urllib.parse
from decimal import Decimal

from sqlalchemy import select, func
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from bot.database.main import Database
from bot.database.models.main import Categories, Goods, ItemValues, BoughtGoods, User
from bot.misc import EnvKeys
from bot.misc.bot_holder import get_bot

logger = logging.getLogger(__name__)


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


async def api_categories(request: Request) -> JSONResponse:
    try:
        async with Database().session() as s:
            result = await s.execute(select(Categories.id, Categories.name).order_by(Categories.name))
            rows = result.all()
        return JSONResponse([{"id": r.id, "name": r.name} for r in rows])
    except Exception as e:
        logger.error(f"api_categories error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500)


async def api_products(request: Request) -> JSONResponse:
    category_name = request.query_params.get("category", "").strip()
    search = request.query_params.get("search", "").strip()
    try:
        async with Database().session() as s:
            stmt = select(Goods)
            if category_name:
                stmt = stmt.join(Categories, Goods.category_id == Categories.id).where(
                    Categories.name == category_name
                )
            if search:
                stmt = stmt.where(Goods.name.ilike(f"%{search}%"))
            stmt = stmt.order_by(Goods.name)
            goods_rows = (await s.execute(stmt)).scalars().all()

            products = []
            for g in goods_rows:
                inf_count = (await s.execute(
                    select(func.count()).select_from(ItemValues)
                    .where(ItemValues.item_id == g.id, ItemValues.is_infinity == True)
                )).scalar() or 0
                fin_count = (await s.execute(
                    select(func.count()).select_from(ItemValues)
                    .where(ItemValues.item_id == g.id, ItemValues.is_infinity == False)
                )).scalar() or 0
                in_stock = inf_count > 0 or fin_count > 0
                products.append({
                    "id": g.id,
                    "name": g.name,
                    "description": g.description,
                    "price": float(g.price),
                    "custom_emoji_id": g.custom_emoji_id,
                    "in_stock": in_stock,
                    "stock_count": None if inf_count > 0 else fin_count,
                })
        return JSONResponse(products)
    except Exception as e:
        logger.error(f"api_products error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500)


async def api_user(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        telegram_id = int(user.get("id", 0))
        async with Database().session() as s:
            result = await s.execute(select(User).where(User.telegram_id == telegram_id))
            db_user = result.scalars().first()
        if not db_user:
            return JSONResponse({"error": "User not found. Start the bot first."}, status_code=404)
        return JSONResponse({
            "id": telegram_id,
            "first_name": user.get("first_name", ""),
            "username": user.get("username", ""),
            "balance": float(db_user.balance),
            "currency": EnvKeys.PAY_CURRENCY,
        })
    except Exception as e:
        logger.error(f"api_user error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500)


async def api_orders(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
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
        } for o in orders])
    except Exception as e:
        logger.error(f"api_orders error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500)


async def api_topup(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    try:
        amount = float(body.get("amount", 0))
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid amount"}, status_code=400)

    if amount < float(EnvKeys.MIN_AMOUNT):
        return JSONResponse({"error": f"Minimum amount is {EnvKeys.MIN_AMOUNT} {EnvKeys.PAY_CURRENCY}"}, status_code=400)
    if amount > float(EnvKeys.MAX_AMOUNT):
        return JSONResponse({"error": f"Maximum amount is {EnvKeys.MAX_AMOUNT} {EnvKeys.PAY_CURRENCY}"}, status_code=400)

    bot = get_bot()
    if not bot:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

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
        return JSONResponse({"invoice_url": link, "stars": stars, "amount": amount})
    except Exception as e:
        logger.error(f"api_topup create_invoice_link error: {e}")
        return JSONResponse({"error": "Failed to create invoice"}, status_code=500)


async def api_buy(request: Request) -> JSONResponse:
    user = _auth(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    item_name = (body.get("item_name") or "").strip()
    if not item_name:
        return JSONResponse({"error": "item_name required"}, status_code=400)

    try:
        telegram_id = int(user.get("id", 0))
        from bot.database.methods.transactions import buy_item
        success, reason, data = await buy_item(telegram_id, item_name)
        if success:
            return JSONResponse({"ok": True, "data": data})
        error_map = {
            "insufficient_funds": ("Insufficient balance", 402),
            "out_of_stock": ("Item is out of stock", 409),
            "item_not_found": ("Item not found", 404),
            "user_not_found": ("User not found. Start the bot first.", 404),
        }
        msg, code = error_map.get(reason, (reason, 400))
        return JSONResponse({"error": msg, "reason": reason}, status_code=code)
    except Exception as e:
        logger.error(f"api_buy error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500)


def get_mini_app_routes() -> list:
    return [
        Route("/mini/api/categories", api_categories, methods=["GET"]),
        Route("/mini/api/products", api_products, methods=["GET"]),
        Route("/mini/api/user", api_user, methods=["GET"]),
        Route("/mini/api/orders", api_orders, methods=["GET"]),
        Route("/mini/api/topup", api_topup, methods=["POST"]),
        Route("/mini/api/buy", api_buy, methods=["POST"]),
    ]
