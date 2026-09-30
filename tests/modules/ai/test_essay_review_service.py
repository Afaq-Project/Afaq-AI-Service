import pytest

from src.modules.ai.essay_review_service import (
    EssayReviewService,
    drop_unverified_evidence,
)
from src.modules.ai.exceptions import OpportunityNotFoundError
from src.modules.ai.models import (
    EssayPoint,
    EssayReview,
    EssaySuggestion,
    LanguageIssue,
)
from src.modules.infrastructure.llm.exceptions import LLMRefusalError

from .fakes import FakeOpportunityRepository, FakeStructuredGenerator, make_opportunity

ESSAY = (
    "I have worked for three years as a software engineer in Damascus. "
    "My goal is to study public policy so I can improve digital services "
    "in my country, and this scholarship would make that possible."
)


def make_review(**overrides) -> EssayReview:
    data = {
        "overall_assessment": "Clear motivation, needs more evidence.",
        "strengths": [
            EssayPoint(
                point="Clear goal",
                evidence="My goal is to study public policy",
            )
        ],
        "weaknesses": [
            EssayPoint(point="No concrete results", evidence="led a team of 40 people"),
            EssayPoint(point="Short", evidence=None),
        ],
        "suggestions": [
            EssaySuggestion(suggestion="Add a measurable achievement", priority="high")
        ],
        "language_issues": [
            LanguageIssue(
                original="in my country",
                correction="in Syria",
                explanation="Be specific",
            )
        ],
        "fit_with_opportunity": "Good fit.",
    }
    data.update(overrides)
    return EssayReview(**data)


class TestReview:
    async def test_returns_review_and_uses_prompts(self):
        llm = FakeStructuredGenerator(output=make_review())
        service = EssayReviewService(
            llm, FakeOpportunityRepository([make_opportunity()])
        )

        review = await service.review(
            user_id="user-1",
            essay_text=ESSAY,
            essay_type="motivation_letter",
            locale="en",
            opportunity_id="opp-1",
        )

        assert review.overall_assessment.startswith("Clear motivation")
        assert review.fit_with_opportunity == "Good fit."
        call = llm.calls[0]
        assert call["output_type"] is EssayReview
        assert "Write all feedback in English" in call["system"]
        assert ESSAY in call["prompt"]
        assert "Chevening Scholarship" in call["prompt"]

    async def test_fit_is_cleared_without_opportunity(self):
        service = EssayReviewService(
            FakeStructuredGenerator(output=make_review()), FakeOpportunityRepository()
        )

        review = await service.review(
            user_id="user-1", essay_text=ESSAY, essay_type="personal_statement"
        )

        assert review.fit_with_opportunity is None

    async def test_unknown_opportunity(self):
        llm = FakeStructuredGenerator(output=make_review())
        service = EssayReviewService(llm, FakeOpportunityRepository())

        with pytest.raises(OpportunityNotFoundError):
            await service.review(
                user_id="user-1",
                essay_text=ESSAY,
                essay_type="cv",
                opportunity_id="missing",
            )
        assert llm.calls == []

    async def test_propagates_llm_errors(self):
        service = EssayReviewService(
            FakeStructuredGenerator(error=LLMRefusalError("declined")),
            FakeOpportunityRepository(),
        )

        with pytest.raises(LLMRefusalError):
            await service.review(user_id="u", essay_text=ESSAY, essay_type="other")


class TestEvidenceVerification:
    def test_keeps_real_quotes_and_drops_invented_ones(self):
        review = drop_unverified_evidence(make_review(), ESSAY)

        assert review.strengths[0].evidence == "My goal is to study public policy"
        assert review.weaknesses[0].evidence is None
        assert review.weaknesses[1].evidence is None

    def test_matching_ignores_whitespace_and_case(self):
        review = make_review(
            strengths=[EssayPoint(point="x", evidence="my  GOAL is\nto study")]
        )

        assert drop_unverified_evidence(review, ESSAY).strengths[0].evidence
