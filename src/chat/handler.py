import logging
import re

from src.auth import is_authorized
from src.chat.attachments import AttachmentDownloadError, is_xlsx_attachment
from src.chat.context import ThreadContextStore
from src.chat.parser import parse_chat_event
from src.chat.response_parser import parse_claude_response
from src.chat.responses import (
    empty_response,
    error_response,
    file_response,
    rate_limit_response,
    removed_response,
    storage_failure_response,
    success_response,
    timeout_response,
    unauthorized_response,
    welcome_response,
)
from src.claude.client import ClaudeApiError, ClaudeClient, ClaudeRateLimitError
from src.claude.models import is_complex_question
from src.claude.prompts import ANALYSIS_CONTEXT_TEMPLATE
from src.claude.usage import CostTracker, RateLimitTracker, ThreadUsageTracker, format_usage_footer
from src.excel.analyzer import AnalysisError, analyze_spreadsheet, format_analysis_for_prompt
from src.excel.reader import ExcelReadError, format_summary_for_prompt, read_spreadsheet
from src.excel.writer import WorkbookBuildError, build_workbook_from_spec, modify_workbook
from src.storage.interface import StorageError
from src.utils import sanitize_email

logger = logging.getLogger(__name__)

_GENERATION_KEYWORDS = re.compile(
    r"\b(create|make|generate|build me|build a|build an)\b", re.IGNORECASE
)

XLSX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _has_generation_intent(question: str) -> bool:
    return bool(_GENERATION_KEYWORDS.search(question))


