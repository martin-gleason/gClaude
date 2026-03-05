from io import BytesIO

import openpyxl
import pytest

from src.excel.reader import (
    ExcelReadError,
    SpreadsheetSummary,
    format_summary_for_prompt,
    read_spreadsheet,
)


def _make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    """Create an .xlsx file in memory. sheets = {"Sheet1": [[header...], [row...]]}"""
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets.items():
        if first:
            ws = wb.active
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestReadSpreadsheet:
    def test_single_sheet_basic(self):
        data = _make_xlsx({"Sheet1": [["Name", "Age"], ["Alice", 30], ["Bob", 25]]})
        result = read_spreadsheet(data, "test.xlsx")

        assert result.filename == "test.xlsx"
        assert len(result.sheets) == 1
        sheet = result.sheets[0]
        assert sheet.name == "Sheet1"
        assert sheet.headers == ["Name", "Age"]
        assert sheet.rows == [["Alice", "30"], ["Bob", "25"]]
        assert sheet.total_rows == 2
        assert sheet.truncated is False

    def test_multi_sheet(self):
        data = _make_xlsx({
            "Employees": [["Name"], ["Alice"]],
            "Salaries": [["Amount"], ["50000"]],
        })
        result = read_spreadsheet(data, "multi.xlsx")
        assert len(result.sheets) == 2
        assert result.sheets[0].name == "Employees"
        assert result.sheets[1].name == "Salaries"

    def test_empty_sheet(self):
        data = _make_xlsx({"Empty": []})
        result = read_spreadsheet(data, "empty.xlsx")
        assert len(result.sheets) == 1
        sheet = result.sheets[0]
        assert sheet.headers == []
        assert sheet.rows == []
        assert sheet.total_rows == 0
        assert sheet.truncated is False

    def test_truncation_at_max_rows(self):
        rows = [["ID", "Value"]] + [[i, i * 10] for i in range(100)]
        data = _make_xlsx({"Data": rows})
        result = read_spreadsheet(data, "big.xlsx", max_rows=5)

        sheet = result.sheets[0]
        assert len(sheet.rows) == 5
        assert sheet.total_rows == 100
        assert sheet.truncated is True

    def test_mixed_types(self):
        data = _make_xlsx({"Types": [["A", "B", "C"], [1, 2.5, None], [True, "text", ""]]})
        result = read_spreadsheet(data, "types.xlsx")
        sheet = result.sheets[0]
        assert sheet.rows[0] == ["1", "2.5", ""]
        assert sheet.rows[1] == ["True", "text", ""]

    def test_headers_only_no_data(self):
        data = _make_xlsx({"Headers": [["Col1", "Col2"]]})
        result = read_spreadsheet(data, "headers.xlsx")
        sheet = result.sheets[0]
        assert sheet.headers == ["Col1", "Col2"]
        assert sheet.rows == []
        assert sheet.total_rows == 0

    def test_corrupt_file_raises_error(self):
        with pytest.raises(ExcelReadError, match="Could not read"):
            read_spreadsheet(b"not-a-valid-xlsx", "bad.xlsx")

    def test_file_too_large_raises_error(self):
        data = _make_xlsx({"Sheet1": [["A"], ["B"]]})
        with pytest.raises(ExcelReadError, match="exceeds the 0 MB limit"):
            read_spreadsheet(data, "big.xlsx", max_size_mb=0)

    def test_returns_spreadsheet_summary_type(self):
        data = _make_xlsx({"Sheet1": [["A"], ["1"]]})
        result = read_spreadsheet(data, "test.xlsx")
        assert isinstance(result, SpreadsheetSummary)


class TestFormatSummaryForPrompt:
    def test_basic_formatting(self):
        data = _make_xlsx({"Sheet1": [["Name", "Age"], ["Alice", 30]]})
        summary = read_spreadsheet(data, "test.xlsx")
        text = format_summary_for_prompt(summary)

        assert "## Spreadsheet: test.xlsx" in text
        assert "### Sheet: Sheet1" in text
        assert "| Name | Age |" in text
        assert "| --- | --- |" in text
        assert "| Alice | 30 |" in text

    def test_empty_sheet_formatting(self):
        data = _make_xlsx({"Empty": []})
        summary = read_spreadsheet(data, "empty.xlsx")
        text = format_summary_for_prompt(summary)
        assert "(empty sheet)" in text

    def test_truncation_note(self):
        rows = [["ID"]] + [[i] for i in range(20)]
        data = _make_xlsx({"Data": rows})
        summary = read_spreadsheet(data, "big.xlsx", max_rows=5)
        text = format_summary_for_prompt(summary)
        assert "Showing 5 of 20 data rows" in text
        assert "truncated" in text

    def test_multi_sheet_formatting(self):
        data = _make_xlsx({
            "Sheet1": [["A"], ["1"]],
            "Sheet2": [["B"], ["2"]],
        })
        summary = read_spreadsheet(data, "multi.xlsx")
        text = format_summary_for_prompt(summary)
        assert "### Sheet: Sheet1" in text
        assert "### Sheet: Sheet2" in text


class TestExcelReadError:
    def test_is_exception(self):
        assert issubclass(ExcelReadError, Exception)

    def test_message_preserved(self):
        err = ExcelReadError("test error")
        assert str(err) == "test error"
