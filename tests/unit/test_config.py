import os
from unittest.mock import patch

import pytest

from src.config import Settings, get_settings


class TestSettings:
    def test_requires_anthropic_api_key(self):
        with pytest.raises(Exception):
            Settings(ANTHROPIC_API_KEY=None)

    def test_defaults(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
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


class TestGCSSettings:
    def test_gcs_defaults(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.GCS_BUCKET_NAME == ""
        assert s.GCS_SIGNED_URL_EXPIRATION_HOURS == 24
        assert s.GCS_GENERATED_FILES_PREFIX == "generated/"
        assert s.GCS_SERVICE_ACCOUNT_FILE == ""

    def test_gcs_bucket_configurable(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", GCS_BUCKET_NAME="my-bucket", _env_file=None)
        assert s.GCS_BUCKET_NAME == "my-bucket"

    def test_timeout_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.CLAUDE_TIMEOUT_SECONDS == 60

    def test_complex_model_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.COMPLEX_MODEL == ""

    def test_complex_model_configurable(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", COMPLEX_MODEL="claude-opus-4-6", _env_file=None)
        assert s.COMPLEX_MODEL == "claude-opus-4-6"


class TestFileRetentionSettings:
    def test_file_retention_hours_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.FILE_RETENTION_HOURS == 24


class TestUsageSettings:
    def test_context_window_tokens_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.CONTEXT_WINDOW_TOKENS == 200_000

    def test_usage_warning_threshold_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.USAGE_WARNING_THRESHOLD == 0.20

    def test_usage_critical_threshold_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.USAGE_CRITICAL_THRESHOLD == 0.05

    def test_rate_limit_input_tpm_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.RATE_LIMIT_INPUT_TPM == 80_000

    def test_rate_limit_rpm_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.RATE_LIMIT_RPM == 50

    def test_rate_limit_warning_threshold_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.RATE_LIMIT_WARNING_THRESHOLD == 0.80


class TestCostSettings:
    def test_daily_budget_usd_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.DAILY_BUDGET_USD == 5.00

    def test_cost_warning_threshold_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.COST_WARNING_THRESHOLD == 0.80

    def test_sonnet_input_cost_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.SONNET_INPUT_COST_PER_M == 3.00

    def test_sonnet_output_cost_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.SONNET_OUTPUT_COST_PER_M == 15.00

    def test_opus_input_cost_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.OPUS_INPUT_COST_PER_M == 5.00

    def test_opus_output_cost_default(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
        assert s.OPUS_OUTPUT_COST_PER_M == 25.00


class TestEnvironmentOverrides:
    """Validate the contract between deployment config and the app Settings.

    The deploy workflow sets env vars at Cloud Run deploy time. These tests
    confirm that the Settings class correctly picks up environment-specific
    overrides — the same mechanism used by both prod and dev deployments.
    """

    def test_dev_daily_budget_override(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", DAILY_BUDGET_USD=1.00, _env_file=None)
        assert s.DAILY_BUDGET_USD == 1.00

    def test_dev_log_level_override(self):
        s = Settings(ANTHROPIC_API_KEY="sk-test", LOG_LEVEL="DEBUG", _env_file=None)
        assert s.LOG_LEVEL == "DEBUG"

    def test_google_chat_project_number_override(self):
        s = Settings(
            ANTHROPIC_API_KEY="sk-test",
            GOOGLE_CHAT_PROJECT_NUMBER="123456789",
            _env_file=None,
        )
        assert s.GOOGLE_CHAT_PROJECT_NUMBER == "123456789"

    def test_all_dev_overrides_together(self):
        s = Settings(
            ANTHROPIC_API_KEY="sk-test",
            DAILY_BUDGET_USD=1.00,
            LOG_LEVEL="DEBUG",
            GCS_BUCKET_NAME="gclaude-dev-files",
            GOOGLE_CHAT_PROJECT_NUMBER="987654321",
            AUTHORIZED_USERS="dev-tester@example.com",
            _env_file=None,
        )
        assert s.DAILY_BUDGET_USD == 1.00
        assert s.LOG_LEVEL == "DEBUG"
        assert s.GCS_BUCKET_NAME == "gclaude-dev-files"
        assert s.GOOGLE_CHAT_PROJECT_NUMBER == "987654321"
        assert s.authorized_users_list == ["dev-tester@example.com"]

    def test_env_var_override_daily_budget(self):
        with patch.dict(os.environ, {"DAILY_BUDGET_USD": "1.00"}):
            s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
            assert s.DAILY_BUDGET_USD == 1.00

    def test_env_var_override_log_level(self):
        with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
            s = Settings(ANTHROPIC_API_KEY="sk-test", _env_file=None)
            assert s.LOG_LEVEL == "DEBUG"
