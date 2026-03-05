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
    "and let them know you specialize in Excel."
)

SPREADSHEET_CONTEXT_TEMPLATE = (
    "The user has attached a spreadsheet. Here is a preview of its contents:\n\n"
    "{spreadsheet_summary}\n\n"
    "Use this data to answer the user's question. "
    "Reference specific cells, columns, and sheet names when relevant."
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
