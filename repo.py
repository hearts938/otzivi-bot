from __future__ import annotations

import re
import secrets
import string
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    AppSetting,
    Platform,
    Submission,
    SubmissionStatus,
    SupportAdminMessage,
    SupportTicket,
    SupportTicketStatus,
    Task,
    TaskText,
    User,
    UserTextRefusal,
    WithdrawalAdminStatus,
    WithdrawalRequest,
    WithdrawalStatus,
    YandexMapsQuestion,
    YandexMapsSession,
)
from services.yandex_maps import (
    YANDEX_QUIZ_DEFAULT_ORDER_KEY,
    default_question_order,
    format_question_order,
    is_yandex_maps_slug,
    parse_question_order,
)
from services.cooldown import compute_cooldown_until
from services.cooldown import release_expired_cooldowns


def _random_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


async def get_user_by_telegram(session: AsyncSession, telegram_id: int) -> User | None:
    r = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return r.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_referral_code(session: AsyncSession, code: str) -> User | None:
    r = await session.execute(select(User).where(User.referral_code == code.upper()))
    return r.scalar_one_or_none()


async def ensure_user(
    session: AsyncSession,
    telegram_id: int,
    username: str | None,
    referred_by_id: int | None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    u = await get_user_by_telegram(session, telegram_id)
    if u:
        changed = False
        if username is not None and u.username != username:
            u.username = username
            changed = True
        if first_name is not None and u.first_name != first_name:
            u.first_name = first_name
            changed = True
        if last_name is not None and u.last_name != last_name:
            u.last_name = last_name
            changed = True
        if referred_by_id and u.referred_by_id is None and referred_by_id != u.id:
            u.referred_by_id = referred_by_id
            changed = True
        if changed:
            await session.commit()
        return u
    code = _random_code()
    for _ in range(20):
        clash = await get_user_by_referral_code(session, code)
        if not clash:
            break
        code = _random_code()
    u = User(
        telegram_id=telegram_id,
        username=username,
        first_name=first_name,
        last_name=last_name,
        referral_code=code,
        referred_by_id=referred_by_id,
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


async def touch_activity(session: AsyncSession, user_id: int) -> None:
    await session.execute(update(User).where(User.id == user_id).values(last_activity_at=datetime.utcnow()))
    await session.commit()


async def count_users(session: AsyncSession) -> int:
    q = await session.execute(select(func.count(User.id)))
    return int(q.scalar_one() or 0)


async def list_users_admin(session: AsyncSession, limit: int = 200) -> list[User]:
    r = await session.execute(select(User).order_by(User.id.desc()).limit(limit))
    return list(r.scalars().all())


async def list_users_admin_page(
    session: AsyncSession, offset: int, limit: int
) -> list[User]:
    r = await session.execute(
        select(User).order_by(User.id.desc()).offset(max(0, offset)).limit(limit)
    )
    return list(r.scalars().all())


async def count_referred_users(session: AsyncSession, inviter_id: int) -> int:
    q = await session.execute(
        select(func.count(User.id)).where(User.referred_by_id == inviter_id)
    )
    return int(q.scalar_one() or 0)


async def count_approved_submissions(session: AsyncSession, user_id: int) -> int:
    q = await session.execute(
        select(func.count(Submission.id)).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.APPROVED,
        )
    )
    return int(q.scalar_one() or 0)


async def list_users_with_stats(session: AsyncSession, limit: int = 200) -> list[tuple[User, int]]:
    users = await list_users_admin(session, limit=limit)
    out: list[tuple[User, int]] = []
    for u in users:
        c = await count_approved_submissions(session, u.id)
        out.append((u, c))
    return out


async def set_user_banned(session: AsyncSession, user_id: int, banned: bool) -> bool:
    u = await session.get(User, user_id)
    if not u:
        return False
    u.is_banned = bool(banned)
    await session.commit()
    return True


async def adjust_user_balance(session: AsyncSession, user_id: int, delta: float) -> User | None:
    u = await session.get(User, user_id, with_for_update=True)
    if not u:
        return None
    u.balance = max(0.0, float(u.balance) + float(delta))
    await session.commit()
    await session.refresh(u)
    return u


async def apply_user_balance_change(
    session: AsyncSession, user_id: int, amount: float, *, credit: bool
) -> User | None:
    """Начисление или списание с кошелька к выплате (положительная сумма)."""
    amt = abs(float(amount))
    delta = amt if credit else -amt
    return await adjust_user_balance(session, user_id, delta)


async def debit_user_balance_if_enough(
    session: AsyncSession, user_id: int, amount: float
) -> User | None:
    """Списать баланс только если достаточно средств."""
    amt = max(0.0, float(amount))
    u = await session.get(User, user_id, with_for_update=True)
    if not u:
        return None
    if float(u.balance or 0) < amt:
        return None
    u.balance = float(u.balance or 0) - amt
    await session.commit()
    await session.refresh(u)
    return u


async def create_withdrawal_request(
    session: AsyncSession,
    *,
    user_id: int,
    amount: float,
    status: str,
    external_payment_id: str | None,
    fps_phone: str | None,
    fps_bank_member_id: str | None,
    error_message: str | None = None,
) -> WithdrawalRequest:
    row = WithdrawalRequest(
        user_id=user_id,
        amount=max(0.0, float(amount)),
        status=status,
        admin_status=WithdrawalAdminStatus.PENDING,
        external_payment_id=external_payment_id,
        fps_phone=fps_phone,
        fps_bank_member_id=fps_bank_member_id,
        error_message=error_message,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def create_withdrawal_and_debit(
    session: AsyncSession,
    *,
    user_id: int,
    amount: float,
    fps_phone: str | None,
    fps_bank_member_id: str | None,
) -> tuple[WithdrawalRequest, User] | None:
    """Атомарно: создать заявку на вывод и списать баланс пользователя."""
    amt = max(0.0, float(amount))
    if amt <= 0:
        return None
    u = await session.get(User, user_id, with_for_update=True)
    if not u:
        return None
    if float(u.balance or 0) < amt:
        return None
    u.balance = float(u.balance or 0) - amt
    row = WithdrawalRequest(
        user_id=user_id,
        amount=amt,
        status=WithdrawalStatus.CREATED,
        admin_status=WithdrawalAdminStatus.PENDING,
        external_payment_id=None,
        fps_phone=fps_phone,
        fps_bank_member_id=fps_bank_member_id,
        error_message=None,
    )
    session.add(row)
    await session.commit()
    await session.refresh(u)
    await session.refresh(row)
    return row, u


async def update_withdrawal_request_status(
    session: AsyncSession,
    request_id: int,
    *,
    status: str,
    external_payment_id: str | None,
    error_message: str | None,
) -> WithdrawalRequest | None:
    row = await session.get(WithdrawalRequest, request_id, with_for_update=True)
    if not row:
        return None
    row.status = (status or row.status)[:32]
    row.external_payment_id = (external_payment_id or "")[:64] or None
    row.error_message = error_message
    await session.commit()
    await session.refresh(row)
    return row


async def fail_withdrawal_and_refund(
    session: AsyncSession,
    request_id: int,
    *,
    status: str,
    external_payment_id: str | None,
    error_message: str | None,
) -> tuple[WithdrawalRequest, User] | None:
    """Помечает заявку неуспешной и возвращает списанную сумму на баланс."""
    from database.models import WithdrawalStatus

    row = await session.get(WithdrawalRequest, request_id, with_for_update=True)
    if not row:
        return None
    u = await session.get(User, row.user_id, with_for_update=True)
    if not u:
        return None
    if row.status == WithdrawalStatus.CREATED and not row.external_payment_id:
        u.balance = float(u.balance or 0) + float(row.amount or 0)
    row.status = (status or WithdrawalStatus.FAILED)[:32]
    row.external_payment_id = (external_payment_id or "")[:64] or None
    row.error_message = error_message
    await session.commit()
    await session.refresh(row)
    await session.refresh(u)
    return row, u


async def list_pending_withdrawals(
    session: AsyncSession, limit: int = 30
) -> list[WithdrawalRequest]:
    r = await session.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.admin_status == WithdrawalAdminStatus.PENDING)
        .order_by(WithdrawalRequest.id.asc())
        .limit(max(1, limit))
    )
    rows = list(r.scalars().all())
    for row in rows:
        row.user = await session.get(User, row.user_id)
    return rows


