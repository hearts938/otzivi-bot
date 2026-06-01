"""Ввод кулдауна платформы в часах (дробные значения)."""

from __future__ import annotations

COOLDOWN_HOURS_PROMPT = (
    "Укажите кулдаун в <b>часах</b>.\n\n"
    "<b>Формат:</b> число целое или с точкой/запятой — дробная часть = доли часа.\n"
    "Примеры: <code>0</code> (без задержки), <code>4</code>, <code>4.5</code> (4½ часа), <code>1,5</code>\n\n"
    "Можно добавить «ч» или «часов» в конце: <code>4.5 ч</code>"
)

COOLDOWN_HOURS_INVALID = (
    "Не удалось разобрать значение.\n\n"
    "Введите число часов, например: <code>4</code> или <code>4.5</code> (четыре с половиной часа)."
)


def parse_cooldown_hours(raw: str) -> float | None:
    s = (raw or "").strip().lower().replace(",", ".")
    for suffix in (" часов", " часа", " час", "часов", "часа", "ч", "h"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break
    s = s.replace(" ", "")
    if not s:
        return None
    try:
        hours = float(s)
    except ValueError:
        return None
    if hours < 0:
        return None
    return hours


def hours_to_cooldown_seconds(hours: float) -> int:
    return max(0, int(round(hours * 3600)))


def format_cooldown_hours(seconds: int) -> str:
    if seconds <= 0:
        return "0 ч"
    hours = seconds / 3600
    if abs(hours - round(hours)) < 0.05:
        return f"{int(round(hours))} ч"
    text = f"{hours:.2f}".rstrip("0").rstrip(".")
    return f"{text} ч"
