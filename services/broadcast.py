"""Рассылка: фото как картинка, остальные файлы — как документ."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

IMAGE_MIMES = frozenset({
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/webp",
})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp"})


def parse_external_button_url(raw: str | None) -> str | None:
    """Ссылка для inline-кнопки (сторонний ресурс)."""
    s = (raw or "").strip()
    if len(s) < 12 or not s.startswith(("http://", "https://")):
        return None
    return s[:2048]


def sniff_is_image(data: bytes) -> bool:
    if len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    return False


def is_image_attachment(
    mime_type: str | None,
    filename: str | None,
    data: bytes | None = None,
) -> bool:
    mime = (mime_type or "").strip().lower()
    if mime in IMAGE_MIMES or mime.startswith("image/"):
        return True
    name = (filename or "").strip().lower()
    if name:
        dot = name.rfind(".")
        if dot >= 0 and name[dot:] in IMAGE_EXTENSIONS:
            return True
    return bool(data and sniff_is_image(data))


def photo_filename_for_upload(data: bytes, filename: str | None) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image.jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image.png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image.gif"
    if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image.webp"
    name = (filename or "").strip()
    if name:
        base = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        dot = base.rfind(".")
        if dot >= 0 and base[dot:].lower() in IMAGE_EXTENSIONS:
            return base
    return "image.jpg"


async def read_upload_file(upload) -> tuple[bytes, str | None, str | None]:
    if upload is None or not hasattr(upload, "read"):
        return b"", None, None
    data = await upload.read()
    filename = (getattr(upload, "filename", None) or "").strip() or None
    content_type = (getattr(upload, "content_type", None) or "").strip() or None
    return data, filename, content_type


@dataclass
class BroadcastAttachment:
    """photo_id — file_id фото; photo_bytes — картинка из файла; document_id — не-картинка."""

    kind: str  # none | photo_id | photo_bytes | document_id
    photo_id: str | None = None
    photo_bytes: bytes | None = None
    photo_filename: str = "image.jpg"
    document_id: str | None = None
    document_filename: str | None = None
    document_bytes: bytes | None = None

    @property
    def has_media(self) -> bool:
        return self.kind != "none"


async def resolve_telegram_attachment(
    bot: Bot,
    *,
    photo_file_id: str | None = None,
    document_file_id: str | None = None,
    document_mime: str | None = None,
    document_filename: str | None = None,
) -> BroadcastAttachment:
    if photo_file_id:
        return BroadcastAttachment(kind="photo_id", photo_id=photo_file_id)
    if not document_file_id:
        return BroadcastAttachment(kind="none")
    if is_image_attachment(document_mime, document_filename):
        tg_file = await bot.get_file(document_file_id)
        buf = BytesIO()
        await bot.download(tg_file, destination=buf)
        name = (document_filename or "image.jpg").strip() or "image.jpg"
        return BroadcastAttachment(
            kind="photo_bytes",
            photo_bytes=buf.getvalue(),
            photo_filename=name,
        )
    return BroadcastAttachment(
        kind="document_id",
        document_id=document_file_id,
        document_filename=document_filename or "file",
    )


def attachment_from_upload(
    data: bytes,
    *,
    filename: str | None,
    mime_type: str | None,
) -> BroadcastAttachment:
    if not data:
        return BroadcastAttachment(kind="none")
    name = (filename or "file").strip() or "file"
    if is_image_attachment(mime_type, name, data):
        return BroadcastAttachment(
            kind="photo_bytes",
            photo_bytes=data,
            photo_filename=photo_filename_for_upload(data, name),
        )
    return BroadcastAttachment(
        kind="document_id",
        document_filename=name,
        document_bytes=data,
    )


async def send_broadcast_message(
    bot: Bot,
    chat_id: int,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    attachment: BroadcastAttachment,
) -> None:
    cap = (text or "")[:1024] or None
    if attachment.kind == "photo_id" and attachment.photo_id:
        await bot.send_photo(
            chat_id,
            attachment.photo_id,
            caption=cap,
            reply_markup=reply_markup,
        )
        return
    if attachment.kind == "photo_bytes" and attachment.photo_bytes:
        await bot.send_photo(
            chat_id,
            BufferedInputFile(attachment.photo_bytes, filename=attachment.photo_filename),
            caption=cap,
            reply_markup=reply_markup,
        )
        return
    if attachment.kind == "document_id":
        if attachment.document_id:
            await bot.send_document(
                chat_id,
                attachment.document_id,
                caption=cap,
                reply_markup=reply_markup,
            )
            return
        raw = attachment.document_bytes
        if raw:
            await bot.send_document(
                chat_id,
                BufferedInputFile(raw, filename=attachment.document_filename or "file"),
                caption=cap,
                reply_markup=reply_markup,
            )
            return
    await bot.send_message(chat_id, text[:3500], reply_markup=reply_markup)


async def run_broadcast(
    bot: Bot,
    user_ids: list[int],
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    attachment: BroadcastAttachment,
    delay: float = 0.05,
) -> tuple[int, int]:
    ok, bad = 0, 0
    for tid in user_ids:
        try:
            await send_broadcast_message(
                bot,
                tid,
                text=text,
                reply_markup=reply_markup,
                attachment=attachment,
            )
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            bad += 1
        if delay > 0:
            await asyncio.sleep(delay)
    return ok, bad
