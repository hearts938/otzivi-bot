from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=0)
    user_recharge_seconds: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referral_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    referred_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    pending_balance: Mapped[float] = mapped_column(Float, default=0.0)
    ban_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    work_region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_earned: Mapped[float] = mapped_column(Float, default=0.0)
    referral_earned_total: Mapped[float] = mapped_column(Float, default=0.0)
    referral_first_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    platform_account_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    referred_by: Mapped["User | None"] = relationship(
        "User", remote_side=[id], foreign_keys=[referred_by_id]
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"), index=True)
    customer_name: Mapped[str] = mapped_column(String(512), default="")
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    reward: Mapped[float] = mapped_column(Float, default=0.0)
    link: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    org_address: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    yandex_question_order: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    platform: Mapped["Platform"] = relationship("Platform")
    texts: Mapped[list["TaskText"]] = relationship(
        "TaskText", back_populates="task", cascade="all, delete-orphan"
    )


class UserTextRefusal(Base):
    """Пользователь отказался от текста — он не может взять его снова."""

    __tablename__ = "user_text_refusals"
    __table_args__ = (UniqueConstraint("user_id", "task_text_id", name="uq_user_text_refusal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    task_text_id: Mapped[int] = mapped_column(
        ForeignKey("task_texts.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TaskText(Base):
    __tablename__ = "task_texts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    text_number: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    required_gender: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    region: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    taken_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped["Task"] = relationship("Task", back_populates="texts")


class SubmissionStatus:
    COOLDOWN = "cooldown"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("user_id", "task_id", name="uq_user_task_submission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    task_text_id: Mapped[int | None] = mapped_column(ForeignKey("task_texts.id"), nullable=True, index=True)
    review_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=SubmissionStatus.PENDING)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User")
    task: Mapped["Task"] = relationship("Task")


class YandexMapsQuestion(Base):
    """Пул контрольных вопросов теста Яндекс Карт (слоты 1–15)."""

    __tablename__ = "yandex_maps_questions"

    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class YandexMapsSession(Base):
    __tablename__ = "yandex_maps_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    task_text_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_texts.id", ondelete="SET NULL"), nullable=True
    )
    step: Mapped[str] = mapped_column(String(32), index=True)
    region: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    question_index: Mapped[int] = mapped_column(Integer, default=0)
    quiz_slots: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_shown_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    freeze_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    review_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SupportTicketStatus:
    OPEN = "open"
    ANSWERED = "answered"
    REJECTED = "rejected"


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    photo_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default=SupportTicketStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User")


class SupportAdminMessage(Base):
    """Сообщение бота в чате админа — для ответа реплаем."""

    __tablename__ = "support_admin_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_id: Mapped[int] = mapped_column(
        ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True
    )
    admin_telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    bot_message_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WithdrawalStatus:
    CREATED = "created"
    EXECUTED = "executed"
    MANUALPAY = "manualpay"
    FAILED = "failed"


class WithdrawalAdminStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default=WithdrawalStatus.CREATED, index=True)
    admin_status: Mapped[str] = mapped_column(
        String(32), default=WithdrawalAdminStatus.PENDING, index=True
    )
    external_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    fps_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fps_bank_member_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class WebAdminSession(Base):
    __tablename__ = "web_admin_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ip_address: Mapped[str] = mapped_column(String(64), index=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class WebAdminEmailCode(Base):
    __tablename__ = "web_admin_email_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    purpose: Mapped[str] = mapped_column(String(32), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
