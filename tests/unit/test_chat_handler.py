import json
from unittest.mock import MagicMock, patch

import pytest

from src.chat.attachments import AttachmentDownloadError
from src.chat.context import ThreadContextStore
from src.chat.handler import handle_chat_event
from src.chat.responses import WELCOME_MESSAGE
from src.claude.client import ClaudeApiError, ClaudeRateLimitError, ClaudeResponse
from src.claude.usage import CostTracker, RateLimitTracker
from src.storage.interface import StorageError
from src.storage.memory import InMemoryStorage


def _cr(text: str, input_tokens: int = 100, output_tokens: int = 50) -> ClaudeResponse:
    """Shorthand to build a ClaudeResponse for mocks."""
    return ClaudeResponse(text=text, input_tokens=input_tokens, output_tokens=output_tokens)


@pytest.fixture
def mock_claude():
    client = MagicMock()
    client.ask.return_value = _cr("Here's how to use VLOOKUP...")
    client.ask_with_history.return_value = _cr("Follow-up answer")
    client.ask_with_context.return_value = _cr("Spreadsheet analysis")
    return client


@pytest.fixture
def thread_store():
    store = ThreadContextStore()
    yield store
    store.clear()


@pytest.fixture
def mock_downloader():
    return MagicMock()


def _room_message_payload(
    email="user@example.com",
    argument_text="How do I use VLOOKUP?",
    thread_name="",
    attachments=None,
):
    payload = {
        "type": "MESSAGE",
        "user": {"email": email, "displayName": "Test User"},
        "message": {
            "text": f"@ExcelBot {argument_text}",
            "argumentText": argument_text,
        },
        "space": {"name": "spaces/AAA", "type": "ROOM"},
    }
    if thread_name:
        payload["message"]["thread"] = {"name": thread_name}
    if attachments:
        payload["message"]["attachment"] = attachments
    return payload


def _dm_message_payload(email="user@example.com", text="How do I use VLOOKUP?"):
    return {
        "type": "MESSAGE",
        "user": {"email": email, "displayName": "Test User"},
        "message": {
            "text": text,
            "argumentText": "",
        },
        "space": {"name": "spaces/DM1", "type": "DM"},
    }


XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_attachment(name="att/1", filename="report.xlsx"):
    return {
        "name": name,
        "contentName": filename,
        "contentType": XLSX_MIME,
        "source": "UPLOADED_CONTENT",
    }


# --- Phase 3: Space Lifecycle (US-1.1) ---


class TestSpaceLifecycle:
    def test_bot_responds_to_added_to_space_event(self, mock_claude):
        payload = {
            "type": "ADDED_TO_SPACE",
            "user": {"email": "admin@example.com", "displayName": "Admin"},
            "space": {"name": "spaces/XYZ", "type": "ROOM"},
        }
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "text" in result
        assert result["text"] == WELCOME_MESSAGE
        mock_claude.ask.assert_not_called()

    def test_bot_welcome_message_content(self, mock_claude):
        payload = {
            "type": "ADDED_TO_SPACE",
            "user": {"email": "admin@example.com"},
            "space": {"type": "ROOM"},
        }
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "ExcelBot" in result["text"]
        assert "@" in result["text"]

    def test_bot_handles_removed_from_space(self, mock_claude):
        payload = {
            "type": "REMOVED_FROM_SPACE",
            "user": {"email": "admin@example.com"},
            "space": {"type": "ROOM"},
        }
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert result == {}
        mock_claude.ask.assert_not_called()


# --- Phase 4: Mention Detection (US-1.2) ---


