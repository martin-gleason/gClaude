from src.claude.models import get_model, is_complex_question


class TestGetModel:
    def test_returns_default(self):
        assert get_model("claude-sonnet-4-5-20250929") == "claude-sonnet-4-5-20250929"

    def test_returns_custom(self):
        assert get_model("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


class TestIsComplexQuestion:
    def test_forecasting_detected_as_complex(self):
        assert is_complex_question(
            "Build a 12-month revenue forecast with seasonal adjustments"
        ) is True

    def test_financial_modeling_detected_as_complex(self):
        assert is_complex_question(
            "Calculate NPV and IRR for this investment"
        ) is True

    def test_project_management_detected_as_complex(self):
        assert is_complex_question(
            "Create a Gantt chart formula with task dependencies and milestones"
        ) is True

    def test_array_formulas_detected_as_complex(self):
        assert is_complex_question(
            "Write a LAMBDA that recursively calculates amortization"
        ) is True

    def test_simple_vlookup_not_complex(self):
        assert is_complex_question("How do I use VLOOKUP?") is False

    def test_basic_sum_not_complex(self):
        assert is_complex_question("What's the SUM formula?") is False

    def test_sensitivity_analysis_detected(self):
        assert is_complex_question(
            "Build a sensitivity table for interest rate scenarios"
        ) is True

    def test_mixed_case_keywords_detected(self):
        assert is_complex_question(
            "Help me with FORECASTING quarterly sales"
        ) is True
