"""Integration tests for the /web-chat endpoint."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.claude.client import ClaudeApiError, ClaudeRateLimitError, ClaudeResponse
from src.config import Settings, get_settings
from src.main import app, get_claude_client


@pytest.fixture
def web_chat_settings():
    return Settings(
        ANTHROPIC_API_KEY="sk-test-key",
        AUTHORIZED_USERS="test@example.com,admin@example.com",
        WEB_CHAT_SECRET="test-web-secret",
        DAILY_BUDGET_USD=5.00,
        _env_file=None,
    )


@pytest.fixture
def web_chat_claude():
    client = MagicMock()
    client.model = "claude-sonnet-4-5-20250929"
    client._call_api.return_value = ClaudeResponse(
        text="Here's how to use VLOOKUP...",
        input_tokens=100,
        output_tokens=50,
    )
    return client


@pytest.fixture
def web_client(web_chat_settings, web_chat_claude):
    app.dependency_overrides[get_settings] = lambda: web_chat_settings
    app.dependency_overrides[get_claude_client] = lambda: web_chat_claude
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class TestWebChatEndpoint:
    """Integration tests for /web-chat."""

    def test_web_chat_returns_200(self, web_client):
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "What does =SUM(A1:A10) do?",
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "VLOOKUP" in data["message"]
        assert data["error"] is None

    def test_web_chat_unauthorized_user(self, web_client):
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "stranger@example.com",
                "message": "Hello",
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "unauthorized"

    def test_web_chat_no_token_returns_401(self, web_client):
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "Hello",
            },
        )
        assert resp.status_code == 401

    def test_web_chat_wrong_token_returns_401(self, web_client):
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "Hello",
            },
            headers={"Authorization": "Bearer wrong-secret"},
        )
        assert resp.status_code == 401

    def test_web_chat_budget_exceeded(self, web_client):
        """When daily budget is exceeded, return friendly rejection."""
        import src.main as main_mod

        # Force cost tracker to be over budget
        tracker = main_mod.get_cost_tracker()
        tracker._daily_cost = 999.99
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "Hello",
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "budget_exceeded"
        assert "daily usage limit" in data["message"]

    def test_web_chat_records_cost(self, web_client, web_chat_claude):
        """Successful request should update cost tracker."""
        import src.main as main_mod

        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "What is a pivot table?",
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        tracker = main_mod.get_cost_tracker()
        assert tracker.daily_cost_usd > 0

    def test_web_chat_rate_limit_error(self, web_client, web_chat_claude):
        """ClaudeRateLimitError should return friendly message."""
        web_chat_claude._call_api.side_effect = ClaudeRateLimitError("rate limited")
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "Hello",
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "rate_limited"

    def test_web_chat_api_error_hides_details(self, web_client, web_chat_claude):
        """ClaudeApiError should not leak error details to client."""
        web_chat_claude._call_api.side_effect = ClaudeApiError(
            "Internal server error: model overloaded, key=sk-ant-xxx"
        )
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "Hello",
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] == "internal_error"
        assert "sk-ant" not in data["message"]
        assert "overloaded" not in data["message"]

    def test_web_chat_with_conversation_history(self, web_client):
        resp = web_client.post(
            "/web-chat",
            json={
                "user_email": "test@example.com",
                "message": "Follow up question",
                "conversation_history": [
                    {"role": "user", "content": "What is VLOOKUP?"},
                    {"role": "assistant", "content": "VLOOKUP looks up values..."},
                ],
            },
            headers={"Authorization": "Bearer test-web-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is None
