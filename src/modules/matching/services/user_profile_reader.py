import logging
from typing import Any
from uuid import UUID

from prisma import Prisma
from src.modules.core.config.settings import get_settings
from src.modules.matching.models import UserProfileDTO

logger = logging.getLogger(__name__)

SELECT_USER_PROFILE_QUERY = """
SELECT
    user_id,
    email,
    first_name,
    last_name,
    full_name,
    date_of_birth,
    nationality,
    education_level,
    current_country,
    current_city,
    phone,
    experience_level,
    has_financial_need,
    career_goals,
    profile_photo_url,
    completion_pct,
    preferences,
    is_draft,
    skills,
    languages,
    educations,
    fields_of_study
FROM public.v_user_full_profile
WHERE user_id = $1::uuid;
"""


class UserProfileReader:
    """Read-only client for retrieving user profiles from the main database.

    Queries public.v_user_full_profile by user_id and converts the result
    into an in-memory UserProfileDTO. Does NOT persist user data locally.
    """

    def __init__(
        self,
        db: Prisma | None = None,
        database_url: str | None = None,
    ) -> None:
        self._db = db
        self._database_url = (
            database_url
            if database_url is not None
            else get_settings().profile_api_database_url
        )
        self._owns_db = db is None

    async def get_client(self) -> Prisma:
        """Returns the connected Prisma client, initializing it if needed."""
        if self._db is None:
            if not self._database_url:
                raise ValueError(
                    "PROFILE_API_DATABASE_URL is not configured and no database client was provided."
                )
            self._db = Prisma(datasource={"url": self._database_url})

        if not self._db.is_connected():
            await self._db.connect()
        return self._db

    async def close(self) -> None:
        """Disconnects the client if managed internally."""
        if self._owns_db and self._db is not None and self._db.is_connected():
            await self._db.disconnect()
            self._db = None

    async def get_profile_by_user_id(
        self, user_id: UUID | str
    ) -> UserProfileDTO | None:
        """Retrieves a user profile by UUID from public.v_user_full_profile.

        Args:
            user_id: The UUID of the user to fetch.

        Returns:
            UserProfileDTO if found, None otherwise.
        """
        if isinstance(user_id, str):
            try:
                user_uuid_str = str(UUID(user_id))
            except ValueError:
                logger.warning("Invalid UUID string provided for user_id: %s", user_id)
                return None
        else:
            user_uuid_str = str(user_id)

        client = await self.get_client()
        rows: list[dict[str, Any]] = await client.query_raw(
            SELECT_USER_PROFILE_QUERY,
            user_uuid_str,
        )

        if not rows:
            return None

        return UserProfileDTO(**rows[0])
