"""
Web Chat endpoint support for Apps Script Web App integration.
Authenticates via a shared bearer token (not Google Chat JWT).
"""

import base64
import hmac
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from src.config import Settings, get_settings
from src.excel.reader import ExcelReadError, format_summary_for_prompt, read_spreadsheet

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class WebChatRequest(BaseModel):
    user_email: str
    message: str
    conversation_history: list[ChatMessage] = []
    file_name: Optional[str] = None
    file_data: Optional[str] = None  # base64-encoded
    file_mime_type: Optional[str] = None


class WebChatResponse(BaseModel):
    message: str
    file_name: Optional[str] = None
    file_data: Optional[str] = None  # base64-encoded
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Auth dependency -- shared-secret bearer token
# ---------------------------------------------------------------------------


def verify_web_chat_secret(
    settings: Settings = Depends(get_settings),
    authorization: str = Header(default=""),
) -> None:
    """Verify the shared secret sent by Apps Script."""
    expected = settings.WEB_CHAT_SECRET
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="WEB_CHAT_SECRET is not configured on the server.",
        )

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    token = authorization[len("Bearer "):]
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# File processing helper
# ---------------------------------------------------------------------------


def summarize_uploaded_file(
    file_data_b64: str,
    file_name: str,
    max_size_mb: int = 10,
    max_preview_rows: int = 50,
) -> str:
    """Decode base64 file data and summarize using existing excel reader."""
    try:
        raw = base64.b64decode(file_data_b64)
    except Exception:
        return f"(Could not decode file data for {file_name})"

    if len(raw) > max_size_mb * 1024 * 1024:
        return f"(File {file_name} exceeds {max_size_mb}MB limit)"

    # CSV files need pandas, not openpyxl
    if file_name.lower().endswith(".csv"):
        return _summarize_csv(raw, file_name, max_preview_rows)

    try:
        summary = read_spreadsheet(
            raw, file_name, max_rows=max_preview_rows, max_size_mb=max_size_mb
        )
        return format_summary_for_prompt(summary)
    except ExcelReadError as e:
        logger.warning("Failed to parse spreadsheet %s: %s", file_name, e)
        return f"(Could not parse {file_name})"


def _summarize_csv(raw: bytes, file_name: str, max_rows: int) -> str:
    """Summarize a CSV file using pandas."""
    import io

    import pandas as pd

    try:
        df = pd.read_csv(io.BytesIO(raw))
        parts = [
            f"## Spreadsheet: {file_name}",
            "\n### Sheet: (CSV)",
            f"**Shape:** {df.shape[0]} rows x {df.shape[1]} columns",
            f"**Columns:** {list(df.columns)}",
            f"\nSample data (first {min(len(df), max_rows)} rows):",
            df.head(max_rows).to_string(index=False),
        ]
        return "\n".join(parts)
    except Exception as e:
        logger.warning("Failed to parse CSV %s: %s", file_name, e)
        return f"(Could not parse {file_name})"
