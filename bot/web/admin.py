import logging
import os
import time
from typing import Any

from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from sqlalchemy import text, select

from markupsafe import Markup

from bot.misc import EnvKeys
from bot.database.methods.audit import log_audit

logger = logging.getLogger(__name__)


class LoginRateLimiter:
    """In-memory rate limiter for login attempts by IP."""

    def __init__(self, max_attempts: int = 5, lockout_seconds: int = 900):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}
        self._last_cleanup: float = time.time()

    def is_blocked(self, ip: str) -> bool:
        if ip not in self._attempts:
            return False
        now = time.time()
        self._attempts[ip] = [t for t in self._attempts[ip] if now - t < self.lockout_seconds]
        return len(self._attempts[ip]) >= self.max_attempts

    def record_failure(self, ip: str) -> None:
        now = time.time()
        if now - self._last_cleanup > 600:
            self._attempts = {
                k: [t for t in v if now - t < self.lockout_seconds]
                for k, v in self._attempts.items()
                if any(now - t < self.lockout_seconds for t in v)
            }
            self._last_cleanup = now
        if ip not in self._attempts:
            self._attempts[ip] = []
        self._attempts[ip].append(now)

    def reset(self, ip: str) -> None:
        self._attempts.pop(ip, None)


_login_limiter = LoginRateLimiter()
from bot.database.main import Database
from bot.database.models.main import (
    User, Role, Categories, Goods, ItemValues,
    BoughtGoods, Operations, Payments, ReferralEarnings,
    AuditLog, PromoCodes, CartItems, Reviews,
)
from bot.misc.metrics import get_metrics
from bot.misc.caching import get_cache_manager


# Authentication
class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        ip = request.client.host

        if _login_limiter.is_blocked(ip):
            await log_audit("web_login_blocked", level="WARNING", details=f"ip={ip}", ip_address=ip)
            return False

        form = await request.form()
        username = form.get("username")
        password = form.get("password")

        if username == EnvKeys.ADMIN_USERNAME and password == EnvKeys.ADMIN_PASSWORD:
            if (
                username == "admin" and password == "admin"
                and ip not in ("127.0.0.1", "::1", "localhost")
            ):
                await log_audit("web_login_blocked_default_creds", level="WARNING", details=f"ip={ip}", ip_address=ip)
                return False
            request.session.update({"authenticated": True})
            _login_limiter.reset(ip)
            await log_audit("web_login", user_id=None, details=f"user={username}", ip_address=ip)
            return True

        _login_limiter.record_failure(ip)
        await log_audit("web_login_failed", level="WARNING", details=f"user={username}", ip_address=ip)
        return False

    async def logout(self, request: Request) -> bool:
        await log_audit("web_logout", ip_address=request.client.host)
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return request.session.get("authenticated", False)


def _safe_model_repr(model: Any, max_len: int = 500) -> str:
    """Return a truncated repr that excludes sensitive fields."""
    _sensitive = {"balance", "password", "secret", "token", "value"}
    parts = []
    for col in getattr(model, "__table__", None).columns if hasattr(model, "__table__") else ():
        if col.name in _sensitive:
            continue
        val = getattr(model, col.name, None)
        parts.append(f"{col.name}={val!r}")
    result = f"{type(model).__name__}({', '.join(parts)})"
    return result[:max_len]


# Audited base view for mutable models
class AuditModelView(ModelView):
    async def after_model_change(self, data: dict, model: Any, is_created: bool, request: Request) -> None:
        action = f"sqladmin_{'create' if is_created else 'update'}"
        await log_audit(
            action,
            resource_type=self.name,
            resource_id=str(getattr(model, 'id', getattr(model, 'name', None))),
            details=_safe_model_repr(model),
            ip_address=request.client.host,
        )

    async def after_model_delete(self, model: Any, request: Request) -> None:
        await log_audit(
            "sqladmin_delete",
            resource_type=self.name,
            resource_id=str(getattr(model, 'id', getattr(model, 'name', None))),
            details=_safe_model_repr(model),
            ip_address=request.client.host,
        )


# Model Views
class UserAdmin(AuditModelView, model=User):
    column_list = [User.telegram_id, User.balance, User.role_id, User.referral_id,
                   User.registration_date, User.is_blocked]
    column_searchable_list = [User.telegram_id]
    column_sortable_list = [User.telegram_id, User.balance, User.registration_date]
    column_default_sort = (User.registration_date, True)
    name = "User"
    name_plural = "Users"
    icon = "fa-solid fa-users"


