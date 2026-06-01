from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from database.models import Task, TaskText
from services.gender import gender_label
from services.reward_input import format_reward_rub


@dataclass
class PoolLine:
    number: int
    gender: str | None
    body: str
    status: str
    status_label: str
    publish_at: datetime | None
    taken: bool


def parse_number_list(raw: str) -> list[int]:
    parts = re.split(r"[,;\s]+", (raw or "").strip())
    out: list[int] = []
    for p in parts:
        p = p.strip()
        if p.isdigit():
            out.append(int(p))
    return sorted(set(out))


def classify_text(tt: TaskText, now: datetime | None = None) -> tuple[str, str]:
    now = now or datetime.utcnow()
    if tt.taken_by_user_id:
        return "taken", "взят пользователем"
    waiting = not tt.published or (tt.publish_at is not None and tt.publish_at > now)
    if waiting:
        if tt.publish_at:
            d = tt.publish_at.strftime("%d.%m.%Y")
            return "waiting", f"ожидает (публ. {d})"
        return "waiting", "ожидает публикации"
    return "active", "активен"


def build_pool_lines(texts: list[TaskText], now: datetime | None = None) -> list[PoolLine]:
    now = now or datetime.utcnow()
    lines: list[PoolLine] = []
    for tt in sorted(texts, key=lambda x: (x.text_number or 999999, x.id)):
        num = tt.text_number or tt.id
        st, label = classify_text(tt, now)
        lines.append(
            PoolLine(
                number=num,
                gender=tt.required_gender,
                body=tt.body,
                status=st,
                status_label=label,
                publish_at=tt.publish_at,
                taken=bool(tt.taken_by_user_id),
            )
        )
    return lines


def format_pool_message(task: Task, lines: list[PoolLine]) -> str:
    name = task.customer_name or task.title or "—"
    link = task.link or "—"
    active = [ln for ln in lines if ln.status == "active"]
    waiting = [ln for ln in lines if ln.status == "waiting"]
    taken = [ln for ln in lines if ln.status == "taken"]

    def _fmt_block(title: str, items: list[PoolLine]) -> str:
        if not items:
            return f"<b>{title}</b>\n— нет —\n"
        rows = []
        for ln in items:
            g = gender_label(ln.gender) if ln.gender else "—"
            preview = ln.body[:120].replace("<", "").replace(">", "")
            rows.append(f"{ln.number}. [{g}] {preview}… — <i>{ln.status_label}</i>")
        return f"<b>{title}</b>\n" + "\n".join(rows) + "\n"

    pay = format_reward_rub(task.reward) if task.reward and task.reward > 0 else "не указана"
    reg = task.region or "любой"
    return (
        f"<b>Заказчик:</b> {name}\n"
        f"<b>Регион:</b> {reg}\n"
        f"<b>Ссылка:</b> {link}\n"
        f"<b>Оплата за отзыв:</b> {pay}\n\n"
        + _fmt_block("Активные (ещё не взяты)", active)
        + "\n"
        + _fmt_block("Ожидают публикации", waiting)
        + ("\n" + _fmt_block("Уже взяты", taken) if taken else "")
    )