async def set_withdrawal_admin_decision(
    session: AsyncSession, request_id: int, *, approve: bool
) -> WithdrawalRequest | None:
    row = await session.get(WithdrawalRequest, request_id, with_for_update=True)
    if not row:
        return None
    if row.admin_status != WithdrawalAdminStatus.PENDING:
        return row
    row.admin_status = (
        WithdrawalAdminStatus.APPROVED if approve else WithdrawalAdminStatus.REJECTED
    )
    row.admin_decided_at = datetime.utcnow()
    await session.commit()
    await session.refresh(row)
    row.user = await session.get(User, row.user_id)
    return row


async def list_user_withdrawals(
    session: AsyncSession, user_id: int, limit: int = 5
) -> list[WithdrawalRequest]:
    r = await session.execute(
        select(WithdrawalRequest)
        .where(WithdrawalRequest.user_id == user_id)
        .order_by(WithdrawalRequest.id.desc())
        .limit(max(1, limit))
    )
    return list(r.scalars().all())


async def get_setting(session: AsyncSession, key: str, default: str = "") -> str:
    row = await session.get(AppSetting, key)
    return row.value if row else default


async def set_setting(session: AsyncSession, key: str, value: str) -> None:
    row = await session.get(AppSetting, key)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=key, value=value))
    await session.commit()


async def get_platform_by_slug(session: AsyncSession, slug: str) -> Platform | None:
    r = await session.execute(select(Platform).where(Platform.slug == slug.strip().lower()))
    return r.scalar_one_or_none()


async def get_default_platform(session: AsyncSession) -> Platform | None:
    return await get_platform_by_slug(session, "default")


async def list_platforms_all(session: AsyncSession) -> list[Platform]:
    r = await session.execute(select(Platform).order_by(Platform.id.asc()))
    return list(r.scalars().all())


async def create_platform(session: AsyncSession, name: str, slug: str, cooldown_seconds: int) -> Platform | None:
    slug_n = re.sub(r"[^a-z0-9_]+", "_", slug.strip().lower()).strip("_") or "platform"
    if await get_platform_by_slug(session, slug_n):
        return None
    p = Platform(name=name.strip()[:255], slug=slug_n, cooldown_seconds=max(0, int(cooldown_seconds)), active=True)
    session.add(p)
    await session.commit()
    await session.refresh(p)
    return p


async def delete_platform(session: AsyncSession, platform_id: int, move_tasks_to_default_id: int) -> bool:
    p = await session.get(Platform, platform_id)
    if not p or p.slug == "default":
        return False
    await session.execute(update(Task).where(Task.platform_id == platform_id).values(platform_id=move_tasks_to_default_id))
    await session.execute(delete(Platform).where(Platform.id == platform_id))
    await session.commit()
    return True


async def update_platform_cooldown(session: AsyncSession, platform_id: int, seconds: int) -> bool:
    p = await session.get(Platform, platform_id)
    if not p:
        return False
    p.cooldown_seconds = max(0, int(seconds))
    await session.commit()
    return True


