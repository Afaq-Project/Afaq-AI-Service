from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.matching.models import CategoryScoreDTO, MatchScoreResultDTO
from src.modules.matching.services.matching_service import MatchingService


@pytest.fixture
def mock_prisma_client():
    client = MagicMock()
    client.matchscore = MagicMock()
    client.matchscore.upsert = AsyncMock()
    client.matchscore.find_unique = AsyncMock()
    client.matchscore.find_many = AsyncMock()
    return client


def test_prepare_upsert_payload():
    repo = MatchScoreRepository(db=MagicMock())
    user_id = uuid4()
    opportunity_id = uuid4()

    category_scores = [
        CategoryScoreDTO(
            category="field_of_study",
            weight=30.0,
            score=100.0,
            is_applicable=True,
            reason="Match",
        ),
        CategoryScoreDTO(
            category="gpa",
            weight=20.0,
            score=75.0,
            is_applicable=True,
            reason="Above min",
        ),
    ]
    match_score = MatchScoreResultDTO(
        user_id=str(user_id),
        opportunity_id=str(opportunity_id),
        total_score=87.5,
        category_scores=category_scores,
        calculated_at="2026-10-01T12:00:00+00:00",
    )

    payload = repo.prepare_upsert_payload(
        user_id=user_id,
        opportunity_id=opportunity_id,
        match_score=match_score,
        calculation_version=1,
    )

    assert payload["where"]["user_id_opportunity_id"]["user_id"] == str(user_id)
    assert payload["where"]["user_id_opportunity_id"]["opportunity_id"] == str(
        opportunity_id
    )

    create_data = payload["data"]["create"]
    assert create_data["user_id"] == str(user_id)
    assert create_data["opportunity_id"] == str(opportunity_id)
    assert create_data["score_pct"] == 88  # 87.5 rounded to 88
    assert create_data["calculation_version"] == 1
    assert isinstance(create_data["calculated_at"], datetime)
    assert len(create_data["score_breakdown"].data) == 2

    update_data = payload["data"]["update"]
    assert update_data["score_pct"] == 88
    assert update_data["calculation_version"] == 1


async def test_save_match_score(mock_prisma_client):
    repo = MatchScoreRepository(db=mock_prisma_client)
    user_id = str(uuid4())
    opp_id = str(uuid4())

    match_score = MatchScoreResultDTO(
        user_id=user_id,
        opportunity_id=opp_id,
        total_score=92.0,
        category_scores=[],
    )

    mock_prisma_client.matchscore.upsert.return_value = {"id": str(uuid4())}

    result = await repo.save_match_score(
        user_id=user_id,
        opportunity_id=opp_id,
        match_score=match_score,
    )

    assert result is not None
    mock_prisma_client.matchscore.upsert.assert_awaited_once()


async def test_find_by_user_and_opportunity(mock_prisma_client):
    repo = MatchScoreRepository(db=mock_prisma_client)
    user_id = str(uuid4())
    opp_id = str(uuid4())

    mock_prisma_client.matchscore.find_unique.return_value = {
        "user_id": user_id,
        "opportunity_id": opp_id,
        "score_pct": 85,
    }

    result = await repo.find_by_user_and_opportunity(user_id, opp_id)

    assert result is not None
    assert result["score_pct"] == 85
    mock_prisma_client.matchscore.find_unique.assert_awaited_once_with(
        where={
            "user_id_opportunity_id": {
                "user_id": user_id,
                "opportunity_id": opp_id,
            }
        }
    )


async def test_find_by_user_id(mock_prisma_client):
    repo = MatchScoreRepository(db=mock_prisma_client)
    user_id = str(uuid4())

    mock_prisma_client.matchscore.find_many.return_value = [
        {"score_pct": 95},
        {"score_pct": 80},
    ]

    results = await repo.find_by_user_id(user_id, limit=50)

    assert len(results) == 2
    mock_prisma_client.matchscore.find_many.assert_awaited_once_with(
        where={"user_id": user_id},
        order={"score_pct": "desc"},
        take=50,
    )


async def test_matching_service_persist_match_score():
    mock_profile_reader = MagicMock()
    mock_opp_repo = MagicMock()
    mock_match_score_repo = MagicMock()
    mock_match_score_repo.save_match_score = AsyncMock(return_value={"saved": True})

    service = MatchingService(
        profile_reader=mock_profile_reader,
        opportunity_repo=mock_opp_repo,
        match_score_repo=mock_match_score_repo,
    )

    user_id = str(uuid4())
    opp_id = str(uuid4())
    match_score = MatchScoreResultDTO(
        user_id=user_id,
        opportunity_id=opp_id,
        total_score=80.0,
        category_scores=[],
    )

    res = await service.persist_match_score(user_id, opp_id, match_score)
    assert res == {"saved": True}
    mock_match_score_repo.save_match_score.assert_awaited_once_with(
        user_id=user_id,
        opportunity_id=opp_id,
        match_score=match_score,
        calculation_version=1,
    )
