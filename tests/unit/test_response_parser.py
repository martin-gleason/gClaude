import json

from src.chat.response_parser import parse_claude_response


def _valid_workbook_json(**overrides):
    spec = {
        "sheets": [
            {
                "name": "Sheet1",
                "columns": ["Name", "Amount"],
                "rows": [["Alice", 100]],
            }
        ],
    }
    spec.update(overrides)
    return json.dumps(spec)


class TestParseClaudeResponse:
    def test_plain_text_response(self):
        result = parse_claude_response("Here is how to use VLOOKUP...")
        assert result.is_workbook is False
        assert result.text == "Here is how to use VLOOKUP..."
        assert result.workbook_spec is None

    def test_valid_json_workbook_response(self):
        result = parse_claude_response(_valid_workbook_json())
        assert result.is_workbook is True
        assert result.workbook_spec is not None
        assert len(result.workbook_spec.sheets) == 1
        assert result.workbook_spec.sheets[0].name == "Sheet1"

    def test_json_with_markdown_fences_stripped(self):
        json_str = "```json\n" + _valid_workbook_json() + "\n```"
        result = parse_claude_response(json_str)
        assert result.is_workbook is True
        assert result.workbook_spec is not None

    def test_invalid_json_returns_text(self):
        result = parse_claude_response("{ not valid json }")
        assert result.is_workbook is False
        assert result.text == "{ not valid json }"

    def test_json_missing_sheets_key_returns_text(self):
        result = parse_claude_response('{"data": [1, 2, 3]}')
        assert result.is_workbook is False
        assert result.text == '{"data": [1, 2, 3]}'

    def test_empty_response_returns_text(self):
        result = parse_claude_response("")
        assert result.is_workbook is False
        assert result.text == ""

    def test_partial_json_returns_text_with_error(self):
        result = parse_claude_response('{"sheets": [{"name": "Sheet1"')
        assert result.is_workbook is False
        assert result.parse_error is not None

    def test_json_with_extra_text_before(self):
        json_str = "Here's your spreadsheet:\n" + _valid_workbook_json()
        result = parse_claude_response(json_str)
        assert result.is_workbook is True
        assert result.workbook_spec is not None

    def test_multi_sheet_json_parsed(self):
        json_str = json.dumps({
            "sheets": [
                {"name": "Income", "columns": ["Source"], "rows": [["Salary"]]},
                {"name": "Expenses", "columns": ["Item"], "rows": [["Rent"]]},
            ]
        })
        result = parse_claude_response(json_str)
        assert result.is_workbook is True
        assert len(result.workbook_spec.sheets) == 2

    def test_parse_error_captured(self):
        # Valid JSON but missing required columns field
        json_str = json.dumps({"sheets": [{"name": "Sheet1", "rows": []}]})
        result = parse_claude_response(json_str)
        assert result.is_workbook is False
        assert result.parse_error is not None
