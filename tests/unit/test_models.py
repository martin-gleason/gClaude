from src.claude.models import get_model


class TestGetModel:
    def test_returns_default(self):
        assert get_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5-20250929"

    def test_returns_custom(self):
        assert get_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"
