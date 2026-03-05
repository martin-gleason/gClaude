import base64
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.config import Settings, get_settings
from src.main import app, get_claude_client

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@pytest.fixture
def mock_settings():
    return Settings(
        ANTHROPIC_API_KEY="sk-test-key",
        AUTHORIZED_USERS="",
        GMAIL_WEBHOOK_SECRET="test-secret",
    )


@pytest.fixture
def mock_claude_client():
    client = MagicMock()
    client.ask.return_value = "Here's how to use VLOOKUP..."
    client.ask_with_context.return_value = "Here's how to use VLOOKUP..."
    return client


@pytest.fixture
def app_client(mock_settings, mock_claude_client):
    app.dependency_overrides[get_settings] = lambda: mock_settings
    app.dependency_overrides[get_claude_client] = lambda: mock_claude_client
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def simple_email_payload():
    return {
        "sender": "shannon@gmail.com",
        "subject": "How do I use VLOOKUP?",
        "body": "I need help with VLOOKUP across sheets",
        "message_id": "msg-123",
        "attachments": [],
    }


@pytest.fixture
def email_with_xlsx_payload():
    xlsx_data = base64.b64encode(b"fake-xlsx-data").decode()
    return {
        "sender": "shannon@gmail.com",
        "subject": "Help with my spreadsheet",
        "body": "Can you analyze this data?",
        "message_id": "msg-456",
        "attachments": [
            {
                "filename": "employees.xlsx",
                "mime_type": XLSX_MIME,
                "data": xlsx_data,
            }
        ],
    }
