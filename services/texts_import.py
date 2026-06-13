from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from services.gender import parse_gender
from services.reward_input import parse_reward_amount
from services.timezone_util import publish_at_midnight


@dataclass
class ImportedReviewText:
    text_number: int
    customer_name: str | None
    link: str
    gender: str
    body: str
    publish_at: datetime
    reward: float = 0.0
    org_address: str | None = None


def _norm(s: str) -> str:
    return str(s).strip().lower().replace("ё", "е")


def normalize_import_body(body: str) -> str:
    """Единая нормализация текста отзыва для сравнения при импорте."""
    s = str(body or "").strip().lower().replace("ё", "е")
    return re.sub(r"\s+", " ", s)


def import_body_key(body: str) -> str:
    """Ключ текста для проверки дубликатов внутри одного заказчика."""
    return normalize_import_body(body)


def _pick_row(row: dict, *keys: str) -> str | None:
    row_norm = {_norm(k): v for k, v in row.items() if k is not None and not pd.isna(k)}
    for key in keys:
        nk = _norm(key)
        if nk in row_norm and not pd.isna(row_norm[nk]):
            val = row_norm[nk]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            return str(val).strip()
    return None


def _parse_reward(row: dict) -> float:
    raw = _pick_row(
        row,
        "вознаграждение",
        "оплата",
        "стоимость",
        "цена",
        "сумма",
        "reward",
        "price",
    )
    if raw is None:
        return 0.0
    v = parse_reward_amount(raw)
    return v if v is not None else 0.0


def _parse_number(row: dict) -> int | None:
    raw = _pick_row(row, "номер", "number", "num", "id", "№")
    if raw is None:
        return None
    try:
        return int(float(raw.replace(",", ".")))
    except ValueError:
        return None


def _parse_publish_date(row: dict, tz_name: str) -> datetime | None:
    row_norm = {_norm(k): v for k, v in row.items() if k is not None and not pd.isna(k)}
    val = None
    for key in ("дата публикации", "дата", "publish date", "publish_at", "date"):
        nk = _norm(key)
        if nk in row_norm and not pd.isna(row_norm[nk]):
            val = row_norm[nk]
            break
    if val is None:
        return None
    if isinstance(val, datetime):
        d = val.date()
    elif isinstance(val, date):
        d = val
    elif isinstance(val, pd.Timestamp):
        d = val.date()
    else:
        s = str(val).strip()
        if not s:
            return None
        try:
            d = pd.to_datetime(s, dayfirst=True).date()
        except Exception:
            return None
    return publish_at_midnight(d, tz_name)


def looks_like_xlsx(filename: str | None, raw: bytes) -> bool:
    """xlsx — ZIP-архив (PK); расширение иногда отсутствует или неверное."""
    if len(raw) >= 2 and raw[:2] == b"PK":
        return True
    return (filename or "").lower().endswith(".xlsx")


def parse_review_texts_excel(file_bytes: bytes, tz_name: str) -> tuple[list[ImportedReviewText], list[str]]:
    errors: list[str] = []
    try:
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    except Exception as exc:
        return [], [
            "Не удалось прочитать файл как .xlsx. "
            "Сохраните книгу в Excel: «Файл → Сохранить как → Книга Excel (.xlsx)».",
            f"Технически: {exc}",
        ]
    if df.empty:
        return [], ["Файл пустой."]
    df.columns = [str(c).strip() for c in df.columns]
    items: list[ImportedReviewText] = []
    for idx, row in df.iterrows():
        r = row.to_dict()
        num = _parse_number(r)
        if num is None:
            errors.append(f"Строка {int(idx) + 2}: нет номера текста.")
            continue
        link = _pick_row(r, "ссылка", "link", "url")
        if not link:
            errors.append(f"Строка {int(idx) + 2}: нет ссылки.")
            continue
        customer = _pick_row(r, "заказчик", "customer", "клиент", "имя заказчика")
        address = _pick_row(r, "адрес", "address", "org_address", "адрес организации")
        gender_raw = _pick_row(r, "пол", "gender", "sex")
        gender = parse_gender(gender_raw) if gender_raw else None
        if not gender:
            errors.append(f"Строка {int(idx) + 2}: пол должен быть М или Ж.")
            continue
        body = _pick_row(r, "текст", "text", "body", "отзыв")
        if not body:
            errors.append(f"Строка {int(idx) + 2}: нет текста.")
            continue
        pub = _parse_publish_date(r, tz_name)
        if pub is None:
            errors.append(f"Строка {int(idx) + 2}: нет даты публикации.")
            continue
        items.append(
            ImportedReviewText(
                text_number=num,
                customer_name=customer[:512] if customer else None,
                link=link[:1024],
                gender=gender,
                body=body[:20000],
                publish_at=pub,
                reward=_parse_reward(r),
                org_address=address[:1024] if address else None,
            )
        )
    return items, errors