class TestMentionDetection:
    def test_bot_responds_to_at_mention(self, mock_claude):
        payload = _room_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "Here's how to use VLOOKUP..." in result["text"]
        mock_claude.ask.assert_called_once()

    def test_bot_ignores_non_mention(self, mock_claude):
        payload = _room_message_payload(argument_text="")
        payload["message"]["text"] = "random conversation"
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert result == {}
        mock_claude.ask.assert_not_called()

    def test_bot_responds_to_dm(self, mock_claude):
        payload = _dm_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "Here's how to use VLOOKUP..." in result["text"]
        mock_claude.ask.assert_called_once()

    def test_mention_config_toggle(self, mock_claude):
        payload = _room_message_payload(argument_text="")
        payload["message"]["text"] = "How do I use VLOOKUP?"
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude, require_mention=False
        )
        assert "Here's how to use VLOOKUP..." in result["text"]
        mock_claude.ask.assert_called_once_with("How do I use VLOOKUP?")


# --- Phase 5: Authorization (US-2.1) ---


class TestAuthorization:
    def test_authorized_user_gets_response(self, mock_claude):
        payload = _room_message_payload(email="shannon@gmail.com")
        result = handle_chat_event(
            payload, allowlist=["shannon@gmail.com"], claude_client=mock_claude
        )
        assert "Here's how to use VLOOKUP..." in result["text"]

    def test_unauthorized_user_rejected(self, mock_claude):
        payload = _room_message_payload(email="stranger@example.com")
        result = handle_chat_event(
            payload, allowlist=["shannon@gmail.com"], claude_client=mock_claude
        )
        assert "authorized" in result["text"].lower()
        mock_claude.ask.assert_not_called()

    def test_empty_allowlist_allows_all(self, mock_claude):
        payload = _room_message_payload(email="anyone@example.com")
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "Here's how to use VLOOKUP..." in result["text"]


# --- Phase 6: Q&A + Errors (US-3.1) ---


class TestLogSanitization:
    def test_unauthorized_chat_log_sanitized(self, mock_claude, caplog):
        import logging
        payload = _room_message_payload(email="stranger@example.com")
        with caplog.at_level(logging.WARNING):
            handle_chat_event(
                payload, allowlist=["shannon@gmail.com"], claude_client=mock_claude
            )
        assert "stranger@example.com" not in caplog.text
        assert "s******r@example.com" in caplog.text


class TestQAAndErrors:
    def test_simple_question_returns_answer(self, mock_claude):
        payload = _room_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "Here's how to use VLOOKUP..." in result["text"]
        mock_claude.ask.assert_called_once_with("How do I use VLOOKUP?")

    def test_claude_api_error_graceful(self, mock_claude):
        mock_claude.ask.side_effect = ClaudeApiError("API failed")
        payload = _room_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "wrong" in result["text"].lower()
        assert "API failed" not in result["text"]

    def test_rate_limit_handling(self, mock_claude):
        mock_claude.ask.side_effect = ClaudeRateLimitError("rate limited")
        payload = _room_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        text = result["text"].lower()
        assert "again" in text or "later" in text


# --- Sprint 2: Thread Context (US-3.2) ---


