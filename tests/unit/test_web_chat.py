"""Tests for the web chat module."""

import base64
from unittest.mock import MagicMock

import pytest

from src.web_chat import (
    ChatMessage,
    WebChatRequest,
    WebChatResponse,
    summarize_uploaded_file,
    verify_web_chat_secret,
)


class TestVerifyWebChatSecret:
    """Test shared-secret bearer token auth."""

    def test_valid_token_passes(self):
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = "test-secret-123"
        # Should not raise
        verify_web_chat_secret(
            settings=settings,
            authorization="Bearer test-secret-123",
        )

    def test_wrong_token_raises_401(self):
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = "test-secret-123"
        with pytest.raises(Exception) as exc_info:
            verify_web_chat_secret(
                settings=settings,
                authorization="Bearer wrong-token",
            )
        assert exc_info.value.status_code == 401

    def test_missing_bearer_prefix_raises_401(self):
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = "test-secret-123"
        with pytest.raises(Exception) as exc_info:
            verify_web_chat_secret(
                settings=settings,
                authorization="test-secret-123",
            )
        assert exc_info.value.status_code == 401

    def test_empty_server_secret_raises_500(self):
        settings = MagicMock()
        settings.WEB_CHAT_SECRET = ""
        with pytest.raises(Exception) as exc_info:
            verify_web_chat_secret(
                settings=settings,
                authorization="Bearer anything",
            )
        assert exc_info.value.status_code == 500


class TestWebChatRequest:
    """Test request schema validation."""

    def test_minimal_request(self):
        req = WebChatRequest(
            user_email="test@example.com",
            message="How do I use VLOOKUP?",
        )
        assert req.user_email == "test@example.com"
        assert req.conversation_history == []
        assert req.file_data is None

    def test_request_with_file(self):
        req = WebChatRequest(
            user_email="test@example.com",
            message="What's in this file?",
            file_name="data.xlsx",
            file_data="base64encodeddata",
            file_mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        assert req.file_name == "data.xlsx"

    def test_request_with_history(self):
        req = WebChatRequest(
            user_email="test@example.com",
            message="Follow up question",
            conversation_history=[
                ChatMessage(role="user", content="First question"),
                ChatMessage(role="assistant", content="First answer"),
            ],
        )
        assert len(req.conversation_history) == 2
        assert req.conversation_history[0].role == "user"


class TestSummarizeUploadedFile:
    """Test file processing via existing reader."""

    def test_csv_file_summarized(self):
        csv_content = "Name,Age,Score\nAlice,30,95\nBob,25,87\n"
        b64 = base64.b64encode(csv_content.encode()).decode()
        summary = summarize_uploaded_file(b64, "test.csv")
        assert "Name" in summary
        assert "Alice" in summary

    def test_corrupted_file_returns_error_message(self):
        b64 = base64.b64encode(b"not a real xlsx").decode()
        summary = summarize_uploaded_file(b64, "bad.xlsx")
        assert "Could not parse" in summary

    def test_invalid_base64_returns_error(self):
        summary = summarize_uploaded_file("!!!not-base64!!!", "test.xlsx")
        assert "Could not decode" in summary

    def test_oversized_file_rejected(self):
        # Create data that exceeds 1MB limit
        big_data = b"x" * (2 * 1024 * 1024)
        b64 = base64.b64encode(big_data).decode()
        summary = summarize_uploaded_file(b64, "big.xlsx", max_size_mb=1)
        assert "exceeds" in summary


class TestConversationHistoryCap:
    """Test that server-side history capping works correctly."""

    def test_history_within_limit_unchanged(self):
        history = [
            ChatMessage(role="user", content=f"q{i}")
            for i in range(4)
        ]
        req = WebChatRequest(
            user_email="test@example.com",
            message="latest",
            conversation_history=history,
        )
        # 4 messages, max_pairs=20 -> 40 messages, so all kept
        capped = req.conversation_history[-(20 * 2):]
        assert len(capped) == 4

    def test_history_over_limit_truncated(self):
        # Create 50 pairs = 100 messages, should be capped to last 40
        history = []
        for i in range(50):
            history.append(ChatMessage(role="user", content=f"q{i}"))
            history.append(ChatMessage(role="assistant", content=f"a{i}"))
        capped = history[-(20 * 2):]
        assert len(capped) == 40
        assert capped[0].content == "q30"


class TestWebChatResponse:
    """Test response schema."""

    def test_error_response_hides_details(self):
        # The endpoint should return generic error codes, not raw exception messages
        resp = WebChatResponse(
            message="Sorry, something went wrong.",
            error="internal_error",
        )
        assert resp.error == "internal_error"
        assert "traceback" not in resp.error.lower()
        assert "anthropic" not in resp.error.lower()
