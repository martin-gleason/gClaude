from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from src.chat.context import Turn
from src.claude.client import ClaudeApiError, ClaudeClient, ClaudeRateLimitError, ClaudeResponse


def _mock_response(text="answer", input_tokens=100, output_tokens=50):
    """Create a mock Anthropic API response with usage metadata."""
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    mock.usage.input_tokens = input_tokens
    mock.usage.output_tokens = output_tokens
    return mock


@pytest.fixture
def mock_anthropic():
    with patch("src.claude.client.anthropic.Anthropic") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def client(mock_anthropic):
    return ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")


# --- ClaudeResponse dataclass tests ---


class TestClaudeResponse:
    def test_claude_response_is_frozen_dataclass(self):
        r = ClaudeResponse(text="hello", input_tokens=10, output_tokens=5)
        with pytest.raises(FrozenInstanceError):
            r.text = "changed"

    def test_claude_response_fields(self):
        r = ClaudeResponse(text="answer", input_tokens=100, output_tokens=50)
        assert r.text == "answer"
        assert r.input_tokens == 100
        assert r.output_tokens == 50

    def test_call_api_returns_claude_response(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask("question")
        assert isinstance(result, ClaudeResponse)

    def test_call_api_captures_input_tokens(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(input_tokens=150)
        result = client.ask("question")
        assert result.input_tokens == 150

    def test_call_api_captures_output_tokens(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(output_tokens=75)
        result = client.ask("question")
        assert result.output_tokens == 75

    def test_ask_returns_claude_response(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask("question")
        assert isinstance(result, ClaudeResponse)

    def test_ask_with_context_returns_claude_response(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask_with_context("q", "ctx")
        assert isinstance(result, ClaudeResponse)

    def test_ask_with_history_returns_claude_response(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask_with_history("q", history=[])
        assert isinstance(result, ClaudeResponse)

    def test_ask_for_generation_returns_claude_response(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask_for_generation("Create a spreadsheet")
        assert isinstance(result, ClaudeResponse)

    def test_ask_complex_returns_claude_response(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        c = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            complex_model="claude-opus-4-6",
        )
        result = c.ask_complex("Calculate NPV")
        assert isinstance(result, ClaudeResponse)

    def test_claude_response_text_matches_old_behavior(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(
            text="Use =VLOOKUP(A1, B:C, 2, FALSE)"
        )
        result = client.ask("How do I use VLOOKUP?")
        assert result.text == "Use =VLOOKUP(A1, B:C, 2, FALSE)"

    def test_error_paths_still_raise_not_return(self, client, mock_anthropic):
        mock_anthropic.messages.create.side_effect = anthropic.APIError(
            message="bad request", request=MagicMock(), body=None,
        )
        with pytest.raises(ClaudeApiError):
            client.ask("question")


# --- Existing tests updated for ClaudeResponse ---


class TestClaudeClient:
    def test_ask_returns_text(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(
            text="Use =VLOOKUP(A1, B:C, 2, FALSE)"
        )
        result = client.ask("How do I use VLOOKUP?")
        assert result.text == "Use =VLOOKUP(A1, B:C, 2, FALSE)"

    def test_ask_calls_api_with_correct_params(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
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
        mock_anthropic.messages.create.return_value = _mock_response(text="Analysis result")
        result = client.ask_with_context("Analyze this", "| A |\n| 1 |")
        assert result.text == "Analysis result"

    def test_without_context(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask_with_context("question")
        assert result.text == "answer"

    def test_context_included_in_message(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
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


class TestAskWithHistory:
    def test_ask_with_history_returns_text(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(text="Follow-up answer")
        result = client.ask_with_history("Q2", history=[Turn(question="Q1", answer="A1")])
        assert result.text == "Follow-up answer"

    def test_passes_history_to_messages(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        history = [Turn(question="Q1", answer="A1")]
        client.ask_with_history("Q2", history=history)

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert len(messages) == 3
        assert messages[0] == {"role": "user", "content": "Q1"}
        assert messages[1] == {"role": "assistant", "content": "A1"}
        assert messages[2] == {"role": "user", "content": "Q2"}

    def test_with_spreadsheet_context(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        client.ask_with_history("Q1", spreadsheet_context="sheet data")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        content = call_kwargs["messages"][-1]["content"]
        assert "sheet data" in content

    def test_empty_history_works(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        result = client.ask_with_history("Q1", history=[])
        assert result.text == "answer"
        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert len(call_kwargs["messages"]) == 1


class TestAskForGeneration:
    def test_ask_for_generation_returns_text(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(text='{"sheets": []}')
        result = client.ask_for_generation("Make me a budget tracker")
        assert result.text == '{"sheets": []}'

    def test_ask_for_generation_uses_generation_system_prompt(self, client, mock_anthropic):
        from src.claude.prompts import GENERATION_SYSTEM_PROMPT

        mock_anthropic.messages.create.return_value = _mock_response(text="json")
        client.ask_for_generation("Create a spreadsheet")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["system"] == GENERATION_SYSTEM_PROMPT

    def test_ask_for_generation_with_context(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(text="json")
        client.ask_for_generation("Add a total column", spreadsheet_context="| A |")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        content = call_kwargs["messages"][0]["content"]
        assert "A |" in content

    def test_ask_for_generation_passes_messages(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(text="json")
        client.ask_for_generation("Make a tracker")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert len(call_kwargs["messages"]) == 1
        assert call_kwargs["messages"][0]["role"] == "user"


class TestCallApiSystemParam:
    def test_call_api_with_custom_system_prompt(self, client, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()
        client._call_api([{"role": "user", "content": "test"}], system="custom prompt")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "custom prompt"

    def test_call_api_default_system_prompt_unchanged(self, client, mock_anthropic):
        from src.claude.prompts import EXCEL_SYSTEM_PROMPT

        mock_anthropic.messages.create.return_value = _mock_response()
        client.ask("question")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["system"] == EXCEL_SYSTEM_PROMPT


class TestAskComplex:
    def test_ask_complex_uses_opus_model(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(text="complex answer")

        complex_client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            complex_model="claude-opus-4-6",
        )
        complex_client.ask_complex("Calculate NPV")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-opus-4-6"

    def test_ask_complex_uses_complex_system_prompt(self, mock_anthropic):
        from src.claude.prompts import COMPLEX_SYSTEM_PROMPT

        mock_anthropic.messages.create.return_value = _mock_response()

        complex_client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            complex_model="claude-opus-4-6",
        )
        complex_client.ask_complex("Build a forecast model")

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        assert call_kwargs["system"] == COMPLEX_SYSTEM_PROMPT

    def test_ask_complex_returns_text(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response(text="NPV is $1,234")

        complex_client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            complex_model="claude-opus-4-6",
        )
        result = complex_client.ask_complex("Calculate NPV")
        assert result.text == "NPV is $1,234"

    def test_ask_complex_with_spreadsheet_context(self, mock_anthropic):
        mock_anthropic.messages.create.return_value = _mock_response()

        complex_client = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            complex_model="claude-opus-4-6",
        )
        complex_client.ask_complex(
            "Forecast revenue", spreadsheet_context="| Revenue |\n| 100 |"
        )

        call_kwargs = mock_anthropic.messages.create.call_args.kwargs
        content = call_kwargs["messages"][0]["content"]
        assert "Revenue" in content


class TestModelProperties:
    def test_model_property_returns_configured_model(self, mock_anthropic):
        c = ClaudeClient(api_key="sk-test", model="claude-sonnet-4-5-20250929")
        assert c.model == "claude-sonnet-4-5-20250929"

    def test_complex_model_property_returns_configured_model(self, mock_anthropic):
        c = ClaudeClient(
            api_key="sk-test",
            model="claude-sonnet-4-5-20250929",
            complex_model="claude-opus-4-6",
        )
        assert c.complex_model == "claude-opus-4-6"


class TestExceptions:
    def test_claude_api_error_is_exception(self):
        assert issubclass(ClaudeApiError, Exception)

    def test_claude_rate_limit_error_is_exception(self):
        assert issubclass(ClaudeRateLimitError, ClaudeApiError)
