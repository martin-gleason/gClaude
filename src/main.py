import hmac
import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from src.chat.context import ThreadContextStore
from src.claude.client import ClaudeApiError, ClaudeClient, ClaudeRateLimitError
from src.claude.usage import CostTracker, RateLimitTracker
from src.config import Settings, get_settings
from src.web_chat import (
    WebChatRequest,
    WebChatResponse,
    summarize_uploaded_file,
    verify_web_chat_secret,
)

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


@app.post("/web-chat", response_model=WebChatResponse)
async def web_chat_endpoint(
    request: WebChatRequest,
    _auth: None = Depends(verify_web_chat_secret),
    settings: Settings = Depends(get_settings),
    claude_client: ClaudeClient = Depends(get_claude_client),
) -> WebChatResponse:
    """Chat endpoint for the Apps Script Web App frontend."""
    logger = logging.getLogger(__name__)

    # Authorization check
    allowed = settings.authorized_users_list
    if allowed and request.user_email.lower() not in [u.lower() for u in allowed]:
        return WebChatResponse(
            message="Sorry, I'm not set up to help this account.",
            error="unauthorized",
        )

    # Budget enforcement
    cost_tracker = get_cost_tracker()
    if cost_tracker.daily_cost_usd > cost_tracker.daily_budget_usd:
        return WebChatResponse(
            message="ExcelBot has reached its daily usage limit. Please try again tomorrow.",
            error="budget_exceeded",
        )

    # Cap conversation history server-side
    max_pairs = settings.MAX_CONVERSATION_HISTORY_PAIRS
    history_messages = request.conversation_history[-(max_pairs * 2):]

    # Build message history for ClaudeClient
    history_dicts = [{"role": msg.role, "content": msg.content} for msg in history_messages]

    # Process file attachment if present
    spreadsheet_context = None
    if request.file_data and request.file_name:
        spreadsheet_context = summarize_uploaded_file(
            request.file_data,
            request.file_name,
            max_size_mb=settings.MAX_XLSX_SIZE_MB,
            max_preview_rows=settings.MAX_PREVIEW_ROWS,
        )

    # Build user content with optional spreadsheet context
    user_content = request.message
    if spreadsheet_context:
        user_content = f"[Uploaded file]\n{spreadsheet_context}\n\n[Question]\n{request.message}"

    # Add current message to history
    history_dicts.append({"role": "user", "content": user_content})

    # Call Claude via the existing wrapper
    rate_tracker = get_rate_limit_tracker()
    try:
        response = claude_client._call_api(messages=history_dicts)

        # Record usage
        rate_tracker.record_request(input_tokens=response.input_tokens)
        cost_tracker.record_usage(
            claude_client.model,
            response.input_tokens,
            response.output_tokens,
            user=request.user_email,
        )

        return WebChatResponse(message=response.text)

    except ClaudeRateLimitError:
        return WebChatResponse(
            message="I'm getting too many questions right now. Wait a moment and try again.",
            error="rate_limited",
        )
    except ClaudeApiError as e:
        logger.error("Claude API error in web-chat: %s", e)
        return WebChatResponse(
            message="Sorry, I ran into a problem. Try asking again in a moment.",
            error="internal_error",
        )
    except Exception as e:
        logger.error("Unexpected error in web-chat: %s", e)
        return WebChatResponse(
            message="Sorry, something went wrong. Please try again.",
            error="internal_error",
        )
