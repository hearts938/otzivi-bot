import os
import secrets
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _parse_admin_ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


def _normalize_bearer_auth(raw: str | None) -> str:
    auth = (raw or "").strip()
    if not auth:
        return ""
    if not auth.lower().startswith("bearer "):
        return f"Bearer {auth}"
    return auth


@dataclass(frozen=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    database_url: str
    referral_percent_up_to_threshold: float
    referral_percent_after_threshold: float
    referral_count_threshold: int
    referral_first_task_bonus: float
    web_admin_password: str
    web_admin_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    web_session_secret: str
    web_host: str
    web_port: int
    app_timezone: str
    task_claim_minutes: int
    reviews_channel_url: str
    yandex_quiz_freeze_hours: int
    yandex_answer_min_seconds: int
    yandex_cheat_ban_days: int
    payments_api_base_url: str
    payments_api_auth: str
    payments_api_timeout_seconds: int
    min_withdrawal_amount: float
    reviews_stock_report_hour: int
    reviews_stock_report_minute: int


def get_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Укажите BOT_TOKEN в .env")
    web_pw = os.getenv("WEB_ADMIN_PASSWORD", "").strip()
    web_secret = os.getenv("WEB_SESSION_SECRET", "").strip() or secrets.token_hex(32)
    return Settings(
        bot_token=token,
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS")),
        database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db"),
        referral_percent_up_to_threshold=float(
            os.getenv(
                "REFERRAL_PERCENT_UP_TO_10",
                os.getenv("REFERRAL_LEVEL1_PERCENT", os.getenv("REFERRAL_PERCENT_OF_REWARD", "20")),
            )
        ),
        referral_percent_after_threshold=float(
            os.getenv("REFERRAL_PERCENT_AFTER_10", os.getenv("REFERRAL_LEVEL2_PERCENT", "5"))
        ),
        referral_count_threshold=int(os.getenv("REFERRAL_COUNT_THRESHOLD", "10")),
        referral_first_task_bonus=float(os.getenv("REFERRAL_FIRST_TASK_BONUS", "0")),
        web_admin_password=web_pw,
        web_admin_email=os.getenv("WEB_ADMIN_EMAIL", "").strip(),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
        smtp_from=os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
        web_session_secret=web_secret,
        web_host=os.getenv("WEB_HOST", "0.0.0.0"),
        web_port=int(os.getenv("WEB_PORT", "8000")),
        app_timezone=os.getenv("APP_TIMEZONE", "Europe/Moscow"),
        task_claim_minutes=int(os.getenv("TASK_CLAIM_MINUTES", "60")),
        reviews_channel_url=os.getenv("REVIEWS_CHANNEL_URL", "").strip(),
        yandex_quiz_freeze_hours=int(os.getenv("YANDEX_QUIZ_FREEZE_HOURS", "4")),
        yandex_answer_min_seconds=int(os.getenv("YANDEX_ANSWER_MIN_SECONDS", "5")),
        yandex_cheat_ban_days=int(os.getenv("YANDEX_CHEAT_BAN_DAYS", "7")),
        payments_api_base_url=os.getenv("PAYMENTS_API_BASE_URL", "https://api-payments.konsol.pro").strip(),
        payments_api_auth=_normalize_bearer_auth(os.getenv("PAYMENTS_API_AUTH", "")),
        payments_api_timeout_seconds=int(os.getenv("PAYMENTS_API_TIMEOUT_SECONDS", "20")),
        min_withdrawal_amount=float(os.getenv("MIN_WITHDRAWAL_AMOUNT", "500")),
        reviews_stock_report_hour=int(os.getenv("REVIEWS_STOCK_REPORT_HOUR", "22")),
        reviews_stock_report_minute=int(os.getenv("REVIEWS_STOCK_REPORT_MINUTE", "0")),
    )
