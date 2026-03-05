from unittest.mock import MagicMock, patch

import anthropic
import pytest

from src.claude.client import ClaudeApiError, ClaudeClient, ClaudeRateLimitError


@pytest.fixture
def mock_anthropic():
    with patch("src.claude.client.anthropic.Anthropic") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def client(mock_anthropic):
    return ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")


class TestClaudeClient:
    def test_ask_returns_text(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Use =VLOOKUP(A1, B:C, 2, FALSE)")]
        mock_anthropic.messages.create.return_value = mock_response

        result = client.ask("How do I use VLOOKUP?")
        assert result == "Use =VLOOKUP(A1, B:C, 2, FALSE)"

    def test_ask_calls_api_with_correct_params(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="answer")]
        mock_anthropic.messages.create.return_value = mock_response

        client.ask("question")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-5-20250929"
        assert call_kwargs["messages"] == [{"role": "user", "content": "question"}]
        assert "system" in call_kwargs
        assert call_kwargs["max_tokens"] > 0

    def test_ask_raises_on_empty_question(self, client):
        with pytest.raises(ValueError):
            client.ask("")

    def test_ask_maps_api_error(self, client, mock_anthropic):
        mock_anthropic.messages.create.side_effect = anthropic.APIError(
            message="bad request",
            request=MagicMock(),
            body=None,
        )
        with pytest.raises(ClaudeApiError):
            client.ask("question")

    def test_ask_maps_rate_limit_error(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_anthropic.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited",
            response=mock_response,
            body=None,
        )
        with pytest.raises(ClaudeRateLimitError):
            client.ask("question")


class TestAskWithContext:
    def test_returns_text(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Analysis result")]
        mock_anthropic.messages.create.return_value = mock_response

        result = client.ask_with_context("Analyze this", "| A |\n| 1 |")
        assert result == "Analysis result"

    def test_without_context(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="answer")]
        mock_anthropic.messages.create.return_value = mock_response

        result = client.ask_with_context("question")
        assert result == "answer"

    def test_context_included_in_message(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="answer")]
        mock_anthropic.messages.create.return_value = mock_response

        client.ask_with_context("question", "spreadsheet data here")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        content = call_kwargs["messages"][0]["content"]
        assert "spreadsheet data here" in content
        assert "question" in content

    def test_raises_on_empty_question(self, client):
        with pytest.raises(ValueError):
            client.ask_with_context("")

    def test_maps_api_error(self, client, mock_anthropic):
        mock_anthropic.messages.create.side_effect = anthropic.APIError(
            message="failed",
            request=MagicMock(),
            body=None,
        )
        with pytest.raises(ClaudeApiError):
            client.ask_with_context("question", "context")

    def test_maps_rate_limit_error(self, client, mock_anthropic):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_anthropic.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited",
            response=mock_response,
            body=None,
        )
        with pytest.raises(ClaudeRateLimitError):
            client.ask_with_context("question")


class TestExceptions:
    def test_claude_api_error_is_exception(self):
        assert issubclass(ClaudeApiError, Exception)

    def test_claude_rate_limit_error_is_exception(self):
        assert issubclass(ClaudeRateLimitError, ClaudeApiError)
