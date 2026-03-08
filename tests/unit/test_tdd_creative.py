"""
TDD Creative Tests — written RED first, then GREEN code is added to pass them.
Each test explores a gap or edge case in the existing implementation.
"""
import base64
from io import BytesIO
from unittest.mock import MagicMock

import openpyxl

from src.claude.client import ClaudeApiError, ClaudeResponse
from src.email.handler import handle_email
from src.email.parser import parse_email_payload

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


# ─── TDD Round 1: Multi-attachment ──────────────────────────────────────

class TestMultiAttachment:
    """When an email has multiple .xlsx files, ALL should be parsed and
    their context concatenated for Claude — not just the first one."""

    def test_two_xlsx_both_appear_in_context(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="Combined analysis.", input_tokens=100, output_tokens=50,
        )

        file1_b64 = _make_xlsx_b64({"Sales": [["Month", "Rev"], ["Jan", 100]]})
        file2_b64 = _make_xlsx_b64({"Costs": [["Month", "Cost"], ["Jan", 50]]})

        payload = {
            "sender": "user@example.com",
            "subject": "Compare these",
            "body": "Compare sales vs costs",
            "message_id": "multi-1",
            "attachments": [
                {"filename": "sales.xlsx", "mime_type": XLSX_MIME, "data": file1_b64},
                {"filename": "costs.xlsx", "mime_type": XLSX_MIME, "data": file2_b64},
            ],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None

        context = mock_claude.ask_with_context.call_args[0][1]
        assert "Sales" in context, "First xlsx sheet name missing from context"
        assert "Costs" in context, "Second xlsx sheet name missing from context"
        assert "sales.xlsx" in context
        assert "costs.xlsx" in context


# ─── TDD Round 2: Unicode/emoji ────────────────────────────────────────

class TestUnicodeSupport:
    """International characters, emoji, and RTL text should survive
    the full pipeline without corruption."""

    def test_emoji_in_body_passes_through(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="Answer with emoji", input_tokens=100, output_tokens=50,
        )

        payload = {
            "sender": "user@example.com",
            "subject": "Help please",
            "body": "How do I sum column A? \U0001f4ca\U0001f4c8",
            "message_id": "unicode-1",
            "attachments": [],
        }
        handle_email(payload, allowlist=[], claude_client=mock_claude)
        question = mock_claude.ask_with_context.call_args[0][0]
        assert "\U0001f4ca" in question
        assert "\U0001f4c8" in question

    def test_japanese_in_subject_used_as_question(self):
        parsed = parse_email_payload({
            "sender": "user@example.jp",
            "subject": "\u30a8\u30af\u30bb\u30eb\u306e\u8cea\u554f",
            "body": "",
            "message_id": "jp-1",
            "attachments": [],
        })
        assert parsed.question == "\u30a8\u30af\u30bb\u30eb\u306e\u8cea\u554f"

    def test_arabic_rtl_text(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="RTL answer", input_tokens=100, output_tokens=50,
        )

        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "\u0643\u064a\u0641 \u0623\u0633\u062a\u062e\u062f\u0645 VLOOKUP\u061f",
            "message_id": "rtl-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result["error"] is None
        question = mock_claude.ask_with_context.call_args[0][0]
        assert "VLOOKUP" in question
        assert "\u0643\u064a\u0641" in question

    def test_unicode_in_xlsx_cell_data(self):
        data = _make_xlsx_bytes(
            {"\u30c7\u30fc\u30bf": [["\u540d\u524d", "\u5e74\u9f62"], ["\u592a\u90ce", 30]]}
        )
        from src.excel.reader import format_summary_for_prompt, read_spreadsheet

        summary = read_spreadsheet(data, "japanese.xlsx")
        text = format_summary_for_prompt(summary)
        assert "\u540d\u524d" in text
        assert "\u592a\u90ce" in text


# ─── TDD Round 3: Cell content truncation ──────────────────────────────

class TestCellTruncation:
    """A single cell with 100K+ characters could blow up the Claude prompt.
    The reader should truncate individual cell values to a sane maximum."""

    def test_huge_cell_gets_truncated(self):
        from src.excel.reader import read_spreadsheet

        huge_text = "A" * 100_000
        data = _make_xlsx_bytes({"Sheet1": [["Content"], [huge_text]]})

        summary = read_spreadsheet(data, "huge.xlsx")
        cell_value = summary.sheets[0].rows[0][0]

        # Cell value must be capped — 100K chars in a prompt is insane
        # Allow small overhead for truncation indicator like "..."
        assert len(cell_value) <= 1010, (
            f"Cell was {len(cell_value)} chars, expected <= 1010"
        )
        assert cell_value.endswith("..."), "Truncated cells should end with '...'"


# ─── TDD Round 4: Strip reply chains ──────────────────────────────────

class TestStripReplyChains:
    """When Shannon replies to her own thread, Gmail includes quoted text
    with '>' prefixes. The question property should strip that noise."""

    def test_strips_quoted_reply(self):
        parsed = parse_email_payload({
            "sender": "shannon@gmail.com",
            "subject": "Re: VLOOKUP help",
            "body": (
                "What about INDEX MATCH instead?\n"
                "\n"
                "On Mon, Jan 1, 2025, Shannon wrote:\n"
                "> How do I use VLOOKUP?\n"
                "> I have data in columns A and B.\n"
            ),
            "message_id": "reply-1",
            "attachments": [],
        })
        question = parsed.question
        assert "INDEX MATCH" in question
        assert "> How do I use VLOOKUP?" not in question

    def test_preserves_body_without_quotes(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "test",
            "body": "Simple question with no reply chain",
            "message_id": "no-reply",
            "attachments": [],
        })
        assert parsed.question == "Simple question with no reply chain"

    def test_strips_multiple_levels_of_quoting(self):
        parsed = parse_email_payload({
            "sender": "user@example.com",
            "subject": "Re: Re: help",
            "body": (
                "Third reply here\n"
                "\n"
                "On Tue wrote:\n"
                "> Second reply\n"
                ">\n"
                ">> First message\n"
                ">> More first message\n"
            ),
            "message_id": "deep-reply",
            "attachments": [],
        })
        question = parsed.question
        assert "Third reply here" in question
        assert ">> First message" not in question
        assert "> Second reply" not in question