async def list_active_tasks(session: AsyncSession) -> list[Task]:
    r = await session.execute(
        select(Task)
        .options(selectinload(Task.platform))
        .where(Task.active.is_(True))
        .order_by(Task.id.desc())
    )
    return list(r.scalars().unique().all())


async def list_all_tasks(session: AsyncSession) -> list[Task]:
    r = await session.execute(
        select(Task).options(selectinload(Task.platform)).order_by(Task.id.desc())
    )
    return list(r.scalars().unique().all())


async def list_tasks_available_for_user(
    session: AsyncSession, user_id: int, gender: str | None
) -> list[Task]:
    """
    Задания, которые пользователь может взять сейчас:
    — есть свободный опубликованный текст под его пол;
    — или он уже взял текст, но ещё не отправил отзыв.
    Заказчик недоступен, если пользователь хоть раз отправлял отзыв по нему.
    """
    if not gender:
        return []
    now = datetime.utcnow()
    has_submission = exists(
        select(1).where(
            Submission.user_id == user_id,
            Submission.task_id == Task.id,
        )
    )
    has_claimed = exists(
        select(1).where(
            TaskText.task_id == Task.id,
            TaskText.taken_by_user_id == user_id,
        )
    )
    text_not_refused = ~exists(
        select(1).where(
            UserTextRefusal.user_id == user_id,
            UserTextRefusal.task_text_id == TaskText.id,
        )
    )
    has_free_text = exists(
        select(1).where(
            TaskText.task_id == Task.id,
            TaskText.required_gender == gender,
            TaskText.taken_by_user_id.is_(None),
            TaskText.published.is_(True),
            or_(TaskText.publish_at.is_(None), TaskText.publish_at <= now),
            text_not_refused,
        )
    )
    r = await session.execute(
        select(Task)
        .options(selectinload(Task.platform))
        .where(
            Task.active.is_(True),
            ~has_submission,
            or_(has_claimed, has_free_text),
        )
        .order_by(Task.id.desc())
    )
    return list(r.scalars().unique().all())


async def list_tasks_available_for_user_on_platform(
    session: AsyncSession, user_id: int, gender: str | None, platform_id: int
) -> list[Task]:
    tasks = await list_tasks_available_for_user(session, user_id, gender)
    return [t for t in tasks if t.platform_id == platform_id]


async def list_platforms_available_for_user(
    session: AsyncSession, user_id: int, gender: str | None
) -> list[tuple[Platform, int]]:
    """Сервисы, у которых есть хотя бы одно доступное пользователю задание."""
    tasks = await list_tasks_available_for_user(session, user_id, gender)
    counts: dict[int, int] = {}
    names: dict[int, Platform] = {}
    for t in tasks:
        pid = t.platform_id
        counts[pid] = counts.get(pid, 0) + 1
        if pid not in names and t.platform:
            names[pid] = t.platform
    out: list[tuple[Platform, int]] = []
    for pid, cnt in counts.items():
        p = names.get(pid) or await session.get(Platform, pid)
        if not p or not p.active:
            continue
        out.append((p, cnt))
    return sorted(out, key=lambda x: x[0].name.lower())


async def get_task(session: AsyncSession, task_id: int) -> Task | None:
    r = await session.execute(
        select(Task)
        .options(selectinload(Task.platform), selectinload(Task.texts))
        .where(Task.id == task_id)
    )
    return r.scalar_one_or_none()


async def get_task_by_link(session: AsyncSession, link: str) -> Task | None:
    r = await session.execute(select(Task).where(Task.link == link).limit(1))
    return r.scalar_one_or_none()


