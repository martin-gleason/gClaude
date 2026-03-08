import datetime
import time

import pytest

from src.claude.usage import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_TOKENS_PER_TURN,
    EMA_ALPHA,
    CostTracker,
    RateLimitTracker,
    ThreadUsageTracker,
    format_usage_footer,
)

# --- Phase 2: ThreadUsageTracker ---


class TestThreadUsageTrackerBasics:
    def test_new_tracker_has_zero_tokens(self):
        t = ThreadUsageTracker()
        assert t.total_tokens == 0

    def test_new_tracker_has_zero_turns(self):
        t = ThreadUsageTracker()
        assert t.turn_count == 0

    def test_record_turn_increments_total_tokens(self):
        t = ThreadUsageTracker()
        t.record_turn(100, 50)
        assert t.total_tokens == 150

    def test_record_turn_increments_turn_count(self):
        t = ThreadUsageTracker()
        t.record_turn(100, 50)
        assert t.turn_count == 1

    def test_multiple_turns_accumulate(self):
        t = ThreadUsageTracker()
        t.record_turn(100, 50)
        t.record_turn(200, 100)
        assert t.total_tokens == 450
        assert t.turn_count == 2


class TestThreadUsageTrackerEstimation:
    def test_remaining_tokens_calculation(self):
        t = ThreadUsageTracker(context_window=10_000)
        t.record_turn(3000, 1000)
        assert t.remaining_tokens == 6000

    def test_remaining_tokens_never_negative(self):
        t = ThreadUsageTracker(context_window=100)
        t.record_turn(80, 80)
        assert t.remaining_tokens == 0

    def test_remaining_fraction_full_window(self):
        t = ThreadUsageTracker()
        assert t.remaining_fraction == 1.0

    def test_remaining_fraction_half_used(self):
        t = ThreadUsageTracker(context_window=10_000)
        t.record_turn(3000, 2000)
        assert t.remaining_fraction == 0.5

    def test_estimate_remaining_turns_initial(self):
        t = ThreadUsageTracker()
        # Default EMA = 2000 tpt, window = 200K → 100 turns
        assert t.estimate_remaining_turns() == DEFAULT_CONTEXT_WINDOW // DEFAULT_TOKENS_PER_TURN

    def test_estimate_remaining_turns_after_usage(self):
        t = ThreadUsageTracker(context_window=10_000)
        # EMA starts at 2000, after recording 4000-token turn:
        # new_ema = 0.3 * 4000 + 0.7 * 2000 = 1200 + 1400 = 2600
        # remaining = 10000 - 4000 = 6000
        # 6000 / 2600 = 2.30... → 2
        t.record_turn(2000, 2000)
        expected_ema = EMA_ALPHA * 4000 + (1 - EMA_ALPHA) * DEFAULT_TOKENS_PER_TURN
        expected_remaining = 10_000 - 4000
        expected = int(expected_remaining / expected_ema)
        assert t.estimate_remaining_turns() == expected

    def test_ema_weights_recent_turns_more(self):
        t = ThreadUsageTracker(context_window=200_000)
        # Record many small turns, then one large turn
        for _ in range(5):
            t.record_turn(500, 500)
        ema_before = t._ema_tokens_per_turn
        t.record_turn(5000, 5000)
        ema_after = t._ema_tokens_per_turn
        # EMA should have moved toward 10000
        assert ema_after > ema_before

    def test_estimate_never_negative(self):
        t = ThreadUsageTracker(context_window=100)
        t.record_turn(80, 80)
        assert t.estimate_remaining_turns() >= 0


class TestThreadUsageTrackerWarningLevel:
    def test_warning_level_normal(self):
        t = ThreadUsageTracker(context_window=10_000)
        # Use 50% → remaining 50% → normal
        t.record_turn(3000, 2000)
        assert t.warning_level == "normal"

    def test_warning_level_warning(self):
        t = ThreadUsageTracker(context_window=10_000)
        # Use 85% → remaining 15% → warning (between 5% and 20%)
        t.record_turn(5000, 3500)
        assert t.warning_level == "warning"

    def test_warning_level_critical(self):
        t = ThreadUsageTracker(context_window=10_000)
        # Use 97% → remaining 3% → critical (<5%)
        t.record_turn(5000, 4700)
        assert t.warning_level == "critical"


