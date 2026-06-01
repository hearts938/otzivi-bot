from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings
from database.models import Submission, SubmissionStatus, Task, TaskText, User
from repo import count_referred_users


def referral_commission_percent(settings: Settings, referred_count: int) -> float:
    """До порога рефералов — один %, после — другой."""
    if referred_count <= settings.referral_count_threshold:
        return settings.referral_percent_up_to_threshold
    return settings.referral_percent_after_threshold


async def _pay_direct_referrer(
    session: AsyncSession,
    settings: Settings,
    earner: User,
    reward_amount: float,
    lines: list[str],
) -> None:
    if reward_amount <= 0 or not earner.referred_by_id:
        return

    referrer = await session.get(User, earner.referred_by_id, with_for_update=True)
    if not referrer:
        return

    ref_count = await count_referred_users(session, referrer.id)
    pct = referral_commission_percent(settings, ref_count)
    pay = round(reward_amount * (pct / 100.0), 2)
    if pay <= 0:
        return

    referrer.balance += pay
    referrer.referral_earned_total += pay
    tier = (
        f"до {settings.referral_count_threshold} реф."
        if ref_count <= settings.referral_count_threshold
        else f"после {settings.referral_count_threshold} реф."
    )
    lines.append(
        f"Реферер (ID {referrer.telegram_id}, {ref_count} приглаш., {tier}): "
        f"{pct:.0f}% от {reward_amount:.2f} = {pay:.2f} ₽."
    )


async def approve_submission(session: AsyncSession, settings: Settings, submission_id: int) -> str | None:
    sub = await session.get(Submission, submission_id, with_for_update=True)
    if not sub or sub.status != SubmissionStatus.PENDING:
        return None
    task = await session.get(Task, sub.task_id)
    if not task:
        return None

    user = await session.get(User, sub.user_id, with_for_update=True)
    if not user:
        return None

    now = datetime.utcnow()
    sub.status = SubmissionStatus.APPROVED
    sub.approved_at = now
    reward = float(task.reward or 0)
    pending_used = min(float(user.pending_balance or 0), reward)
    user.pending_balance = max(0.0, float(user.pending_balance or 0) - pending_used)
    user.balance += reward
    user.total_earned += reward

    lines = [f"Начислено исполнителю {reward:.2f} ₽ за «{task.title}»."]

    if settings.referral_first_task_bonus > 0 and user.referred_by_id:
        referrer = await session.get(User, user.referred_by_id, with_for_update=True)
        if referrer and not user.referral_first_paid:
            bonus = settings.referral_first_task_bonus
            referrer.balance += bonus
            referrer.referral_earned_total += bonus
            lines.append(
                f"Бонус рефереру (ID {referrer.telegram_id}) за первое одобренное задание: {bonus:.2f} ₽."
            )
            user.referral_first_paid = True

    await _pay_direct_referrer(session, settings, user, reward, lines)

    await session.commit()
    return "\n".join(lines)


async def reject_submission(session: AsyncSession, submission_id: int) -> bool:
    sub = await session.get(Submission, submission_id, with_for_update=True)
    if not sub or sub.status not in (SubmissionStatus.PENDING, SubmissionStatus.COOLDOWN):
        return False
    task = await session.get(Task, sub.task_id)
    user = await session.get(User, sub.user_id, with_for_update=True)
    if task and user:
        rw = float(task.reward or 0)
        user.pending_balance = max(0.0, float(user.pending_balance or 0) - rw)
    sub.status = SubmissionStatus.REJECTED
    if sub.task_text_id:
        tt = await session.get(TaskText, sub.task_text_id, with_for_update=True)
        if tt:
            tt.taken_by_user_id = None
            tt.claimed_at = None
    await session.commit()
    return True


async def count_approved_for_user(session: AsyncSession, user_id: int) -> int:
    q = await session.execute(
        select(Submission).where(
            Submission.user_id == user_id,
            Submission.status == SubmissionStatus.APPROVED,
        )
    )
    return len(q.scalars().all())
