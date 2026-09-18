from src.modules.ai.constants import NO_DATA_MARKER, decline_message, disclaimer_for
from src.modules.ai.context import (
    NOT_PROVIDED,
    build_opportunity_context,
    build_profile_context,
)
from src.modules.ai.models import LanguageSkill, UserProfile
from src.modules.ai.prompts import (
    build_chat_system_prompt,
    build_essay_review_prompt,
    build_essay_review_system_prompt,
)

from .fakes import make_opportunity


class TestOpportunityContext:
    def test_renders_known_fields(self):
        context = build_opportunity_context(make_opportunity())

        assert "Title: Chevening Scholarship" in context
        assert "Deadline: 2026-11-05" in context
        assert "Study levels: Master" in context
        assert '"min_experience_years": 2' in context

    def test_marks_missing_fields(self):
        context = build_opportunity_context(
            make_opportunity(eligibility={}, organization=None, description=None)
        )

        assert f"Organization: {NOT_PROVIDED}" in context
        assert f"Eligibility: {NOT_PROVIDED}" in context
        assert f"Description:\n{NOT_PROVIDED}" in context

    def test_output_is_stable(self):
        opportunity = make_opportunity(eligibility={"b": 1, "a": 2})
        assert build_opportunity_context(opportunity) == build_opportunity_context(
            opportunity
        )


class TestProfileContext:
    def test_without_profile(self):
        assert build_profile_context(None) == "No profile was provided."

    def test_renders_profile(self):
        profile = UserProfile(
            nationality="Syria",
            gpa=3.4,
            languages=[LanguageSkill(name="English", level="B2")],
            has_financial_need=True,
        )
        context = build_profile_context(profile)

        assert "Nationality: Syria" in context
        assert "Gpa: 3.4" in context
        assert "Languages: English (B2)" in context
        assert "Has financial need: yes" in context


class TestChatPrompt:
    def test_contains_rules_and_context(self):
        prompt = build_chat_system_prompt(make_opportunity(), None, "ar")

        assert NO_DATA_MARKER in prompt
        assert "Reply in Arabic" in prompt
        assert "<opportunity>" in prompt and "</opportunity>" in prompt
        assert "<student_profile>" in prompt

    def test_english_locale(self):
        prompt = build_chat_system_prompt(make_opportunity(), None, "en")
        assert "Reply in English" in prompt


class TestEssayPrompts:
    def test_system_prompt_language(self):
        assert "Write all feedback in English" in build_essay_review_system_prompt("en")

    def test_prompt_without_opportunity(self):
        prompt = build_essay_review_prompt("My essay text", "motivation_letter")

        assert "Document type: motivation letter" in prompt
        assert "<document>\nMy essay text\n</document>" in prompt
        assert "<opportunity>" not in prompt

    def test_prompt_with_opportunity(self):
        prompt = build_essay_review_prompt("text", "cv", make_opportunity())
        assert "<opportunity>" in prompt


class TestMessages:
    def test_disclaimer_defaults_to_arabic(self):
        assert disclaimer_for("fr") == disclaimer_for("ar")

    def test_decline_message_includes_source(self):
        message = decline_message("en", "https://example.org/apply")
        assert "https://example.org/apply" in message

    def test_decline_message_without_source(self):
        assert "الجهة المانحة" in decline_message("ar", None)