_PERM_FLAGS = [
    (1,   "USE"),
    (2,   "BROADCAST"),
    (4,   "SETTINGS"),
    (8,   "USERS"),
    (16,  "CATALOG"),
    (32,  "ADMINS"),
    (64,  "OWNER"),
    (128, "STATS"),
    (256, "BALANCE"),
    (512, "PROMOS"),
]


def _format_perms_html(model, name):
    perms = getattr(model, name, 0) or 0
    if not perms:
        return Markup('<span style="color:#999">\u2014</span>')
    badges = []
    for bit, label in _PERM_FLAGS:
        if perms & bit:
            badges.append(
                f'<span style="display:inline-block;background:#e2e8f0;padding:1px 6px;'
                f'border-radius:4px;margin:1px;font-size:12px">{label}</span>'
            )
    raw = f'<span style="color:#999;font-size:11px;margin-left:4px">({perms})</span>'
    return Markup(" ".join(badges) + raw)


class RoleAdmin(AuditModelView, model=Role):
    column_list = [Role.id, Role.name, Role.default, Role.permissions]
    column_details_exclude_list = ["users"]
    column_sortable_list = [Role.id, Role.name]
    name = "Role"
    name_plural = "Roles"
    icon = "fa-solid fa-shield-halved"
    column_formatters = {"permissions": _format_perms_html}
    column_formatters_detail = {"permissions": _format_perms_html}
    form_args = {
        "permissions": {
            "description": (
                "Bitmask value — sum the flags you need: "
                "USE=1, BROADCAST=2, SETTINGS=4, USERS=8, CATALOG=16, ADMINS=32, "
                "OWNER=64, STATS=128, BALANCE=256, PROMOS=512. "
                "Example: 927 = full Admin, 1023 = all (Owner)."
            ),
        },
    }


class CategoryAdmin(AuditModelView, model=Categories):
    column_list = [Categories.name]
    column_searchable_list = [Categories.name]
    form_columns = ["name"]
    name = "Category"
    name_plural = "Categories"
    icon = "fa-solid fa-folder"


def _format_emoji_id(model, name):
    val = getattr(model, name, None)
    if not val:
        return Markup('<span style="color:#999">—</span>')
    return Markup(
        f'<code style="background:#f0f4f8;padding:2px 6px;border-radius:4px;'
        f'font-size:12px;user-select:all">{val}</code>'
    )


def _format_image_url(model, name):
    val = getattr(model, name, None)
    if not val:
        return Markup('<span style="color:#999">—</span>')
    return Markup(
        f'<a href="{val}" target="_blank" rel="noopener">'
        f'<img src="{val}" style="height:42px;width:42px;object-fit:cover;'
        f'border-radius:6px;border:1px solid #2a3147;background:#0f1422" '
        f'onerror="this.style.display=\'none\'"/></a>'
    )


class GoodsAdmin(AuditModelView, model=Goods):
    column_list = [Goods.id, Goods.image_url, Goods.name, Goods.price, Goods.category_id, Goods.custom_emoji_id]
    column_details_list = [
        Goods.id, Goods.image_url, Goods.name, Goods.price, Goods.description,
        Goods.category_id, Goods.custom_emoji_id,
    ]
    column_searchable_list = [Goods.name]
    column_sortable_list = [Goods.id, Goods.name, Goods.price]
    column_formatters = {
        "custom_emoji_id": _format_emoji_id,
        "image_url": _format_image_url,
    }
    column_formatters_detail = {
        "custom_emoji_id": _format_emoji_id,
        "image_url": _format_image_url,
    }
    column_labels = {"image_url": "Image"}
    form_columns = ["name", "price", "description", "category", "image_url", "custom_emoji_id"]
    form_args = {
        "category": {
            "label": "Category",
        },
        "image_url": {
            "label": "Product Image URL",
            "description": (
                "Paste an image URL, or upload via /admin/upload (returns a /uploads/... path). "
                "Recommended 600×600 px, JPG/PNG/WEBP, &lt; 1.5 MB. Leave empty to use emoji fallback."
            ),
        },
        "custom_emoji_id": {
            "label": "Premium Emoji ID",
            "description": (
                "Telegram custom_emoji_id (18–20 digit number). "
                "How to get one: forward any message with a premium emoji to @getidsbot "
                "— it will reply with the ID. "
                "Leave empty for no emoji. "
                "Example: 5368324170671202286"
            ),
        },
    }
    name = "Product"
    name_plural = "Products"
    icon = "fa-solid fa-box"


