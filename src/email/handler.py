import logging
from collections import OrderedDict

from src.auth import is_authorized
from src.claude.client import ClaudeApiError, ClaudeClient, ClaudeRateLimitError
from src.email.parser import parse_email_payload
from src.email.responses import (
    error_response,
    rate_limit_response,
    success_response,
    unauthorized_response,
)
from src.excel.reader import ExcelReadError, format_summary_for_prompt, read_spreadsheet
from src.utils import sanitize_email

logger = logging.getLogger(__name__)

_MAX_SEEN = 1000
_seen_message_ids: OrderedDict[str, bool] = OrderedDict()


def clear_seen_messages() -> None:
    _seen_message_ids.clear()


def _is_duplicate(message_id: str) -> bool:
    if not message_id:
        return False
    if message_id in _seen_message_ids:
        return True
    _seen_message_ids[message_id] = True
    if len(_seen_message_ids) > _MAX_SEEN:
        _seen_message_ids.popitem(last=False)
    return False


def handle_email(
    payload: dict,
    allowlist: list[str],
    claude_client: ClaudeClient,
    max_xlsx_size_mb: int = 10,
    max_preview_rows: int = 50,
) -> dict:
    email = parse_email_payload(payload)

    if _is_duplicate(email.message_id):
        return {
            "reply": "This message has already been processed.",
            "error": "duplicate",
        }

    if not is_authorized(email.sender, allowlist):
        logger.warning("Unauthorized sender: %s", sanitize_email(email.sender))
        return unauthorized_response()

    question = email.question
    if not question:
        return error_response("No question found in email body or subject.")

    spreadsheet_context = None
    if email.attachments:
        context_parts = []
        for attachment in email.attachments:
            try:
                summary = read_spreadsheet(
                    attachment.data,
                    attachment.filename,
                    max_rows=max_preview_rows,
                    max_size_mb=max_xlsx_size_mb,
                )
                context_parts.append(format_summary_for_prompt(summary))
            except ExcelReadError as e:
                logger.warning("Excel read error: %s", e)
                return error_response(str(e))
        if context_parts:
            spreadsheet_context = "\n\n".join(context_parts)

    try:
        response = claude_client.ask_with_context(question, spreadsheet_context)
        return success_response(response.text)
    except ClaudeRateLimitError:
        return rate_limit_response()
    except ClaudeApiError as e:
        logger.error("Claude API error: %s", e)
        return error_response(str(e))
