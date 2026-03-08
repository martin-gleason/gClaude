import re


def extract_email(sender: str) -> str:
    """Extract bare email from 'Name <email>' format or return as-is."""
    match = re.search(r"<([^>]+)>", sender)
    return match.group(1) if match else sender


def is_authorized(user_id: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    email = extract_email(user_id).lower()
    return email in [u.lower() for u in allowlist]


def get_unauthorized_response() -> dict:
    return {
        "text": "Sorry, you are not authorized to use this bot. "
        "Please contact an administrator to request access."
    }
