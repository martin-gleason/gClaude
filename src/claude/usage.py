import datetime
import time
from dataclasses import dataclass, field

# Defaults — overridable via config
DEFAULT_CONTEXT_WINDOW = 200_000
DEFAULT_TOKENS_PER_TURN = 2_000
EMA_ALPHA = 0.3

WARNING_THRESHOLD = 0.20
CRITICAL_THRESHOLD = 0.05

DEFAULT_RPM_LIMIT = 50
DEFAULT_ITPM_LIMIT = 80_000
RATE_LIMIT_WARNING_THRESHOLD = 0.80


@dataclass
class ThreadUsageTracker:
    """Per-thread token accumulation with remaining-turn estimation."""

    context_window: int = DEFAULT_CONTEXT_WINDOW
    warning_threshold: float = WARNING_THRESHOLD
    critical_threshold: float = CRITICAL_THRESHOLD

    total_input_tokens: int = field(default=0, init=False)
    total_output_tokens: int = field(default=0, init=False)
    turn_count: int = field(default=0, init=False)
    _ema_tokens_per_turn: float = field(default=float(DEFAULT_TOKENS_PER_TURN), init=False)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def record_turn(self, input_tokens: int, output_tokens: int) -> None:
        turn_tokens = input_tokens + output_tokens
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.turn_count += 1
        # Update EMA
        self._ema_tokens_per_turn = (
            EMA_ALPHA * turn_tokens + (1 - EMA_ALPHA) * self._ema_tokens_per_turn
        )

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.context_window - self.total_tokens)

    @property
    def remaining_fraction(self) -> float:
        if self.context_window == 0:
            return 0.0
        return self.remaining_tokens / self.context_window

    def estimate_remaining_turns(self) -> int:
        if self._ema_tokens_per_turn <= 0:
            return 0
        return max(0, int(self.remaining_tokens / self._ema_tokens_per_turn))

    @property
    def warning_level(self) -> str:
        frac = self.remaining_fraction
        if frac < self.critical_threshold:
            return "critical"
        if frac < self.warning_threshold:
            return "warning"
        return "normal"


@dataclass
class _RequestRecord:
    timestamp: float
    input_tokens: int


@dataclass
class RateLimitTracker:
    """Global sliding-window tracker for requests/tokens per minute."""

    rpm_limit: int = DEFAULT_RPM_LIMIT
    itpm_limit: int = DEFAULT_ITPM_LIMIT
    warning_threshold: float = RATE_LIMIT_WARNING_THRESHOLD

    _requests: list[_RequestRecord] = field(default_factory=list, init=False)

    def record_request(self, input_tokens: int = 0) -> None:
        self._requests.append(_RequestRecord(
            timestamp=time.time(),
            input_tokens=input_tokens,
        ))

    def _prune(self) -> None:
        cutoff = time.time() - 60.0
        self._requests = [r for r in self._requests if r.timestamp > cutoff]

    @property
    def current_rpm(self) -> int:
        self._prune()
        return len(self._requests)

    @property
    def current_itpm(self) -> int:
        self._prune()
        return sum(r.input_tokens for r in self._requests)

    @property
    def rpm_fraction(self) -> float:
        if self.rpm_limit == 0:
            return 0.0
        return self.current_rpm / self.rpm_limit

    @property
    def itpm_fraction(self) -> float:
        if self.itpm_limit == 0:
            return 0.0
        return self.current_itpm / self.itpm_limit

    @property
    def is_approaching_limit(self) -> bool:
        return (
            self.rpm_fraction >= self.warning_threshold
            or self.itpm_fraction >= self.warning_threshold
        )

    @property
    def warning_message(self) -> str | None:
        if not self.is_approaching_limit:
            return None
        return (
            "ExcelBot is handling a lot of requests right now. "
            "Responses may be slower for the next minute."
        )


@dataclass
class CostTracker:
    """Global in-memory tracker for estimated API cost per day."""

    daily_budget_usd: float = 5.00
    warning_threshold: float = 0.80
    sonnet_input_cost_per_m: float = 3.00
    sonnet_output_cost_per_m: float = 15.00
    opus_input_cost_per_m: float = 5.00
    opus_output_cost_per_m: float = 25.00

    _daily_cost: float = field(default=0.0, init=False)
    _last_reset_date: datetime.date = field(
        default_factory=datetime.date.today, init=False
    )
    _user_costs: dict[str, float] = field(default_factory=dict, init=False)

    def _maybe_reset_day(self) -> None:
        today = datetime.date.today()
        if today > self._last_reset_date:
            self._daily_cost = 0.0
            self._user_costs.clear()
            self._last_reset_date = today

    def _cost_rates(self, model: str) -> tuple[float, float]:
        model_lower = model.lower()
        if "opus" in model_lower:
            return self.opus_input_cost_per_m, self.opus_output_cost_per_m
        return self.sonnet_input_cost_per_m, self.sonnet_output_cost_per_m

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        user: str | None = None,
    ) -> None:
        self._maybe_reset_day()
        input_rate, output_rate = self._cost_rates(model)
        cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
        self._daily_cost += cost
        if user:
            self._user_costs[user] = self._user_costs.get(user, 0.0) + cost

    def get_user_cost(self, user: str) -> float:
        self._maybe_reset_day()
        return self._user_costs.get(user, 0.0)

    @property
    def daily_cost_usd(self) -> float:
        self._maybe_reset_day()
        return self._daily_cost

    @property
    def budget_fraction(self) -> float:
        if self.daily_budget_usd <= 0:
            return 0.0
        return self.daily_cost_usd / self.daily_budget_usd

    @property
    def is_approaching_budget(self) -> bool:
        if self.daily_budget_usd <= 0:
            return False
        return self.budget_fraction >= self.warning_threshold

    @property
    def warning_message(self) -> str | None:
        if self.daily_budget_usd <= 0:
            return None
        if not self.is_approaching_budget:
            return None
        cost = self.daily_cost_usd
        budget = self.daily_budget_usd
        if cost > budget:
            return (
                f"Today's API usage: ${cost:.2f} / ${budget:.2f} budget "
                "(over daily budget)"
            )
        return f"Today's API usage: ${cost:.2f} / ${budget:.2f} budget"


def format_usage_footer(
    thread_tracker: ThreadUsageTracker | None = None,
    rate_tracker: RateLimitTracker | None = None,
    cost_tracker: CostTracker | None = None,
) -> str:
    if thread_tracker is None and rate_tracker is None and cost_tracker is None:
        return ""

    parts: list[str] = []

    if thread_tracker is not None:
        remaining = thread_tracker.estimate_remaining_turns()
        level = thread_tracker.warning_level

        if level == "critical":
            if remaining == 0:
                parts.append(
                    "This thread is full. Please start a new thread to continue."
                )
            else:
                parts.append(
                    f"This thread is nearly full (~{remaining} questions remaining). "
                    "Consider starting a new thread."
                )
        elif level == "warning":
            parts.append(
                f"Heads up! Only ~{remaining} questions remaining "
                "before this thread's context fills up."
            )
        else:
            parts.append(f"~{remaining} questions remaining in this thread")

    if rate_tracker is not None:
        rate_msg = rate_tracker.warning_message
        if rate_msg:
            parts.append(rate_msg)

    if cost_tracker is not None:
        cost_msg = cost_tracker.warning_message
        if cost_msg:
            parts.append(cost_msg)

    if not parts:
        return ""

    return "\n\n---\n" + "\n".join(parts)
