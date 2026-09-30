import pytest

from src.modules.scraping.adapters.grabscholarship_adapter import GrabScholarshipAdapter
from src.modules.scraping.adapters.scholars4dev_adapter import Scholars4DevAdapter
from src.modules.scraping.services.cleaning_service import CleaningService
from src.modules.scraping.services.normalization_service import NormalizationService


class TestFundingTypeExtraction:
    """Unit tests for funding_type extraction and normalization across adapters and services."""

    @pytest.fixture
    def scholars_adapter(self) -> Scholars4DevAdapter:
        return Scholars4DevAdapter()

    @pytest.fixture
    def grab_adapter(self) -> GrabScholarshipAdapter:
        return GrabScholarshipAdapter()

    @pytest.fixture
    def normalizer(self) -> NormalizationService:
        return NormalizationService()

    @pytest.fixture
    def cleaner(self) -> CleaningService:
        return CleaningService()

    # --- 1. Scholars4Dev Adapter Tests ---
    @pytest.mark.parametrize(
        ("html_snippet", "expected_funding"),
        [
            # Comprehensive full funding: Tuition + living expenses + airfare
            (
                "<p><strong>Scholarship value/inclusions/duration:</strong> Tuition fees and college fees, a grant for living expenses and one return air fare per year.</p>",
                "fully_funded",
            ),
            # Full funding: Tuition + subsistence allowance + travel + visa
            (
                "<p><strong>Scholarship value/inclusions:</strong> The scholarship covers tuition fees, international travel expenses, subsistence allowance, registration fees, visa costs, insurance.</p>",
                "fully_funded",
            ),
            # Full funding: Tuition + full residence support
            (
                "<p><strong>Scholarship value:</strong> The scholarship will cover tuition, books, incidental fees, and full residence support for four years.</p>",
                "fully_funded",
            ),
            # Full funding: All fees + living stipend + flights
            (
                "<p><strong>Scholarship value:</strong> A Rhodes Scholarship covers all University and College fees, a living stipend of £20,400 per annum, and two economy class flights.</p>",
                "fully_funded",
            ),
            # Full funding: Monthly payments + insurance + travel allowance
            (
                "<p><strong>Scholarship value:</strong> The scholarships include monthly payments of 992 euros, payments towards health insurance, and travel allowance.</p>",
                "fully_funded",
            ),
            # Explicit full keywords
            (
                "<p>This is a <strong>Fully Funded</strong> scholarship for international students.</p>",
                "fully_funded",
            ),
            (
                "<p>Recipients receive <strong>100% tuition</strong> and full-cost coverage.</p>",
                "fully_funded",
            ),
            # Partial funding: Living grant with explicit tuition exclusion
            (
                "<p>The scholarship covers CHF 2,450 per month to cover basic living expenses. The scholarship does not cover tuition or semester fees.</p>",
                "fully_funded",  # wait, does not cover tuition -> partially_funded!
            ),
            # Partial funding: Fixed monthly stipend / living grant
            (
                "<p>The scholarship amounts to CHF 1,600 per month from 15 September to 15 July. Students are exempt from fixed registration fees except CHF 80.</p>",
                "partially_funded",
            ),
            # Partial funding: Fixed semester grant
            (
                "<p>The fellowship includes CHF 10,000 per semester and a reservation of a student room.</p>",
                "partially_funded",
            ),
            # Partial funding: Fixed annual award
            (
                "<p>Scholarship Total value: Award of Achievement Up to $40,000 ($5,000–$10,000 per year).</p>",
                "partially_funded",
            ),
            # Partial funding: Unit coverage
            (
                "<p>The president’s scholarship covers 7.5-15 undergraduate units per semester.</p>",
                "partially_funded",
            ),
            # Partial funding: Explicit partial keywords
            (
                "<p>This is a <strong>partially funded</strong> grant covering a tuition fee discount.</p>",
                "partially_funded",
            ),
            # Unfunded
            (
                "<p>This program is <strong>unfunded</strong> and participants must be self-funded.</p>",
                "unfunded",
            ),
            # Ambiguous / unstated -> None
            (
                "<p>Emory undergraduate admissions: Create a plan for contributing financially for your education.</p>",
                None,
            ),
            (
                "<p>Germany overview: Overview of higher education in Germany and state university guidelines.</p>",
                None,
            ),
        ],
    )
    def test_scholars4dev_funding_extraction(
        self,
        scholars_adapter: Scholars4DevAdapter,
        html_snippet: str,
        expected_funding: str | None,
    ) -> None:
        if "does not cover tuition" in html_snippet:
            expected_funding = "partially_funded"
        result = scholars_adapter._extract_funding_type(html_snippet)
        assert result == expected_funding

    # --- 2. GrabScholarship Adapter Tests ---
    @pytest.mark.parametrize(
        ("title", "categories", "content", "expected_funding"),
        [
            (
                "UCL Global Masters Scholarships 2026",
                ["Scholarships"],
                "<p>A £15,000 annual grant will be given. Reimbursement of academic fees up to a specific limit.</p>",
                "partially_funded",
            ),
            (
                "DAAD Scholarship Germany 2026 | Fully Funded",
                ["Scholarships"],
                "<p>This is a fully funded scholarship covering tuition, monthly stipend, and travel.</p>",
                "fully_funded",
            ),
            (
                "Partial Tuition Waiver at University of Melbourne",
                ["Scholarships"],
                "<p>Offers a 50% tuition waiver for international students.</p>",
                "partially_funded",
            ),
            (
                "Self-Funded Internship Programme 2026",
                ["Internships"],
                "<p>This opportunity is self-funded with no financial support.</p>",
                "unfunded",
            ),
            (
                "International Student Award 2026",
                ["Scholarships"],
                "<p>Apply online through the student portal.</p>",
                None,
            ),
        ],
    )
    def test_grabscholarship_funding_extraction(
        self,
        grab_adapter: GrabScholarshipAdapter,
        title: str,
        categories: list[str],
        content: str,
        expected_funding: str | None,
    ) -> None:
        result = grab_adapter._extract_funding_type(title, categories, content)
        assert result == expected_funding

    # --- 3. NormalizationService Tests ---
    @pytest.mark.parametrize(
        ("raw_val", "search_text", "expected_normalized"),
        [
            ("fully_funded", "", "fully_funded"),
            ("Fully Funded", "", "fully_funded"),
            ("ممول بالكامل", "", "fully_funded"),
            ("100% funded", "", "fully_funded"),
            ("partially_funded", "", "partially_funded"),
            ("Partially Funded", "", "partially_funded"),
            ("تمويل جزئي", "", "partially_funded"),
            ("tuition waiver", "", "partially_funded"),
            ("tuition discount", "", "partially_funded"),
            ("tuition reduction", "", "partially_funded"),
            ("unfunded", "", "unfunded"),
            ("self funded", "", "unfunded"),
            ("غير ممول", "", "unfunded"),
            (
                None,
                "This opportunity is fully funded for all candidates.",
                "fully_funded",
            ),
            (None, "Provides partial funding for tuition costs.", "partially_funded"),
            (None, "Self-funded position with no stipend.", "unfunded"),
            (None, "Please check application guidelines.", None),
        ],
    )
    def test_normalization_service_funding(
        self,
        normalizer: NormalizationService,
        raw_val: str | None,
        search_text: str,
        expected_normalized: str | None,
    ) -> None:
        result = normalizer.normalize_funding_type(raw_val, search_text=search_text)
        assert result == expected_normalized