def handle_chat_event(
    payload: dict,
    allowlist: list[str],
    claude_client: ClaudeClient,
    require_mention: bool = True,
    thread_store: ThreadContextStore | None = None,
    attachment_downloader=None,
    file_storage=None,
    max_xlsx_size_mb: int = 10,
    max_preview_rows: int = 50,
    rate_limit_tracker: RateLimitTracker | None = None,
    cost_tracker: CostTracker | None = None,
) -> dict:
    event = parse_chat_event(payload)

    if event.event_type == "ADDED_TO_SPACE":
        return welcome_response()

    if event.event_type == "REMOVED_FROM_SPACE":
        return removed_response()

    if event.event_type != "MESSAGE":
        return empty_response()

    if event.space_type == "ROOM" and require_mention and not event.question:
        return empty_response()

    if not is_authorized(event.sender_email, allowlist):
        logger.warning("Unauthorized chat sender: %s", sanitize_email(event.sender_email))
        return unauthorized_response()

    question = event.question
    if not question:
        question = event.raw_text.strip()
    if not question:
        return error_response()

    thread_name = event.thread_name

    # --- Attachment processing ---
    spreadsheet_context = None
    attachment_bytes = None
    if attachment_downloader and event.attachments:
        xlsx_attachments = [
            att for att in event.attachments
            if att.source == "UPLOADED_CONTENT"
            and is_xlsx_attachment(att.content_type, att.content_name)
        ]
        if xlsx_attachments:
            try:
                att = xlsx_attachments[0]  # Process first xlsx attachment
                file_bytes = attachment_downloader.download(att.resource_name)
                attachment_bytes = file_bytes
                summary = read_spreadsheet(
                    file_bytes, att.content_name,
                    max_rows=max_preview_rows, max_size_mb=max_xlsx_size_mb,
                )
                raw_preview = format_summary_for_prompt(summary)
                try:
                    analysis = analyze_spreadsheet(
                        file_bytes, att.content_name,
                        max_rows=1000, max_size_mb=max_xlsx_size_mb,
                    )
                    analysis_stats = format_analysis_for_prompt(analysis)
                except AnalysisError:
                    analysis_stats = ""

                if analysis_stats:
                    spreadsheet_context = ANALYSIS_CONTEXT_TEMPLATE.format(
                        raw_preview=raw_preview, analysis_stats=analysis_stats,
                    )
                else:
                    spreadsheet_context = raw_preview
            except AttachmentDownloadError as e:
                logger.warning("Attachment download error: %s", e)
                return error_response()
            except ExcelReadError as e:
                logger.warning("Excel read error: %s", e)
                return error_response()

    # --- Generation / Modification flow ---
    if file_storage and _has_generation_intent(question):
        try:
            response = claude_client.ask_for_generation(
                question, spreadsheet_context=spreadsheet_context
            )
            if cost_tracker:
                cost_tracker.record_usage(
                    claude_client.model, response.input_tokens,
                    response.output_tokens, user=event.sender_email,
                )
            raw_response = response.text
            parsed = parse_claude_response(raw_response)

            gen_footer = format_usage_footer(cost_tracker=cost_tracker)

            if parsed.is_workbook:
                if attachment_bytes and spreadsheet_context:
                    # Modification: apply spec to existing workbook
                    xlsx_bytes = modify_workbook(attachment_bytes, parsed.workbook_spec)
                else:
                    # Generation: build new workbook from spec
                    xlsx_bytes = build_workbook_from_spec(parsed.workbook_spec)

                filename = _generate_filename(question)
                download_url = file_storage.upload(
                    xlsx_bytes, filename, XLSX_CONTENT_TYPE
                )
                return file_response(
                    "Here's your spreadsheet!",
                    download_url, filename, thread_name=thread_name,
                    usage_footer=gen_footer,
                )
            else:
                # Claude decided a text response was better
                return success_response(
                    parsed.text, thread_name=thread_name, usage_footer=gen_footer,
                )

        except WorkbookBuildError as e:
            logger.warning("Workbook build error: %s", e)
            return error_response()
        except StorageError as e:
            logger.warning("Storage error: %s", e)
            return storage_failure_response(thread_name=thread_name)
        except TimeoutError:
            return timeout_response(thread_name=thread_name)
        except ClaudeRateLimitError:
            return rate_limit_response()
        except ClaudeApiError as e:
            logger.error("Claude API error in generation: %s", e)
            return error_response()

    # --- Route to appropriate Claude method ---
    try:
        if thread_store and thread_name:
            history = thread_store.get_history(thread_name)
            # Get persisted spreadsheet context from previous turns if no new attachment
            persisted_context = None
            existing_ctx = thread_store.get(thread_name)
            if existing_ctx:
                persisted_context = existing_ctx.spreadsheet_context
            effective_context = spreadsheet_context or persisted_context

            response = claude_client.ask_with_history(
                question,
                history=history,
                spreadsheet_context=effective_context,
            )
            answer = response.text

            # Record usage in thread store
            thread_store.add_turn(
                thread_name, question, answer,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
            if spreadsheet_context:
                thread_store.set_spreadsheet_context(thread_name, spreadsheet_context)

            # Record in rate limit tracker
            if rate_limit_tracker:
                rate_limit_tracker.record_request(
                    input_tokens=response.input_tokens,
                )

            # Record cost
            if cost_tracker:
                cost_tracker.record_usage(
                    claude_client.model, response.input_tokens,
                    response.output_tokens, user=event.sender_email,
                )

            # Build usage footer
            thread_ctx = thread_store.get(thread_name)
            thread_tracker = ThreadUsageTracker()
            if thread_ctx:
                for turn in thread_ctx.turns:
                    thread_tracker.record_turn(turn.input_tokens, turn.output_tokens)

            footer = format_usage_footer(
                thread_tracker=thread_tracker,
                rate_tracker=rate_limit_tracker,
                cost_tracker=cost_tracker,
            )
            return success_response(answer, thread_name=thread_name, usage_footer=footer)
        elif is_complex_question(question):
            response = claude_client.ask_complex(
                question, spreadsheet_context=spreadsheet_context
            )
            if rate_limit_tracker:
                rate_limit_tracker.record_request(
                    input_tokens=response.input_tokens,
                )
            if cost_tracker:
                model = claude_client.complex_model or claude_client.model
                cost_tracker.record_usage(
                    model, response.input_tokens,
                    response.output_tokens, user=event.sender_email,
                )
            qa_footer = format_usage_footer(cost_tracker=cost_tracker)
            return success_response(response.text, usage_footer=qa_footer)
        elif spreadsheet_context:
            response = claude_client.ask_with_context(question, spreadsheet_context)
            if rate_limit_tracker:
                rate_limit_tracker.record_request(
                    input_tokens=response.input_tokens,
                )
            if cost_tracker:
                cost_tracker.record_usage(
                    claude_client.model, response.input_tokens,
                    response.output_tokens, user=event.sender_email,
                )
            qa_footer = format_usage_footer(cost_tracker=cost_tracker)
            return success_response(response.text, usage_footer=qa_footer)
        else:
            response = claude_client.ask(question)
            if rate_limit_tracker:
                rate_limit_tracker.record_request(
                    input_tokens=response.input_tokens,
                )
            if cost_tracker:
                cost_tracker.record_usage(
                    claude_client.model, response.input_tokens,
                    response.output_tokens, user=event.sender_email,
                )
            qa_footer = format_usage_footer(cost_tracker=cost_tracker)
            return success_response(response.text, usage_footer=qa_footer)
    except ClaudeRateLimitError:
        return rate_limit_response()
    except ClaudeApiError as e:
        logger.error("Claude API error in chat: %s", e)
        return error_response()


def _generate_filename(question: str) -> str:
    # Extract a meaningful filename from the question
    words = re.sub(r"[^\w\s]", "", question).split()
    # Take first few meaningful words, skip generation keywords
    skip = {"create", "make", "generate", "build", "me", "a", "an", "the"}
    name_parts = [w.lower() for w in words if w.lower() not in skip][:3]
    if name_parts:
        return "_".join(name_parts) + ".xlsx"
    return "spreadsheet.xlsx"
