from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd


@dataclass
class ImportedTask:
    title: str
    description: str
    reward: float
    link: str | None
    platform_slug: str | None


def _norm(s: str) -> str:
    return str(s).strip().lower().replace("ё", "е")


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


def _float_cell(row: dict, *keys: str) -> float:
    raw = _pick_row(row, *keys)
    if raw is None:
        return 0.0
    raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def parse_tasks_excel(file_bytes: bytes) -> tuple[list[ImportedTask], list[str]]:
    errors: list[str] = []
    df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    if df.empty:
        return [], ["Файл пустой или нет строк с данными."]
    df.columns = [str(c).strip() for c in df.columns]
    tasks: list[ImportedTask] = []
    for idx, row in df.iterrows():
        r = row.to_dict()
        title = _pick_row(r, "title", "заголовок", "название", "name", "имя")
        if not title:
            errors.append(f"Строка {int(idx) + 2}: нет колонки заголовка (title / заголовок).")
            continue
        desc = _pick_row(r, "description", "описание", "text", "текст") or ""
        reward = _float_cell(r, "reward", "вознаграждение", "сумма", "оплата", "price")
        link = _pick_row(r, "link", "ссылка", "url")
        plat = _pick_row(r, "platform", "платформа", "slug", "сервис")
        tasks.append(
            ImportedTask(
                title=title[:512],
                description=desc[:10000],
                reward=max(0.0, reward),
                link=link[:1024] if link else None,
                platform_slug=plat.lower().strip() if plat else None,
            )
        )
    return tasks, errors
