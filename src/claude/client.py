import anthropic

from src.claude.models import get_model
from src.claude.prompts import build_messages, build_messages_with_context, get_excel_system_prompt


class ClaudeApiError(Exception):
    pass


class ClaudeRateLimitError(ClaudeApiError):
    pass


class ClaudeClient:
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = get_model(model)
        self._max_tokens = max_tokens

    def ask(self, question: str) -> str:
        messages = build_messages(question)
        return self._call_api(messages)

    def ask_with_context(
        self, question: str, spreadsheet_context: str | None = None
    ) -> str:
        messages = build_messages_with_context(question, spreadsheet_context)
        return self._call_api(messages)

    def _call_api(self, messages: list[dict]) -> str:
        try:
            response = self._client.messages.create(
                model=self._model,
                system=get_excel_system_prompt(),
                messages=messages,
                max_tokens=self._max_tokens,
            )
            return response.content[0].text
        except anthropic.RateLimitError as e:
            raise ClaudeRateLimitError(str(e)) from e
        except anthropic.APIError as e:
            raise ClaudeApiError(str(e)) from e