# --- Phase 3: RateLimitTracker ---


class TestRateLimitTrackerBasics:
    def test_new_rate_tracker_empty(self):
        r = RateLimitTracker()
        assert r.current_rpm == 0
        assert r.current_itpm == 0

    def test_record_request_increments_rpm(self):
        r = RateLimitTracker()
        r.record_request(input_tokens=100)
        assert r.current_rpm == 1

    def test_record_request_tracks_tokens(self):
        r = RateLimitTracker()
        r.record_request(input_tokens=500)
        r.record_request(input_tokens=300)
        assert r.current_itpm == 800

    def test_old_requests_pruned(self):
        r = RateLimitTracker()
        r.record_request(input_tokens=100)
        # Backdate the request to >60s ago
        r._requests[0].timestamp = time.time() - 61
        assert r.current_rpm == 0
        assert r.current_itpm == 0


class TestRateLimitTrackerFractions:
    def test_rpm_fraction_calculation(self):
        r = RateLimitTracker(rpm_limit=50)
        for _ in range(25):
            r.record_request(input_tokens=10)
        assert r.rpm_fraction == 0.5

    def test_itpm_fraction_calculation(self):
        r = RateLimitTracker(itpm_limit=1000)
        r.record_request(input_tokens=800)
        assert r.itpm_fraction == 0.8


class TestRateLimitTrackerApproaching:
    def test_is_approaching_limit_false_when_low(self):
        r = RateLimitTracker(rpm_limit=50)
        r.record_request(input_tokens=10)
        assert r.is_approaching_limit is False

    def test_is_approaching_limit_true_at_rpm_threshold(self):
        r = RateLimitTracker(rpm_limit=10, warning_threshold=0.80)
        for _ in range(8):
            r.record_request(input_tokens=1)
        assert r.is_approaching_limit is True

    def test_is_approaching_limit_true_at_itpm_threshold(self):
        r = RateLimitTracker(itpm_limit=1000, warning_threshold=0.80)
        r.record_request(input_tokens=800)
        assert r.is_approaching_limit is True

    def test_warning_message_none_when_ok(self):
        r = RateLimitTracker()
        assert r.warning_message is None

    def test_warning_message_present_when_approaching(self):
        r = RateLimitTracker(rpm_limit=10, warning_threshold=0.80)
        for _ in range(8):
            r.record_request(input_tokens=1)
        msg = r.warning_message
        assert msg is not None
        assert "requests" in msg.lower()

    def test_concurrent_requests_track_correctly(self):
        r = RateLimitTracker(rpm_limit=100)
        for _ in range(50):
            r.record_request(input_tokens=100)
        assert r.current_rpm == 50
        assert r.current_itpm == 5000


# --- Phase 4: Footer Formatting ---


class TestFormatUsageFooter:
    def test_format_footer_no_trackers_returns_empty(self):
        assert format_usage_footer() == ""

    def test_format_footer_none_trackers_returns_empty(self):
        assert format_usage_footer(thread_tracker=None, rate_tracker=None) == ""

    def test_format_footer_normal_shows_estimate(self):
        t = ThreadUsageTracker(context_window=200_000)
        footer = format_usage_footer(thread_tracker=t)
        assert "questions remaining" in footer
        assert "100" in footer

    def test_format_footer_warning_shows_heads_up(self):
        t = ThreadUsageTracker(context_window=10_000)
        t.record_turn(5000, 3500)  # 85% used → warning
        footer = format_usage_footer(thread_tracker=t)
        assert "Heads up" in footer

    def test_format_footer_critical_suggests_new_thread(self):
        t = ThreadUsageTracker(context_window=10_000)
        t.record_turn(5000, 4700)  # 97% used → critical
        footer = format_usage_footer(thread_tracker=t)
        assert "new thread" in footer

    def test_format_footer_rate_limit_warning(self):
        r = RateLimitTracker(rpm_limit=10, warning_threshold=0.80)
        for _ in range(8):
            r.record_request(input_tokens=1)
        footer = format_usage_footer(rate_tracker=r)
        assert "requests" in footer.lower()

    def test_format_footer_both_warnings_shows_both(self):
        t = ThreadUsageTracker(context_window=10_000)
        t.record_turn(5000, 3500)  # warning level
        r = RateLimitTracker(rpm_limit=10, warning_threshold=0.80)
        for _ in range(8):
            r.record_request(input_tokens=1)
        footer = format_usage_footer(thread_tracker=t, rate_tracker=r)
        assert "Heads up" in footer
        assert "requests" in footer.lower()

    def test_format_footer_starts_with_separator(self):
        t = ThreadUsageTracker()
        footer = format_usage_footer(thread_tracker=t)
        assert footer.startswith("\n\n---\n")

    def test_format_footer_with_zero_remaining(self):
        t = ThreadUsageTracker(context_window=100)
        t.record_turn(80, 80)  # over budget
        footer = format_usage_footer(thread_tracker=t)
        assert "full" in footer.lower()

    def test_format_footer_normal_has_separator(self):
        t = ThreadUsageTracker()
        footer = format_usage_footer(thread_tracker=t)
        assert "---" in footer


