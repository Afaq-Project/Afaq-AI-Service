"""Tests for Matching HTTP API routes."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import get_api_key_service, get_matching_service
from src.api.routes.v1 import matching
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.matching.models import (
    CategoryScoreDTO,
    EligibilityDecision,
    FeedRankingResultDTO,
    HardFilterResultDTO,
    MatchScoreResultDTO,
    RankedOpportunityDTO,
    UserProfileDTO,
)
from src.modules.matching.services.matching_service import (
    MatchingService,
    OpportunityNotFoundError,
    UserProfileNotFoundError,
)

USER_ID = "3f1c2b4e-8d5a-4c7e-9b1f-2a6d8e0c4b7a"
OPPORTUNITY_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"


class FakeMatchingService:
    """Mock MatchingService for isolated API route testing."""

    def __init__(
        self,
        feed_result: FeedRankingResultDTO | None = None,
        score_result: MatchScoreResultDTO | None = None,
        error: Exception | None = None,
    ) -> None:
        self.feed_result = feed_result or FeedRankingResultDTO(
            user_id=USER_ID,
            ranked_opportunities=[
                RankedOpportunityDTO(
                    opportunity={
                        "id": OPPORTUNITY_ID,
                        "title": "Global Tech Scholarship",
                        "study_levels": ["Bachelor"],
                        "fields_of_study": ["Computer Science"],
                        "country": "United Kingdom",
                    },
                    match_score=MatchScoreResultDTO(
                        user_id=USER_ID,
                        opportunity_id=OPPORTUNITY_ID,
                        total_score=85.0,
                        requirements_coverage_pct=100.0,
                        category_scores=[
                            CategoryScoreDTO(
                                category="field_of_study",
                                weight=30.0,
                                score=100.0,
                                is_applicable=True,
                                reason="Field matches exactly",
                            ),
                            CategoryScoreDTO(
                                category="opportunity_requirements",
                                weight=25.0,
                                score=100.0,
                                is_applicable=True,
                                reason="Requirements matched",
                            ),
                            CategoryScoreDTO(
                                category="gpa",
                                weight=20.0,
                                score=100.0,
                                is_applicable=True,
                                reason="GPA meets requirement",
                            ),
                            CategoryScoreDTO(
                                category="language",
                                weight=15.0,
                                score=0.0,
                                is_applicable=True,
                                reason="Missing language",
                            ),
                            CategoryScoreDTO(
                                category="experience",
                                weight=10.0,
                                score=100.0,
                                is_applicable=True,
                                reason="Experience matches",
                            ),
                        ],
                        calculated_at=datetime.now(UTC).isoformat(),
                        is_preliminary=False,
                    ),
                    hard_filter_result=HardFilterResultDTO(
                        is_eligible=True,
                        decision=EligibilityDecision.ELIGIBLE,
                    ),
                    is_relaxed=False,
                )
            ],
            total_evaluated=1,
            total_eligible=1,
            is_relaxed=False,
            core_fields_complete=True,
            is_preliminary=False,
        )
        self.score_result = score_result or MatchScoreResultDTO(
            user_id=USER_ID,
            opportunity_id=OPPORTUNITY_ID,
            total_score=90.0,
            requirements_coverage_pct=100.0,
            category_scores=[],
            calculated_at=datetime.now(UTC).isoformat(),
            is_preliminary=False,
        )
        self.error = error
        self.feed_calls: list[dict] = []
        self.calc_calls: list[dict] = []

    async def get_feed_for_user(self, **kwargs) -> FeedRankingResultDTO:
        self.feed_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.feed_result

    async def calculate_match(self, **kwargs) -> MatchScoreResultDTO:
        self.calc_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.score_result


class FakeApiKeyService:
    """Mock ApiKeyService for authentication testing."""

    def __init__(self, valid_key: str = "test-api-key") -> None:
        self._valid_key = valid_key

    async def validate(self, api_key: str) -> ApiKeyInfo | None:
        if api_key == self._valid_key:
            return ApiKeyInfo(
                id="key-1",
                name="frontend-service",
                is_active=True,
            )
        return None


@pytest.fixture
def api_app() -> FastAPI:
    app = FastAPI()
    app.include_router(matching.router)
    return app


@pytest.fixture
def client(api_app: FastAPI) -> TestClient:
    api_app.dependency_overrides[get_api_key_service] = lambda: FakeApiKeyService()
    return TestClient(api_app)


# ---------------------------------------------------------------------------
# 1. Authentication & Security Tests
# ---------------------------------------------------------------------------


def test_matching_feed_rejects_missing_api_key(client: TestClient):
    """Feed endpoint returns 401 when X-API-Key header is omitted."""
    resp = client.post(f"/api/v1/matching/feed/{USER_ID}")
    assert resp.status_code == 401
    assert "Invalid or missing API key" in resp.text


def test_matching_feed_rejects_invalid_api_key(client: TestClient):
    """Feed endpoint returns 401 when X-API-Key is invalid."""
    resp = client.post(
        f"/api/v1/matching/feed/{USER_ID}",
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 401


def test_calculate_rejects_missing_api_key(client: TestClient):
    """Calculate endpoint returns 401 when X-API-Key is omitted."""
    resp = client.post(
        "/api/v1/matching/calculate",
        json={"user_id": USER_ID, "opportunity_id": OPPORTUNITY_ID},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 2. Feed Endpoint Tests
# ---------------------------------------------------------------------------


def test_matching_feed_success(api_app: FastAPI, client: TestClient):
    """Feed endpoint returns 200 OK and FeedRankingResultDTO structure."""
    fake_service = FakeMatchingService()
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    resp = client.post(
        f"/api/v1/matching/feed/{USER_ID}",
        headers={"X-API-Key": "test-api-key"},
        json={"filter_hard_eligibility": True, "enable_relaxation": True, "limit": 25},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == USER_ID
    assert data["total_evaluated"] == 1
    assert data["total_eligible"] == 1
    assert data["is_relaxed"] is False
    assert data["is_preliminary"] is False
    assert len(data["ranked_opportunities"]) == 1

    ranked = data["ranked_opportunities"][0]
    assert ranked["opportunity"]["title"] == "Global Tech Scholarship"
    assert ranked["match_score"]["total_score"] == 85.0
    assert len(ranked["match_score"]["category_scores"]) == 5


def test_matching_feed_preliminary_preservation(api_app: FastAPI, client: TestClient):
    """Feed endpoint preserves is_preliminary=True when user profile is incomplete."""
    prelim_feed = FeedRankingResultDTO(
        user_id=USER_ID,
        ranked_opportunities=[],
        total_evaluated=5,
        total_eligible=5,
        is_relaxed=False,
        core_fields_complete=False,
        is_preliminary=True,
    )
    fake_service = FakeMatchingService(feed_result=prelim_feed)
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    resp = client.post(
        f"/api/v1/matching/feed/{USER_ID}",
        headers={"X-API-Key": "test-api-key"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_preliminary"] is True
    assert data["core_fields_complete"] is False


def test_matching_feed_user_not_found(api_app: FastAPI, client: TestClient):
    """Feed endpoint returns 404 when UserProfileReader cannot find the user."""
    fake_service = FakeMatchingService(
        error=UserProfileNotFoundError(f"User {USER_ID} not found.")
    )
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    resp = client.post(
        f"/api/v1/matching/feed/{USER_ID}",
        headers={"X-API-Key": "test-api-key"},
    )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 3. Calculate Match Endpoint Tests
# ---------------------------------------------------------------------------


def test_calculate_match_by_ids(api_app: FastAPI, client: TestClient):
    """Calculate endpoint successfully computes match by user_id and opportunity_id."""
    fake_service = FakeMatchingService()
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    resp = client.post(
        "/api/v1/matching/calculate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": USER_ID, "opportunity_id": OPPORTUNITY_ID},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_score"] == 90.0
    assert data["requirements_coverage_pct"] == 100.0


def test_calculate_match_direct_payload(api_app: FastAPI, client: TestClient):
    """Calculate endpoint supports direct in-memory UserProfileDTO and Opportunity dict."""
    fake_service = FakeMatchingService()
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    payload = {
        "user_profile": {
            "user_id": USER_ID,
            "nationality": "Palestine",
            "education_level": "Bachelor",
            "fields_of_study": [{"name": "Computer Science"}],
        },
        "opportunity": {
            "id": OPPORTUNITY_ID,
            "title": "Direct Opportunity",
            "study_levels": ["Bachelor"],
            "fields_of_study": ["Computer Science"],
        },
    }

    resp = client.post(
        "/api/v1/matching/calculate",
        headers={"X-API-Key": "test-api-key"},
        json=payload,
    )

    assert resp.status_code == 200
    assert fake_service.calc_calls[0]["user_profile"] is not None
    assert fake_service.calc_calls[0]["opportunity"] is not None


def test_calculate_match_missing_user_input(api_app: FastAPI, client: TestClient):
    """Calculate endpoint returns 422 when neither user_id nor user_profile is provided."""
    fake_service = FakeMatchingService(
        error=ValueError("Either 'user_id' or 'user_profile' must be provided.")
    )
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    resp = client.post(
        "/api/v1/matching/calculate",
        headers={"X-API-Key": "test-api-key"},
        json={"opportunity_id": OPPORTUNITY_ID},
    )

    assert resp.status_code == 422


def test_calculate_match_opportunity_not_found(api_app: FastAPI, client: TestClient):
    """Calculate endpoint returns 404 when opportunity_id is not found."""
    fake_service = FakeMatchingService(
        error=OpportunityNotFoundError(f"Opportunity {OPPORTUNITY_ID} not found.")
    )
    api_app.dependency_overrides[get_matching_service] = lambda: fake_service

    resp = client.post(
        "/api/v1/matching/calculate",
        headers={"X-API-Key": "test-api-key"},
        json={"user_id": USER_ID, "opportunity_id": OPPORTUNITY_ID},
    )

    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 4. Specialization & Engine Regression Tests via Service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_specialization_workflow_preservation():
    """Demonstrates that suggested and manually entered specializations are preserved verbatim."""

    class FakeReader:
        async def get_profile_by_user_id(self, user_id):
            return UserProfileDTO(
                user_id=user_id,
                nationality="Palestine",
                education_level="Bachelor",
                fields_of_study=[
                    # Manually entered specialized string:
                    {"name": "Quantum Computing & Applied Nanotechnology"}
                ],
                educations=[],
                is_matchable=True,
            )

    class FakeRepo:
        async def find_within_visibility_window(self):
            return [
                {
                    "id": "opp-1",
                    "title": "Quantum Tech Fellowship",
                    "study_levels": ["Bachelor"],
                    "fields_of_study": ["Quantum Computing & Applied Nanotechnology"],
                }
            ]

    service = MatchingService(
        profile_reader=FakeReader(),
        opportunity_repo=FakeRepo(),
    )

    feed = await service.get_feed_for_user(user_id=UUID(USER_ID))
    assert feed.total_eligible == 1
    assert feed.ranked_opportunities[0].match_score.total_score == 100.0
    fos_score = next(
        c
        for c in feed.ranked_opportunities[0].match_score.category_scores
        if c.category == "field_of_study"
    )
    assert fos_score.score == 100.0
    assert "quantum computing & applied nanotechnology" in fos_score.reason.lower()
