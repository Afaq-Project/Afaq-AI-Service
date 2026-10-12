from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
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
    FieldOfStudyDTO,
    UserProfileDTO,
)
from src.modules.matching.services.matching_service import MatchingService


def fake_key_info() -> ApiKeyInfo:
    return ApiKeyInfo(id="key-1", name="main-service", is_active=True)


class DummyProfileReader:
    def __init__(self, profiles: dict[str, UserProfileDTO] | None = None) -> None:
        self.profiles = profiles or {}
        self.get_profile_calls = []
        self.get_all_calls = []

    async def get_profile_by_user_id(self, user_id: str) -> UserProfileDTO | None:
        self.get_profile_calls.append(user_id)
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
        self.get_by_id_calls = []
        self.find_within_calls = 0

    async def get_cleaned_by_id(self, opp_id: str) -> dict | None:
        self.get_by_id_calls.append(opp_id)
        return self.opps.get(str(opp_id))

    async def find_within_visibility_window(self) -> list[dict]:
        self.find_within_calls += 1
        return list(self.opps.values())


class DummyMatchScoreRepo:
    def __init__(self) -> None:
        self.scores: dict[tuple[str, str], dict] = {}
        self.upsert_calls = []

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
        assert data["matches_count"] >= 1
        assert "operation_id" in data

        # Check DB persistence
        assert len(score_repo.scores) >= 1
        persisted = list(score_repo.scores.values())[0]
        assert persisted["user_id"] == user_id
        assert persisted["score_pct"] > 0
        assert "score_breakdown" in persisted

        # Check webhook notification
        assert len(webhook_client.notifications) == 1
        noti = webhook_client.notifications[0]
        assert noti.operation_type == "user_matching"
        assert noti.user_id == user_id
        assert noti.matches_count == data["matches_count"]

    def test_user_matching_does_not_trigger_full_rematch(self, test_setup):
        client = test_setup["client"]
        user_id = test_setup["user_id"]
        profile_reader = test_setup["profile_reader"]

        response = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert response.status_code == 200

        # get_profile_by_user_id called, but get_all_profiles (used for full rematch) NOT called
        assert len(profile_reader.get_profile_calls) == 1
        assert len(profile_reader.get_all_calls) == 0

    def test_user_matching_missing_user_returns_404(self, test_setup):
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

    def test_duplicate_user_matching_respects_uniqueness_contract(self, test_setup):
        client = test_setup["client"]
        user_id = test_setup["user_id"]
        score_repo = test_setup["score_repo"]

        # Run first time
        res1 = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert res1.status_code == 200
        initial_score_count = len(score_repo.scores)

        # Run second time
        res2 = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert res2.status_code == 200

        # Total unique (user_id, opp_id) entries must NOT multiply or cause duplicate key error
        assert len(score_repo.scores) == initial_score_count


class TestOpportunityMatching:
    def test_opportunity_matching_processes_only_specified_opp(self, test_setup):
        client = test_setup["client"]
        opp_id = test_setup["opp_id"]
        opp_repo = test_setup["opp_repo"]
        webhook_client = test_setup["webhook_client"]

        response = client.post(
            "/api/v1/matching/opportunity", json={"opportunity_id": opp_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["opportunity_id"] == opp_id
        assert data["users_evaluated"] >= 1
        assert data["matches_persisted"] >= 1

        # Checked that opportunity repo looked up only the specified opportunity
        assert opp_repo.get_by_id_calls == [opp_id]
        # find_within_visibility_window was NOT called (it's not scanning all opps)
        assert opp_repo.find_within_calls == 0

        # Check webhook notification
        assert len(webhook_client.notifications) == 1
        noti = webhook_client.notifications[0]
        assert noti.operation_type == "opportunity_matching"
        assert noti.opportunity_id == opp_id

    def test_opportunity_matching_missing_opp_returns_404(self, test_setup):
        client = test_setup["client"]
        missing_id = str(uuid4())

        response = client.post(
            "/api/v1/matching/opportunity", json={"opportunity_id": missing_id}
        )
        assert response.status_code == 404
        assert "Opportunity not found" in response.json()["detail"]

    def test_opportunity_matching_invalid_uuid_returns_422(self, test_setup):
        client = test_setup["client"]
        response = client.post(
            "/api/v1/matching/opportunity", json={"opportunity_id": "invalid-uuid"}
        )
        assert response.status_code == 422


class TestFullRematching:
    def test_full_rematching_returns_202_accepted(self, test_setup):
        client = test_setup["client"]
        response = client.post("/api/v1/matching/full-rematch", json={"batch_size": 50})

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "operation_id" in data

    @pytest.mark.asyncio
    async def test_full_rematching_prevents_concurrent_runs(self, test_setup):
        client = test_setup["client"]
        service = test_setup["service"]

        await service._rematch_lock.acquire()
        try:
            response = client.post(
                "/api/v1/matching/full-rematch", json={"batch_size": 100}
            )
            assert response.status_code == 409
            assert "already in progress" in response.json()["detail"]
        finally:
            service._rematch_lock.release()

    @pytest.mark.asyncio
    async def test_full_rematch_service_execution_evaluates_all(self, test_setup):
        service = test_setup["service"]
        score_repo = test_setup["score_repo"]
        webhook_client = test_setup["webhook_client"]

        result = await service.full_rematch(batch_size=10)

        assert result["status"] == "success"
        assert result["users_processed"] >= 1
        assert result["opportunities_processed"] >= 1
        assert result["matches_persisted"] >= 1
        assert len(score_repo.scores) >= 1

        assert len(webhook_client.notifications) == 1
        noti = webhook_client.notifications[0]
        assert noti.operation_type == "full_rematch"
        assert noti.matches_count == result["matches_persisted"]


class TestWebhookHandling:
    def test_webhook_failure_does_not_break_matching(self, test_setup):
        """Even if webhook client returns False or fails, the API response and DB persist succeed."""
        test_setup["webhook_client"].should_fail = True
        client = test_setup["client"]
        user_id = test_setup["user_id"]
        score_repo = test_setup["score_repo"]

        response = client.post("/api/v1/matching/user", json={"user_id": user_id})
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert len(score_repo.scores) >= 1

    @pytest.mark.asyncio
    async def test_webhook_client_handles_http_error_gracefully(self):
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
        assert success is False  # returns False without raising exception
