"""Логика платформы Яндекс Карты (только slug yandex_maps)."""

from __future__ import annotations

YANDEX_MAPS_SLUG = "yandex_maps"


def is_yandex_maps_slug(slug: str | None) -> bool:
    return (slug or "").strip().lower() == YANDEX_MAPS_SLUG


def parse_question_order(raw: str) -> tuple[list[int] | None, str | None]:
    """Порядок слотов 1–10 через запятую."""
    parts = [p.strip() for p in (raw or "").replace(";", ",").split(",") if p.strip()]
    if len(parts) != 10:
        return None, "Нужно ровно 10 номеров (слоты 1–10), через запятую."
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None, "Только целые числа от 1 до 10."
    if sorted(nums) != list(range(1, 11)):
        return None, "Каждый номер от 1 до 10 должен встретиться ровно один раз."
    return nums, None


def format_question_order(order: list[int]) -> str:
    return ",".join(str(x) for x in order)
