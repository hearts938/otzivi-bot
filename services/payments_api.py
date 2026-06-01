from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from config import Settings


@dataclass
class PaymentCreateResult:
    ok: bool
    status: str
    payment_id: str | None
    error_message: str | None = None
    raw: dict[str, Any] | None = None


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Authorization": settings.payments_api_auth,
        "Content-Type": "application/json",
    }


def _make_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _http_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout: int,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(url=url, data=data, method=method.upper(), headers=headers)
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)


def create_fps_payment(
    settings: Settings,
    *,
    amount: float,
    service_title: str,
    purpose: str,
    fps_mobile_phone: str,
    fps_bank_member_id: str,
    first_name: str | None,
    last_name: str | None,
    patronymic: str | None = None,
) -> PaymentCreateResult:
    if not settings.payments_api_auth:
        return PaymentCreateResult(
            ok=False,
            status="failed",
            payment_id=None,
            error_message="Не настроен PAYMENTS_API_AUTH",
        )
    payload: dict[str, Any] = {
        "services_list": [{"title": service_title[:255], "amount": f"{float(amount):.2f}"}],
        "bank_details_kind": "fps",
        "bank_details": {
            "fps_mobile_phone": fps_mobile_phone.strip(),
            "fps_bank_member_id": fps_bank_member_id.strip(),
        },
        "purpose": purpose[:512],
        "amount": f"{float(amount):.2f}",
        "contractor": {
            "first_name": (first_name or "").strip() or None,
            "last_name": (last_name or "").strip() or None,
            "patronymic": (patronymic or "").strip() or None,
        },
    }
    url = _make_url(settings.payments_api_base_url, "/api/v1/payments")
    try:
        raw = _http_json(
            method="POST",
            url=url,
            headers=_headers(settings),
            payload=payload,
            timeout=max(5, int(settings.payments_api_timeout_seconds)),
        )
        status = str(raw.get("status") or "").strip().lower() or "created"
        pid = str(raw.get("id") or "").strip() or None
        ok = status in {"created", "manualpay", "executed"}
        msg = raw.get("error_message")
        return PaymentCreateResult(
            ok=ok,
            status=status,
            payment_id=pid,
            error_message=str(msg) if msg else None,
            raw=raw,
        )
    except error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        em = body.strip() or f"HTTP {e.code}"
        return PaymentCreateResult(ok=False, status="failed", payment_id=None, error_message=em)
    except Exception as e:
        return PaymentCreateResult(ok=False, status="failed", payment_id=None, error_message=str(e))

