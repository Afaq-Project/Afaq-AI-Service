from unittest.mock import AsyncMock, MagicMock, patch

from src.api.dependencies import get_matching_service, get_user_profile_reader
from src.modules.core.config.settings import get_settings
from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.matching.services.user_profile_reader import UserProfileReader


def test_get_user_profile_reader_defaults_to_profile_api_database_url():
    """Verifies that UserProfileReader initializes with PROFILE_API_DATABASE_URL."""
    reader = get_user_profile_reader()
    settings = get_settings()

    assert isinstance(reader, UserProfileReader)
    assert reader._owns_db is True
    assert reader._db is None
    assert reader._database_url == settings.profile_api_database_url


def test_matching_service_dependencies_database_separation():
    """Verifies that UserProfileReader is isolated from Opportunities DB Prisma client."""
    mock_opp_client = MagicMock(name="OpportunitiesPrismaClient")

    with patch("src.api.dependencies.get_client", return_value=mock_opp_client):
        service = get_matching_service()

        # 1. Opportunities & Match Score Repositories use Opportunities DB
        assert isinstance(service._opportunity_repo, OpportunityRepository)
        assert service._opportunity_repo._db is mock_opp_client

        assert isinstance(service._match_score_repo, MatchScoreRepository)
        assert service._match_score_repo._db is mock_opp_client

        # 2. UserProfileReader does NOT share Opportunities DB client
        assert isinstance(service._profile_reader, UserProfileReader)
        assert service._profile_reader._db is not mock_opp_client
        assert service._profile_reader._db is None
        assert service._profile_reader._owns_db is True
        assert (
            service._profile_reader._database_url
            == get_settings().profile_api_database_url
        )


async def test_user_profile_reader_creates_isolated_client():
    """Verifies that UserProfileReader creates a Prisma instance targeting User DB URL."""
    fake_url = "postgresql://user_test_host:5432/user_db"
    reader = UserProfileReader(database_url=fake_url)

    with patch(
        "src.modules.matching.services.user_profile_reader.Prisma"
    ) as mock_prisma_cls:
        mock_instance = MagicMock()
        mock_instance.is_connected.return_value = False
        mock_instance.connect = AsyncMock()
        mock_prisma_cls.return_value = mock_instance

        client = await reader.get_client()

        mock_prisma_cls.assert_called_once_with(datasource={"url": fake_url})
        mock_instance.connect.assert_awaited_once()
        assert client is mock_instance
