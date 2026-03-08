WELCOME_MESSAGE = (
    "Hi! I'm ExcelBot \u2014 your Excel and spreadsheet assistant. "
    "I can help with formulas, data analysis, pivot tables, and more.\n\n"
    "In group spaces, mention me with @ExcelBot followed by your question. "
    "In DMs, just type your question directly."
)


def welcome_response() -> dict:
    return {"text": WELCOME_MESSAGE}


def success_response(
    answer: str, thread_name: str | None = None, usage_footer: str = ""
) -> dict:
    text = answer + usage_footer if usage_footer else answer
    response = {"text": text}
    if thread_name:
        response["thread"] = {"name": thread_name}
    return response


def error_response() -> dict:
    return {
        "text": "Something went wrong while processing your request. Please try again."
    }


def rate_limit_response() -> dict:
    return {
        "text": (
            "I'm receiving too many requests right now. "
            "Please try again in a few minutes."
        )
    }


def unauthorized_response() -> dict:
    return {
        "text": (
            "Sorry, you are not authorized to use this bot. "
            "Please contact an administrator to request access."
        )
    }


def removed_response() -> dict:
    return {}


def file_response(
    answer: str, download_url: str, filename: str,
    thread_name: str | None = None, usage_footer: str = "",
) -> dict:
    text = f"{answer}\n\n[Download {filename}]({download_url})"
    if usage_footer:
        text += usage_footer
    response = {"text": text}
    if thread_name:
        response["thread"] = {"name": thread_name}
    return response


def timeout_response(thread_name: str | None = None) -> dict:
    response = {
        "text": (
            "Sorry, the request took too long to process. "
            "Please try again with a simpler request."
        )
    }
    if thread_name:
        response["thread"] = {"name": thread_name}
    return response


def storage_failure_response(thread_name: str | None = None) -> dict:
    response = {
        "text": (
            "Sorry, I was unable to save the generated file. "
            "Please try again in a few minutes."
        )
    }
    if thread_name:
        response["thread"] = {"name": thread_name}
    return response


def corrupt_file_response(thread_name: str | None = None) -> dict:
    response = {
        "text": (
            "Sorry, I couldn't read the uploaded file. "
            "Please make sure it's a valid .xlsx spreadsheet and try again."
        )
    }
    if thread_name:
        response["thread"] = {"name": thread_name}
    return response


def empty_response() -> dict:
    return {}
