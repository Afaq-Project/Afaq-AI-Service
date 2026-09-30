import pytest

from src.modules.ai.constants import NO_DATA_MARKER
from src.modules.ai.eligibility import EligibilityGuard, has_eligibility_data

from .fakes import make_opportunity


@pytest.fixture
def guard() -> EligibilityGuard:
    return EligibilityGuard()


class TestEligibilityQuestionDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "هل أنا مؤهل لهذه المنحة؟",
            "هل يحق لي التقديم وأنا في سنة التخرج؟",
            "ما هي شروط القبول؟",
            "بقدر قدم إذا معدلي 3.2؟",
            "Am I eligible for this scholarship?",
            "Can I apply with a diploma?",
        ],
    )
    def test_detects_eligibility_questions(self, guard, text):
        assert guard.is_eligibility_question(text)

    @pytest.mark.parametrize(
        "text",
        [
            "متى آخر موعد للتقديم؟",
            "كيف أكتب رسالة الدافع؟",
            "What documents do I need to upload?",
        ],
    )
    def test_ignores_general_questions(self, guard, text):
        assert not guard.is_eligibility_question(text)


class TestCheckBeforeAnswer:
    def test_allows_general_question_even_without_data(self, guard):
        opportunity = make_opportunity(eligibility={}, description="")
        assert guard.check_before_answer("متى الموعد النهائي؟", opportunity) is None

    def test_allows_eligibility_question_with_data(self, guard):
        assert guard.check_before_answer("هل أنا مؤهل؟", make_opportunity()) is None

    def test_declines_when_no_eligibility_source(self, guard):
        opportunity = make_opportunity(eligibility={}, description="  ")
        assert (
            guard.check_before_answer("هل أنا مؤهل؟", opportunity)
            == "missing_eligibility_data"
        )

    def test_declines_when_opportunity_not_cleaned(self, guard):
        opportunity = make_opportunity(status="failed")
        assert (
            guard.check_before_answer("Am I eligible?", opportunity)
            == "unverified_opportunity"
        )

    def test_description_counts_as_source(self):
        assert has_eligibility_data(
            make_opportunity(eligibility=None, description="Applicants need a BSc.")
        )


class TestUnanswerable:
    def test_marker_means_unanswerable(self, guard):
        assert guard.is_unanswerable(NO_DATA_MARKER)
        assert guard.is_unanswerable(f"  {NO_DATA_MARKER}\n")

    def test_empty_answer_is_unanswerable(self, guard):
        assert guard.is_unanswerable("   ")

    def test_real_answer_is_answerable(self, guard):
        assert not guard.is_unanswerable("The deadline is 5 November 2026.")
