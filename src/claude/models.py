import re

_COMPLEX_KEYWORDS = re.compile(
    r"\b("
    r"forecast(?:ing)?|npv|irr|amortiz(?:ation|e)|"
    r"sensitivity|scenario|monte carlo|"
    r"gantt|milestone|critical path|resource allocation|"
    r"model(?:ing)?|regression|trend analysis|"
    r"lambda|let\s+function|dynamic array|spill|"
    r"solver|goal seek|"
    r"dcf|wacc|capm|ebitda|"
    r"pivot\s+table.*calculated|olap|power\s+query|"
    r"array\s+formula|cse\s+formula|"
    r"vba|macro|user.?defined\s+function"
    r")\b",
    re.IGNORECASE,
)


def get_model(default_model: str) -> str:
    return default_model


def is_complex_question(question: str) -> bool:
    return bool(_COMPLEX_KEYWORDS.search(question))
