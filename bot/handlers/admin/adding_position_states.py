from urllib.parse import urlparse

import os
import secrets
import time as _time

from aiogram import Router, F
from aiogram.exceptions import TelegramForbiddenError, TelegramNotFound, TelegramBadRequest
from aiogram.types import CallbackQuery, Message

from bot.database.models import Permission
from bot.database.methods import (
    check_category_cached, get_item_info_cached, create_item, add_values_to_item
)
from bot.handlers.other import _parse_channel_username
from bot.keyboards.inline import back, question_buttons, simple_buttons
from bot.database.methods.audit import log_audit
from bot.filters import HasPermissionFilter
from bot.misc import EnvKeys
from bot.misc.services.notifications import notify_new_stock
from bot.i18n import localize
from bot.states import AddItemFSM

router = Router()


@router.callback_query(F.data == 'add_item', HasPermissionFilter(permission=Permission.CATALOG_MANAGE))
async def add_item_callback_handler(call: CallbackQuery, state):
    """
    Ask administrator for a new position name.
    """
    await call.message.edit_text(localize('admin.goods.add.prompt.name'), reply_markup=back("goods_management"))
    await state.set_state(AddItemFSM.waiting_item_name)


@router.message(AddItemFSM.waiting_item_name, F.text)
async def check_item_name_for_add(message: Message, state):
    """
    If position already exists — inform the user; otherwise save name and ask for description.
    """
    item_name = (message.text or "").strip()
    item = await get_item_info_cached(item_name)
    if item:
        await message.answer(
            localize('admin.goods.add.name.exists'),
            reply_markup=back('goods_management')
        )
        return

    await state.update_data(item_name=item_name)
    await message.answer(localize('admin.goods.add.prompt.description'), reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_item_description)


@router.message(AddItemFSM.waiting_item_description, F.text)
async def add_item_description(message: Message, state):
    """
    Save description and proceed to image upload.
    """
    await state.update_data(item_description=(message.text or "").strip())
    await message.answer(localize('admin.goods.add.prompt.image'), reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_item_image)


def _resolve_uploads_dir() -> str:
    env_dir = os.environ.get("UPLOADS_DIR")
    candidates = [
        env_dir,
        "/app/data/uploads",
        "/tmp/evrest_uploads",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "uploads"),
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
_MAX_PHOTO_BYTES = 3 * 1024 * 1024  # 3 MB


async def _ask_price(message: Message, state):
    await message.answer(
        localize('admin.goods.add.prompt.price', currency=EnvKeys.PAY_CURRENCY),
        reply_markup=back('goods_management'),
    )
    await state.set_state(AddItemFSM.waiting_item_price)


@router.message(AddItemFSM.waiting_item_image, F.photo)
async def add_item_image_photo(message: Message, state):
    """Save uploaded photo to uploads dir and proceed to price."""
    try:
        import io
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        ext = os.path.splitext(file.file_path or "")[1].lower() or ".jpg"
        if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
            ext = ".jpg"
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime = mime_map.get(ext, "image/jpeg")

        buf = io.BytesIO()
        await message.bot.download_file(file.file_path, destination=buf)
        raw = buf.getvalue()
        if len(raw) == 0 or len(raw) > _MAX_PHOTO_BYTES:
            await message.answer(localize('admin.goods.add.image.invalid'))
            return

        # Persist to DB (survives container restarts).
        from bot.database.main import Database
        from bot.database.models.main import ProductImage
        token = secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]
        async with Database().session() as s:
            s.add(ProductImage(token=token, mime=mime, data=raw, size=len(raw)))
            await s.commit()

        await state.update_data(item_image_url=f"/uploads/img/{token}")
        await message.answer(localize('admin.goods.add.image.saved'))
        await _ask_price(message, state)
    except Exception:
        await message.answer(localize('admin.goods.add.image.invalid'))


@router.message(AddItemFSM.waiting_item_image, F.text)
async def add_item_image_skip(message: Message, state):
    """Allow /skip or any text to bypass image step."""
    txt = (message.text or "").strip().lower()
    if txt in ("/skip", "skip", "пропустить"):
        await state.update_data(item_image_url=None)
        await _ask_price(message, state)
    else:
        await message.answer(localize('admin.goods.add.prompt.image'))


@router.message(AddItemFSM.waiting_item_price, F.text)
async def add_item_price(message: Message, state):
    """
    Validate price and ask for category.
    """
    price_text = (message.text or "").strip()
    if not price_text.isdigit():
        await message.answer(localize('admin.goods.add.price.invalid'), reply_markup=back('goods_management'))
        return

    await state.update_data(item_price=int(price_text))
    await message.answer(localize('admin.goods.add.prompt.category'), reply_markup=back('goods_management'))
    await state.set_state(AddItemFSM.waiting_category)


@router.message(AddItemFSM.waiting_category, F.text)
async def check_category_for_add_item(message: Message, state):
    """
    Category must exist; then ask about infinite mode.
    """
    category_name = (message.text or "").strip()
    category = await check_category_cached(category_name)
    if not category:
        await message.answer(
            localize('admin.goods.add.category.not_found'),
            reply_markup=back('goods_management')
        )
        return

    await state.update_data(item_category=category_name)
    await message.answer(
        localize('admin.goods.add.infinity.question'),
        reply_markup=question_buttons('infinity', 'goods_management')
    )
    await state.set_state(AddItemFSM.waiting_infinity)


