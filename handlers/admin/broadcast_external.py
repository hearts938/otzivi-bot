from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from config import Settings
from database.models import User
from handlers.admin.common import is_admin
from handlers.admin.states import BroadcastExternalFSM
from handlers.formatting import blockquote
from handlers.keyboards import A_BROADCAST_EXTERNAL, admin_cancel_kb, admin_root_kb
from services.broadcast import (
    parse_external_button_url,
    resolve_telegram_attachment,
    run_broadcast,
)

router = Router(name="admin_broadcast_external")


@router.message(F.text == A_BROADCAST_EXTERNAL)
async def br_ext_start(message: Message, settings: Settings, state: FSMContext):
    if not is_admin(message.from_user.id, settings):
        return
    await state.set_state(BroadcastExternalFSM.text)
    await message.answer(
        f"🔗 <b>Рассылка на другое</b>\n\n"
        f"{blockquote('Введите текст сообщения. Далее — подпись кнопки и ссылку на сторонний ресурс (сайт, канал и т.д.).')}",
        reply_markup=admin_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(BroadcastExternalFSM.text, F.text)
async def br_ext_text(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(text=message.text or "")
    await state.set_state(BroadcastExternalFSM.button)
    await message.answer(
        "Текст кнопки под сообщением (например «Перейти»):",
        reply_markup=admin_cancel_kb(),
    )


@router.message(BroadcastExternalFSM.button, F.text)
async def br_ext_btn(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    await state.update_data(btn=(message.text or "Перейти").strip()[:64])
    await state.set_state(BroadcastExternalFSM.url)
    await message.answer(
        "Ссылка для кнопки (https://…):",
        reply_markup=admin_cancel_kb(),
    )


@router.message(BroadcastExternalFSM.url, F.text)
async def br_ext_url(message: Message, state: FSMContext, settings: Settings):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    url = parse_external_button_url(message.text)
    if not url:
        await message.answer(
            "Нужна ссылка, начинающаяся с http:// или https://",
            reply_markup=admin_cancel_kb(),
        )
        return
    await state.update_data(url=url)
    await state.set_state(BroadcastExternalFSM.photo)
    await message.answer(
        "Пришлите фото или файл (необязательно).\nИли напишите «нет».",
        reply_markup=admin_cancel_kb(),
    )


@router.message(BroadcastExternalFSM.photo, F.text)
async def br_ext_attachment_skip(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    if (message.text or "").strip().lower() not in ("нет", "no", "-"):
        await message.answer(
            "Пришлите фото/файл или напишите «нет».",
            reply_markup=admin_cancel_kb(),
        )
        return
    data = await state.get_data()
    await state.clear()
    await _run_external_broadcast(
        message,
        session_factory,
        data.get("text", ""),
        data.get("btn", "Перейти"),
        data.get("url", ""),
        None,
        None,
    )


@router.message(BroadcastExternalFSM.photo, F.photo)
async def br_ext_attachment_photo(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    await _run_external_broadcast(
        message,
        session_factory,
        data.get("text", ""),
        data.get("btn", "Перейти"),
        data.get("url", ""),
        photo_file_id=message.photo[-1].file_id,
        document=None,
    )


@router.message(BroadcastExternalFSM.photo, F.document)
async def br_ext_attachment_document(
    message: Message,
    state: FSMContext,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
):
    if not is_admin(message.from_user.id, settings):
        await state.clear()
        return
    data = await state.get_data()
    await state.clear()
    await _run_external_broadcast(
        message,
        session_factory,
        data.get("text", ""),
        data.get("btn", "Перейти"),
        data.get("url", ""),
        photo_file_id=None,
        document=message.document,
    )


async def _run_external_broadcast(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    text: str,
    btn: str,
    url: str,
    photo_file_id: str | None,
    document,
) -> None:
    link = parse_external_button_url(url)
    if not link:
        await message.answer("Некорректная ссылка.", reply_markup=admin_root_kb())
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=btn, url=link)]]
    )
    attachment = await resolve_telegram_attachment(
        message.bot,
        photo_file_id=photo_file_id,
        document_file_id=document.file_id if document else None,
        document_mime=document.mime_type if document else None,
        document_filename=document.file_name if document else None,
    )
    async with session_factory() as session:
        r = await session.execute(select(User.telegram_id))
        ids = [row[0] for row in r.all()]
    await message.answer(
        f"Рассылка на другое: {len(ids)} получателей…",
        reply_markup=admin_root_kb(),
    )
    ok, bad = await run_broadcast(
        message.bot,
        ids,
        text=text,
        reply_markup=kb,
        attachment=attachment,
    )
    await message.answer(f"Готово. Успешно: {ok}, ошибок: {bad}.", reply_markup=admin_root_kb())
