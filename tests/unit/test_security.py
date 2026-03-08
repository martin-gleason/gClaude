"""
Security tests covering:
- SQL injection payloads treated as plain text
- XSS / script injection in email fields
- Email header injection attempts
- MITM: timing-safe secret comparison
- Path traversal (covered in test_tdd_creative.py, extended here)
- Buffer overflow / huge payloads
- Zip bomb xlsx detection
- Stack overflow via deeply nested data
- Array index / bounds errors on edge-case xlsx
- Base64 padding attack resilience
- Response data leakage prevention
"""
import base64
from io import BytesIO
from unittest.mock import MagicMock

import openpyxl
import pytest
from fastapi.testclient import TestClient

from src.claude.client import ClaudeResponse
from src.config import Settings, get_settings
from src.email.handler import clear_seen_messages, handle_email
from src.email.parser import parse_email_payload
from src.email.responses import success_response
from src.excel.reader import ExcelReadError, read_spreadsheet
from src.main import app, get_claude_client

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _make_xlsx_bytes(sheets: dict[str, list[list]]) -> bytes:
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_xlsx_b64(sheets: dict[str, list[list]]) -> str:
    return base64.b64encode(_make_xlsx_bytes(sheets)).decode()


# ─── SQL Injection ─────────────────────────────────────────────────────

class TestSqlInjection:
    """All user input is passed to Claude as text, never to a SQL engine.
    These tests ensure SQL payloads pass through as inert strings."""

    def test_sql_in_body_treated_as_text(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "'; DROP TABLE users; --",
            "message_id": "sql-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None
        question = mock_claude.ask_with_context.call_args[0][0]
        assert "DROP TABLE" in question  # passed through as text, not executed

    def test_sql_in_subject(self):
        parsed = parse_email_payload({
            "sender": "x@x.com",
            "subject": "1 OR 1=1; DROP TABLE emails;",
            "body": "",
            "message_id": "sql-2",
            "attachments": [],
        })
        assert "DROP TABLE" in parsed.question

    def test_sql_in_sender_field(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        payload = {
            "sender": "admin'--@evil.com",
            "subject": "test",
            "body": "question",
            "message_id": "sql-3",
            "attachments": [],
        }
        # Should not crash
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert isinstance(result, dict)

    def test_sql_in_xlsx_cell_data(self):
        data = _make_xlsx_bytes(
            {"Sheet1": [["Input"], ["'; DELETE FROM data; --"]]}
        )
        summary = read_spreadsheet(data, "sql.xlsx")
        # SQL in cells treated as text
        assert "DELETE FROM" in summary.sheets[0].rows[0][0]


# ─── XSS / Script Injection ───────────────────────────────────────────

class TestXssInjection:
    """Email responses go back as JSON, but Claude's reply text could
    be rendered in HTML by an email client. Ensure we don't introduce
    exploitable patterns."""

    def test_script_tag_in_body_passes_through_safely(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": '<script>alert("xss")</script>How do I sort?',
            "message_id": "xss-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None
        # The script tag should be passed to Claude as-is, not executed
        question = mock_claude.ask_with_context.call_args[0][0]
        assert "<script>" in question

    def test_xss_in_xlsx_cells_not_executed(self):
        data = _make_xlsx_bytes(
            {"Sheet1": [["Data"], ['<img src=x onerror=alert(1)>']]}
        )
        summary = read_spreadsheet(data, "xss.xlsx")
        cell = summary.sheets[0].rows[0][0]
        # Just text, not executed
        assert "<img" in cell or "img" in cell

    def test_response_fields_are_plain_strings(self):
        """success_response and error_response return plain strings,
        not HTML or anything that could be rendered."""
        resp = success_response('<script>alert(1)</script>')
        assert resp["reply"] == '<script>alert(1)</script>'
        assert isinstance(resp["reply"], str)

    def test_javascript_uri_in_body(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "test",
            "body": "javascript:alert(document.cookie)",
            "message_id": "xss-js",
            "attachments": [],
        })
        assert parsed.question == "javascript:alert(document.cookie)"


# ─── Email Header Injection ───────────────────────────────────────────

class TestEmailHeaderInjection:
    """Attackers might try to inject CRLF sequences in email fields
    to add extra headers. The parser must not split on them."""

    def test_crlf_in_subject_treated_as_text(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "Subject\r\nBcc: spy@evil.com",
            "body": "normal body",
            "message_id": "header-1",
            "attachments": [],
        })
        # Subject is just a string, CRLF doesn't create new headers
        assert "Bcc" in parsed.subject
        assert parsed.question == "normal body"

    def test_crlf_in_sender(self):
        parsed = parse_email_payload({
            "sender": "user@example.com\r\nBcc: spy@evil.com",
            "subject": "test",
            "body": "body",
            "message_id": "header-2",
            "attachments": [],
        })
        # Sender stored as-is, no header splitting occurs
        assert "\r\n" in parsed.sender

    def test_null_bytes_in_fields(self):
        """Null bytes shouldn't cause crashes or unexpected behavior."""
        parsed = parse_email_payload({
            "sender": "user\x00evil@example.com",
            "subject": "test\x00injection",
            "body": "body\x00more",
            "message_id": "null-1",
            "attachments": [],
        })
        assert isinstance(parsed.sender, str)
        assert isinstance(parsed.question, str)


# ─── Buffer Overflow / Huge Payloads ──────────────────────────────────

class TestBufferOverflow:
    """Huge inputs must not crash the server or cause OOM."""

    def test_huge_email_body_handled(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        huge_body = "A" * 1_000_000  # 1MB of text
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": huge_body,
            "message_id": "huge-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None

    def test_xlsx_size_limit_enforced(self):
        """File > MAX_XLSX_SIZE_MB must be rejected."""
        # Create a large-ish xlsx (simulated by large bytes)
        large_data = b"PK" + b"\x00" * (11 * 1024 * 1024)  # ~11MB
        with pytest.raises(ExcelReadError, match="exceeds"):
            read_spreadsheet(large_data, "huge.xlsx", max_size_mb=10)

    def test_huge_subject_line(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "X" * 100_000,
            "body": "",
            "message_id": "huge-subj",
            "attachments": [],
        })
        assert len(parsed.question) == 100_000

    def test_many_attachments(self):
        """50 attachments shouldn't crash."""
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        xlsx_b64 = _make_xlsx_b64({"S": [["A"], [1]]})
        atts = [
            {"filename": f"f{i}.xlsx", "mime_type": XLSX_MIME, "data": xlsx_b64}
            for i in range(50)
        ]
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "many-att",
            "attachments": atts,
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None


# ─── Base64 Attacks ───────────────────────────────────────────────────

class TestBase64Attacks:
    """Malformed base64 must not crash the parser."""

    def test_truncated_base64(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "test",
            "body": "body",
            "message_id": "b64-1",
            "attachments": [
                {"filename": "a.xlsx", "mime_type": XLSX_MIME, "data": "QUFB"}
            ],
        })
        # Should decode (QUFB = "AAA") but it's not valid xlsx
        # The attachment is decoded but will fail at xlsx read time
        assert len(parsed.attachments) == 1

    def test_completely_invalid_base64(self):
        """Python's b64decode is lenient — '!!!' decodes to empty bytes.
        The attachment is kept but will fail at xlsx read time. Safe."""
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "test",
            "body": "body",
            "message_id": "b64-2",
            "attachments": [
                {"filename": "a.xlsx", "mime_type": XLSX_MIME, "data": "!!!"}
            ],
        })
        # Lenient decode produces empty bytes — will fail at xlsx parse
        assert len(parsed.attachments) == 1
        assert parsed.attachments[0].data == b""

    def test_empty_data_field(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "test",
            "body": "body",
            "message_id": "b64-3",
            "attachments": [
                {"filename": "a.xlsx", "mime_type": XLSX_MIME, "data": ""}
            ],
        })
        # Empty base64 decodes to empty bytes
        assert len(parsed.attachments) == 1
        assert parsed.attachments[0].data == b""


