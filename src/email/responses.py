def success_response(reply_text: str) -> dict:
    return {"reply": reply_text, "error": None}


def error_response(message: str | None = None) -> dict:
    friendly = "Something went wrong while processing your request. Please try again."
    return {"reply": friendly, "error": message or friendly}


def rate_limit_response() -> dict:
    return {
        "reply": "I'm receiving too many requests right now. Please try again in a few minutes.",
        "error": "rate_limit",
    }


def unauthorized_response() -> dict:
    return {
        "reply": "Sorry, you are not authorized to use this bot. "
        "Please contact an administrator to request access.",
        "error": "unauthorized",
    }