async def create_customer_task(
    session: AsyncSession,
    customer_name: str,
    link: str,
    platform_id: int,
    reward: float = 0.0,
    description: str = "",
    *,
    org_address: str | None = None,
    region: str | None = None,
    yandex_question_order: str | None = None,
) -> tuple[Task | None, str | None]:
    """Создаёт заказчика. Ошибка, если ссылка уже занята."""
    link = link.strip()[:1024]
    if not link:
        return None, "Ссылка обязательна."
    if await get_task_by_link(session, link):
        return None, "Эта ссылка уже привязана к другому заказчику."
    name = customer_name.strip()[:512]
    t = Task(
        platform_id=platform_id,
        customer_name=name,
        title=name,
        description=(description or "")[:10000],
        reward=max(0.0, float(reward)),
        link=link,
        org_address=(org_address or "")[:1024] or None,
        region=(region or "").strip()[:255] or None,
        yandex_question_order=(yandex_question_order or "")[:64] or None,
        active=True,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t, None


async def get_yandex_conditions(session: AsyncSession) -> str:
    row = await session.get(AppSetting, "yandex_maps_conditions")
    return (row.value if row else "").strip() or "Условия не заданы."


INCOMPLETE_YM_STEPS = frozenset({
    "conditions",
    "gender",
    "yandex_account",
    "region",
    "assign",
    "org",
    "assign_retry",
    "website",
    "quiz_intro",
    "question",
})


async def get_active_ym_session(session: AsyncSession, user_id: int) -> YandexMapsSession | None:
    r = await session.execute(
        select(YandexMapsSession)
        .where(YandexMapsSession.user_id == user_id)
        .order_by(YandexMapsSession.id.desc())
        .limit(1)
    )
    row = r.scalar_one_or_none()
    if not row or row.review_sent_at or row.step == "done":
        return None
    return row


async def task_platform_is_yandex(session: AsyncSession, task_id: int | None) -> bool:
    if not task_id:
        return False
    t = await get_task(session, task_id)
    if not t or not t.platform_id:
        return False
    p = await session.get(Platform, t.platform_id)
    return p is not None and is_yandex_maps_slug(p.slug)



async def clear_ym_session(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(YandexMapsSession).where(YandexMapsSession.user_id == user_id))
    await session.commit()


async def save_ym_session(session: AsyncSession, row: YandexMapsSession) -> YandexMapsSession:
    row.updated_at = datetime.utcnow()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def start_ym_session(session: AsyncSession, user_id: int, step: str) -> YandexMapsSession:
    await clear_ym_session(session, user_id)
    row = YandexMapsSession(user_id=user_id, step=step)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def ban_user_for_days(session: AsyncSession, user_id: int, days: int) -> None:
    u = await session.get(User, user_id, with_for_update=True)
    if not u:
        return
    u.ban_until = datetime.utcnow() + timedelta(days=max(1, int(days)))
    u.is_banned = True
    await session.commit()


def user_is_banned_now(u: User) -> bool:
    if u.ban_until and u.ban_until > datetime.utcnow():
        return True
    if u.ban_until and u.ban_until <= datetime.utcnow():
        return False
    return bool(u.is_banned)


async def get_yandex_quiz_default_order(session: AsyncSession) -> str:
    row = await session.get(AppSetting, YANDEX_QUIZ_DEFAULT_ORDER_KEY)
    raw = (row.value if row else "").strip()
    order, err = parse_question_order(raw)
    if err or not order:
        return format_question_order(default_question_order())
    return format_question_order(order)


async def set_yandex_quiz_default_order(session: AsyncSession, order_csv: str) -> tuple[str | None, str | None]:
    order, err = parse_question_order(order_csv)
    if err or not order:
        return None, err or "Некорректный порядок вопросов."
    value = format_question_order(order)
    row = await session.get(AppSetting, YANDEX_QUIZ_DEFAULT_ORDER_KEY)
    if row:
        row.value = value
    else:
        session.add(AppSetting(key=YANDEX_QUIZ_DEFAULT_ORDER_KEY, value=value))
    await session.commit()
    return value, None


async def list_all_yandex_questions(session: AsyncSession) -> list[YandexMapsQuestion]:
    r = await session.execute(
        select(YandexMapsQuestion).order_by(YandexMapsQuestion.slot)
    )
    return list(r.scalars().all())


async def update_yandex_question(
    session: AsyncSession,
    slot: int,
    *,
    body: str | None = None,
    active: bool | None = None,
) -> YandexMapsQuestion | None:
    q = await session.get(YandexMapsQuestion, slot)
    if not q:
        return None
    if body is not None:
        q.body = body.strip()
    if active is not None:
        q.active = bool(active)
    await session.commit()
    await session.refresh(q)
    return q


async def list_yandex_questions_by_order(
    session: AsyncSession, order_csv: str | None
) -> list[YandexMapsQuestion]:
    order, err = parse_question_order(order_csv or "")
    if err or not order:
        order = default_question_order()
    r = await session.execute(
        select(YandexMapsQuestion).where(
            YandexMapsQuestion.slot.in_(order),
            YandexMapsQuestion.active.is_(True),
        )
    )
    by_slot = {q.slot: q for q in r.scalars().all()}
    return [by_slot[s] for s in order if s in by_slot]


async def claim_yandex_assignment(
    session: AsyncSession,
    user_id: int,
    gender: str,
    region: str,
    platform_id: int,
) -> tuple[Task | None, TaskText | None]:
    region_norm = (region or "").strip().lower()
    tasks = await list_tasks_available_for_user_on_platform(
        session, user_id, gender, platform_id
    )
    tasks = sorted(tasks, key=lambda t: _task_region_rank(t, region_norm))
    for task in tasks:
        if region_norm and _task_region_rank(task, region_norm) == 2:
            continue
        sub = await get_submission_for_user_task(session, user_id, task.id)
        if sub:
            continue
        now = datetime.utcnow()
        refused = await get_refused_text_ids(session, user_id, task.id)
        q = select(TaskText).where(
            TaskText.task_id == task.id,
            TaskText.required_gender == gender,
            TaskText.taken_by_user_id.is_(None),
            TaskText.published.is_(True),
            or_(TaskText.publish_at.is_(None), TaskText.publish_at <= now),
        )
        if refused:
            q = q.where(TaskText.id.not_in(refused))
        q = q.order_by(TaskText.text_number.asc(), TaskText.id.asc())
        r = await session.execute(q)
        for tt in r.scalars().all():
            claimed = await claim_task_text(session, user_id, tt.id, gender)
            if claimed:
                full = await get_task(session, task.id)
                return full, claimed
    if region_norm:
        for task in tasks:
            if _task_region_rank(task, region_norm) != 2:
                continue
            sub = await get_submission_for_user_task(session, user_id, task.id)
            if sub:
                continue
            now = datetime.utcnow()
            refused = await get_refused_text_ids(session, user_id, task.id)
            q = select(TaskText).where(
                TaskText.task_id == task.id,
                TaskText.required_gender == gender,
                TaskText.taken_by_user_id.is_(None),
                TaskText.published.is_(True),
                or_(TaskText.publish_at.is_(None), TaskText.publish_at <= now),
            )
            if refused:
                q = q.where(TaskText.id.not_in(refused))
            q = q.order_by(TaskText.text_number.asc(), TaskText.id.asc())
            r = await session.execute(q)
            for tt in r.scalars().all():
                claimed = await claim_task_text(session, user_id, tt.id, gender)
                if claimed:
                    full = await get_task(session, task.id)
                    return full, claimed
    return None, None


async def list_due_yandex_reviews(session: AsyncSession) -> list[YandexMapsSession]:
    now = datetime.utcnow()
    r = await session.execute(
        select(YandexMapsSession).where(
            YandexMapsSession.freeze_until.is_not(None),
            YandexMapsSession.freeze_until <= now,
            YandexMapsSession.review_sent_at.is_(None),
            YandexMapsSession.task_text_id.is_not(None),
        )
    )
    out: list[YandexMapsSession] = []
    for row in r.scalars().all():
        row.user = await session.get(User, row.user_id)
        out.append(row)
    return out


async def release_ym_assignment(
    session: AsyncSession, user_id: int, text_id: int | None
) -> None:
    if text_id:
        tt = await session.get(TaskText, text_id, with_for_update=True)
        if tt and tt.taken_by_user_id == user_id:
            tt.taken_by_user_id = None
            tt.claimed_at = None
    await session.commit()


async def reset_incomplete_ym_flow(session: AsyncSession, user_id: int) -> None:
    """Сбросить незавершённый сценарий Яндекс Карт (не трогает «заморозку» с ожиданием текста)."""
    ym = await get_active_ym_session(session, user_id)
    if not ym or ym.step not in INCOMPLETE_YM_STEPS:
        return
    if ym.task_text_id:
        await release_ym_assignment(session, user_id, ym.task_text_id)
    await clear_ym_session(session, user_id)


async def create_task(
    session: AsyncSession,
    platform_id: int,
    title: str,
    description: str,
    reward: float,
    link: str | None,
    customer_name: str | None = None,
) -> Task:
    name = (customer_name or title).strip()[:512]
    t = Task(
        platform_id=platform_id,
        customer_name=name,
        title=name,
        description=description[:10000],
        reward=max(0.0, float(reward)),
        link=link[:1024] if link else None,
        active=True,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    return t


async def delete_task(session: AsyncSession, task_id: int) -> bool:
    t = await session.get(Task, task_id)
    if not t:
        return False
    await session.execute(delete(TaskText).where(TaskText.task_id == task_id))
    await session.execute(delete(Task).where(Task.id == task_id))
    await session.commit()
    return True


async def update_task_fields(
    session: AsyncSession,
    task_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    reward: float | None = None,
    link: str | None = None,
    active: bool | None = None,
    platform_id: int | None = None,
    region: str | None = None,
    org_address: str | None = None,
) -> Task | None:
    t = await session.get(Task, task_id)
    if not t:
        return None
    if title is not None:
        t.title = title[:512]
    if description is not None:
        t.description = description[:10000]
    if reward is not None:
        t.reward = max(0.0, float(reward))
    if link is not None:
        t.link = link[:1024] if link else None
    if active is not None:
        t.active = active
    if platform_id is not None:
        t.platform_id = platform_id
    if region is not None:
        t.region = region.strip()[:255] or None
    if org_address is not None:
        t.org_address = org_address.strip()[:1024] or None
    await session.commit()
    await session.refresh(t)
    return t


def _task_region_rank(task: Task, region_norm: str) -> int:
    """0 — совпадение, 1 — без региона (любой), 2 — другой регион."""
    tr = (task.region or "").strip().lower()
    if not region_norm:
        return 0
    if tr == region_norm:
        return 0
    if not tr:
        return 1
    return 2


async def next_text_number(session: AsyncSession, task_id: int) -> int:
    r = await session.execute(
        select(func.max(TaskText.text_number)).where(TaskText.task_id == task_id)
    )
    mx = r.scalar_one()
    return int(mx or 0) + 1


async def add_task_text(
    session: AsyncSession,
    task_id: int,
    body: str,
    *,
    text_number: int | None = None,
    required_gender: str | None = None,
    publish_at: datetime | None = None,
    published: bool | None = None,
) -> TaskText:
    now = datetime.utcnow()
    num = text_number if text_number is not None else await next_text_number(session, task_id)
    if published is None:
        published = publish_at is None or publish_at <= now
    task = await session.get(Task, task_id)
    text_region = (task.region if task else None) or None
    tt = TaskText(
        task_id=task_id,
        text_number=num,
        required_gender=required_gender,
        body=body[:20000],
        region=text_region,
        publish_at=publish_at,
        published=published,
    )
    session.add(tt)
    await session.commit()
    await session.refresh(tt)
    return tt


async def complete_onboarding(
    session: AsyncSession,
    user_id: int,
    gender: str,
    platform_account_name: str,
) -> User | None:
    u = await session.get(User, user_id)
    if not u:
        return None
    u.gender = gender
    u.platform_account_name = platform_account_name[:512]
    u.onboarding_completed = True
    await session.commit()
    await session.refresh(u)
    return u


async def get_or_create_customer_by_link(
    session: AsyncSession,
    link: str,
    platform_id: int,
    customer_name: str | None = None,
    reward: float = 0.0,
    org_address: str | None = None,
) -> tuple[Task, bool]:
    rw = max(0.0, float(reward))
    existing = await get_task_by_link(session, link)
    if existing:
        if customer_name and not existing.customer_name:
            existing.customer_name = customer_name[:512]
            existing.title = existing.customer_name
        if rw > 0:
            existing.reward = rw
        if org_address and not (existing.org_address or "").strip():
            existing.org_address = org_address.strip()[:1024]
        await session.commit()
        return existing, False
    name = (customer_name or "Заказчик").strip()[:512]
    t = Task(
        platform_id=platform_id,
        customer_name=name,
        title=name,
        description="",
        reward=rw,
        link=link[:1024],
        org_address=(org_address or "").strip()[:1024] or None,
        active=True,
    )
    session.add(t)
    await session.flush()
    return t, True


async def import_review_texts(
    session: AsyncSession,
    items: list,
    platform_id: int,
) -> tuple[int, int, list[str]]:
    """Возвращает (добавлено текстов, создано заданий, ошибки)."""
    from services.texts_import import ImportedReviewText

    now = datetime.utcnow()
    texts_n = 0
    tasks_n = 0
    errors: list[str] = []
    batch = 0
    for item in items:
        if not isinstance(item, ImportedReviewText):
            continue
        task, created = await get_or_create_customer_by_link(
            session,
            item.link,
            platform_id,
            item.customer_name,
            getattr(item, "reward", 0.0),
            getattr(item, "org_address", None),
        )
        addr = getattr(item, "org_address", None)
        if addr and task and not (task.org_address or "").strip():
            task.org_address = addr.strip()[:1024]
        if created:
            tasks_n += 1
        elif item.customer_name and task.customer_name != item.customer_name:
            task.customer_name = item.customer_name[:512]
            task.title = task.customer_name
        rw = float(getattr(item, "reward", 0) or 0)
        if rw > (task.reward or 0):
            task.reward = rw
        published = item.publish_at <= now
        clash = await session.execute(
            select(TaskText.id).where(
                TaskText.task_id == task.id,
                TaskText.text_number == item.text_number,
            )
        )
        if clash.scalar_one_or_none():
            errors.append(
                f"Номер {item.text_number} уже есть у заказчика «{task.customer_name}», строка пропущена."
            )
            continue
        session.add(
            TaskText(
                task_id=task.id,
                text_number=item.text_number,
                required_gender=item.gender,
                body=item.body,
                publish_at=item.publish_at,
                published=published,
            )
        )
        texts_n += 1
        batch += 1
        if batch >= 25:
            await session.commit()
            batch = 0
    await session.commit()
    return texts_n, tasks_n, errors


async def import_review_texts_to_task(
    session: AsyncSession,
    task_id: int,
    items: list,
) -> tuple[int, list[str]]:
    from services.texts_import import ImportedReviewText

    task = await session.get(Task, task_id)
    if not task:
        return 0, ["Заказчик не найден."]
    now = datetime.utcnow()
    added = 0
    notes: list[str] = []
    for item in items:
        if not isinstance(item, ImportedReviewText):
            continue
        if item.link.strip() != (task.link or "").strip():
            notes.append(f"№{item.text_number}: другая ссылка — пропуск.")
            continue
        clash = await session.execute(
            select(TaskText.id).where(
                TaskText.task_id == task_id,
                TaskText.text_number == item.text_number,
            )
        )
        if clash.scalar_one_or_none():
            notes.append(f"№{item.text_number}: уже есть.")
            continue
        published = item.publish_at <= now
        session.add(
            TaskText(
                task_id=task_id,
                text_number=item.text_number,
                required_gender=item.gender,
                body=item.body,
                publish_at=item.publish_at,
                published=published,
            )
        )
        added += 1
    rw_vals = [
        float(getattr(i, "reward", 0) or 0)
        for i in items
        if isinstance(i, ImportedReviewText)
    ]
    if rw_vals:
        batch_rw = max(rw_vals)
        if batch_rw > (task.reward or 0):
            task.reward = batch_rw
    await session.commit()
    return added, notes


async def get_refused_text_ids(
    session: AsyncSession, user_id: int, task_id: int
) -> set[int]:
    r = await session.execute(
        select(UserTextRefusal.task_text_id).where(
            UserTextRefusal.user_id == user_id,
            UserTextRefusal.task_id == task_id,
        )
    )
    return {int(x) for x in r.scalars().all()}


async def _add_user_text_refusal(
    session: AsyncSession, user_id: int, text_id: int, task_id: int
) -> None:
    exists = await session.execute(
        select(UserTextRefusal.id).where(
            UserTextRefusal.user_id == user_id,
            UserTextRefusal.task_text_id == text_id,
        )
    )
    if exists.scalar_one_or_none():
        return
    session.add(
        UserTextRefusal(
            user_id=user_id,
            task_id=task_id,
            task_text_id=text_id,
        )
    )


async def user_refused_text(
    session: AsyncSession, user_id: int, text_id: int
) -> bool:
    r = await session.execute(
        select(UserTextRefusal.id).where(
            UserTextRefusal.user_id == user_id,
            UserTextRefusal.task_text_id == text_id,
        )
    )
    return r.scalar_one_or_none() is not None


async def list_available_texts(
    session: AsyncSession,
    task_id: int,
    gender: str | None,
    *,
    for_user_id: int | None = None,
) -> list[TaskText]:
    if not gender:
        return []
    now = datetime.utcnow()
    q = (
        select(TaskText)
        .where(
            TaskText.task_id == task_id,
            TaskText.required_gender == gender,
            TaskText.taken_by_user_id.is_(None),
            TaskText.published.is_(True),
            or_(TaskText.publish_at.is_(None), TaskText.publish_at <= now),
        )
        .order_by(TaskText.text_number.asc(), TaskText.id.asc())
    )
    if for_user_id is not None:
        refused = await get_refused_text_ids(session, for_user_id, task_id)
        if refused:
            q = q.where(TaskText.id.not_in(refused))
    r = await session.execute(q)
    return list(r.scalars().all())


async def get_user_claimed_text(
    session: AsyncSession, user_id: int, task_id: int
) -> TaskText | None:
    r = await session.execute(
        select(TaskText).where(
            TaskText.task_id == task_id,
            TaskText.taken_by_user_id == user_id,
        )
    )
    return r.scalar_one_or_none()


async def release_task_text(session: AsyncSession, user_id: int, text_id: int) -> bool:
    """Вернуть текст в пул (отказ). Отказ и снятие брони — одна транзакция."""
    tt = await session.get(TaskText, text_id, with_for_update=True)
    if not tt:
        return False
    if tt.taken_by_user_id not in (None, user_id):
        return False
    if tt.taken_by_user_id == user_id:
        tt.taken_by_user_id = None
        tt.claimed_at = None
    await _add_user_text_refusal(session, user_id, text_id, tt.task_id)
    await session.commit()
    return True


async def claim_min_available_text(
    session: AsyncSession, user_id: int, task_id: int, gender: str | None
) -> TaskText | None:
    """Взять свободный текст с наименьшим номером, кроме отказанных этим пользователем."""
    texts = await list_available_texts(session, task_id, gender, for_user_id=user_id)
    if not texts:
        return None
    refused = await get_refused_text_ids(session, user_id, task_id)
    for tt in texts:
        if tt.id in refused:
            continue
        claimed = await claim_task_text(session, user_id, tt.id, gender)
        if claimed:
            return claimed
    return None


async def claim_task_text(
    session: AsyncSession, user_id: int, text_id: int, gender: str | None
) -> TaskText | None:
    tt = await session.get(TaskText, text_id, with_for_update=True)
    if not tt or not gender:
        return None
    now = datetime.utcnow()
    if (
        tt.taken_by_user_id is not None
        or tt.required_gender != gender
        or not tt.published
        or (tt.publish_at and tt.publish_at > now)
    ):
        return None
    tt.taken_by_user_id = user_id
    tt.claimed_at = now
    await session.commit()
    await session.refresh(tt)
    return tt


async def release_expired_task_claims(
    session: AsyncSession, max_minutes: int
) -> int:
    """Снять просроченные брони (без отказа — текст снова в пуле)."""
    cutoff = datetime.utcnow() - timedelta(minutes=max(1, int(max_minutes)))
    r = await session.execute(
        select(TaskText).where(
            TaskText.taken_by_user_id.is_not(None),
            TaskText.claimed_at.is_not(None),
            TaskText.claimed_at < cutoff,
        )
    )
    rows = list(r.scalars().all())
    for tt in rows:
        tt.taken_by_user_id = None
        tt.claimed_at = None
    if rows:
        await session.commit()
    return len(rows)


async def delete_task_text(session: AsyncSession, text_id: int) -> bool:
    row = await session.get(TaskText, text_id)
    if not row:
        return False
    await session.execute(delete(TaskText).where(TaskText.id == text_id))
    await session.commit()
    return True


async def delete_task_texts_by_numbers(
    session: AsyncSession, task_id: int, numbers: list[int]
) -> tuple[int, list[str]]:
    """Удаляет тексты по номерам. Возвращает (удалено, сообщения об ошибках)."""
    if not numbers:
        return 0, ["Не указаны номера."]
    notes: list[str] = []
    deleted = 0
    for num in numbers:
        r = await session.execute(
            select(TaskText).where(TaskText.task_id == task_id, TaskText.text_number == num)
        )
        row = r.scalar_one_or_none()
        if not row:
            notes.append(f"№{num}: не найден.")
            continue
        if row.taken_by_user_id:
            notes.append(f"№{num}: взят пользователем — не удалён.")
            continue
        await session.execute(delete(TaskText).where(TaskText.id == row.id))
        deleted += 1
    await session.commit()
    return deleted, notes


async def add_tasks_bulk(
    session: AsyncSession,
    items: list[tuple[str, str, float, str | None, int]],
) -> int:
    n = 0
    for title, desc, reward, link, platform_id in items:
        session.add(
            Task(
                platform_id=platform_id,
                title=title,
                description=desc,
                reward=reward,
                link=link,
                active=True,
            )
        )
        n += 1
    await session.commit()
    return n


async def get_submission_for_user_task(
    session: AsyncSession, user_id: int, task_id: int
) -> Submission | None:
    r = await session.execute(
        select(Submission).where(Submission.user_id == user_id, Submission.task_id == task_id)
    )
    return r.scalar_one_or_none()


async def create_submission(
    session: AsyncSession,
    user_id: int,
    task_id: int,
    text: str,
    task_text_id: int | None = None,
) -> Submission | None:
    existing = await get_submission_for_user_task(session, user_id, task_id)
    if existing:
        return None
    task = await session.execute(
        select(Task).options(selectinload(Task.platform)).where(Task.id == task_id)
    )
    t = task.scalar_one_or_none()
    if not t:
        return None
    cd_sec = t.platform.cooldown_seconds if t.platform else 0
    until = compute_cooldown_until(cd_sec)
    status = SubmissionStatus.COOLDOWN if until else SubmissionStatus.PENDING
    s = Submission(
        user_id=user_id,
        task_id=task_id,
        task_text_id=task_text_id,
        review_text=text[:12000],
        status=status,
        cooldown_until=until,
        completed_at=datetime.utcnow(),
    )
    session.add(s)
    await session.commit()
    await session.refresh(s)
    return s


async def list_pending_submissions(session: AsyncSession, limit: int = 30) -> list[Submission]:
    await release_expired_cooldowns(session)
    r = await session.execute(
        select(Submission)
        .where(Submission.status == SubmissionStatus.PENDING)
        .options(selectinload(Submission.user), selectinload(Submission.task))
        .order_by(Submission.id.asc())
        .limit(limit)
    )
    return list(r.scalars().unique().all())


def _moderation_queue_statuses():
    return (SubmissionStatus.PENDING,)


async def count_submissions_in_cooldown(
    session: AsyncSession, *, task_id: int | None = None, platform_id: int | None = None
) -> int:
    """Выполнено, но кулдаун ещё не истёк — не в очереди на проверку."""
    now = datetime.utcnow()
    q = select(func.count(Submission.id)).where(
        Submission.status == SubmissionStatus.COOLDOWN,
        Submission.cooldown_until.is_not(None),
        Submission.cooldown_until > now,
    )
    if task_id is not None:
        q = q.where(Submission.task_id == task_id)
    if platform_id is not None:
        q = q.join(Task, Task.id == Submission.task_id).where(Task.platform_id == platform_id)
    r = await session.execute(q)
    return int(r.scalar_one() or 0)


async def list_platforms_with_pending_reviews(
    session: AsyncSession,
) -> list[tuple[Platform, int]]:
    await release_expired_cooldowns(session)
    r = await session.execute(
        select(Task.platform_id, func.count(Submission.id))
        .join(Submission, Submission.task_id == Task.id)
        .where(Submission.status.in_(_moderation_queue_statuses()))
        .group_by(Task.platform_id)
    )
    rows = r.all()
    if not rows:
        return []
    out: list[tuple[Platform, int]] = []
    for platform_id, cnt in rows:
        p = await session.get(Platform, int(platform_id))
        if p:
            out.append((p, int(cnt)))
    return sorted(out, key=lambda x: x[0].name)


async def list_tasks_with_pending_reviews(
    session: AsyncSession, platform_id: int
) -> list[tuple[Task, int]]:
    await release_expired_cooldowns(session)
    r = await session.execute(
        select(Task.id, func.count(Submission.id))
        .join(Submission, Submission.task_id == Task.id)
        .where(
            Task.platform_id == platform_id,
            Submission.status.in_(_moderation_queue_statuses()),
        )
        .group_by(Task.id)
    )
    out: list[tuple[Task, int]] = []
    for task_id, cnt in r.all():
        t = await get_task(session, int(task_id))
        if t:
            out.append((t, int(cnt)))
    return out


async def list_pending_submissions_for_task(
    session: AsyncSession, task_id: int
) -> list[Submission]:
    await release_expired_cooldowns(session)
    r = await session.execute(
        select(Submission)
        .where(
            Submission.task_id == task_id,
            Submission.status.in_(_moderation_queue_statuses()),
        )
        .options(selectinload(Submission.user), selectinload(Submission.task))
        .order_by(Submission.completed_at.asc().nulls_last(), Submission.id.asc())
    )
    return list(r.scalars().unique().all())


async def get_submission_detail(session: AsyncSession, submission_id: int) -> Submission | None:
    await release_expired_cooldowns(session)
    r = await session.execute(
        select(Submission)
        .where(Submission.id == submission_id)
        .options(selectinload(Submission.user), selectinload(Submission.task))
    )
    return r.scalar_one_or_none()


async def get_submission(session: AsyncSession, sid: int) -> Submission | None:
    return await session.get(Submission, sid)


async def resolve_user_ref(session: AsyncSession, ref: str) -> User | None:
    s = ref.strip()
    if s.startswith("@"):
        s = s[1:]
    if not s:
        return None
    if s.isdigit():
        return await get_user_by_telegram(session, int(s))
    r = await session.execute(
        select(User).where(
            User.username.is_not(None),
            func.lower(User.username) == s.lower(),
        )
    )
    return r.scalar_one_or_none()


async def create_support_ticket(
    session: AsyncSession,
    user_id: int,
    text: str,
    photo_file_id: str | None,
) -> SupportTicket:
    ticket = SupportTicket(
        user_id=user_id,
        text=text.strip(),
        photo_file_id=photo_file_id,
        status=SupportTicketStatus.OPEN,
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def get_support_ticket(
    session: AsyncSession, ticket_id: int, *, with_user: bool = False
) -> SupportTicket | None:
    if with_user:
        r = await session.execute(
            select(SupportTicket)
            .where(SupportTicket.id == ticket_id)
            .options(selectinload(SupportTicket.user))
        )
        return r.scalar_one_or_none()
    return await session.get(SupportTicket, ticket_id)


async def count_open_support_tickets(session: AsyncSession) -> int:
    r = await session.execute(
        select(func.count())
        .select_from(SupportTicket)
        .where(SupportTicket.status == SupportTicketStatus.OPEN)
    )
    return int(r.scalar() or 0)


async def list_open_support_tickets(
    session: AsyncSession, *, limit: int = 100
) -> list[SupportTicket]:
    r = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.status == SupportTicketStatus.OPEN)
        .order_by(SupportTicket.created_at.asc(), SupportTicket.id.asc())
        .limit(limit)
        .options(selectinload(SupportTicket.user))
    )
    return list(r.scalars().all())


async def get_oldest_open_support_ticket(session: AsyncSession) -> SupportTicket | None:
    r = await session.execute(
        select(SupportTicket)
        .where(SupportTicket.status == SupportTicketStatus.OPEN)
        .order_by(SupportTicket.created_at.asc(), SupportTicket.id.asc())
        .limit(1)
        .options(selectinload(SupportTicket.user))
    )
    return r.scalar_one_or_none()


async def set_support_ticket_status(
    session: AsyncSession, ticket_id: int, status: str
) -> SupportTicket | None:
    ticket = await session.get(SupportTicket, ticket_id)
    if not ticket:
        return None
    ticket.status = status
    if status == SupportTicketStatus.ANSWERED:
        ticket.answered_at = datetime.utcnow()
    await session.commit()
    return ticket


async def save_support_admin_message(
    session: AsyncSession,
    ticket_id: int,
    admin_telegram_id: int,
    bot_message_id: int,
) -> None:
    session.add(
        SupportAdminMessage(
            ticket_id=ticket_id,
            admin_telegram_id=admin_telegram_id,
            bot_message_id=bot_message_id,
        )
    )
    await session.commit()


async def get_support_ticket_by_admin_reply(
    session: AsyncSession, admin_telegram_id: int, reply_message_id: int
) -> SupportTicket | None:
    r = await session.execute(
        select(SupportTicket)
        .join(
            SupportAdminMessage,
            SupportAdminMessage.ticket_id == SupportTicket.id,
        )
        .where(
            SupportAdminMessage.admin_telegram_id == admin_telegram_id,
            SupportAdminMessage.bot_message_id == reply_message_id,
        )
        .options(selectinload(SupportTicket.user))
        .limit(1)
    )
    return r.scalar_one_or_none()
