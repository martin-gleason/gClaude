def is_authorized(user_id: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    return user_id in allowlist


def get_unauthorized_response() -> dict:
    return {
        "text": "Sorry, you are not authorized to use this bot. "
        "Please contact an administrator to request access."
    }
