import base64
from io import BytesIO
from unittest.mock import MagicMock

import openpyxl
import pytest

from src.claude.client import ClaudeApiError, ClaudeRateLimitError
from src.email.handler import handle_email

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _make_xlsx_bytes(data: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in data:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def mock_claude():
    client = MagicMock()
    client.ask_with_context.return_value = "Here's the answer about VLOOKUP."
    return client


class TestHandleEmailBasic:
    def test_successful_question(self, mock_claude):
        payload = {
            "sender": "shannon@gmail.com",
            "subject": "VLOOKUP help",
            "body": "How do I use VLOOKUP?",
            "message_id": "msg-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["reply"] == "Here's the answer about VLOOKUP."
        assert result["error"] is None
        mock_claude.ask_with_context.assert_called_once_with("How do I use VLOOKUP?", None)

    def test_question_from_subject_when_body_empty(self, mock_claude):
        payload = {
            "sender": "user@example.com",
            "subject": "How do I freeze panes?",
            "body": "",
            "message_id": "msg-2",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None
        mock_claude.ask_with_context.assert_called_once_with("How do I freeze panes?", None)


class TestHandleEmailAuth:
    def test_unauthorized_sender(self, mock_claude):
        payload = {
            "sender": "stranger@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-3",
            "attachments": [],
        }
        result = handle_email(
            payload, allowlist=["shannon@gmail.com"], claude_client=mock_claude
        )
        assert result["error"] == "unauthorized"
        assert "authorized" in result["reply"].lower()
        mock_claude.ask_with_context.assert_not_called()

    def test_authorized_sender(self, mock_claude):
        payload = {
            "sender": "shannon@gmail.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-4",
            "attachments": [],
        }
        result = handle_email(
            payload, allowlist=["shannon@gmail.com"], claude_client=mock_claude
        )
        assert result["error"] is None

    def test_empty_allowlist_allows_anyone(self, mock_claude):
        payload = {
            "sender": "anyone@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-5",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None


class TestHandleEmailNoQuestion:
    def test_empty_body_and_subject(self, mock_claude):
        payload = {
            "sender": "user@example.com",
            "subject": "",
            "body": "",
            "message_id": "msg-6",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is not None
        mock_claude.ask_with_context.assert_not_called()


class TestHandleEmailWithXlsx:
    def test_processes_xlsx_attachment(self, mock_claude):
        xlsx_bytes = _make_xlsx_bytes([["Name", "Age"], ["Alice", 30]])
        xlsx_b64 = base64.b64encode(xlsx_bytes).decode()
        payload = {
            "sender": "user@example.com",
            "subject": "Analyze",
            "body": "Summarize this data",
            "message_id": "msg-7",
            "attachments": [
                {
                    "filename": "data.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": xlsx_b64,
                }
            ],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None
        call_args = mock_claude.ask_with_context.call_args
        assert call_args[0][0] == "Summarize this data"
        context = call_args[0][1]
        assert "Alice" in context
        assert "Name" in context

    def test_corrupt_xlsx_returns_error(self, mock_claude):
        bad_data = base64.b64encode(b"not-valid-xlsx").decode()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-8",
            "attachments": [
                {
                    "filename": "bad.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": bad_data,
                }
            ],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is not None
        mock_claude.ask_with_context.assert_not_called()


class TestHandleEmailClaudeErrors:
    def test_api_error(self, mock_claude):
        mock_claude.ask_with_context.side_effect = ClaudeApiError("API failed")
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-9",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert "wrong" in result["reply"].lower()
        assert result["error"] is not None

    def test_rate_limit_error(self, mock_claude):
        mock_claude.ask_with_context.side_effect = ClaudeRateLimitError("rate limited")
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-10",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] == "rate_limit"
        text = result["reply"].lower()
        assert "again" in text or "later" in text
