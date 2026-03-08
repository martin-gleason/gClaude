from dataclasses import dataclass

import anthropic

from src.claude.models import get_model
from src.claude.prompts import (
    COMPLEX_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    build_complex_messages,
    build_generation_messages,
    build_messages,
    build_messages_with_context,
    build_messages_with_history,
    get_excel_system_prompt,
)


@dataclass(frozen=True)
class ClaudeResponse:
    text: str
    input_tokens: int
    output_tokens: int


class ClaudeApiError(Exception):
    pass


class ClaudeRateLimitError(ClaudeApiError):
    pass


class ClaudeClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        complex_model: str = "",
    ):
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = get_model(model)
        self._complex_model = get_model(complex_model) if complex_model else ""
        self._max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self._model

    @property
    def complex_model(self) -> str:
        return self._complex_model

    def ask(self, question: str) -> ClaudeResponse:
        messages = build_messages(question)
        return self._call_api(messages)

    def ask_with_context(
        self, question: str, spreadsheet_context: str | None = None
    ) -> ClaudeResponse:
        messages = build_messages_with_context(question, spreadsheet_context)
        return self._call_api(messages)

    def ask_with_history(
        self,
        question: str,
        history: list | None = None,
        spreadsheet_context: str | None = None,
    ) -> ClaudeResponse:
        messages = build_messages_with_history(question, history, spreadsheet_context)
        return self._call_api(messages)

    def ask_for_generation(
        self, question: str, spreadsheet_context: str | None = None
    ) -> ClaudeResponse:
        messages = build_generation_messages(question, spreadsheet_context)
        return self._call_api(messages, system=GENERATION_SYSTEM_PROMPT)

    def ask_complex(
        self, question: str, spreadsheet_context: str | None = None
    ) -> ClaudeResponse:
        messages = build_complex_messages(question, spreadsheet_context)
        model = self._complex_model or self._model
        return self._call_api(
            messages, system=COMPLEX_SYSTEM_PROMPT, model=model
        )

    def _call_api(
        self,
        messages: list[dict],
        system: str | None = None,
        model: str | None = None,
    ) -> ClaudeResponse:
        try:
            response = self._client.messages.create(
                model=model or self._model,
                system=system or get_excel_system_prompt(),
                messages=messages,
                max_tokens=self._max_tokens,
            )
            return ClaudeResponse(
                text=response.content[0].text,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        except anthropic.RateLimitError as e:
            raise ClaudeRateLimitError(str(e)) from e
        except anthropic.APIError as e:
            raise ClaudeApiError(str(e)) from e
