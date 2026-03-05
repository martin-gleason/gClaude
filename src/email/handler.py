import logging

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

logger = logging.getLogger(__name__)


def handle_email(
    payload: dict,
    allowlist: list[str],
    claude_client: ClaudeClient,
    max_xlsx_size_mb: int = 10,
    max_preview_rows: int = 50,
) -> dict:
    email = parse_email_payload(payload)

    if not is_authorized(email.sender, allowlist):
        logger.warning("Unauthorized sender: %s", email.sender)
        return unauthorized_response()

    question = email.question
    if not question:
        return error_response("No question found in email body or subject.")

    spreadsheet_context = None
    if email.attachments:
        attachment = email.attachments[0]
        try:
            summary = read_spreadsheet(
                attachment.data,
                attachment.filename,
                max_rows=max_preview_rows,
                max_size_mb=max_xlsx_size_mb,
            )
            spreadsheet_context = format_summary_for_prompt(summary)
        except ExcelReadError as e:
            logger.warning("Excel read error: %s", e)
            return error_response(str(e))

    try:
        answer = claude_client.ask_with_context(question, spreadsheet_context)
        return success_response(answer)
    except ClaudeRateLimitError:
        return rate_limit_response()
    except ClaudeApiError as e:
        logger.error("Claude API error: %s", e)
        return error_response(str(e))
