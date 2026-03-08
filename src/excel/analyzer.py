from dataclasses import dataclass, field
from io import BytesIO

import pandas as pd


class AnalysisError(Exception):
    pass


@dataclass
class SheetAnalysis:
    name: str
    row_count: int
    column_count: int
    columns: list[str]
    dtypes: dict[str, str]
    numeric_summary: dict[str, dict[str, float]]
    sample_values: dict[str, list]


@dataclass
class SpreadsheetAnalysis:
    filename: str
    sheets: list[SheetAnalysis] = field(default_factory=list)


def analyze_spreadsheet(
    file_bytes: bytes,
    filename: str,
    max_rows: int = 1000,
    max_size_mb: int = 10,
) -> SpreadsheetAnalysis:
    size_mb = len(file_bytes) / (1024 * 1024)
    if size_mb > max_size_mb:
        raise AnalysisError(
            f"File '{filename}' is {size_mb:.1f} MB, exceeds {max_size_mb} MB limit."
        )

    try:
        sheets_dict = pd.read_excel(
            BytesIO(file_bytes), sheet_name=None, nrows=max_rows, engine="openpyxl"
        )
    except Exception as e:
        raise AnalysisError(f"Could not analyze '{filename}': {e}") from e

    analysis = SpreadsheetAnalysis(filename=filename)

    for sheet_name, df in sheets_dict.items():
        columns = list(df.columns.astype(str))
        dtypes = {col: str(dtype) for col, dtype in df.dtypes.items()}

        numeric_summary = {}
        numeric_cols = df.select_dtypes(include="number")
        if not numeric_cols.empty:
            desc = numeric_cols.describe()
            for col in numeric_cols.columns:
                numeric_summary[str(col)] = {
                    str(stat): float(val)
                    for stat, val in desc[col].items()
                    if pd.notna(val)
                }

        sample_values = {}
        for col in df.columns:
            sample_values[str(col)] = df[col].head(5).tolist()

        analysis.sheets.append(
            SheetAnalysis(
                name=str(sheet_name),
                row_count=len(df),
                column_count=len(df.columns),
                columns=columns,
                dtypes=dtypes,
                numeric_summary=numeric_summary,
                sample_values=sample_values,
            )
        )

    return analysis


def format_analysis_for_prompt(analysis: SpreadsheetAnalysis) -> str:
    parts = [f"## Analysis: {analysis.filename}"]

    for sheet in analysis.sheets:
        parts.append(f"\n### Sheet: {sheet.name}")
        parts.append(f"- Rows: {sheet.row_count}, Columns: {sheet.column_count}")
        parts.append(f"- Column types: {', '.join(f'{c} ({t})' for c, t in sheet.dtypes.items())}")

        if sheet.numeric_summary:
            parts.append("\nNumeric statistics:")
            for col, stats in sheet.numeric_summary.items():
                stat_strs = [f"{k}={v:.2f}" for k, v in stats.items()]
                parts.append(f"  {col}: {', '.join(stat_strs)}")

    return "\n".join(parts)