# ─── TDD Round 5: Case-insensitive sender auth ────────────────────────

class TestCaseInsensitiveAuth:
    """Email addresses are case-insensitive per RFC 5321.
    Shannon@Gmail.COM must match shannon@gmail.com in the allowlist."""

    def test_mixed_case_sender_matches_lowercase_allowlist(self):
        from src.auth import is_authorized

        assert is_authorized(
            "Shannon@Gmail.COM", ["shannon@gmail.com"]
        ) is True

    def test_lowercase_sender_matches_uppercase_allowlist(self):
        from src.auth import is_authorized

        assert is_authorized(
            "shannon@gmail.com", ["SHANNON@GMAIL.COM"]
        ) is True

    def test_case_insensitive_in_handler(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        payload = {
            "sender": "Shannon@Gmail.COM",
            "subject": "test",
            "body": "question",
            "message_id": "case-1",
            "attachments": [],
        }
        result = handle_email(
            payload,
            allowlist=["shannon@gmail.com"],
            claude_client=mock_claude,
        )
        assert result["error"] is None, (
            "Case-different sender should still be authorized"
        )


# ─── TDD Round 6: Special chars in sheet names + pipe in cells ─────────

class TestSpecialCharsInSheetData:
    """Sheet names with $, (), and pipe chars in cell data should not
    break the markdown table formatting."""

    def test_pipe_char_in_cell_is_escaped(self):
        import re

        from src.excel.reader import format_summary_for_prompt, read_spreadsheet

        data = _make_xlsx_bytes(
            {"Sheet1": [["Formula", "Result"], ["=A1|B1", "yes|no"]]}
        )
        summary = read_spreadsheet(data, "pipes.xlsx")
        text = format_summary_for_prompt(summary)
        # Pipes in cells must be escaped so they don't add extra columns
        # Count only unescaped pipes (not preceded by backslash)
        data_lines = [
            line for line in text.split("\n")
            if line.startswith("|") and "---" not in line
        ]
        for line in data_lines:
            unescaped = len(re.findall(r"(?<!\\)\|", line))
            col_count = unescaped - 1
            assert col_count == 2, (
                f"Expected 2 columns but got {col_count}: {line}"
            )

    def test_special_chars_in_sheet_name(self):
        from src.excel.reader import format_summary_for_prompt, read_spreadsheet

        data = _make_xlsx_bytes(
            {"Q1 $$$ Revenue (2024)": [["Amount"], [50000]]}
        )
        summary = read_spreadsheet(data, "special.xlsx")
        text = format_summary_for_prompt(summary)
        assert "Q1 $$$ Revenue (2024)" in text
        assert "50000" in text


# ─── TDD Round 7: Duplicate message_id detection ──────────────────────

class TestDuplicateDetection:
    """Processing the same message_id twice should return an
    'already processed' response without calling Claude again."""

    def test_same_message_id_not_processed_twice(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "dupe-test-123",
            "attachments": [],
        }

        from src.email.handler import clear_seen_messages, handle_email

        clear_seen_messages()  # reset state for test isolation

        result1 = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result1["error"] is None

        result2 = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert result2["error"] == "duplicate"

        # Claude should only be called once
        assert mock_claude.ask_with_context.call_count == 1

    def test_different_message_ids_both_processed(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        from src.email.handler import clear_seen_messages, handle_email

        clear_seen_messages()

        p1 = {
            "sender": "a@b.com", "subject": "s", "body": "q1",
            "message_id": "unique-1", "attachments": [],
        }
        p2 = {
            "sender": "a@b.com", "subject": "s", "body": "q2",
            "message_id": "unique-2", "attachments": [],
        }
        handle_email(p1, allowlist=[], claude_client=mock_claude)
        handle_email(p2, allowlist=[], claude_client=mock_claude)
        assert mock_claude.ask_with_context.call_count == 2


# ─── TDD Round 8: Filename path traversal ─────────────────────────────

class TestPathTraversal:
    """Malicious filenames like '../../etc/passwd.xlsx' should be
    sanitized to just the basename, preventing directory traversal."""

    def test_dot_dot_slash_stripped(self):
        from src.email.parser import parse_email_payload

        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "path-1",
            "attachments": [
                {
                    "filename": "../../etc/passwd.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": _make_xlsx_b64({"S": [["A"], [1]]}),
                }
            ],
        }
        parsed = parse_email_payload(payload)
        # Filename must be just the basename
        assert "/" not in parsed.attachments[0].filename
        assert "\\" not in parsed.attachments[0].filename
        assert parsed.attachments[0].filename == "passwd.xlsx"

    def test_absolute_path_stripped(self):
        from src.email.parser import parse_email_payload

        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "path-2",
            "attachments": [
                {
                    "filename": "/tmp/evil/data.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": _make_xlsx_b64({"S": [["A"], [1]]}),
                }
            ],
        }
        parsed = parse_email_payload(payload)
        assert parsed.attachments[0].filename == "data.xlsx"

    def test_windows_path_stripped(self):
        from src.email.parser import parse_email_payload

        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "path-3",
            "attachments": [
                {
                    "filename": "C:\\Users\\evil\\data.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": _make_xlsx_b64({"S": [["A"], [1]]}),
                }
            ],
        }
        parsed = parse_email_payload(payload)
        assert parsed.attachments[0].filename == "data.xlsx"


