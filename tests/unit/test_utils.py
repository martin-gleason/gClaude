from src.utils import sanitize_email


class TestSanitizeEmail:
    def test_sanitize_normal_email(self):
        assert sanitize_email("shannon@gmail.com") == "s*****n@gmail.com"

    def test_sanitize_short_local(self):
        assert sanitize_email("ab@x.com") == "**@x.com"

    def test_sanitize_single_char_local(self):
        assert sanitize_email("a@x.com") == "**@x.com"

    def test_sanitize_preserves_domain(self):
        result = sanitize_email("user@example.com")
        assert result.endswith("@example.com")

    def test_sanitize_empty_string(self):
        assert sanitize_email("") == "<unknown>"

    def test_sanitize_no_at_sign(self):
        assert sanitize_email("not-an-email") == "<invalid>"

    def test_sanitize_long_email(self):
        result = sanitize_email("verylonglocalpart@example.com")
        assert result == "v***************t@example.com"

    def test_sanitize_subdomain_email(self):
        result = sanitize_email("user@sub.domain.com")
        assert result.endswith("@sub.domain.com")
