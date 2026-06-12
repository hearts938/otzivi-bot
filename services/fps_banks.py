"""Справочник банков СБП для вывода (Консоль.Про API + НСПК)."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from config import Settings
from services.payments_api import _headers, _make_url, _parse_api_error_body

NSPK_BANKS_URL = "https://qr.nspk.ru/proxyapp/c2bmembers.json"
_NSPK_MEMBER_RE = re.compile(r"^(\d{10,15})$")

@dataclass(frozen=True)
class FpsBank:
    member_id: str
    title: str


# Последний запасной вариант — только коды НСПК (не slug вроде t_bank).
MINIMAL_FPS_BANKS: tuple[FpsBank, ...] = (
    FpsBank("100000000111", "Сбербанк"),
    FpsBank("100000000004", "Т-Банк"),
    FpsBank("100000000005", "ВТБ"),
    FpsBank("100000000008", "Альфа-Банк"),
    FpsBank("100000000007", "Райффайзенбанк"),
    FpsBank("100000000001", "Газпромбанк"),
    FpsBank("100000000012", "Росбанк"),
    FpsBank("100000000013", "Совкомбанк"),
    FpsBank("100000000010", "ПСБ"),
    FpsBank("100000000020", "Россельхозбанк"),
    FpsBank("100000000015", "Открытие"),
)

_CACHE_TTL_SECONDS = 3600
_cache: tuple[float, list[FpsBank], str | None] | None = None
_nspk_cache: tuple[float, list[FpsBank]] | None = None


def member_id_from_schema(schema: str | None) -> str | None:
    s = (schema or "").strip()
    if not s:
        return None
    if s.startswith("bank"):
        s = s[4:]
    if _NSPK_MEMBER_RE.match(s):
        return s
    return None


def _is_nspk_member_id(value: str | None) -> bool:
    return bool(value and _NSPK_MEMBER_RE.match(value.strip()))


def _pick_member_id(item: dict[str, Any]) -> str | None:
    candidates: list[str] = []
    schema_id = member_id_from_schema(str(item.get("schema") or ""))
    if schema_id:
        candidates.append(schema_id)
    for key in (
        "fps_bank_member_id",
        "member_id",
        "bank_member_id",
        "nspk_id",
        "id",
        "code",
        "slug",
        "bank_id",
    ):
        val = item.get(key)
        if val is not None and str(val).strip():
            candidates.append(str(val).strip())
    for c in candidates:
        if _is_nspk_member_id(c):
            return c
    return candidates[0] if candidates else None


def _parse_bank_item(item: Any) -> FpsBank | None:
    if isinstance(item, str):
        s = item.strip()
        if _is_nspk_member_id(s):
            return FpsBank(member_id=s, title=s)
        schema_id = member_id_from_schema(s)
        if schema_id:
            return FpsBank(member_id=schema_id, title=schema_id)
        return None
    if not isinstance(item, dict):
        return None
    member_id = _pick_member_id(item)
    if not member_id or not _is_nspk_member_id(member_id):
        return None
    title: str | None = None
    for key in ("bankName", "name", "title", "label", "bank_name", "display_name", "short_name"):
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
        if raw.get("success") is False:
            return []
        for key in ("fps_banks", "banks", "data", "items", "results", "dictionary"):
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


def _fetch_nspk_banks() -> list[FpsBank]:
    global _nspk_cache
    now = time.time()
    if _nspk_cache is not None and now - _nspk_cache[0] < _CACHE_TTL_SECONDS:
        return _nspk_cache[1]
    req = request.Request(NSPK_BANKS_URL, method="GET", headers={"Accept": "application/json"})
    with request.urlopen(req, timeout=30) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    banks = _parse_banks_payload(raw)
    if not banks:
        banks = list(MINIMAL_FPS_BANKS)
    _nspk_cache = (now, banks)
    return banks


def get_fps_banks(settings: Settings, *, force_refresh: bool = False) -> tuple[list[FpsBank], str | None]:
    """Список банков: API Консоль.Про → справочник НСПК → минимальный запасной список."""
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
        try:
            banks = _fetch_nspk_banks()
            if err:
                err = f"{err}. Показан официальный справочник НСПК."
            else:
                err = None
        except Exception as nspk_exc:
            banks = list(MINIMAL_FPS_BANKS)
            parts = [p for p in (err, str(nspk_exc)) if p]
            err = ". ".join(parts) + ". Показан базовый список банков."
    _cache = (now, banks, err)
    return banks, err


def _norm_search(text: str) -> str:
    s = (text or "").strip().lower().replace("ё", "е")
    for ch in "-—_./\\":
        s = s.replace(ch, " ")
    return " ".join(s.split())


# Популярные синонимы → подстрока в названии банка из справочника.
_SEARCH_ALIASES: tuple[tuple[str, str], ...] = (
    ("сбер", "сбер"),
    ("sber", "сбер"),
    ("тинькофф", "т банк"),
    ("tinkoff", "т банк"),
    ("тбанк", "т банк"),
    ("т банк", "т банк"),
    ("втб", "втб"),
    ("альфа", "альфа"),
    ("ozon", "ozon"),
    ("озон", "ozon"),
    ("яндекс", "яндекс"),
    ("yandex", "яндекс"),
    ("райф", "райфф"),
    ("газпром", "газпром"),
    ("совком", "совком"),
    ("россельхоз", "россельхоз"),
    ("рсхб", "россельхоз"),
    ("почта", "почта"),
    ("мтс", "мтс"),
    ("открытие", "открыт"),
    ("псб", "псб"),
    ("промсвязь", "промсвяз"),
)


def _expand_search_tokens(query: str) -> list[str]:
    q = _norm_search(query)
    if not q:
        return []
    tokens = q.split()
    expanded: list[str] = []
    for token in tokens:
        repl = token
        for alias, needle in _SEARCH_ALIASES:
            if token == _norm_search(alias) or token.startswith(_norm_search(alias)):
                repl = needle
                break
        expanded.append(repl)
    return expanded


def search_fps_banks(banks: list[FpsBank], query: str) -> list[FpsBank]:
    """Поиск банка по части названия (регистр и «ё» не важны)."""
    tokens = _expand_search_tokens(query)
    if not tokens:
        return []
    hits: list[FpsBank] = []
    for bank in banks:
        title = _norm_search(bank.title)
        if all(token in title for token in tokens):
            hits.append(bank)
    if not hits and len(tokens) == 1:
        token = tokens[0]
        hits = [b for b in banks if token in _norm_search(b.title)]
    hits.sort(key=lambda b: (len(b.title), b.title.casefold()))
    return hits


def fps_bank_title(member_id: str, banks: list[FpsBank] | None = None) -> str:
    mid = (member_id or "").strip()
    if banks:
        for b in banks:
            if b.member_id == mid:
                return b.title
    for b in MINIMAL_FPS_BANKS:
        if b.member_id == mid:
            return b.title
    try:
        for b in _fetch_nspk_banks():
            if b.member_id == mid:
                return b.title
    except Exception:
        pass
    return mid or "—"