# --- CostTracker ---


class TestCostTrackerBasics:
    def test_new_cost_tracker_zero_daily_cost(self):
        ct = CostTracker()
        assert ct.daily_cost_usd == 0.0

    def test_record_usage_sonnet_calculates_cost(self):
        ct = CostTracker()
        # 1000 in * 3.00/1M + 500 out * 15.00/1M = 0.003 + 0.0075 = 0.0105
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500)
        assert ct.daily_cost_usd == pytest.approx(0.0105)

    def test_record_usage_opus_calculates_cost(self):
        ct = CostTracker()
        # 1000 in * 5.00/1M + 500 out * 25.00/1M = 0.005 + 0.0125 = 0.0175
        ct.record_usage("claude-opus-4-6", 1000, 500)
        assert ct.daily_cost_usd == pytest.approx(0.0175)

    def test_record_usage_unknown_model_uses_sonnet_rates(self):
        ct = CostTracker()
        ct.record_usage("some-future-model", 1000, 500)
        assert ct.daily_cost_usd == pytest.approx(0.0105)

    def test_multiple_records_accumulate(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500)
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500)
        assert ct.daily_cost_usd == pytest.approx(0.0210)

    def test_daily_cost_usd_property(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1_000_000, 0)
        assert ct.daily_cost_usd == pytest.approx(3.00)


class TestCostTrackerDailyReset:
    def test_daily_reset_zeroes_cost(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500)
        assert ct.daily_cost_usd > 0
        # Simulate date change
        ct._last_reset_date = datetime.date.today() - datetime.timedelta(days=1)
        assert ct.daily_cost_usd == 0.0

    def test_no_reset_same_day(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500)
        cost = ct.daily_cost_usd
        assert cost > 0
        # Access again — same day, no reset
        assert ct.daily_cost_usd == cost

    def test_reset_clears_per_user_tracking(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500, user="alice@test.com")
        assert ct.get_user_cost("alice@test.com") > 0
        ct._last_reset_date = datetime.date.today() - datetime.timedelta(days=1)
        assert ct.get_user_cost("alice@test.com") == 0.0


class TestCostTrackerPerUser:
    def test_record_with_user_tracks_per_user(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500, user="alice@test.com")
        assert ct.get_user_cost("alice@test.com") == pytest.approx(0.0105)

    def test_multiple_users_tracked_separately(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500, user="alice@test.com")
        ct.record_usage("claude-sonnet-4-5-20250929", 2000, 1000, user="bob@test.com")
        assert ct.get_user_cost("alice@test.com") == pytest.approx(0.0105)
        assert ct.get_user_cost("bob@test.com") == pytest.approx(0.0210)

    def test_get_user_cost_returns_zero_for_unknown(self):
        ct = CostTracker()
        assert ct.get_user_cost("nobody@test.com") == 0.0

    def test_user_costs_sum_to_daily_total(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1000, 500, user="alice@test.com")
        ct.record_usage("claude-sonnet-4-5-20250929", 2000, 1000, user="bob@test.com")
        total = ct.get_user_cost("alice@test.com") + ct.get_user_cost("bob@test.com")
        assert ct.daily_cost_usd == pytest.approx(total)