# ─── TDD Round 9: No internal error leakage ───────────────────────────

class TestNoErrorLeakage:
    """The 'reply' field sent back to the user must NEVER contain
    stack traces, API keys, file paths, or internal error details."""

    def test_api_key_never_in_reply(self):
        mock_claude = MagicMock()
        api_key = "sk-ant-secret-key-12345"
        mock_claude.ask_with_context.side_effect = ClaudeApiError(
            f"Authentication failed for key {api_key}"
        )

        from src.email.handler import clear_seen_messages

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "leak-1",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert api_key not in result["reply"], (
            "API key leaked into user-facing reply!"
        )

    def test_file_paths_never_in_reply(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.side_effect = ClaudeApiError(
            "Error at /usr/local/app/src/claude/client.py:34"
        )

        from src.email.handler import clear_seen_messages

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "leak-2",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert "/usr/local" not in result["reply"]
        assert "client.py" not in result["reply"]

    def test_traceback_never_in_reply(self):
        mock_claude = MagicMock()
        mock_claude.ask_with_context.side_effect = ClaudeApiError(
            "Traceback (most recent call last):\n  File 'x.py'\nKeyError"
        )

        from src.email.handler import clear_seen_messages

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "leak-3",
            "attachments": [],
        }
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        assert "Traceback" not in result["reply"]
        assert "KeyError" not in result["reply"]


# ─── TDD Round 10: Timing-safe secret comparison ──────────────────────

class TestTimingSafeComparison:
    """Webhook secret comparison must use hmac.compare_digest to prevent
    timing attacks. A simple '==' leaks info about the secret length."""

    def test_verify_webhook_secret_uses_compare_digest(self):
        """Inspect the source code of verify_webhook_secret to confirm
        it uses hmac.compare_digest, not bare == comparison."""
        import inspect

        from src.main import verify_webhook_secret

        source = inspect.getsource(verify_webhook_secret)
        assert "compare_digest" in source, (
            "verify_webhook_secret must use hmac.compare_digest, "
            "not == for constant-time comparison"
        )
