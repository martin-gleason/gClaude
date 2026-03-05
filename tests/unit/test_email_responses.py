from src.email.responses import (
    error_response,
    rate_limit_response,
    success_response,
    unauthorized_response,
)


class TestSuccessResponse:
    def test_wraps_reply_text(self):
        result = success_response("Use =VLOOKUP(A1, B:C, 2, FALSE)")
        assert result["reply"] == "Use =VLOOKUP(A1, B:C, 2, FALSE)"
        assert result["error"] is None

    def test_preserves_formatting(self):
        text = "Step 1:\n=VLOOKUP()\n\nStep 2:\n=INDEX()"
        result = success_response(text)
        assert result["reply"] == text


class TestErrorResponse:
    def test_default_message(self):
        result = error_response()
        assert "wrong" in result["reply"].lower()
        assert result["error"] is not None

    def test_custom_message(self):
        result = error_response("Custom error detail")
        assert "wrong" in result["reply"].lower()
        assert result["error"] == "Custom error detail"

    def test_friendly_reply_always_present(self):
        result = error_response("internal detail")
        assert len(result["reply"]) > 10


class TestRateLimitResponse:
    def test_returns_dict(self):
        result = rate_limit_response()
        assert "reply" in result
        assert "error" in result

    def test_suggests_retry(self):
        result = rate_limit_response()
        text = result["reply"].lower()
        assert "again" in text or "later" in text

    def test_error_field(self):
        result = rate_limit_response()
        assert result["error"] == "rate_limit"


class TestUnauthorizedResponse:
    def test_returns_dict(self):
        result = unauthorized_response()
        assert "reply" in result
        assert "error" in result

    def test_mentions_authorized(self):
        result = unauthorized_response()
        assert "authorized" in result["reply"].lower()

    def test_error_field(self):
        result = unauthorized_response()
        assert result["error"] == "unauthorized"
