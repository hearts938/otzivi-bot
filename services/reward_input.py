"""Парсинг и форматирование суммы вознаграждения (₽)."""

from __future__ import annotations


def parse_reward_amount(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", ".").replace("₽", "").replace("руб", "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 0:
        return None
    return round(v, 2)


def format_reward_rub(amount: float) -> str:
    v = max(0.0, float(amount))
    if v == int(v):
        return f"{int(v)} ₽"
    return f"{v:.2f} ₽"
