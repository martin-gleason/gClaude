import json
import re
from dataclasses import dataclass

from src.excel.writer import WorkbookBuildError, WorkbookSpec, parse_workbook_spec


@dataclass
class ParsedResponse:
    is_workbook: bool
    workbook_spec: WorkbookSpec | None = None
    text: str = ""
    parse_error: str | None = None


def parse_claude_response(response: str) -> ParsedResponse:
    """Try to parse as workbook JSON. If valid, return is_workbook=True. Otherwise plain text."""
    stripped = response.strip()
    if not stripped:
        return ParsedResponse(is_workbook=False, text=response)

    json_str = _extract_json(response)
    if json_str is None:
        # If it looks like an attempted JSON response, record a parse error
        if stripped.startswith("{") or stripped.startswith("```"):
            return ParsedResponse(
                is_workbook=False, text=response, parse_error="Could not extract valid JSON"
            )
        return ParsedResponse(is_workbook=False, text=response)

    try:
        spec = parse_workbook_spec(json_str)
        return ParsedResponse(is_workbook=True, workbook_spec=spec)
    except WorkbookBuildError as e:
        return ParsedResponse(is_workbook=False, text=response, parse_error=str(e))


def _extract_json(text: str) -> str | None:
    # Strip markdown code fences
    stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    stripped = re.sub(r"\n?```\s*$", "", stripped)

    # Try the whole thing as JSON first
    if _looks_like_json(stripped):
        return stripped

    # Try to find a JSON object in the text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        candidate = match.group(0)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict) and "sheets" in data:
                return candidate
        except json.JSONDecodeError:
            pass

    return None


def _looks_like_json(text: str) -> bool:
    text = text.strip()
    return text.startswith("{") and text.endswith("}")