class ItemValuesAdmin(AuditModelView, model=ItemValues):
    column_list = [ItemValues.id, ItemValues.item_id, ItemValues.value, ItemValues.is_infinity]
    column_searchable_list = [ItemValues.value]
    column_sortable_list = [ItemValues.id, ItemValues.item_id]
    form_columns = ["item", "value", "is_infinity"]
    form_args = {
        "item": {"label": "Product"},
        "value": {"label": "Content / Code (leave empty if Infinite)"},
        "is_infinity": {"label": "Unlimited Stock"},
    }
    name = "Stock Item"
    name_plural = "Stock Items"
    icon = "fa-solid fa-warehouse"


class BoughtGoodsAdmin(ModelView, model=BoughtGoods):
    column_list = [BoughtGoods.id, BoughtGoods.item_name, BoughtGoods.value,
                   BoughtGoods.price, BoughtGoods.buyer_id, BoughtGoods.bought_datetime,
                   BoughtGoods.unique_id]
    column_searchable_list = [BoughtGoods.item_name, BoughtGoods.buyer_id, BoughtGoods.unique_id]
    column_sortable_list = [BoughtGoods.id, BoughtGoods.bought_datetime, BoughtGoods.price]
    column_default_sort = (BoughtGoods.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Purchase"
    name_plural = "Purchases"
    icon = "fa-solid fa-cart-shopping"


class OperationsAdmin(ModelView, model=Operations):
    column_list = [Operations.id, Operations.user_id, Operations.operation_value,
                   Operations.operation_time]
    column_searchable_list = [Operations.user_id]
    column_sortable_list = [Operations.id, Operations.operation_time, Operations.operation_value]
    column_default_sort = (Operations.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Operation"
    name_plural = "Operations"
    icon = "fa-solid fa-money-bill-transfer"


class PaymentsAdmin(ModelView, model=Payments):
    column_list = [Payments.id, Payments.provider, Payments.external_id, Payments.user_id,
                   Payments.amount, Payments.currency, Payments.status, Payments.created_at]
    column_searchable_list = [Payments.user_id, Payments.external_id, Payments.provider]
    column_sortable_list = [Payments.id, Payments.created_at, Payments.amount, Payments.status]
    column_default_sort = (Payments.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Payment"
    name_plural = "Payments"
    icon = "fa-solid fa-credit-card"


class ReferralEarningsAdmin(ModelView, model=ReferralEarnings):
    column_list = [ReferralEarnings.id, ReferralEarnings.referrer_id,
                   ReferralEarnings.referral_id, ReferralEarnings.amount,
                   ReferralEarnings.original_amount, ReferralEarnings.created_at]
    column_searchable_list = [ReferralEarnings.referrer_id, ReferralEarnings.referral_id]
    column_sortable_list = [ReferralEarnings.id, ReferralEarnings.created_at, ReferralEarnings.amount]
    column_default_sort = (ReferralEarnings.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Referral Earning"
    name_plural = "Referral Earnings"
    icon = "fa-solid fa-handshake"


class AuditLogAdmin(ModelView, model=AuditLog):
    column_list = [AuditLog.id, AuditLog.timestamp, AuditLog.level, AuditLog.user_id,
                   AuditLog.action, AuditLog.resource_type, AuditLog.resource_id,
                   AuditLog.details, AuditLog.ip_address]
    column_searchable_list = [AuditLog.action, AuditLog.resource_type, AuditLog.details]
    column_sortable_list = [AuditLog.id, AuditLog.timestamp, AuditLog.level, AuditLog.action]
    column_default_sort = (AuditLog.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Audit Log"
    name_plural = "Audit Logs"
    icon = "fa-solid fa-clipboard-list"


class PromoCodeAdmin(AuditModelView, model=PromoCodes):
    column_list = [PromoCodes.id, PromoCodes.code, PromoCodes.discount_type,
                   PromoCodes.discount_value, PromoCodes.max_uses, PromoCodes.current_uses,
                   PromoCodes.is_active, PromoCodes.expires_at, PromoCodes.created_at]
    column_searchable_list = [PromoCodes.code]
    column_sortable_list = [PromoCodes.id, PromoCodes.code, PromoCodes.created_at]
    column_default_sort = (PromoCodes.id, True)
    name = "Promo Code"
    name_plural = "Promo Codes"
    icon = "fa-solid fa-tag"


class CartItemsAdmin(ModelView, model=CartItems):
    column_list = [CartItems.id, CartItems.user_id, CartItems.item_name, CartItems.added_at]
    column_searchable_list = [CartItems.user_id, CartItems.item_name]
    column_sortable_list = [CartItems.id, CartItems.added_at]
    column_default_sort = (CartItems.id, True)
    can_create = False
    can_edit = False
    can_delete = False
    name = "Cart Item"
    name_plural = "Cart Items"
    icon = "fa-solid fa-cart-plus"



class ReviewsAdmin(AuditModelView, model=Reviews):
    column_list = [Reviews.id, Reviews.user_id, Reviews.item_name,
                   Reviews.rating, Reviews.text, Reviews.created_at]
    column_searchable_list = [Reviews.user_id, Reviews.item_name]
    column_sortable_list = [Reviews.id, Reviews.rating, Reviews.created_at]
    column_default_sort = (Reviews.id, True)
    name = "Review"
    name_plural = "Reviews"
    icon = "fa-solid fa-star"


# Health & Metrics Endpoints
def _resolve_uploads_dir() -> str:
    env_dir = os.environ.get("UPLOADS_DIR")
    candidates = [
        env_dir,
        "/app/data/uploads",
        "/tmp/evrest_uploads",
        os.path.join(os.path.dirname(__file__), "uploads"),
    ]
    for c in candidates:
        if not c:
            continue
        try:
            os.makedirs(c, exist_ok=True)
            test = os.path.join(c, ".write_test")
            with open(test, "w") as f:
                f.write("ok")
            os.remove(test)
            return c
        except Exception:
            continue
    return "/tmp"


_UPLOADS_DIR = _resolve_uploads_dir()
_ALLOWED_IMG_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_ALLOWED_IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_IMG_BYTES = 2 * 1024 * 1024  # 2 MB


_IMG_MAGIC = {
    ".jpg":  [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".png":  [b"\x89PNG\r\n\x1a\n"],
    ".gif":  [b"GIF87a", b"GIF89a"],
    ".webp": [b"RIFF"],  # second check below for "WEBP" at offset 8
}


def _verify_image_bytes(raw: bytes, ext: str) -> bool:
    sigs = _IMG_MAGIC.get(ext)
    if not sigs:
        return False
    if not any(raw.startswith(sig) for sig in sigs):
        return False
    if ext == ".webp":
        if len(raw) < 12 or raw[8:12] != b"WEBP":
            return False
    return True


async def nowpayments_ipn(request: Request) -> JSONResponse:
    """
    NowPayments IPN (Instant Payment Notification) webhook.
    Public endpoint — authentication is via HMAC-SHA512 signature.
    """
    try:
        raw_body = await request.body()
        sig = request.headers.get("x-nowpayments-sig", "")
        if not sig:
            return JSONResponse({"error": "Missing signature"}, status_code=400)

        from bot.misc.services.nowpayments import NowPaymentsAPI
        client = NowPaymentsAPI()
        if not client.verify_ipn_signature(raw_body, sig):
            logger.warning("NowPayments IPN: invalid signature")
            return JSONResponse({"error": "Invalid signature"}, status_code=401)

        import json as _json
        data = _json.loads(raw_body)
        payment_status = data.get("payment_status", "")
        payment_id = str(data.get("payment_id", ""))
        order_id = str(data.get("order_id", ""))
        pay_amount = float(data.get("actually_paid", 0) or data.get("pay_amount", 0))
        price_currency = str(data.get("price_currency", EnvKeys.PAY_CURRENCY)).upper()

        if payment_status not in ("finished", "confirmed"):
            return JSONResponse({"ok": True, "status": payment_status})

        # order_id encodes "nowpay:{user_id}:{fiat_amount}"
        try:
            parts = order_id.split(":")
            user_id = int(parts[1])
            fiat_amount = float(parts[2])
        except (IndexError, ValueError):
            logger.error(f"NowPayments IPN: malformed order_id={order_id}")
            return JSONResponse({"error": "Malformed order_id"}, status_code=400)

        from decimal import Decimal
        from bot.database.methods.transactions import process_payment_with_referral
        success, msg = await process_payment_with_referral(
            user_id=user_id,
            amount=Decimal(str(fiat_amount)),
            provider="nowpayments",
            external_id=payment_id,
            referral_percent=EnvKeys.REFERRAL_PERCENT,
        )

        if success:
            from bot.misc.bot_holder import get_bot
            from bot.misc.services.notifications import notify_new_deposit
            bot = get_bot()
            if bot:
                try:
                    chat = await bot.get_chat(user_id)
                    user_name = chat.first_name or str(user_id)
                    await bot.send_message(
                        user_id,
                        f"✅ <b>Deposit confirmed!</b>\n"
                        f"💰 <b>+{fiat_amount:.2f} {price_currency}</b> added to your balance via NowPayments.",
                        parse_mode="HTML",
                    )
                    await notify_new_deposit(bot, fiat_amount, "nowpayments", user_name, user_id)
                except Exception as e:
                    logger.warning(f"NowPayments IPN: notify failed for user {user_id}: {e}")

            await log_audit("balance_replenish", user_id=user_id, resource_type="Payment",
                            details=f"provider=nowpayments, amount={fiat_amount}, payment_id={payment_id}")

        return JSONResponse({"ok": True})

    except Exception as e:
        logger.error(f"NowPayments IPN handler error: {e}")
        return JSONResponse({"error": "Internal error"}, status_code=500)


_EXT_TO_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif",
}


async def upload_product_image(request: Request) -> JSONResponse:
    """Admin-only image upload. Stores bytes in DB (persistent) and returns {url: '/uploads/img/<token>'}."""
    if not request.session.get("authenticated"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        form = await request.form()
        f = form.get("file")
        if f is None or not hasattr(f, "filename"):
            return JSONResponse({"error": "No file provided"}, status_code=400)
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in _ALLOWED_IMG_EXT:
            return JSONResponse({"error": "Unsupported file type"}, status_code=400)
        if getattr(f, "content_type", None) and f.content_type not in _ALLOWED_IMG_TYPES:
            return JSONResponse({"error": "Unsupported content type"}, status_code=400)
        raw = await f.read()
        if len(raw) == 0:
            return JSONResponse({"error": "Empty file"}, status_code=400)
        if len(raw) > _MAX_IMG_BYTES:
            return JSONResponse({"error": "File too large (max 2 MB)"}, status_code=413)
        if not _verify_image_bytes(raw, ext):
            return JSONResponse({"error": "Invalid image content"}, status_code=400)

        import secrets
        from bot.database.models.main import ProductImage
        token = secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]
        mime = _EXT_TO_MIME.get(ext, "application/octet-stream")

        try:
            async with Database().session() as s:
                s.add(ProductImage(token=token, mime=mime, data=raw, size=len(raw)))
                await s.commit()
        except Exception as e:
            logger.error(f"upload_product_image db error: {e}")
            return JSONResponse({"error": "Storage unavailable"}, status_code=503)

        return JSONResponse(
            {"url": f"/uploads/img/{token}", "size": len(raw)},
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )
    except Exception as e:
        logger.error(f"upload_product_image error: {e}")
        return JSONResponse({"error": "Upload failed"}, status_code=500)


async def serve_product_image(request: Request) -> Response:
    """Public read-only endpoint that streams a stored product image."""
    from starlette.responses import Response as _R
    token = (request.path_params.get("token") or "").strip()
    if not token or len(token) > 48 or not token.isalnum():
        return _R(status_code=404)
    try:
        from bot.database.models.main import ProductImage
        async with Database().session() as s:
            result = await s.execute(select(ProductImage).where(ProductImage.token == token))
            img = result.scalars().first()
        if not img:
            return _R(status_code=404)
        return _R(
            content=img.data,
            media_type=img.mime,
            headers={
                "Cache-Control": "public, max-age=86400, immutable",
                "X-Content-Type-Options": "nosniff",
                "Content-Length": str(img.size),
            },
        )
    except Exception as e:
        logger.error(f"serve_product_image error: {e}")
        return _R(status_code=500)


async def health_check(request: Request) -> JSONResponse:
    health_status = {
        "status": "healthy",
        "checks": {},
    }

    try:
        async with Database().session() as s:
            await s.execute(text("SELECT 1"))
        health_status["checks"]["database"] = "ok"
    except Exception as e:
        logger.error(f"Health check database error: {e}")
        health_status["checks"]["database"] = "error"
        health_status["status"] = "unhealthy"

    cache = get_cache_manager()
    if cache:
        health_status["checks"]["redis"] = "ok" if cache._healthy else "degraded"
    else:
        health_status["checks"]["redis"] = "not configured"

    metrics = get_metrics()
    if metrics:
        health_status["checks"]["metrics"] = "ok"
        health_status["uptime"] = metrics.get_metrics_summary()["uptime_seconds"]

    status_code = 200 if health_status["status"] == "healthy" else 503
    return JSONResponse(health_status, status_code=status_code)


async def prometheus_metrics(request: Request) -> PlainTextResponse:
    if not request.session.get("authenticated"):
        return PlainTextResponse("Unauthorized", status_code=401)
    metrics = get_metrics()
    if not metrics:
        return PlainTextResponse("# Metrics not initialized\n", status_code=503)
    return PlainTextResponse(metrics.export_to_prometheus(), media_type="text/plain")


async def metrics_json(request: Request) -> JSONResponse:
    if not request.session.get("authenticated"):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    metrics = get_metrics()
    if not metrics:
        return JSONResponse({"error": "Metrics not initialized"}, status_code=503)
    return JSONResponse(metrics.get_metrics_summary(), status_code=200)


# ── Security headers middleware ──
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds defense-in-depth security headers. CSP is path-aware:
      - /mini/*  : strict mini-app CSP (allows Telegram WebApp JS)
      - default  : relaxed CSP suited for SQLAdmin (Tabler CDN, inline scripts)
    """

    _MINI_CSP = (
        "default-src 'self'; "
        "script-src 'self' https://telegram.org 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "font-src 'self' data:; "
        "connect-src 'self' https://telegram.org; "
        "frame-ancestors https://web.telegram.org https://*.telegram.org 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'"
    )

    _ADMIN_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' data: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "object-src 'none'"
    )

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        path = request.url.path

        # HSTS — only meaningful over HTTPS; Railway terminates TLS and forwards X-Forwarded-Proto.
        xfp = request.headers.get("x-forwarded-proto", request.url.scheme)
        if xfp == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()",
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        # X-Frame-Options + CSP frame-ancestors
        if path.startswith("/mini") or path.startswith("/uploads"):
            # Mini app: allow framing by Telegram clients. Do not send X-Frame-Options
            # (it would conflict with CSP frame-ancestors and is the legacy header).
            response.headers.setdefault("Content-Security-Policy", self._MINI_CSP)
        else:
            response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
            response.headers.setdefault("Content-Security-Policy", self._ADMIN_CSP)

        return response


# App Factory
def create_admin_app() -> Starlette:

    from bot.web.export import export_routes
    from bot.web.mini_app_api import get_mini_app_routes

    _mini_app_dir = os.path.join(os.path.dirname(__file__), "mini_app")

    try:
        os.makedirs(_UPLOADS_DIR, exist_ok=True)
    except Exception as e:
        logger.warning(f"Could not create uploads dir {_UPLOADS_DIR}: {e}")

    routes = [
        Route("/health", health_check),
        Route("/metrics", metrics_json),
        Route("/metrics/prometheus", prometheus_metrics),
        Route("/admin/upload", upload_product_image, methods=["POST"]),
        Route("/uploads/img/{token}", serve_product_image, methods=["GET"]),
        Route("/api/nowpayments/ipn", nowpayments_ipn, methods=["POST"]),
    ] + export_routes + get_mini_app_routes() + [
        Mount("/uploads", app=StaticFiles(directory=_UPLOADS_DIR)),
        Mount("/mini", app=StaticFiles(directory=_mini_app_dir, html=True)),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=EnvKeys.SECRET_KEY, max_age=1800)

    _templates_dir = os.path.join(os.path.dirname(__file__), "templates")
    auth_backend = AdminAuth(secret_key=EnvKeys.SECRET_KEY)
    admin = Admin(
        app,
        engine=Database().engine,
        authentication_backend=auth_backend,
        title="Evrest Market Admin Panel",
        templates_dir=_templates_dir,
    )

    admin.add_view(UserAdmin)
    admin.add_view(RoleAdmin)
    admin.add_view(CategoryAdmin)
    admin.add_view(GoodsAdmin)
    admin.add_view(ItemValuesAdmin)
    admin.add_view(BoughtGoodsAdmin)
    admin.add_view(OperationsAdmin)
    admin.add_view(PaymentsAdmin)
    admin.add_view(ReferralEarningsAdmin)
    admin.add_view(AuditLogAdmin)
    admin.add_view(PromoCodeAdmin)
    admin.add_view(CartItemsAdmin)
    if EnvKeys.REVIEWS_ENABLED == "1":
        admin.add_view(ReviewsAdmin)

    return app
