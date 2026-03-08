from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app, get_claude_client
from src.storage.interface import StorageError
from src.storage.memory import InMemoryStorage


class TestChatEndpoint:
    def test_message_returns_answer(
        self, app_client, chat_message_payload, mock_claude_client
    ):
        resp = app_client.post("/chat", json=chat_message_payload)
        assert resp.status_code == 200
        body = resp.json()
        # Payload has a thread, so ask_with_history is used (returns "Follow-up answer")
        # Response now includes a usage footer for threaded messages
        assert "Follow-up answer" in body["text"] or "Here's how to use VLOOKUP..." in body["text"]

    def test_added_to_space_returns_welcome(self, app_client, chat_added_payload):
        resp = app_client.post("/chat", json=chat_added_payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "ExcelBot" in body["text"]

    def test_unauthorized_user_rejected(self, mock_claude_client):
        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            AUTHORIZED_USERS="shannon@gmail.com",
            GMAIL_WEBHOOK_SECRET="",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
        client = TestClient(app)

        payload = {
            "type": "MESSAGE",
            "user": {"email": "stranger@example.com"},
            "message": {
                "text": "@ExcelBot help",
                "argumentText": "help",
            },
            "space": {"type": "ROOM"},
        }
        resp = client.post("/chat", json=payload)
        assert resp.status_code == 200
        assert "authorized" in resp.json()["text"].lower()
        mock_claude_client.ask.assert_not_called()
        app.dependency_overrides.clear()

    def test_401_when_token_required_but_missing(self, mock_claude_client):
        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GOOGLE_CHAT_PROJECT_NUMBER="123456",
            GMAIL_WEBHOOK_SECRET="",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
        client = TestClient(app)

        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com"},
            "message": {"text": "hello", "argumentText": "hello"},
            "space": {"type": "ROOM"},
        }
        resp = client.post("/chat", json=payload)
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    def test_passes_when_no_project_number_configured(
        self, app_client, chat_message_payload
    ):
        resp = app_client.post("/chat", json=chat_message_payload)
        assert resp.status_code == 200


class TestChatWithThreadContext:
    def test_thread_context_across_requests(
        self, app_client, mock_claude_client
    ):
        """Two sequential POSTs to same thread; second should get history."""
        payload1 = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "@ExcelBot What is VLOOKUP?",
                "argumentText": "What is VLOOKUP?",
                "thread": {"name": "spaces/AAA/threads/INTEG1"},
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        resp1 = app_client.post("/chat", json=payload1)
        assert resp1.status_code == 200

        payload2 = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "@ExcelBot Give me an example",
                "argumentText": "Give me an example",
                "thread": {"name": "spaces/AAA/threads/INTEG1"},
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        resp2 = app_client.post("/chat", json=payload2)
        assert resp2.status_code == 200
        # Both calls use ask_with_history; second call should have 1 prior turn in history
        assert mock_claude_client.ask_with_history.call_count == 2
        # First call: no prior history
        first_call_kwargs = mock_claude_client.ask_with_history.call_args_list[0].kwargs
        assert len(first_call_kwargs["history"]) == 0
        # Second call: 1 turn of history from the first exchange
        second_call_kwargs = mock_claude_client.ask_with_history.call_args_list[1].kwargs
        assert len(second_call_kwargs["history"]) == 1


class TestChatWithAttachment:
    def test_attachment_payload_accepted(
        self, app_client, chat_message_with_attachment_payload
    ):
        """POST with attachment payload returns 200 (no downloader configured)."""
        resp = app_client.post("/chat", json=chat_message_with_attachment_payload)
        assert resp.status_code == 200


class TestFileGeneration:
    @patch("src.main.get_file_storage")
    def test_generate_request_returns_200(
        self, mock_get_storage, app_client, mock_claude_client
    ):
        mock_get_storage.return_value = InMemoryStorage()
        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "@ExcelBot Make me a budget tracker",
                "argumentText": "Make me a budget tracker",
                "thread": {"name": "spaces/AAA/threads/GEN1"},
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        resp = app_client.post("/chat", json=payload)
        assert resp.status_code == 200

    @patch("src.main.get_file_storage")
    def test_generate_response_contains_url(
        self, mock_get_storage, app_client, mock_claude_client
    ):
        mock_get_storage.return_value = InMemoryStorage()
        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "@ExcelBot Create a sales report",
                "argumentText": "Create a sales report",
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        resp = app_client.post("/chat", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "Download" in body["text"]
        assert "memory://" in body["text"]


class TestFileModificationIntegration:
    def test_modify_with_attachment_returns_200(
        self, app_client, chat_message_with_attachment_payload
    ):
        """POST with attachment + non-generation text returns 200 even without storage."""
        resp = app_client.post("/chat", json=chat_message_with_attachment_payload)
        assert resp.status_code == 200


class TestErrorHandlingIntegration:
    @patch("src.main.get_file_storage")
    def test_storage_failure_returns_friendly_message(
        self, mock_get_storage, app_client, mock_claude_client
    ):
        failing_storage = MagicMock()
        failing_storage.upload.side_effect = StorageError("GCS down")
        mock_get_storage.return_value = failing_storage

        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "@ExcelBot Generate a report",
                "argumentText": "Generate a report",
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        resp = app_client.post("/chat", json=payload)
        assert resp.status_code == 200
        text = resp.json()["text"].lower()
        assert "unable" in text or "save" in text


class TestUsageEstimatesIntegration:
    def test_thread_response_contains_usage_info(
        self, app_client, mock_claude_client
    ):
        """Threaded responses should include a usage footer."""
        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "@ExcelBot What is VLOOKUP?",
                "argumentText": "What is VLOOKUP?",
                "thread": {"name": "spaces/AAA/threads/USAGE1"},
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        resp = app_client.post("/chat", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "---" in body["text"]
        assert "questions remaining" in body["text"]

    def test_simple_response_still_works(
        self, app_client, mock_claude_client
    ):
        """Non-threaded DM responses should not have usage footer."""
        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "How do I freeze panes?",
                "argumentText": "",
            },
            "space": {"name": "spaces/DM1", "type": "DM"},
        }
        resp = app_client.post("/chat", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "questions remaining" not in body["text"]


class TestCostTrackerIntegration:
    def test_chat_response_no_cost_warning_under_budget(
        self, app_client, mock_claude_client
    ):
        """Under-budget responses should not show cost warning."""
        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "How do I freeze panes?",
                "argumentText": "",
            },
            "space": {"name": "spaces/DM1", "type": "DM"},
        }
        resp = app_client.post("/chat", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert "budget" not in body["text"].lower()

    def test_cost_tracker_wired_in_webhook(self, app_client, mock_claude_client):
        """Cost tracker should be wired and accumulate cost across requests."""
        import src.main as main_mod

        payload = {
            "type": "MESSAGE",
            "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "message": {
                "text": "How do I freeze panes?",
                "argumentText": "",
            },
            "space": {"name": "spaces/DM1", "type": "DM"},
        }
        app_client.post("/chat", json=payload)
        # After a request, the cost tracker should have been initialized and recorded usage
        ct = main_mod._cost_tracker
        assert ct is not None
        assert ct.daily_cost_usd > 0