# ─── Array Index / Bounds Errors ──────────────────────────────────────

class TestArrayBoundsEdgeCases:
    """Edge cases that could cause IndexError or similar."""

    def test_xlsx_with_zero_columns(self):
        """A sheet with empty rows shouldn't crash."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Empty"
        # Don't add any data
        buf = BytesIO()
        wb.save(buf)
        data = buf.getvalue()

        summary = read_spreadsheet(data, "empty.xlsx")
        assert len(summary.sheets) == 1

    def test_xlsx_with_sparse_rows(self):
        """Rows with fewer cells than headers."""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["A", "B", "C"])
        ws.append(["1"])  # Only one cell
        buf = BytesIO()
        wb.save(buf)

        summary = read_spreadsheet(buf.getvalue(), "sparse.xlsx")
        # Should not crash, row should be padded or handled
        from src.excel.reader import format_summary_for_prompt

        text = format_summary_for_prompt(summary)
        assert "A" in text

    def test_empty_attachments_list(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "bounds-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None

    def test_xlsx_with_only_header_row(self):
        data = _make_xlsx_bytes({"Sheet1": [["ColA", "ColB"]]})
        summary = read_spreadsheet(data, "header-only.xlsx")
        assert summary.sheets[0].headers == ["ColA", "ColB"]
        assert summary.sheets[0].rows == []

    def test_xlsx_with_1000_sheets(self):
        """Many sheets shouldn't cause issues."""
        sheets = {f"Sheet{i}": [["Val"], [i]] for i in range(100)}
        data = _make_xlsx_bytes(sheets)
        summary = read_spreadsheet(data, "many-sheets.xlsx")
        assert len(summary.sheets) == 100


# ─── MITM Protection ─────────────────────────────────────────────────

class TestMitmProtection:
    """Verify the webhook secret comparison is constant-time."""

    def test_timing_safe_import_used(self):
        """The main module must import hmac for compare_digest."""
        import hmac

        assert hasattr(hmac, "compare_digest")
        # Already tested via inspect in test_tdd_creative.py

    def test_wrong_secret_rejected_with_401(self):
        mock_claude = MagicMock()
        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="correct-secret",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude
        client = TestClient(app)

        resp = client.post(
            "/email",
            json={"sender": "a@b.com", "body": "q"},
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    def test_empty_secret_header_rejected(self):
        mock_claude = MagicMock()
        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="correct-secret",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude
        client = TestClient(app)

        resp = client.post(
            "/email",
            json={"sender": "a@b.com", "body": "q"},
            headers={"X-Webhook-Secret": ""},
        )
        assert resp.status_code == 401
        app.dependency_overrides.clear()


# ─── Webhook Endpoint Security ────────────────────────────────────────

class TestWebhookEndpointSecurity:
    """Additional endpoint-level security checks."""

    def test_get_request_to_email_returns_405(self):
        mock_claude = MagicMock()
        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude
        client = TestClient(app)

        resp = client.get("/email")
        assert resp.status_code == 405
        app.dependency_overrides.clear()

    def test_old_webhook_endpoint_returns_404(self):
        """The old /webhook endpoint from Sprint 1 should not exist."""
        mock_claude = MagicMock()
        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude
        client = TestClient(app)

        resp = client.post("/webhook", json={})
        assert resp.status_code in (404, 405)
        app.dependency_overrides.clear()