class TestCostTrackerBudgetAwareness:
    def test_budget_fraction_zero_when_no_usage(self):
        ct = CostTracker()
        assert ct.budget_fraction == 0.0

    def test_budget_fraction_calculation(self):
        ct = CostTracker(daily_budget_usd=10.00)
        ct._daily_cost = 5.00
        assert ct.budget_fraction == pytest.approx(0.5)

    def test_budget_fraction_can_exceed_one(self):
        ct = CostTracker(daily_budget_usd=5.00)
        ct._daily_cost = 6.00
        assert ct.budget_fraction > 1.0

    def test_is_approaching_budget_false_when_low(self):
        ct = CostTracker(daily_budget_usd=10.00)
        ct._daily_cost = 1.00
        assert ct.is_approaching_budget is False

    def test_is_approaching_budget_true_at_threshold(self):
        ct = CostTracker(daily_budget_usd=10.00, warning_threshold=0.80)
        ct._daily_cost = 8.00
        assert ct.is_approaching_budget is True

    def test_is_approaching_budget_true_when_over(self):
        ct = CostTracker(daily_budget_usd=5.00)
        ct._daily_cost = 6.00
        assert ct.is_approaching_budget is True

    def test_warning_message_none_when_ok(self):
        ct = CostTracker(daily_budget_usd=10.00)
        ct._daily_cost = 1.00
        assert ct.warning_message is None

    def test_warning_message_shows_spend_at_threshold(self):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.12
        msg = ct.warning_message
        assert msg is not None
        assert "$4.12" in msg
        assert "$5.00" in msg
        assert "over" not in msg

    def test_warning_message_shows_over_budget(self):
        ct = CostTracker(daily_budget_usd=5.00)
        ct._daily_cost = 5.30
        msg = ct.warning_message
        assert msg is not None
        assert "$5.30" in msg
        assert "over daily budget" in msg

    def test_zero_budget_never_warns(self):
        ct = CostTracker(daily_budget_usd=0.0)
        ct._daily_cost = 100.0
        assert ct.is_approaching_budget is False
        assert ct.warning_message is None
        assert ct.budget_fraction == 0.0


class TestCostTrackerModelMatching:
    def test_model_string_sonnet_match(self):
        ct = CostTracker()
        ct.record_usage("claude-sonnet-4-5-20250929", 1_000_000, 0)
        assert ct.daily_cost_usd == pytest.approx(3.00)

    def test_model_string_opus_match(self):
        ct = CostTracker()
        ct.record_usage("claude-opus-4-6", 1_000_000, 0)
        assert ct.daily_cost_usd == pytest.approx(5.00)


# --- Footer with CostTracker ---


class TestFormatUsageFooterCost:
    def test_format_footer_cost_tracker_none_no_cost_line(self):
        footer = format_usage_footer(cost_tracker=None)
        assert footer == ""

    def test_format_footer_cost_tracker_no_warning_no_cost_line(self):
        ct = CostTracker(daily_budget_usd=10.00)
        ct._daily_cost = 1.00
        footer = format_usage_footer(cost_tracker=ct)
        assert footer == ""

    def test_format_footer_cost_approaching_budget_shows_spend(self):
        ct = CostTracker(daily_budget_usd=5.00, warning_threshold=0.80)
        ct._daily_cost = 4.12
        footer = format_usage_footer(cost_tracker=ct)
        assert "$4.12" in footer
        assert "$5.00" in footer
        assert "---" in footer

    def test_format_footer_cost_over_budget_shows_over(self):
        ct = CostTracker(daily_budget_usd=5.00)
        ct._daily_cost = 5.30
        footer = format_usage_footer(cost_tracker=ct)
        assert "over daily budget" in footer

    def test_format_footer_cost_with_thread_tracker_both_shown(self):
        t = ThreadUsageTracker(context_window=10_000)
        t.record_turn(5000, 3500)  # warning level
        ct = CostTracker(daily_budget_usd=5.00)
        ct._daily_cost = 4.50
        footer = format_usage_footer(thread_tracker=t, cost_tracker=ct)
        assert "Heads up" in footer
        assert "$4.50" in footer

    def test_format_footer_cost_only_no_thread(self):
        ct = CostTracker(daily_budget_usd=5.00)
        ct._daily_cost = 4.00
        footer = format_usage_footer(cost_tracker=ct)
        assert "$4.00" in footer
        assert "questions remaining" not in footer

    def test_format_footer_cost_zero_budget_no_line(self):
        ct = CostTracker(daily_budget_usd=0.0)
        ct._daily_cost = 100.0
        footer = format_usage_footer(cost_tracker=ct)
        assert footer == ""
