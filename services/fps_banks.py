"""Справочник банков СБП для вывода (Консоль.Про API)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from config import Settings
from services.payments_api import _headers, _make_url, _parse_api_error_body


@dataclass(frozen=True)
class FpsBank:
    member_id: str
    title: str


# Запасной список, если API временно недоступен (id как в Консоль.Про).
FALLBACK_FPS_BANKS: tuple[FpsBank, ...] = (
    FpsBank("sberbank", "Сбербанк"),
    FpsBank("t_bank", "Т-Банк"),
    FpsBank("vtb", "ВТБ"),
    FpsBank("alfa_bank", "Альфа-Банк"),
    FpsBank("raiffeisen", "Райффайзенбанк"),
    FpsBank("gazprombank", "Газпромбанк"),
    FpsBank("rosbank", "Росбанк"),
    FpsBank("sovcombank", "Совкомбанк"),
    FpsBank("pochta_bank", "Почта Банк"),
    FpsBank("mts_bank", "МТС Банк"),
    FpsBank("ozon_bank", "OZON Банк"),
    FpsBank("yandex_bank", "Яндекс Банк"),
    FpsBank("psb", "ПСБ"),
    FpsBank("rshb", "Россельхозбанк"),
    FpsBank("uralsib", "Уралсиб"),
    FpsBank("open", "Открытие"),
)

_CACHE_TTL_SECONDS = 3600
_cache: tuple[float, list[FpsBank], str | None] | None = None


def _parse_bank_item(item: Any) -> FpsBank | None:
    if isinstance(item, str):
        s = item.strip()
        if s:
            return FpsBank(member_id=s, title=s)
        return None
    if not isinstance(item, dict):
        return None
    member_id: str | None = None
    for key in ("fps_bank_member_id", "member_id", "id", "code", "slug", "bank_id"):
        val = item.get(key)
        if val is not None and str(val).strip():
            member_id = str(val).strip()
            break
    if not member_id:
        return None
    title: str | None = None
    for key in ("name", "title", "label", "bank_name", "display_name", "short_name"):
        val = item.get(key)
        if val is not None and str(val).strip():
            title = str(val).strip()
            break
    return FpsBank(member_id=member_id, title=title or member_id)


def _parse_banks_payload(raw: Any) -> list[FpsBank]:
    items: list[Any] | None = None
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        for key in ("fps_banks", "banks", "data", "items", "results"):
            val = raw.get(key)
            if isinstance(val, list):
                items = val
                break
        if items is None:
            one = _parse_bank_item(raw)
            return [one] if one else []
    if not items:
        return []
    out: list[FpsBank] = []
    seen: set[str] = set()
    for item in items:
        bank = _parse_bank_item(item)
        if not bank or bank.member_id in seen:
            continue
        seen.add(bank.member_id)
        out.append(bank)
    out.sort(key=lambda b: b.title.casefold())
    return out


def _fetch_fps_banks_from_api(settings: Settings) -> tuple[list[FpsBank], str | None]:
    if not settings.payments_api_auth:
        return [], "Не настроен PAYMENTS_API_AUTH"
    url = _make_url(settings.payments_api_base_url, "/api/v1/payments/fps_banks")
    req = request.Request(
        url=url,
        method="GET",
        headers={**_headers(settings), "Accept": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=max(5, int(settings.payments_api_timeout_seconds))) as resp:
            import json

            raw_text = resp.read().decode("utf-8")
            raw = json.loads(raw_text) if raw_text.strip() else []
    except error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        em = _parse_api_error_body(body) or f"HTTP {e.code}"
        return [], em
    except Exception as e:
        return [], str(e)
    banks = _parse_banks_payload(raw)
    if not banks:
        return [], "Пустой список банков от API"
    return banks, None


def get_fps_banks(settings: Settings, *, force_refresh: bool = False) -> tuple[list[FpsBank], str | None]:
    """Список банков для СБП: из API, при ошибке — запасной список."""
    global _cache
    now = time.time()
    if (
        not force_refresh
        and _cache is not None
        and now - _cache[0] < _CACHE_TTL_SECONDS
    ):
        return _cache[1], _cache[2]

    banks, err = _fetch_fps_banks_from_api(settings)
    if not banks:
        banks = list(FALLBACK_FPS_BANKS)
        if err:
            err = f"{err} (показан базовый список банков)"
    _cache = (now, banks, err)
    return banks, err


def fps_bank_title(member_id: str, banks: list[FpsBank] | None = None) -> str:
    mid = (member_id or "").strip()
    if banks:
        for b in banks:
            if b.member_id == mid:
                return b.title
    for b in FALLBACK_FPS_BANKS:
        if b.member_id == mid:
            return b.title
    return mid or "—"
