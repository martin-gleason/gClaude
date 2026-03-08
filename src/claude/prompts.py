EXCEL_SYSTEM_PROMPT = (
    "You are ExcelBot, an expert Microsoft Excel assistant. "
    "Your role is to help users with Excel questions, formulas, functions, "
    "formatting, data analysis, and troubleshooting.\n\n"
    "Guidelines:\n"
    "- Provide clear, step-by-step explanations for Excel tasks.\n"
    "- When writing formulas, explain what each part does.\n"
    "- If a question is ambiguous, ask for clarification about the data layout, "
    "Excel version, or desired outcome.\n"
    "- Use proper Excel formula syntax (e.g., =VLOOKUP, =INDEX/MATCH, =SUMIFS).\n"
    "- When relevant, suggest more efficient or modern alternatives "
    "(e.g., XLOOKUP instead of VLOOKUP).\n"
    "- Keep responses concise but thorough.\n"
    "- If a question is not about Excel, politely redirect the user "
    "and let them know you specialize in Excel.\n\n"
    "**Data Privacy:** Do not repeat back sensitive data (names, financial figures, "
    "personal details) from uploaded spreadsheets unless directly relevant to the "
    "user's question. Summarize and reference cell locations instead of echoing raw values."
)

SPREADSHEET_CONTEXT_TEMPLATE = (
    "The user has attached a spreadsheet. Here is a preview of its contents:\n\n"
    "{spreadsheet_summary}\n\n"
    "Use this data to answer the user's question. "
    "Reference specific cells, columns, and sheet names when relevant."
)

ANALYSIS_CONTEXT_TEMPLATE = (
    "The user has attached a spreadsheet. Here is a raw preview:\n\n"
    "{raw_preview}\n\n"
    "Here are computed statistics from pandas:\n\n"
    "{analysis_stats}\n\n"
    "Use both the raw data and the computed statistics to answer the user's question. "
    "Provide exact numbers from the statistics when relevant."
)


GENERATION_SYSTEM_PROMPT = (
    "You are ExcelBot. The user wants you to create or modify a spreadsheet.\n\n"
    "You MUST respond with ONLY a JSON object (no markdown fences, no explanation) "
    "matching this schema:\n"
    "{\n"
    '  "sheets": [\n'
    "    {\n"
    '      "name": "Sheet1",\n'
    '      "columns": ["Col A", "Col B"],\n'
    '      "rows": [\n'
    '        ["value1", {"formula": "=SUM(B2:B5)", "bold": true}],\n'
    "        ...\n"
    "      ],\n"
    '      "column_widths": {"A": 20, "B": 15}\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Each row value can be a string, number, null, or an object with "
    "'value'/'formula', 'bold', 'number_format' fields\n"
    "- Use real Excel formula syntax (=SUM, =VLOOKUP, etc.)\n"
    "- Include sample data rows that illustrate the spreadsheet's purpose\n"
    "- Column widths are optional but recommended for readability\n"
)

COMPLEX_SYSTEM_PROMPT = (
    "You are ExcelBot, an expert-level Microsoft Excel power user and "
    "financial analyst. You specialize in advanced Excel capabilities "
    "including complex modeling, forecasting, and automation.\n\n"
    "Your expertise includes:\n"
    "- Financial modeling: NPV, IRR, DCF, WACC, CAPM, amortization schedules\n"
    "- Forecasting: FORECAST functions, trend analysis, seasonal adjustments, "
    "regression, Monte Carlo simulation approaches\n"
    "- Project management: Gantt chart formulas, critical path calculations, "
    "resource allocation, milestone tracking\n"
    "- Advanced formulas: LAMBDA, LET, dynamic array functions (FILTER, SORT, "
    "UNIQUE, SEQUENCE), CSE array formulas\n"
    "- Data tools: Power Query, OLAP, pivot table calculated fields\n"
    "- Automation: VBA macros, user-defined functions\n"
    "- Sensitivity analysis, scenario modeling, goal seek, Solver\n\n"
    "Guidelines:\n"
    "- Provide production-ready formulas, not simplified examples.\n"
    "- When a problem can be solved with modern dynamic arrays, prefer them "
    "over legacy CSE formulas.\n"
    "- Explain assumptions and limitations of any model you propose.\n"
    "- Suggest validation checks the user should add.\n"
    "- If the problem involves financial modeling, state any assumptions "
    "about compounding, timing, or discount rates.\n"
    "- For VBA solutions, include error handling.\n"
    "- Keep responses thorough — these are expert users who need complete answers."
)

MODIFICATION_CONTEXT_TEMPLATE = (
    "The user has uploaded a spreadsheet with the following structure:\n\n"
    "{spreadsheet_summary}\n\n"
    "They want you to modify it. Respond with a JSON workbook spec that "
    "represents the MODIFIED version. Include ALL sheets (modified and unmodified)."
)


def get_excel_system_prompt() -> str:
    return EXCEL_SYSTEM_PROMPT


def build_messages(question: str) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be empty")
    return [{"role": "user", "content": question}]


def build_messages_with_context(
    question: str, spreadsheet_context: str | None = None
) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be empty")

    if spreadsheet_context:
        content = (
            SPREADSHEET_CONTEXT_TEMPLATE.format(spreadsheet_summary=spreadsheet_context)
            + "\n\n"
            + question
        )
    else:
        content = question

    return [{"role": "user", "content": content}]


def build_messages_with_history(
    question: str,
    history: list | None = None,
    spreadsheet_context: str | None = None,
) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be empty")

    messages = []
    if history:
        for turn in history:
            messages.append({"role": "user", "content": turn.question})
            messages.append({"role": "assistant", "content": turn.answer})

    if spreadsheet_context:
        content = (
            SPREADSHEET_CONTEXT_TEMPLATE.format(spreadsheet_summary=spreadsheet_context)
            + "\n\n"
            + question
        )
    else:
        content = question

    messages.append({"role": "user", "content": content})
    return messages


def build_generation_messages(
    question: str, spreadsheet_context: str | None = None
) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be empty")

    if spreadsheet_context:
        content = (
            MODIFICATION_CONTEXT_TEMPLATE.format(spreadsheet_summary=spreadsheet_context)
            + "\n\n"
            + question
        )
    else:
        content = question

    return [{"role": "user", "content": content}]


def build_complex_messages(
    question: str, spreadsheet_context: str | None = None
) -> list[dict]:
    if not question.strip():
        raise ValueError("Question cannot be empty")

    if spreadsheet_context:
        content = (
            SPREADSHEET_CONTEXT_TEMPLATE.format(spreadsheet_summary=spreadsheet_context)
            + "\n\n"
            + question
        )
    else:
        content = question

    return [{"role": "user", "content": content}]
