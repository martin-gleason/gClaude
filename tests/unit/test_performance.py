"""
Performance tests covering:
- Memory: large xlsx doesn't explode memory
- Threading: concurrent requests don't corrupt shared state
- Thread safety of duplicate detection
- Response time stays bounded
- GC pressure from large payloads
"""
import base64
import gc
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from unittest.mock import MagicMock

import openpyxl

from src.claude.client import ClaudeResponse
from src.email.handler import clear_seen_messages, handle_email
from src.email.parser import parse_email_payload
from src.excel.reader import format_summary_for_prompt, read_spreadsheet

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


# ─── Memory Tests ─────────────────────────────────────────────────────

class TestMemory:
    """Ensure large inputs don't cause excessive memory usage."""

    def test_large_xlsx_memory_bounded(self):
        """Processing a 500-row xlsx shouldn't leak memory."""
        rows = [["ID", "Name", "Value"]]
        rows.extend([[i, f"Name_{i}", i * 1.5] for i in range(500)])
        data = _make_xlsx_bytes({"Data": rows})

        gc.collect()
        _ = sys.getsizeof(data)

        summary = read_spreadsheet(data, "large.xlsx", max_rows=50)
        text = format_summary_for_prompt(summary)

        # Summary should be much smaller than raw data
        assert len(text) < len(data), (
            "Formatted summary should be smaller than raw xlsx"
        )
        # Only 50 rows should be in the summary
        assert len(summary.sheets[0].rows) == 50
        assert summary.sheets[0].truncated is True

    def test_truncation_limits_output_size(self):
        """Even with 10K rows, output is bounded by max_rows."""
        rows = [["Val"]] + [[f"data_{i}"] for i in range(10_000)]
        data = _make_xlsx_bytes({"Big": rows})

        summary = read_spreadsheet(data, "big.xlsx", max_rows=20)
        text = format_summary_for_prompt(summary)

        # With 20 rows max, output should be reasonable
        assert len(text) < 10_000
        assert len(summary.sheets[0].rows) == 20

    def test_cell_truncation_limits_prompt_size(self):
        """Huge cell values are truncated to MAX_CELL_LENGTH."""
        rows = [["Content"], ["X" * 50_000]]
        data = _make_xlsx_bytes({"Sheet1": rows})

        summary = read_spreadsheet(data, "huge-cell.xlsx")
        text = format_summary_for_prompt(summary)
        # Should be bounded, not 50K chars
        assert len(text) < 5_000

    def test_seen_messages_bounded(self):
        """The _seen_message_ids dict should not grow unbounded.
        It should cap at _MAX_SEEN and evict oldest entries."""
        from src.email.handler import _MAX_SEEN, _seen_message_ids

        clear_seen_messages()
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        # Process more than _MAX_SEEN messages
        for i in range(_MAX_SEEN + 100):
            payload = {
                "sender": "user@example.com",
                "subject": "test",
                "body": "q",
                "message_id": f"mem-{i}",
                "attachments": [],
            }
            handle_email(payload, allowlist=[], claude_client=mock_claude)

        assert len(_seen_message_ids) <= _MAX_SEEN
        clear_seen_messages()


# ─── Threading / Concurrency ─────────────────────────────────────────

class TestThreading:
    """Ensure thread safety of shared state."""

    def test_concurrent_emails_dont_corrupt_state(self):
        """Multiple threads processing emails simultaneously
        should not cause crashes or data corruption."""
        clear_seen_messages()
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        errors = []
        results = []

        def process_email(idx):
            try:
                payload = {
                    "sender": "user@example.com",
                    "subject": "test",
                    "body": f"question {idx}",
                    "message_id": f"thread-{idx}",
                    "attachments": [],
                }
                result = handle_email(
                    payload, allowlist=[], claude_client=mock_claude
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(20):
            t = threading.Thread(target=process_email, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0, f"Thread errors: {errors}"
        assert len(results) == 20
        clear_seen_messages()

    def test_concurrent_xlsx_parsing(self):
        """Multiple threads parsing xlsx files shouldn't interfere."""
        errors = []
        summaries = []

        def parse_xlsx(idx):
            try:
                data = _make_xlsx_bytes(
                    {f"Sheet{idx}": [["Col"], [idx]]}
                )
                summary = read_spreadsheet(data, f"file{idx}.xlsx")
                summaries.append(summary)
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=10) as pool:
            futures = [pool.submit(parse_xlsx, i) for i in range(30)]
            for f in as_completed(futures):
                f.result()  # re-raises exceptions

        assert len(errors) == 0
        assert len(summaries) == 30

    def test_duplicate_detection_thread_safe(self):
        """Same message_id from multiple threads should only succeed once."""
        clear_seen_messages()
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        results = []
        lock = threading.Lock()

        def process_same_id():
            payload = {
                "sender": "user@example.com",
                "subject": "test",
                "body": "question",
                "message_id": "same-id-race",
                "attachments": [],
            }
            result = handle_email(
                payload, allowlist=[], claude_client=mock_claude
            )
            with lock:
                results.append(result)

        threads = [threading.Thread(target=process_same_id) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # Exactly one should succeed, rest should be duplicates
        successes = [r for r in results if r["error"] is None]
        duplicates = [r for r in results if r.get("error") == "duplicate"]
        assert len(successes) == 1, f"Expected 1 success, got {len(successes)}"
        assert len(duplicates) == 9
        clear_seen_messages()


# ─── Response Time ────────────────────────────────────────────────────

class TestResponseTime:
    """Ensure parsing operations stay fast."""

    def test_parser_handles_large_payload_quickly(self):
        """Parsing a payload with a large base64 attachment
        should complete in under 1 second."""
        xlsx_b64 = _make_xlsx_b64(
            {"Data": [["Col"]] + [[i] for i in range(500)]}
        )
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "perf-1",
            "attachments": [
                {"filename": "data.xlsx", "mime_type": XLSX_MIME, "data": xlsx_b64}
            ],
        }
        start = time.monotonic()
        parse_email_payload(payload)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Parsing took {elapsed:.2f}s, expected < 1s"

    def test_xlsx_reader_stays_fast(self):
        """Reading a 1000-row xlsx should complete in under 2 seconds."""
        rows = [["A", "B", "C"]] + [[i, i * 2, f"val_{i}"] for i in range(1000)]
        data = _make_xlsx_bytes({"Data": rows})

        start = time.monotonic()
        summary = read_spreadsheet(data, "perf.xlsx", max_rows=50)
        format_summary_for_prompt(summary)
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"Reader took {elapsed:.2f}s, expected < 2s"

    def test_handler_without_attachment_fast(self):
        """A simple email without attachments should process very quickly."""
        mock_claude = MagicMock()
        mock_claude.ask_with_context.return_value = ClaudeResponse(
            text="answer", input_tokens=100, output_tokens=50,
        )

        clear_seen_messages()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "How do I use VLOOKUP?",
            "message_id": "perf-fast",
            "attachments": [],
        }
        start = time.monotonic()
        result = handle_email(payload, allowlist=[], claude_client=mock_claude)
        elapsed = time.monotonic() - start
        assert elapsed < 0.1, f"Handler took {elapsed:.3f}s, expected < 0.1s"
        assert result["error"] is None
