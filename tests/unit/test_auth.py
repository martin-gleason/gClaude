from src.auth import extract_email, get_unauthorized_response, is_authorized


class TestIsAuthorized:
    def test_empty_allowlist_allows_anyone(self):
        assert is_authorized("any-user-id", []) is True

    def test_user_in_allowlist(self):
        assert is_authorized("user1", ["user1", "user2"]) is True

    def test_user_not_in_allowlist(self):
        assert is_authorized("user3", ["user1", "user2"]) is False

    def test_empty_user_id_with_empty_allowlist(self):
        assert is_authorized("", []) is True

    def test_empty_user_id_with_allowlist(self):
        assert is_authorized("", ["user1"]) is False

    def test_gmail_display_name_format(self):
        assert is_authorized("Shannon <shannon@gmail.com>", ["shannon@gmail.com"]) is True

    def test_gmail_display_name_not_in_allowlist(self):
        assert is_authorized("Shannon <other@gmail.com>", ["shannon@gmail.com"]) is False


class TestExtractEmail:
    def test_bare_email(self):
        assert extract_email("user@example.com") == "user@example.com"

    def test_name_angle_bracket_format(self):
        assert extract_email("Shannon <shannon@gmail.com>") == "shannon@gmail.com"

    def test_quoted_name_format(self):
        assert extract_email('"Shannon M" <shannon@gmail.com>') == "shannon@gmail.com"


class TestGetUnauthorizedResponse:
    def test_returns_dict_with_text(self):
        resp = get_unauthorized_response()
        assert isinstance(resp, dict)
        assert "text" in resp

    def test_message_is_polite(self):
        resp = get_unauthorized_response()
        assert "authorized" in resp["text"].lower() or "permission" in resp["text"].lower()
