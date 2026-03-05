import pytest

from src.claude.prompts import (
    EXCEL_SYSTEM_PROMPT,
    SPREADSHEET_CONTEXT_TEMPLATE,
    build_messages,
    build_messages_with_context,
    get_excel_system_prompt,
)


class TestExcelSystemPrompt:
    def test_constant_is_string(self):
        assert isinstance(EXCEL_SYSTEM_PROMPT, str)

    def test_mentions_excel(self):
        assert "Excel" in EXCEL_SYSTEM_PROMPT or "excel" in EXCEL_SYSTEM_PROMPT.lower()

    def test_mentions_formulas(self):
        assert "formula" in EXCEL_SYSTEM_PROMPT.lower()

    def test_get_returns_prompt(self):
        assert get_excel_system_prompt() == EXCEL_SYSTEM_PROMPT


class TestSpreadsheetContextTemplate:
    def test_is_string(self):
        assert isinstance(SPREADSHEET_CONTEXT_TEMPLATE, str)

    def test_has_placeholder(self):
        assert "{spreadsheet_summary}" in SPREADSHEET_CONTEXT_TEMPLATE

    def test_mentions_spreadsheet(self):
        assert "spreadsheet" in SPREADSHEET_CONTEXT_TEMPLATE.lower()


class TestBuildMessages:
    def test_returns_user_message(self):
        result = build_messages("How do I use VLOOKUP?")
        assert result == [{"role": "user", "content": "How do I use VLOOKUP?"}]

    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError):
            build_messages("")

    def test_raises_on_whitespace_only(self):
        with pytest.raises(ValueError):
            build_messages("   ")


class TestBuildMessagesWithContext:
    def test_without_context_returns_plain_question(self):
        result = build_messages_with_context("How do I sort?")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "How do I sort?"

    def test_with_context_includes_spreadsheet_data(self):
        context = "| Name | Age |\n| --- | --- |\n| Alice | 30 |"
        result = build_messages_with_context("Summarize this data", context)
        assert len(result) == 1
        content = result[0]["content"]
        assert "Alice" in content
        assert "Summarize this data" in content
        assert "spreadsheet" in content.lower()

    def test_raises_on_empty_question(self):
        with pytest.raises(ValueError):
            build_messages_with_context("")

    def test_raises_on_whitespace_question(self):
        with pytest.raises(ValueError):
            build_messages_with_context("   ", "some context")

    def test_none_context_treated_as_no_context(self):
        result = build_messages_with_context("question", None)
        assert result[0]["content"] == "question"

    def test_empty_context_treated_as_no_context(self):
        result = build_messages_with_context("question", "")
        assert result[0]["content"] == "question"