class TestThreadContext:
    def test_thread_context_maintained(self, mock_claude, thread_store):
        """Second message in same thread gets history passed to ask_with_history."""
        payload1 = _room_message_payload(
            argument_text="What is VLOOKUP?",
            thread_name="spaces/AAA/threads/T1",
        )
        handle_chat_event(
            payload1, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )

        payload2 = _room_message_payload(
            argument_text="Can you give an example?",
            thread_name="spaces/AAA/threads/T1",
        )
        handle_chat_event(
            payload2, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )

        mock_claude.ask_with_history.assert_called()
        # The first call should have created a turn in the store
        assert len(thread_store.get_history("spaces/AAA/threads/T1")) == 2

    def test_separate_threads_independent(self, mock_claude, thread_store):
        payload1 = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        payload2 = _room_message_payload(
            argument_text="Q2", thread_name="spaces/AAA/threads/T2"
        )
        handle_chat_event(
            payload1, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        handle_chat_event(
            payload2, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        assert len(thread_store.get_history("spaces/AAA/threads/T1")) == 1
        assert len(thread_store.get_history("spaces/AAA/threads/T2")) == 1

    def test_context_window_limit(self, mock_claude):
        store = ThreadContextStore(max_turns=2)
        for i in range(3):
            payload = _room_message_payload(
                argument_text=f"Q{i}", thread_name="spaces/AAA/threads/T1"
            )
            handle_chat_event(
                payload, allowlist=[], claude_client=mock_claude,
                thread_store=store,
            )
        assert len(store.get_history("spaces/AAA/threads/T1")) == 2

    def test_no_thread_store_falls_back_to_simple_ask(self, mock_claude):
        """Without thread_store, handler uses claude_client.ask() (backward compat)."""
        payload = _room_message_payload(thread_name="spaces/AAA/threads/T1")
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=None,
        )
        mock_claude.ask.assert_called_once()
        mock_claude.ask_with_history.assert_not_called()

    def test_thread_response_includes_thread_key(self, mock_claude, thread_store):
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        assert "thread" in result
        assert result["thread"]["name"] == "spaces/AAA/threads/T1"


# --- Sprint 2: Attachment Handling (US-4.1) ---


class TestAttachmentHandling:
    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_xlsx_upload_detected_and_processed(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "| col A |"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "mean: 42"

        payload = _room_message_payload(
            argument_text="Analyze this",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        mock_downloader.download.assert_called_once()
        mock_read.assert_called_once()

    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_spreadsheet_summary_in_context(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "| col A |"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "mean: 42"

        payload = _room_message_payload(
            argument_text="Summarize",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        # Should call ask_with_context with combined context
        mock_claude.ask_with_context.assert_called_once()
        context_arg = mock_claude.ask_with_context.call_args[0][1]
        assert "col A" in context_arg
        assert "mean: 42" in context_arg

    def test_no_downloader_ignores_attachments(self, mock_claude):
        payload = _room_message_payload(
            argument_text="Analyze this",
            attachments=[_xlsx_attachment()],
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=None,
        )
        # Falls back to simple ask
        mock_claude.ask.assert_called_once()
        assert "text" in result

    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_download_error_returns_friendly_error(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        mock_downloader.download.side_effect = AttachmentDownloadError("Failed")
        payload = _room_message_payload(
            argument_text="Analyze",
            attachments=[_xlsx_attachment()],
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        assert "wrong" in result["text"].lower() or "error" in result["text"].lower()

    def test_non_xlsx_attachment_skipped(self, mock_claude, mock_downloader):
        payload = _room_message_payload(
            argument_text="Check this",
            attachments=[{
                "name": "att/1",
                "contentName": "notes.pdf",
                "contentType": "application/pdf",
                "source": "UPLOADED_CONTENT",
            }],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        mock_downloader.download.assert_not_called()
        mock_claude.ask.assert_called_once()

    def test_drive_attachment_skipped_for_mvp(self, mock_claude, mock_downloader):
        payload = _room_message_payload(
            argument_text="Check this",
            attachments=[{
                "name": "att/1",
                "contentName": "report.xlsx",
                "contentType": XLSX_MIME,
                "source": "DRIVE_FILE",
            }],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        mock_downloader.download.assert_not_called()
        mock_claude.ask.assert_called_once()

    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_spreadsheet_context_persists_in_thread(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader, thread_store,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "| col A |"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "mean: 42"

        # First message: upload attachment
        payload1 = _room_message_payload(
            argument_text="Analyze",
            thread_name="spaces/AAA/threads/T1",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload1, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
            attachment_downloader=mock_downloader,
        )

        # Second message: follow-up without attachment
        payload2 = _room_message_payload(
            argument_text="What is the average?",
            thread_name="spaces/AAA/threads/T1",
        )
        handle_chat_event(
            payload2, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )

        # ask_with_history should be called with spreadsheet_context
        mock_claude.ask_with_history.assert_called()
        call_kwargs = mock_claude.ask_with_history.call_args.kwargs
        assert call_kwargs.get("spreadsheet_context") is not None


# --- Sprint 2: Data Analysis (US-4.2) ---


class TestDataAnalysis:
    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_data_question_uses_pandas(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "raw preview"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "mean: 50"

        payload = _room_message_payload(
            argument_text="What is the average?",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        mock_analyze.assert_called_once()
        context_arg = mock_claude.ask_with_context.call_args[0][1]
        assert "mean: 50" in context_arg

    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_multi_sheet_awareness(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "Sheet1 data\nSheet2 data"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "Sheet1: mean=10\nSheet2: mean=20"

        payload = _room_message_payload(
            argument_text="Compare sheets",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        context_arg = mock_claude.ask_with_context.call_args[0][1]
        assert "Sheet1" in context_arg
        assert "Sheet2" in context_arg


# --- Sprint 3: File Generation (US-5.1) ---


def _valid_workbook_json():
    return json.dumps({
        "sheets": [{
            "name": "Budget",
            "columns": ["Category", "Amount"],
            "rows": [["Rent", 1500], ["Food", 500]],
        }]
    })


@pytest.fixture
def mock_file_storage():
    return InMemoryStorage()


class TestFileGeneration:
    def test_generate_spreadsheet_returns_file_response(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert "Download" in result["text"]
        assert ".xlsx" in result["text"]

    def test_generate_uploads_to_storage(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(argument_text="Make me a budget tracker")
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert len(mock_file_storage._store) == 1

    def test_generate_url_in_response(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(argument_text="Generate a sales report")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert "memory://" in result["text"]

    def test_generate_fallback_to_text(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr("I can't create that as a spreadsheet.")

        payload = _room_message_payload(argument_text="Create something abstract")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert "can't create" in result["text"]
        assert len(mock_file_storage._store) == 0

    def test_generate_without_storage_falls_back(self, mock_claude):
        """Without file_storage, generation keywords just go through normal Q&A."""
        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=None,
        )
        mock_claude.ask.assert_called_once()
        assert "Here's how to use VLOOKUP..." in result["text"]

    def test_generate_build_error_returns_error(self, mock_claude, mock_file_storage):
        # Return JSON that will parse but cause a build error
        mock_claude.ask_for_generation.return_value = _cr(json.dumps({
            "sheets": [{"name": "S", "columns": [], "rows": []}]
        }))

        payload = _room_message_payload(argument_text="Create a tracker")
        # This produces a valid spec with empty columns; let's instead simulate
        # a WorkbookBuildError via a bad spec
        mock_claude.ask_for_generation.return_value = _cr(json.dumps({"sheets": []}))
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        # parse_claude_response will fail → text fallback, or WorkbookBuildError
        # With empty sheets, parse_workbook_spec raises WorkbookBuildError,
        # parse_claude_response returns is_workbook=False with parse_error
        assert "text" in result


# --- Sprint 3: File Modification (US-5.2) ---


class TestFileModification:
    @patch("src.chat.handler.modify_workbook")
    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_modify_spreadsheet_returns_file_response(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_modify_wb, mock_claude, mock_downloader, mock_file_storage,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "| col A |"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "mean: 42"
        mock_modify_wb.return_value = b"modified-xlsx-bytes"
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(
            argument_text="Make a total column",
            attachments=[_xlsx_attachment()],
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
            file_storage=mock_file_storage,
        )
        assert "Download" in result["text"]
        mock_claude.ask_for_generation.assert_called_once()
        mock_modify_wb.assert_called_once()

    @patch("src.chat.handler.modify_workbook")
    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_modify_preserves_original_context(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_modify_wb, mock_claude, mock_downloader, mock_file_storage,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "spreadsheet data"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "stats"
        mock_modify_wb.return_value = b"modified-xlsx-bytes"
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(
            argument_text="Create a new version with totals",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
            file_storage=mock_file_storage,
        )
        call_kwargs = mock_claude.ask_for_generation.call_args
        context = (
            call_kwargs.kwargs.get("spreadsheet_context")
            or call_kwargs[1].get("spreadsheet_context")
        )
        assert context is not None

    def test_modify_without_attachment_generates_new(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert "Download" in result["text"]

    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_modify_download_error_returns_error(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader, mock_file_storage,
    ):
        mock_downloader.download.side_effect = AttachmentDownloadError("Failed")
        payload = _room_message_payload(
            argument_text="Create a modified version",
            attachments=[_xlsx_attachment()],
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
            file_storage=mock_file_storage,
        )
        assert "wrong" in result["text"].lower() or "error" in result["text"].lower()


# --- Sprint 3: Error Handling (US-6.1) ---


class TestGenerationErrorHandling:
    def test_storage_upload_error_returns_storage_failure(self, mock_claude):
        storage = MagicMock()
        storage.upload.side_effect = StorageError("GCS down")
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=storage,
        )
        assert "unable" in result["text"].lower() or "save" in result["text"].lower()

    def test_claude_timeout_returns_timeout_response(self, mock_claude):
        storage = InMemoryStorage()
        mock_claude.ask_for_generation.side_effect = TimeoutError("Timed out")

        payload = _room_message_payload(argument_text="Generate a complex spreadsheet")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=storage,
        )
        assert "too long" in result["text"].lower()


# --- US-4.3: Complex Excel Functions ---


class TestComplexRouting:
    def test_complex_question_routes_to_opus(self, mock_claude):
        mock_claude.ask_complex.return_value = _cr("NPV is $1,234")
        payload = _room_message_payload(
            argument_text="Calculate NPV and IRR for this investment"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude
        )
        mock_claude.ask_complex.assert_called_once()
        mock_claude.ask.assert_not_called()
        assert result["text"] == "NPV is $1,234"

    def test_simple_question_stays_on_sonnet(self, mock_claude):
        payload = _room_message_payload(
            argument_text="How do I freeze panes?"
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude
        )
        mock_claude.ask.assert_called_once()
        mock_claude.ask_complex.assert_not_called()

    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    @patch("src.chat.handler.format_analysis_for_prompt")
    def test_complex_with_attachment_uses_context(
        self, mock_fmt_analysis, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "| Revenue |"
        mock_analyze.return_value = MagicMock()
        mock_fmt_analysis.return_value = "mean: 500"
        mock_claude.ask_complex.return_value = _cr("Forecast result")

        payload = _room_message_payload(
            argument_text="Build a forecast model from this data",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        mock_claude.ask_complex.assert_called_once()
        call_kwargs = mock_claude.ask_complex.call_args
        context = call_kwargs.kwargs.get("spreadsheet_context")
        assert context is not None
        assert "Revenue" in context

    def test_complex_question_in_thread_routes_to_history(self, mock_claude, thread_store):
        """Complex questions in threads go through ask_with_history, not ask_complex."""
        mock_claude.ask_with_history.return_value = _cr("Thread answer about forecasting")
        payload = _room_message_payload(
            argument_text="Build a forecast model",
            thread_name="spaces/AAA/threads/T1",
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        mock_claude.ask_with_history.assert_called_once()
        mock_claude.ask_complex.assert_not_called()
        assert "Thread answer about forecasting" in result["text"]

    def test_complex_without_complex_model_still_works(self, mock_claude):
        """Even if complex_model isn't configured, ask_complex is called
        and falls back to default model internally."""
        mock_claude.ask_complex.return_value = _cr("Amortization schedule")
        payload = _room_message_payload(
            argument_text="Calculate amortization for a 30-year mortgage"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude
        )
        mock_claude.ask_complex.assert_called_once()
        assert result["text"] == "Amortization schedule"


# --- Coverage gap tests ---


class TestUnknownEventType:
    def test_unknown_event_type_returns_empty(self, mock_claude):
        """Line 64: event_type not MESSAGE/ADDED/REMOVED → empty_response."""
        payload = {
            "type": "CARD_CLICKED",
            "user": {"email": "user@example.com"},
            "space": {"type": "ROOM"},
        }
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert result == {}
        mock_claude.ask.assert_not_called()


class TestEmptyQuestion:
    def test_empty_raw_text_and_argument_text_returns_error(self, mock_claude):
        """Line 77: question is empty after fallback to raw_text → error_response."""
        payload = _dm_message_payload(text="")
        payload["message"]["argumentText"] = ""
        payload["message"]["text"] = ""
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            require_mention=False,
        )
        assert "wrong" in result["text"].lower() or "error" in result["text"].lower()
        mock_claude.ask.assert_not_called()


class TestAnalysisErrorFallback:
    @patch("src.chat.handler.read_spreadsheet")
    @patch("src.chat.handler.format_summary_for_prompt")
    @patch("src.chat.handler.analyze_spreadsheet")
    def test_analysis_error_falls_back_to_raw_preview(
        self, mock_analyze, mock_fmt_summary, mock_read,
        mock_claude, mock_downloader,
    ):
        """Lines 106-107, 114: AnalysisError → analysis_stats='', context=raw_preview."""
        from src.excel.analyzer import AnalysisError

        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.return_value = MagicMock()
        mock_fmt_summary.return_value = "| raw preview data |"
        mock_analyze.side_effect = AnalysisError("pandas failed")

        payload = _room_message_payload(
            argument_text="Summarize this",
            attachments=[_xlsx_attachment()],
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        mock_claude.ask_with_context.assert_called_once()
        context_arg = mock_claude.ask_with_context.call_args[0][1]
        assert context_arg == "| raw preview data |"


class TestExcelReadErrorOnAttachment:
    @patch("src.chat.handler.read_spreadsheet")
    def test_excel_read_error_returns_error_response(
        self, mock_read, mock_claude, mock_downloader,
    ):
        """Lines 118-120: ExcelReadError during attachment processing → error_response."""
        from src.excel.reader import ExcelReadError

        mock_downloader.download.return_value = b"xlsx-bytes"
        mock_read.side_effect = ExcelReadError("Corrupt file")

        payload = _room_message_payload(
            argument_text="Analyze this",
            attachments=[_xlsx_attachment()],
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            attachment_downloader=mock_downloader,
        )
        assert "wrong" in result["text"].lower() or "error" in result["text"].lower()
        mock_claude.ask.assert_not_called()


class TestGenerationExceptionBranches:
    @patch("src.chat.handler.build_workbook_from_spec")
    @patch("src.chat.handler.parse_claude_response")
    def test_workbook_build_error_returns_error(
        self, mock_parse, mock_build, mock_claude,
    ):
        """Lines 150-152: WorkbookBuildError in generation → error_response."""
        from src.excel.writer import WorkbookBuildError

        mock_claude.ask_for_generation.return_value = _cr("json")
        mock_parsed = MagicMock()
        mock_parsed.is_workbook = True
        mock_parsed.workbook_spec = MagicMock()
        mock_parse.return_value = mock_parsed
        mock_build.side_effect = WorkbookBuildError("Bad spec")

        storage = InMemoryStorage()
        payload = _room_message_payload(argument_text="Create a tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=storage,
        )
        assert "wrong" in result["text"].lower() or "error" in result["text"].lower()

    def test_rate_limit_in_generation_returns_rate_limit(self, mock_claude):
        """Lines 158-159: ClaudeRateLimitError in generation → rate_limit_response."""
        mock_claude.ask_for_generation.side_effect = ClaudeRateLimitError("rate limited")

        storage = InMemoryStorage()
        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=storage,
        )
        text = result["text"].lower()
        assert "again" in text or "later" in text

    def test_api_error_in_generation_returns_error(self, mock_claude):
        """Lines 160-162: ClaudeApiError in generation → error_response."""
        mock_claude.ask_for_generation.side_effect = ClaudeApiError("API broke")

        storage = InMemoryStorage()
        payload = _room_message_payload(argument_text="Generate a sales report")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=storage,
        )
        assert "wrong" in result["text"].lower() or "error" in result["text"].lower()
        assert "API broke" not in result["text"]


class TestFallbackFilename:
    def test_generation_keywords_only_produces_default_filename(self, mock_claude):
        """Line 210: question with only skip words → 'spreadsheet.xlsx'."""
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())

        storage = InMemoryStorage()
        payload = _room_message_payload(argument_text="Create a")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=storage,
        )
        assert "spreadsheet.xlsx" in result["text"]


# --- US-6.2: Usage Estimates ---


class TestUsageEstimates:
    def test_simple_ask_extracts_text_from_response(self, mock_claude):
        payload = _room_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "Here's how to use VLOOKUP..." in result["text"]

    def test_threaded_ask_extracts_text(self, mock_claude, thread_store):
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        assert "Follow-up answer" in result["text"]

    def test_complex_ask_extracts_text(self, mock_claude):
        mock_claude.ask_complex.return_value = _cr("Complex answer")
        payload = _room_message_payload(
            argument_text="Calculate NPV and IRR for this investment"
        )
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert result["text"] == "Complex answer"

    def test_generation_extracts_text(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr("I can't make that.")
        payload = _room_message_payload(argument_text="Create something weird")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert "can't make" in result["text"]

    def test_response_includes_usage_footer_in_thread(self, mock_claude, thread_store):
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        assert "---" in result["text"]
        assert "questions remaining" in result["text"]

    def test_response_footer_not_present_without_thread(self, mock_claude):
        payload = _room_message_payload()
        result = handle_chat_event(payload, allowlist=[], claude_client=mock_claude)
        assert "---" not in result["text"]
        assert "questions remaining" not in result["text"]

    def test_usage_tokens_recorded_in_thread_store(self, mock_claude, thread_store):
        mock_claude.ask_with_history.return_value = _cr(
            "answer", input_tokens=500, output_tokens=200
        )
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        ctx = thread_store.get("spaces/AAA/threads/T1")
        assert ctx.total_input_tokens == 500
        assert ctx.total_output_tokens == 200

    def test_turn_stores_token_usage(self, mock_claude, thread_store):
        mock_claude.ask_with_history.return_value = _cr(
            "answer", input_tokens=300, output_tokens=100
        )
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        turns = thread_store.get_history("spaces/AAA/threads/T1")
        assert turns[0].input_tokens == 300
        assert turns[0].output_tokens == 100

    def test_rate_limit_tracker_receives_request(self, mock_claude, thread_store):
        rate_tracker = RateLimitTracker()
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
            rate_limit_tracker=rate_tracker,
        )
        assert rate_tracker.current_rpm == 1

    def test_rate_limit_warning_appears_in_footer(self, mock_claude, thread_store):
        rate_tracker = RateLimitTracker(rpm_limit=10, warning_threshold=0.50)
        # Record many requests to trigger warning
        for _ in range(5):
            rate_tracker.record_request(input_tokens=10)

        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
            rate_limit_tracker=rate_tracker,
        )
        assert "requests" in result["text"].lower()

    def test_no_rate_tracker_no_crash(self, mock_claude, thread_store):
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
            rate_limit_tracker=None,
        )
        assert "Follow-up answer" in result["text"]

    def test_no_thread_store_no_usage_footer(self, mock_claude):
        payload = _room_message_payload()
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=None,
        )
        assert "questions remaining" not in result["text"]

    def test_warning_escalation_near_context_limit(self, mock_claude, thread_store):
        # Use large token counts to push near context limit
        mock_claude.ask_with_history.return_value = _cr(
            "answer", input_tokens=90_000, output_tokens=90_000
        )
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store,
        )
        # 180K/200K = 90% used → 10% remaining → warning level
        assert "Heads up" in result["text"] or "new thread" in result["text"]

    def test_generation_response_no_usage_footer(self, mock_claude, mock_file_storage):
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())
        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage,
        )
        assert "questions remaining" not in result["text"]


# --- R-01: Cost Tracking ---


class TestCostTracking:
    def test_cost_tracker_receives_usage_on_simple_ask(self, mock_claude):
        ct = CostTracker()
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload()
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        assert ct.daily_cost_usd > 0

    def test_cost_tracker_receives_usage_on_threaded_ask(self, mock_claude, thread_store):
        ct = CostTracker()
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store, cost_tracker=ct,
        )
        assert ct.daily_cost_usd > 0

    def test_cost_tracker_receives_usage_on_complex_ask(self, mock_claude):
        ct = CostTracker()
        mock_claude.model = "claude-sonnet-4-5-20250929"
        mock_claude.complex_model = "claude-opus-4-6"
        mock_claude.ask_complex.return_value = _cr("NPV answer")
        payload = _room_message_payload(
            argument_text="Calculate NPV and IRR for this investment"
        )
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        assert ct.daily_cost_usd > 0

    def test_cost_tracker_receives_usage_on_generation(self, mock_claude, mock_file_storage):
        ct = CostTracker()
        mock_claude.model = "claude-sonnet-4-5-20250929"
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())
        payload = _room_message_payload(argument_text="Create a budget tracker")
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage, cost_tracker=ct,
        )
        assert ct.daily_cost_usd > 0

    def test_cost_tracker_records_correct_model(self, mock_claude):
        ct = CostTracker()
        mock_claude.model = "claude-sonnet-4-5-20250929"
        mock_claude.complex_model = "claude-opus-4-6"
        # Simple ask → sonnet rates
        payload = _room_message_payload()
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        sonnet_cost = ct.daily_cost_usd
        # Complex ask → opus rates
        mock_claude.ask_complex.return_value = _cr(
            "answer", input_tokens=100, output_tokens=50
        )
        payload2 = _room_message_payload(
            argument_text="Calculate NPV and IRR for this investment"
        )
        handle_chat_event(
            payload2, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        # Opus costs more per token, so total should be more than 2x sonnet
        opus_incremental = ct.daily_cost_usd - sonnet_cost
        assert opus_incremental > sonnet_cost

    def test_cost_tracker_records_user_email(self, mock_claude):
        ct = CostTracker()
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload(email="shannon@gmail.com")
        handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        assert ct.get_user_cost("shannon@gmail.com") > 0

    def test_no_cost_tracker_no_crash(self, mock_claude):
        payload = _room_message_payload()
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=None,
        )
        assert "VLOOKUP" in result["text"]

    def test_cost_warning_appears_in_threaded_footer(self, mock_claude, thread_store):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.50
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store, cost_tracker=ct,
        )
        assert "$" in result["text"]
        assert "budget" in result["text"].lower()

    def test_cost_warning_appears_in_non_threaded_response(self, mock_claude):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.50
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload()
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        assert "$" in result["text"]
        assert "budget" in result["text"].lower()

    def test_cost_warning_appears_in_generation_response(self, mock_claude, mock_file_storage):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.50
        mock_claude.model = "claude-sonnet-4-5-20250929"
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())
        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage, cost_tracker=ct,
        )
        assert "$" in result["text"]
        assert "budget" in result["text"].lower()

    def test_no_cost_warning_when_under_budget(self, mock_claude):
        ct = CostTracker(daily_budget_usd=100.00)
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload()
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            cost_tracker=ct,
        )
        assert "budget" not in result["text"].lower()

    def test_cost_and_rate_warnings_both_appear(self, mock_claude, thread_store):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.50
        rate_tracker = RateLimitTracker(rpm_limit=10, warning_threshold=0.50)
        for _ in range(5):
            rate_tracker.record_request(input_tokens=10)
        mock_claude.model = "claude-sonnet-4-5-20250929"
        payload = _room_message_payload(
            argument_text="Q1", thread_name="spaces/AAA/threads/T1"
        )
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            thread_store=thread_store, rate_limit_tracker=rate_tracker,
            cost_tracker=ct,
        )
        assert "budget" in result["text"].lower()
        assert "requests" in result["text"].lower()

    def test_cost_footer_on_file_response(self, mock_claude, mock_file_storage):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.50
        mock_claude.model = "claude-sonnet-4-5-20250929"
        mock_claude.ask_for_generation.return_value = _cr(_valid_workbook_json())
        payload = _room_message_payload(argument_text="Create a budget tracker")
        result = handle_chat_event(
            payload, allowlist=[], claude_client=mock_claude,
            file_storage=mock_file_storage, cost_tracker=ct,
        )
        assert "Download" in result["text"]
        assert "$" in result["text"]
