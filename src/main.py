import hmac
import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from src.chat.context import ThreadContextStore
from src.claude.client import ClaudeClient
from src.claude.usage import CostTracker, RateLimitTracker
from src.config import Settings, get_settings

app = FastAPI(title="ExcelBot", version="0.5.0")

_thread_store: ThreadContextStore | None = None
_rate_limit_tracker: RateLimitTracker | None = None
_cost_tracker: CostTracker | None = None


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


@lru_cache
def get_claude_client() -> ClaudeClient:
    settings = get_settings()
    return ClaudeClient(
        api_key=settings.ANTHROPIC_API_KEY,
        model=settings.DEFAULT_MODEL,
        complex_model=settings.COMPLEX_MODEL,
    )


def get_thread_store() -> ThreadContextStore:
    global _thread_store
    if _thread_store is None:
        settings = get_settings()
        _thread_store = ThreadContextStore(
            max_entries=settings.THREAD_CONTEXT_MAX_ENTRIES,
            ttl_seconds=settings.THREAD_CONTEXT_TTL_SECONDS,
            max_turns=settings.THREAD_CONTEXT_MAX_TURNS,
        )
    return _thread_store


def get_rate_limit_tracker() -> RateLimitTracker:
    global _rate_limit_tracker
    if _rate_limit_tracker is None:
        settings = get_settings()
        _rate_limit_tracker = RateLimitTracker(
            rpm_limit=settings.RATE_LIMIT_RPM,
            itpm_limit=settings.RATE_LIMIT_INPUT_TPM,
            warning_threshold=settings.RATE_LIMIT_WARNING_THRESHOLD,
        )
    return _rate_limit_tracker


def get_cost_tracker() -> CostTracker:
    global _cost_tracker
    if _cost_tracker is None:
        settings = get_settings()
        _cost_tracker = CostTracker(
            daily_budget_usd=settings.DAILY_BUDGET_USD,
            warning_threshold=settings.COST_WARNING_THRESHOLD,
            sonnet_input_cost_per_m=settings.SONNET_INPUT_COST_PER_M,
            sonnet_output_cost_per_m=settings.SONNET_OUTPUT_COST_PER_M,
            opus_input_cost_per_m=settings.OPUS_INPUT_COST_PER_M,
            opus_output_cost_per_m=settings.OPUS_OUTPUT_COST_PER_M,
        )
    return _cost_tracker


def get_file_storage():
    settings = get_settings()
    if not settings.GCS_BUCKET_NAME:
        return None
    from src.storage.gcs import GCSStorage

    service_account = (
        settings.GCS_SERVICE_ACCOUNT_FILE
        or settings.GOOGLE_CHAT_SERVICE_ACCOUNT_FILE
        or None
    )
    return GCSStorage(
        bucket_name=settings.GCS_BUCKET_NAME,
        signed_url_expiration_hours=settings.GCS_SIGNED_URL_EXPIRATION_HOURS,
        prefix=settings.GCS_GENERATED_FILES_PREFIX,
        service_account_file=service_account,
    )


def get_attachment_downloader():
    settings = get_settings()
    if not settings.GOOGLE_CHAT_SERVICE_ACCOUNT_FILE:
        return None
    from src.chat.attachments import ChatAttachmentDownloader

    return ChatAttachmentDownloader(
        service_account_file=settings.GOOGLE_CHAT_SERVICE_ACCOUNT_FILE
    )


def verify_webhook_secret(
    settings: Settings = Depends(get_settings),
    x_webhook_secret: str | None = Header(default=None),
) -> None:
    if not settings.GMAIL_WEBHOOK_SECRET:
        return
    if not x_webhook_secret or not hmac.compare_digest(
        x_webhook_secret, settings.GMAIL_WEBHOOK_SECRET
    ):
        raise HTTPException(
            status_code=401, detail="Invalid or missing webhook secret"
        )


def verify_google_token(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    if not settings.GOOGLE_CHAT_PROJECT_NUMBER:
        return
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = auth_header[len("Bearer "):]
    from src.chat.auth import GoogleTokenError, verify_google_chat_token

    try:
        verify_google_chat_token(token, settings.GOOGLE_CHAT_PROJECT_NUMBER)
    except GoogleTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/email")
async def email_webhook(
    request: Request,
    _secret: None = Depends(verify_webhook_secret),
    settings: Settings = Depends(get_settings),
    claude_client: ClaudeClient = Depends(get_claude_client),
) -> dict:
    from src.email.handler import handle_email

    payload = await request.json()
    return handle_email(
        payload=payload,
        allowlist=settings.authorized_users_list,
        claude_client=claude_client,
        max_xlsx_size_mb=settings.MAX_XLSX_SIZE_MB,
        max_preview_rows=settings.MAX_PREVIEW_ROWS,
    )


@app.post("/chat")
async def chat_webhook(
    request: Request,
    _token: None = Depends(verify_google_token),
    settings: Settings = Depends(get_settings),
    claude_client: ClaudeClient = Depends(get_claude_client),
) -> dict:
    from src.chat.handler import handle_chat_event

    payload = await request.json()
    thread_store = get_thread_store()
    attachment_downloader = get_attachment_downloader()
    file_storage = get_file_storage()
    rate_tracker = get_rate_limit_tracker()
    cost_tracker = get_cost_tracker()
    return handle_chat_event(
        payload=payload,
        allowlist=settings.authorized_users_list,
        claude_client=claude_client,
        require_mention=settings.MENTION_TRIGGER,
        thread_store=thread_store,
        attachment_downloader=attachment_downloader,
        file_storage=file_storage,
        max_xlsx_size_mb=settings.MAX_XLSX_SIZE_MB,
        max_preview_rows=settings.MAX_PREVIEW_ROWS,
        rate_limit_tracker=rate_tracker,
        cost_tracker=cost_tracker,
    )
