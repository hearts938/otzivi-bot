"""Логика платформы Яндекс Карты (только slug yandex_maps)."""

from __future__ import annotations

YANDEX_MAPS_SLUG = "yandex_maps"
YANDEX_QUIZ_POOL_SIZE = 2
YANDEX_QUIZ_MIN_COUNT = 10
YANDEX_QUIZ_MAX_COUNT = 15
YANDEX_QUIZ_MAX_SLOT = 15
YANDEX_QUIZ_DEFAULT_ORDER_KEY = "yandex_quiz_default_order"


def is_yandex_maps_slug(slug: str | None) -> bool:
    return (slug or "").strip().lower() == YANDEX_MAPS_SLUG


def default_question_order(count: int = YANDEX_QUIZ_MIN_COUNT) -> list[int]:
    n = max(YANDEX_QUIZ_MIN_COUNT, min(YANDEX_QUIZ_MAX_COUNT, int(count)))
    return list(range(1, n + 1))


def parse_question_order(raw: str) -> tuple[list[int] | None, str | None]:
    """Порядок слотов 1–15 через запятую, от 10 до 15 вопросов без повторов."""
    parts = [p.strip() for p in (raw or "").replace(";", ",").split(",") if p.strip()]
    if not (YANDEX_QUIZ_MIN_COUNT <= len(parts) <= YANDEX_QUIZ_MAX_COUNT):
        return (
            None,
            f"Нужно от {YANDEX_QUIZ_MIN_COUNT} до {YANDEX_QUIZ_MAX_COUNT} номеров "
            f"(слоты 1–{YANDEX_QUIZ_MAX_SLOT}), через запятую.",
        )
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None, f"Только целые числа от 1 до {YANDEX_QUIZ_MAX_SLOT}."
    if len(set(nums)) != len(nums):
        return None, "Номера слотов не должны повторяться."
    if any(n < 1 or n > YANDEX_QUIZ_MAX_SLOT for n in nums):
        return None, f"Каждый номер от 1 до {YANDEX_QUIZ_MAX_SLOT}."
    return nums, None


def format_question_order(order: list[int]) -> str:
    return ",".join(str(x) for x in order)
