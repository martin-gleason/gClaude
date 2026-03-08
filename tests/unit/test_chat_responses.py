from src.chat.responses import (
    WELCOME_MESSAGE,
    corrupt_file_response,
    empty_response,
    error_response,
    file_response,
    rate_limit_response,
    removed_response,
    storage_failure_response,
    success_response,
    timeout_response,
    unauthorized_response,
    welcome_response,
)


class TestWelcomeResponse:
    def test_returns_text_dict(self):
        result = welcome_response()
        assert "text" in result
        assert result["text"] == WELCOME_MESSAGE

    def test_mentions_excelbot(self):
        result = welcome_response()
        assert "ExcelBot" in result["text"]

    def test_mentions_at_mention(self):
        result = welcome_response()
        assert "@ExcelBot" in result["text"]


class TestSuccessResponse:
    def test_wraps_answer(self):
        result = success_response("Use =VLOOKUP(A1, B:C, 2, FALSE)")
        assert result == {"text": "Use =VLOOKUP(A1, B:C, 2, FALSE)"}

    def test_preserves_formatting(self):
        answer = "Step 1:\n=VLOOKUP()\n\nStep 2:\n=INDEX()"
        result = success_response(answer)
        assert result["text"] == answer


class TestErrorResponse:
    def test_returns_text_dict(self):
        result = error_response()
        assert "text" in result

    def test_friendly_message(self):
        result = error_response()
        assert "wrong" in result["text"].lower()


class TestRateLimitResponse:
    def test_suggests_retry(self):
        result = rate_limit_response()
        text = result["text"].lower()
        assert "again" in text or "later" in text


class TestUnauthorizedResponse:
    def test_mentions_authorized(self):
        result = unauthorized_response()
        assert "authorized" in result["text"].lower()


class TestRemovedResponse:
    def test_returns_empty_dict(self):
        assert removed_response() == {}


class TestEmptyResponse:
    def test_returns_empty_dict(self):
        assert empty_response() == {}


class TestSuccessResponseWithThread:
    def test_success_includes_thread_when_provided(self):
        result = success_response("answer", thread_name="spaces/AAA/threads/CCC")
        assert result["text"] == "answer"
        assert result["thread"] == {"name": "spaces/AAA/threads/CCC"}

    def test_success_no_thread_when_none(self):
        result = success_response("answer", thread_name=None)
        assert result == {"text": "answer"}
        assert "thread" not in result

    def test_success_no_thread_when_empty_string(self):
        result = success_response("answer", thread_name="")
        assert result == {"text": "answer"}
        assert "thread" not in result


class TestFileResponse:
    def test_file_response_includes_url(self):
        result = file_response("Here's your file", "https://example.com/f.xlsx", "budget.xlsx")
        assert "https://example.com/f.xlsx" in result["text"]

    def test_file_response_includes_filename(self):
        result = file_response("Done", "https://example.com/f.xlsx", "budget.xlsx")
        assert "budget.xlsx" in result["text"]

    def test_file_response_includes_thread(self):
        result = file_response(
            "Done", "https://example.com/f.xlsx", "budget.xlsx",
            thread_name="spaces/AAA/threads/T1",
        )
        assert result["thread"] == {"name": "spaces/AAA/threads/T1"}

    def test_file_response_no_thread(self):
        result = file_response("Done", "https://example.com/f.xlsx", "budget.xlsx")
        assert "thread" not in result


class TestTimeoutResponse:
    def test_timeout_response_text(self):
        result = timeout_response()
        assert "too long" in result["text"].lower()

    def test_timeout_response_with_thread(self):
        result = timeout_response(thread_name="spaces/AAA/threads/T1")
        assert result["thread"] == {"name": "spaces/AAA/threads/T1"}


class TestStorageFailureResponse:
    def test_storage_failure_response_text(self):
        result = storage_failure_response()
        assert "unable" in result["text"].lower() or "save" in result["text"].lower()


class TestCorruptFileResponse:
    def test_corrupt_file_response_text(self):
        result = corrupt_file_response()
        assert "read" in result["text"].lower() or "valid" in result["text"].lower()


class TestSuccessResponseUsageFooter:
    def test_success_response_with_usage_footer(self):
        footer = "\n\n---\n~45 questions remaining in this thread"
        result = success_response("answer", thread_name="t1", usage_footer=footer)
        assert result["text"] == "answer" + footer

    def test_success_response_empty_footer_unchanged(self):
        result = success_response("answer", usage_footer="")
        assert result["text"] == "answer"

    def test_success_response_default_footer_is_empty(self):
        result = success_response("answer")
        assert result["text"] == "answer"

    def test_success_response_footer_with_thread(self):
        result = success_response(
            "answer", thread_name="spaces/AAA/threads/T1",
            usage_footer="\n\n---\n~10 remaining",
        )
        assert result["text"] == "answer\n\n---\n~10 remaining"
        assert result["thread"] == {"name": "spaces/AAA/threads/T1"}

    def test_success_response_backward_compat(self):
        result = success_response("answer", thread_name="spaces/AAA/threads/T1")
        assert result == {"text": "answer", "thread": {"name": "spaces/AAA/threads/T1"}}


class TestFileResponseUsageFooter:
    def test_file_response_with_usage_footer(self):
        footer = "\n\n---\nToday's API usage: $4.12 / $5.00 budget"
        result = file_response(
            "Here's your spreadsheet!", "https://example.com/f.xlsx",
            "budget.xlsx", usage_footer=footer,
        )
        assert "$4.12" in result["text"]
        assert "Download budget.xlsx" in result["text"]

    def test_file_response_default_footer_empty(self):
        result = file_response("Done", "https://example.com/f.xlsx", "budget.xlsx")
        assert result["text"] == "Done\n\n[Download budget.xlsx](https://example.com/f.xlsx)"
