import base64
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.claude.client import ClaudeResponse
from src.config import Settings, get_settings
from src.main import app, get_claude_client
from src.storage.memory import InMemoryStorage


def make_claude_response(
    text: str, input_tokens: int = 100, output_tokens: int = 50,
) -> ClaudeResponse:
    """Helper to create ClaudeResponse objects for tests."""
    return ClaudeResponse(
        text=text, input_tokens=input_tokens, output_tokens=output_tokens,
    )

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


@pytest.fixture(autouse=True)
def _clear_seen_messages():
    """Reset duplicate detection state between tests."""
    from src.email.handler import clear_seen_messages

    clear_seen_messages()
    yield
    clear_seen_messages()


@pytest.fixture(autouse=True)
def _clear_thread_store():
    """Reset thread context store, rate limit tracker, and cost tracker between tests."""
    import src.main as main_mod

    old_store = main_mod._thread_store
    old_rate_tracker = main_mod._rate_limit_tracker
    old_cost_tracker = main_mod._cost_tracker
    main_mod._thread_store = None
    main_mod._rate_limit_tracker = None
    main_mod._cost_tracker = None
    yield
    main_mod._thread_store = old_store
    main_mod._rate_limit_tracker = old_rate_tracker
    main_mod._cost_tracker = old_cost_tracker


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
    client.ask.return_value = make_claude_response("Here's how to use VLOOKUP...")
    client.ask_with_context.return_value = make_claude_response("Here's how to use VLOOKUP...")
    client.ask_with_history.return_value = make_claude_response("Follow-up answer")
    client.ask_for_generation.return_value = make_claude_response(json.dumps({
        "sheets": [{
            "name": "Budget",
            "columns": ["Category", "Amount"],
            "rows": [["Rent", 1500], ["Food", 500]],
        }]
    }))
    return client


@pytest.fixture
def mock_file_storage():
    return InMemoryStorage()


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
def chat_message_payload():
    return {
        "type": "MESSAGE",
        "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
        "message": {
            "name": "spaces/AAA/messages/BBB",
            "text": "@ExcelBot How do I use VLOOKUP?",
            "argumentText": "How do I use VLOOKUP?",
            "sender": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "thread": {"name": "spaces/AAA/threads/CCC"},
        },
        "space": {"name": "spaces/AAA", "type": "ROOM"},
    }


@pytest.fixture
def chat_added_payload():
    return {
        "type": "ADDED_TO_SPACE",
        "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
        "space": {"name": "spaces/AAA", "type": "ROOM"},
    }


@pytest.fixture
def chat_message_with_attachment_payload():
    return {
        "type": "MESSAGE",
        "user": {"email": "shannon@gmail.com", "displayName": "Shannon"},
        "message": {
            "name": "spaces/AAA/messages/BBB",
            "text": "@ExcelBot Analyze this spreadsheet",
            "argumentText": "Analyze this spreadsheet",
            "sender": {"email": "shannon@gmail.com", "displayName": "Shannon"},
            "thread": {"name": "spaces/AAA/threads/CCC"},
            "attachment": [
                {
                    "name": "spaces/AAA/messages/BBB/attachments/DDD",
                    "contentName": "report.xlsx",
                    "contentType": XLSX_MIME,
                    "source": "UPLOADED_CONTENT",
                }
            ],
        },
        "space": {"name": "spaces/AAA", "type": "ROOM"},
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
