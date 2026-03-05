import base64
from io import BytesIO

import openpyxl

from src.claude.client import ClaudeApiError, ClaudeRateLimitError
from src.config import Settings, get_settings
from src.main import app, get_claude_client

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _make_xlsx_b64(data: list[list]) -> str:
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in data:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


class TestHealthCheck:
    def test_health_returns_ok(self, app_client):
        resp = app_client.get("/")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestEmailEndpoint:
    def test_simple_question(self, app_client, simple_email_payload, mock_claude_client):
        resp = app_client.post(
            "/email",
            json=simple_email_payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["reply"] == "Here's how to use VLOOKUP..."
        assert body["error"] is None

    def test_question_with_xlsx(self, app_client, mock_claude_client):
        xlsx_b64 = _make_xlsx_b64([["Name", "Age"], ["Alice", 30], ["Bob", 25]])
        payload = {
            "sender": "shannon@gmail.com",
            "subject": "Analyze data",
            "body": "Summarize this spreadsheet",
            "message_id": "msg-int-1",
            "attachments": [
                {
                    "filename": "employees.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": xlsx_b64,
                }
            ],
        }
        resp = app_client.post(
            "/email",
            json=payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] is None
        # Verify ask_with_context was called with spreadsheet context
        call_args = mock_claude_client.ask_with_context.call_args
        assert "Summarize this spreadsheet" in call_args[0][0]
        context = call_args[0][1]
        assert "Alice" in context


class TestEmailAuthorization:
    def test_unauthorized_sender(self, mock_claude_client):
        from fastapi.testclient import TestClient

        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            AUTHORIZED_USERS="shannon@gmail.com",
            GMAIL_WEBHOOK_SECRET="test-secret",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
        client = TestClient(app)

        payload = {
            "sender": "stranger@example.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-unauth",
            "attachments": [],
        }
        resp = client.post(
            "/email",
            json=payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] == "unauthorized"
        mock_claude_client.ask_with_context.assert_not_called()
        app.dependency_overrides.clear()


class TestEmailErrorHandling:
    def test_claude_api_error(self, app_client, simple_email_payload, mock_claude_client):
        mock_claude_client.ask_with_context.side_effect = ClaudeApiError("API failed")
        resp = app_client.post(
            "/email",
            json=simple_email_payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "wrong" in body["reply"].lower()
        assert body["error"] is not None

    def test_claude_rate_limit(self, app_client, simple_email_payload, mock_claude_client):
        mock_claude_client.ask_with_context.side_effect = ClaudeRateLimitError("rate limited")
        resp = app_client.post(
            "/email",
            json=simple_email_payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["error"] == "rate_limit"

    def test_corrupt_xlsx(self, app_client, mock_claude_client):
        payload = {
            "sender": "shannon@gmail.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-corrupt",
            "attachments": [
                {
                    "filename": "bad.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": base64.b64encode(b"not-xlsx").decode(),
                }
            ],
        }
        resp = app_client.post(
            "/email",
            json=payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200
        assert resp.json()["error"] is not None


class TestWebhookSecretVerification:
    def test_401_when_secret_required_and_missing(self, mock_claude_client):
        from fastapi.testclient import TestClient

        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="my-secret",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
        client = TestClient(app)

        resp = client.post("/email", json={"sender": "test@test.com", "body": "hi"})
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    def test_401_when_secret_wrong(self, mock_claude_client):
        from fastapi.testclient import TestClient

        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="my-secret",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
        client = TestClient(app)

        resp = client.post(
            "/email",
            json={"sender": "test@test.com", "body": "hi"},
            headers={"X-Webhook-Secret": "wrong-secret"},
        )
        assert resp.status_code == 401
        app.dependency_overrides.clear()

    def test_passes_with_correct_secret(self, app_client, simple_email_payload):
        resp = app_client.post(
            "/email",
            json=simple_email_payload,
            headers={"X-Webhook-Secret": "test-secret"},
        )
        assert resp.status_code == 200

    def test_passes_when_no_secret_configured(self, mock_claude_client):
        from fastapi.testclient import TestClient

        settings = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GMAIL_WEBHOOK_SECRET="",
        )
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
        client = TestClient(app)

        payload = {
            "sender": "anyone@test.com",
            "subject": "test",
            "body": "question",
            "message_id": "msg-1",
            "attachments": [],
        }
        resp = client.post("/email", json=payload)
        assert resp.status_code == 200
        app.dependency_overrides.clear()