@router.callback_query(F.data.startswith('infinity_'), AddItemFSM.waiting_infinity)
async def adding_value_to_position(call: CallbackQuery, state):
    """
    If infinite — wait for a single value.
    If not — collect multiple values until completion.
    """
    answer = call.data.split('_')[1]
    await state.update_data(is_infinity=(answer == 'yes'))

    if answer == 'no':
        # “Finish adding” button will appear after the first value is provided
        await call.message.edit_text(
            localize('admin.goods.add.values.prompt_multi'),
            reply_markup=back("goods_management")
        )
        await state.set_state(AddItemFSM.waiting_values)
    else:
        await call.message.edit_text(
            localize('admin.goods.add.single.prompt_value'),
            reply_markup=back('goods_management')
        )
        await state.set_state(AddItemFSM.waiting_single_value)


@router.message(AddItemFSM.waiting_values, F.text)
async def collect_item_value(message: Message, state):
    """
    Accumulate values in FSM state. After the first one — show a “Finish adding” button.
    """
    data = await state.get_data()
    values = data.get('item_values', [])
    value = (message.text or "")
    values.append(value)
    await state.update_data(item_values=values)

    # Show progress + “Finish adding” button
    await message.answer(
        localize('admin.goods.add.values.added', value=value, count=len(values)),
        reply_markup=simple_buttons([
            (localize('btn.add_values_finish'), "finish_adding_items"),
            (localize('btn.back'), "goods_management")
        ], per_row=1)
    )


@router.callback_query(F.data == 'finish_adding_items', AddItemFSM.waiting_values)
async def finish_adding_items_callback_handler(call: CallbackQuery, state):
    """
    Create a position, add all collected values, notify group (if configured).
    """
    data = await state.get_data()
    item_name = data.get('item_name')
    item_description = data.get('item_description')
    item_price = data.get('item_price')
    category_name = data.get('item_category')
    image_url = data.get('item_image_url')
    raw_values: list[str] = data.get("item_values", []) or []

    added = 0
    skipped_db_dup = 0
    skipped_batch_dup = 0
    skipped_invalid = 0
    seen_in_batch: set[str] = set()

    # Create position
    await create_item(item_name, item_description, item_price, category_name, image_url=image_url)

    for v in raw_values:
        v_norm = (v or "").strip()
        if not v_norm:
            skipped_invalid += 1
            continue

        # Duplicate within the current input batch
        if v_norm in seen_in_batch:
            skipped_batch_dup += 1
            continue
        seen_in_batch.add(v_norm)

        # Try to insert — False means it already exists in DB
        if await add_values_to_item(item_name, v_norm, False):
            added += 1
        else:
            skipped_db_dup += 1

    text_lines = [
        localize('admin.goods.add.result.created'),
        localize('admin.goods.add.result.added', n=added)
    ]
    if skipped_db_dup:
        text_lines.append(localize('admin.goods.add.result.skipped_db_dup', n=skipped_db_dup))
    if skipped_batch_dup:
        text_lines.append(localize('admin.goods.add.result.skipped_batch_dup', n=skipped_batch_dup))
    if skipped_invalid:
        text_lines.append(localize('admin.goods.add.result.skipped_invalid', n=skipped_invalid))

    await call.message.edit_text("\n".join(text_lines), parse_mode="HTML", reply_markup=back("goods_management"))

    item_info = await get_item_info_cached(item_name)
    try:
        item_price = float(item_info["price"]) if item_info else float(item_price or 0)
    except Exception:
        item_price = float(item_price or 0)

    # Notify channel via notifications service (includes Open App button)
    if added > 0:
        await notify_new_stock(call.bot, item_name, added, item_price, category_name or "")

    admin_info = await call.message.bot.get_chat(call.from_user.id)
    await log_audit("create_item", user_id=call.from_user.id, resource_type="Item", resource_id=item_name, details=f"admin={admin_info.first_name}")

    await state.clear()


@router.message(AddItemFSM.waiting_single_value, F.text)
async def finish_adding_item_callback_handler(message: Message, state):
    """
    Create a position and add one “infinite” value. Notify group (if configured).
    """
    data = await state.get_data()
    item_name = data.get('item_name')
    item_description = data.get('item_description')
    item_price = data.get('item_price')
    category_name = data.get('item_category')
    image_url = data.get('item_image_url')

    single_value = (message.text or "").strip()
    if not single_value:
        await message.answer(localize('admin.goods.add.single.empty'), reply_markup=back('goods_management'))
        return

    # 1) Create position
    await create_item(item_name, item_description, item_price, category_name, image_url=image_url)
    # 2) Add 1 “infinite” value
    await add_values_to_item(item_name, single_value, True)

    # 3) Notify channel via notifications service (includes Open App button)
    inf_item_info = await get_item_info_cached(item_name)
    try:
        inf_item_price = float(inf_item_info["price"]) if inf_item_info else float(item_price or 0)
    except Exception:
        inf_item_price = float(item_price or 0)
    await notify_new_stock(message.bot, item_name, "∞", inf_item_price, category_name or "")

    await message.answer(localize('admin.goods.add.single.created'), reply_markup=back('goods_management'))
    admin_info = await message.bot.get_chat(message.from_user.id)
    await log_audit("create_item", user_id=message.from_user.id, resource_type="Item", resource_id=item_name, details=f"admin={admin_info.first_name}, infinite=true")

    await state.clear()
