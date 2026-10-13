"""Tests for Matching HTTP API routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_api_key_service,
    get_matching_service,
    get_matching_webhook_client,
    require_api_key,
)
from src.api.routes.v1 import matching
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.infrastructure.http.exceptions import HttpClientError
from src.modules.infrastructure.webhook.webhook_client import (
    MatchingCompletePayload,
    WebhookClient,
)
from src.modules.matching.models import (
    CategoryScoreDTO,
    EligibilityDecision,
    FeedRankingResultDTO,
    FieldOfStudyDTO,
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


def fake_key_info() -> ApiKeyInfo:
    return ApiKeyInfo(id="key-1", name="main-service", is_active=True)


class DummyProfileReader:
    def __init__(self, profiles: dict[str, UserProfileDTO] | None = None) -> None:
        self.profiles = profiles or {}
        self.get_profile_calls: list[str] = []
        self.get_all_calls: list[dict] = []

    async def get_profile_by_user_id(
        self, user_id: str | UUID
    ) -> UserProfileDTO | None:
        self.get_profile_calls.append(str(user_id))
        return self.profiles.get(str(user_id))

    async def get_all_profiles(
        self, limit: int = 100, offset: int = 0
    ) -> list[UserProfileDTO]:
        self.get_all_calls.append({"limit": limit, "offset": offset})
        all_profs = list(self.profiles.values())
        return all_profs[offset : offset + limit]


class DummyOpportunityRepo:
    def __init__(self, opps: dict[str, dict] | None = None) -> None:
        self.opps = opps or {}
        self.get_by_id_calls: list[str] = []
        self.find_within_calls = 0

    async def get_cleaned_by_id(self, opp_id: str | UUID) -> dict | None:
        self.get_by_id_calls.append(str(opp_id))
        return self.opps.get(str(opp_id))

    async def find_within_visibility_window(self) -> list[dict]:
        self.find_within_calls += 1
        return list(self.opps.values())


class DummyMatchScoreRepo:
    def __init__(self) -> None:
        self.scores: dict[tuple[str, str], dict] = {}
        self.upsert_calls: list[dict] = []

    async def upsert_score(
        self,
        user_id: str,
        opportunity_id: str,
        score_pct: int,
        score_breakdown: dict | None = None,
        calculation_version: int = 1,
    ) -> dict:
        key = (user_id, opportunity_id)
        rec = {
            "user_id": user_id,
            "opportunity_id": opportunity_id,
            "score_pct": score_pct,
            "score_breakdown": score_breakdown or {},
            "calculation_version": calculation_version,
            "updated_at": datetime.now(UTC),
        }
        self.scores[key] = rec
        self.upsert_calls.append(rec)
        return rec

    async def upsert_many_scores(self, scores: list[dict]) -> int:
        for s in scores:
            await self.upsert_score(
                user_id=s["user_id"],
                opportunity_id=s["opportunity_id"],
                score_pct=s["score_pct"],
                score_breakdown=s.get("score_breakdown"),
                calculation_version=s.get("calculation_version", 1),
            )
        return len(scores)


class DummyWebhookClient:
    def __init__(self, should_fail: bool = False, timeout: bool = False) -> None:
        self.should_fail = should_fail
        self.timeout = timeout
        self.notifications: list[MatchingCompletePayload] = []

    async def notify_matching_complete(self, payload: MatchingCompletePayload) -> bool:
        if self.timeout:
            return False
        if self.should_fail:
            return False
        self.notifications.append(payload)
        return True


@pytest.fixture
def sample_user_id() -> str:
    return str(uuid4())


@pytest.fixture
def sample_opp_id() -> str:
    return str(uuid4())


@pytest.fixture
def sample_user_profile(sample_user_id) -> UserProfileDTO:
    return UserProfileDTO(
        user_id=sample_user_id,
        first_name="Nada",
        nationality="Palestine",
        education_level="Bachelor",
        is_matchable=True,
        completion_pct=100,
        fields_of_study=[FieldOfStudyDTO(name="Computer Science")],
        experiences=["Software Engineer"],
    )


@pytest.fixture
def sample_opportunity(sample_opp_id) -> dict:
    return {
        "id": sample_opp_id,
        "title": "Master of AI Fellowship",
        "study_levels": ["Master"],
        "fields_of_study": ["Computer Science"],
        "deadline": datetime(2027, 1, 1, tzinfo=UTC),
    }


@pytest.fixture
def test_setup(sample_user_id, sample_user_profile, sample_opp_id, sample_opportunity):
    profile_reader = DummyProfileReader({sample_user_id: sample_user_profile})
    opp_repo = DummyOpportunityRepo({sample_opp_id: sample_opportunity})
    score_repo = DummyMatchScoreRepo()
    webhook_client = DummyWebhookClient()

    service = MatchingService(
        profile_reader=profile_reader,
        opportunity_repo=opp_repo,
        match_score_repo=score_repo,
        webhook_client=webhook_client,
    )

    app = FastAPI()
    app.include_router(matching.router)
    app.dependency_overrides[get_api_key_service] = lambda: FakeApiKeyService(
        valid_key="test-api-key"
    )
    app.dependency_overrides[require_api_key] = fake_key_info
    app.dependency_overrides[get_matching_service] = lambda: service
    app.dependency_overrides[get_matching_webhook_client] = lambda: webhook_client

    client = TestClient(app)

    return {
        "app": app,
        "client": client,
        "service": service,
        "profile_reader": profile_reader,
        "opp_repo": opp_repo,
        "score_repo": score_repo,
        "webhook_client": webhook_client,
        "user_id": sample_user_id,
        "opp_id": sample_opp_id,
    }


class TestUserMatching:
    def test_user_matching_invokes_engine_and_persists(self, test_setup):
        client = test_setup["client"]
        user_id = test_setup["user_id"]
        score_repo = test_setup["score_repo"]
        webhook_client = test_setup["webhook_client"]

        response = client.post("/api/v1/matching/user", json={"user_id": user_id})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["user_id"] == user_id
        assert "operation_id" in data
        assert data["matches_count"] >= 0
        assert data["total_evaluated"] >= 0
        assert data["message"] == "User matching completed successfully."

        assert len(score_repo.upsert_calls) == data["matches_count"]
        assert len(webhook_client.notifications) == 1
        notif = webhook_client.notifications[0]
        assert notif.operation_type == "user_matching"
        assert notif.user_id == user_id

    def test_user_matching_missing_profile_returns_404(self, test_setup):
        client = test_setup["client"]
        non_existent_id = str(uuid4())

        response = client.post(
            "/api/v1/matching/user", json={"user_id": non_existent_id}
        )
        assert response.status_code == 404
        assert "User profile not found" in response.json()["detail"]

    def test_user_matching_invalid_uuid_returns_422(self, test_setup):
        client = test_setup["client"]
        response = client.post(
            "/api/v1/matching/user", json={"user_id": "not-a-valid-uuid"}
        )
        assert response.status_code == 422

    def test_user_matching_unauthorized(self, test_setup):
        app = test_setup["app"]
        app.dependency_overrides.pop(require_api_key, None)
        client = TestClient(app)

        response = client.post("/api/v1/matching/user", json={"user_id": str(uuid4())})
        assert response.status_code == 401


class TestOpportunityMatching:
    def test_opportunity_matching_invokes_engine_and_persists(self, test_setup):
        client = test_setup["client"]
        opp_id = test_setup["opp_id"]
        score_repo = test_setup["score_repo"]
        webhook_client = test_setup["webhook_client"]

        response = client.post(
            "/api/v1/matching/opportunity", json={"opportunity_id": opp_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["opportunity_id"] == opp_id
        assert data["users_evaluated"] >= 1
        assert "operation_id" in data
        assert data["message"] == "Opportunity matching completed successfully."

        assert len(score_repo.upsert_calls) == data["matches_persisted"]
        assert len(webhook_client.notifications) == 1
        notif = webhook_client.notifications[0]
        assert notif.operation_type == "opportunity_matching"
        assert notif.opportunity_id == opp_id

    def test_opportunity_matching_missing_returns_404(self, test_setup):
        client = test_setup["client"]
        non_existent_id = str(uuid4())

        response = client.post(
            "/api/v1/matching/opportunity",
            json={"opportunity_id": non_existent_id},
        )
        assert response.status_code == 404
        assert "Opportunity not found" in response.json()["detail"]

    def test_opportunity_matching_outside_visibility_skipped(self, test_setup):
        client = test_setup["client"]
        opp_repo = test_setup["opp_repo"]
        expired_opp_id = str(uuid4())
        opp_repo.opps[expired_opp_id] = {
            "id": expired_opp_id,
            "title": "Expired Fellowship",
            "deadline": datetime(2020, 1, 1, tzinfo=UTC),
        }

        response = client.post(
            "/api/v1/matching/opportunity",
            json={"opportunity_id": expired_opp_id},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "skipped"
        assert data["matches_persisted"] == 0

    def test_opportunity_matching_unauthorized(self, test_setup):
        app = test_setup["app"]
        app.dependency_overrides.pop(require_api_key, None)
        client = TestClient(app)

        response = client.post(
            "/api/v1/matching/opportunity",
            json={"opportunity_id": str(uuid4())},
        )
        assert response.status_code == 401


class TestFullRematch:
    def test_full_rematch_triggers_background_and_accepts(self, test_setup):
        client = test_setup["client"]
        webhook_client = test_setup["webhook_client"]

        response = client.post("/api/v1/matching/full-rematch", json={"batch_size": 50})

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "operation_id" in data
        assert "Full rematch operation started" in data["message"]

        assert len(webhook_client.notifications) == 1
        notif = webhook_client.notifications[0]
        assert notif.operation_type == "full_rematch"

    def test_full_rematch_duplicate_returns_409(self, test_setup):
        client = test_setup["client"]
        service = test_setup["service"]

        async def lock_and_test():
            await service._rematch_lock.acquire()
            try:
                resp = client.post(
                    "/api/v1/matching/full-rematch", json={"batch_size": 50}
                )
                assert resp.status_code == 409
                assert "already in progress" in resp.json()["detail"]
            finally:
                service._rematch_lock.release()

        import asyncio

        asyncio.run(lock_and_test())

    def test_full_rematch_unauthorized(self, test_setup):
        app = test_setup["app"]
        app.dependency_overrides.pop(require_api_key, None)
        client = TestClient(app)

        response = client.post("/api/v1/matching/full-rematch", json={})
        assert response.status_code == 401


class TestPersistenceAndIdempotency:
    def test_repeated_matches_upsert_cleanly(self, test_setup):
        client = test_setup["client"]
        user_id = test_setup["user_id"]
        score_repo = test_setup["score_repo"]

        resp1 = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert resp1.status_code == 200
        count1 = len(score_repo.scores)

        resp2 = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert resp2.status_code == 200
        count2 = len(score_repo.scores)

        assert count1 == count2


class TestWebhookDelivery:
    def test_webhook_failure_does_not_fail_matching(self, test_setup):
        client = test_setup["client"]
        webhook_client = test_setup["webhook_client"]
        webhook_client.should_fail = True
        user_id = test_setup["user_id"]

        response = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    @pytest.mark.asyncio
    async def test_direct_webhook_client_delivery_failure(self):
        """Direct test of WebhookClient with HttpClientError."""
        mock_http = AsyncMock()
        mock_http.post.side_effect = HttpClientError("Connection refused")

        client = WebhookClient(
            webhook_url="http://example.com/webhook",
            secret="test-secret",
            http_client=mock_http,
        )

        payload = MatchingCompletePayload(
            operation_type="user_matching",
            operation_id="op-1",
            user_id="user-1",
            matches_count=5,
        )

        success = await client.notify_matching_complete(payload)
        assert success is False


# ---------------------------------------------------------------------------
# Feed & Calculate Route Tests (From origin/main)
# ---------------------------------------------------------------------------

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
