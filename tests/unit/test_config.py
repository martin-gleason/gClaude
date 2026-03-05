from unittest.mock import patch

import pytest

from src.config import Settings, get_settings


class TestSettings:
    def test_requires_anthropic_api_key(self):
        with pytest.raises(Exception):
            Settings(ANTHROPIC_API_KEY=None)

    def test_defaults(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test")
        assert s.ANTHROPIC_API_KEY == "sk-test"
        assert s.AUTHORIZED_USERS == ""
        assert s.GMAIL_WEBHOOK_SECRET == ""
        assert s.DEFAULT_MODEL == "claude-sonnet-4-5-20250929"
        assert s.MAX_XLSX_SIZE_MB == 10
        assert s.MAX_PREVIEW_ROWS == 50
        assert s.LOG_LEVEL == "INFO"

    def test_authorized_users_list_empty(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", AUTHORIZED_USERS="")
        assert s.authorized_users_list == []

    def test_authorized_users_list_single(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", AUTHORIZED_USERS="user1")
        assert s.authorized_users_list == ["user1"]

    def test_authorized_users_list_multiple(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", AUTHORIZED_USERS="user1,user2,user3")
        assert s.authorized_users_list == ["user1", "user2", "user3"]

    def test_authorized_users_list_strips_whitespace(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", AUTHORIZED_USERS=" user1 , user2 ")
        assert s.authorized_users_list == ["user1", "user2"]

    def test_custom_values(self):
        s = Settings(
            ANTHROPIC_API_KEY="sk-custom",
            GMAIL_WEBHOOK_SECRET="my-secret",
            DEFAULT_MODEL="claude-haiku-4-5-20251001",
            MAX_XLSX_SIZE_MB=5,
            MAX_PREVIEW_ROWS=100,
            LOG_LEVEL="DEBUG",
        )
        assert s.GMAIL_WEBHOOK_SECRET == "my-secret"
        assert s.DEFAULT_MODEL == "claude-haiku-4-5-20251001"
        assert s.MAX_XLSX_SIZE_MB == 5
        assert s.MAX_PREVIEW_ROWS == 100
        assert s.LOG_LEVEL == "DEBUG"


class TestGetSettings:
    def test_returns_settings_instance(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            get_settings.cache_clear()
            s = get_settings()
            assert isinstance(s, Settings)
            assert s.ANTHROPIC_API_KEY == "sk-test"

    def test_caches_result(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            get_settings.cache_clear()
            s1 = get_settings()
            s2 = get_settings()
            assert s1 is s2
