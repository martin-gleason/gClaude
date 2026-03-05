import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Request

from src.claude.client import ClaudeClient
from src.config import Settings, get_settings

app = FastAPI(title="ExcelBot", version="0.2.0")


def _configure_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO))


@lru_cache
def get_claude_client() -> ClaudeClient:
    settings = get_settings()
    return ClaudeClient(api_key=settings.ANTHROPIC_API_KEY, model=settings.DEFAULT_MODEL)


def verify_webhook_secret(
    settings: Settings = Depends(get_settings),
    x_webhook_secret: str | None = Header(default=None),
) -> None:
    if not settings.GMAIL_WEBHOOK_SECRET:
        return
    if not x_webhook_secret or x_webhook_secret != settings.GMAIL_WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")


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
