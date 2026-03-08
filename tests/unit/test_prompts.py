import pytest

from src.chat.context import Turn
from src.claude.prompts import (
    ANALYSIS_CONTEXT_TEMPLATE,
    COMPLEX_SYSTEM_PROMPT,
    EXCEL_SYSTEM_PROMPT,
    GENERATION_SYSTEM_PROMPT,
    MODIFICATION_CONTEXT_TEMPLATE,
    SPREADSHEET_CONTEXT_TEMPLATE,
    build_complex_messages,
    build_generation_messages,
    build_messages,
    build_messages_with_context,
    build_messages_with_history,
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


class TestDataPrivacyGuideline:
    def test_system_prompt_contains_data_privacy_guideline(self):
        assert "data privacy" in EXCEL_SYSTEM_PROMPT.lower()


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


class TestAnalysisContextTemplate:
    def test_is_string(self):
        assert isinstance(ANALYSIS_CONTEXT_TEMPLATE, str)

    def test_has_placeholders(self):
        assert "{raw_preview}" in ANALYSIS_CONTEXT_TEMPLATE
        assert "{analysis_stats}" in ANALYSIS_CONTEXT_TEMPLATE


class TestBuildMessagesWithHistory:
    def test_no_history_returns_single_user_message(self):
        result = build_messages_with_history("What is VLOOKUP?")
        assert len(result) == 1
        assert result[0] == {"role": "user", "content": "What is VLOOKUP?"}

    def test_one_turn_history(self):
        history = [Turn(question="Q1", answer="A1")]
        result = build_messages_with_history("Q2", history=history)
        assert len(result) == 3
        assert result[0] == {"role": "user", "content": "Q1"}
        assert result[1] == {"role": "assistant", "content": "A1"}
        assert result[2] == {"role": "user", "content": "Q2"}

    def test_multi_turn_history(self):
        history = [
            Turn(question="Q1", answer="A1"),
            Turn(question="Q2", answer="A2"),
        ]
        result = build_messages_with_history("Q3", history=history)
        assert len(result) == 5
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"
        assert result[2]["role"] == "user"
        assert result[3]["role"] == "assistant"
        assert result[4] == {"role": "user", "content": "Q3"}

    def test_with_spreadsheet_context_and_history(self):
        history = [Turn(question="Q1", answer="A1")]
        result = build_messages_with_history(
            "Q2", history=history, spreadsheet_context="sheet data"
        )
        # Current question should include spreadsheet context
        last_msg = result[-1]
        assert "sheet data" in last_msg["content"]
        assert "Q2" in last_msg["content"]

    def test_raises_on_empty_question(self):
        with pytest.raises(ValueError):
            build_messages_with_history("")

    def test_no_context_no_history_same_as_build_messages(self):
        result_history = build_messages_with_history("question")
        result_plain = build_messages("question")
        assert result_history == result_plain


class TestGenerationSystemPrompt:
    def test_generation_system_prompt_contains_json_schema(self):
        assert "sheets" in GENERATION_SYSTEM_PROMPT
        assert "columns" in GENERATION_SYSTEM_PROMPT
        assert "rows" in GENERATION_SYSTEM_PROMPT

    def test_modification_context_template_includes_summary(self):
        assert "{spreadsheet_summary}" in MODIFICATION_CONTEXT_TEMPLATE

    def test_modification_template_format(self):
        result = MODIFICATION_CONTEXT_TEMPLATE.format(spreadsheet_summary="test data")
        assert "test data" in result
        assert "modify" in result.lower() or "MODIFIED" in result


class TestBuildGenerationMessages:
    def test_build_generation_messages_simple(self):
        result = build_generation_messages("Make me a budget tracker")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "budget tracker" in result[0]["content"]

    def test_build_generation_messages_with_context(self):
        result = build_generation_messages(
            "Add a total column", spreadsheet_context="| A | B |"
        )
        assert len(result) == 1
        content = result[0]["content"]
        assert "A | B" in content
        assert "Add a total column" in content

    def test_build_generation_messages_empty_question_raises(self):
        with pytest.raises(ValueError):
            build_generation_messages("")

    def test_build_generation_messages_returns_list(self):
        result = build_generation_messages("Create a spreadsheet")
        assert isinstance(result, list)

    def test_generation_messages_context_appended(self):
        result = build_generation_messages("Modify it", spreadsheet_context="sheet info")
        content = result[0]["content"]
        assert "sheet info" in content
        assert "Modify it" in content


class TestComplexSystemPrompt:
    def test_complex_prompt_mentions_advanced_functions(self):
        prompt = COMPLEX_SYSTEM_PROMPT.lower()
        assert "lambda" in prompt or "dynamic array" in prompt

    def test_complex_prompt_mentions_modeling(self):
        prompt = COMPLEX_SYSTEM_PROMPT.lower()
        assert "model" in prompt or "forecast" in prompt

    def test_complex_prompt_differs_from_base(self):
        assert COMPLEX_SYSTEM_PROMPT != EXCEL_SYSTEM_PROMPT


class TestBuildComplexMessages:
    def test_build_complex_messages_simple(self):
        result = build_complex_messages("Calculate NPV for this investment")
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert "NPV" in result[0]["content"]

    def test_build_complex_messages_with_context(self):
        result = build_complex_messages(
            "Forecast next quarter", spreadsheet_context="| Revenue |"
        )
        content = result[0]["content"]
        assert "Revenue" in content
        assert "Forecast next quarter" in content

    def test_build_complex_messages_empty_raises(self):
        with pytest.raises(ValueError):
            build_complex_messages("")
