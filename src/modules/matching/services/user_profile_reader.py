import logging
from typing import Any
from uuid import UUID

from prisma import Prisma
from src.modules.core.config.settings import get_settings
from src.modules.matching.models import UserProfileDTO

logger = logging.getLogger(__name__)

SELECT_USER_PROFILE_QUERY = """
SELECT
    u.id AS user_id,
    u.email::text AS email,
    COALESCE(p.first_name, u.first_name) AS first_name,
    COALESCE(p.last_name, u.last_name) AS last_name,
    TRIM(CONCAT(COALESCE(p.first_name, u.first_name), ' ', COALESCE(p.last_name, u.last_name))) AS full_name,
    p.date_of_birth,
    COALESCE(nat.nationality_name_en, nat.name_en) AS nationality,
    el.name_en AS education_level,
    c_res.name_en AS current_country,
    city.name_en AS current_city,
    p.phone,
    NULL::text AS experience_level,
    NULL::boolean AS has_financial_need,
    p.bio AS career_goals,
    p.profile_photo_url,
    COALESCE(p.completion_pct, 0) AS completion_pct,
    COALESCE(p.is_matchable, false) AS is_matchable,
    '{}'::jsonb AS preferences,
    false AS is_draft,
    '[]'::jsonb AS skills,
    COALESCE(p.experiences, ARRAY[]::text[]) AS experiences,
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', ul.language_id,
                'name', lm.name_en,
                'proficiency', CASE WHEN ul.is_native THEN 'Native' ELSE COALESCE(pl.name_en, 'Intermediate') END
            )
        )
        FROM public.user_languages ul
        JOIN public.languages_master lm ON lm.id = ul.language_id
        LEFT JOIN public.proficiency_levels pl ON pl.id = ul.proficiency_level_id
        WHERE ul.user_id = u.id
    ), '[]'::jsonb) AS languages,
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', ue.id,
                'degree', edl.name_en,
                'major', m.name_en,
                'institution', inst.name_en,
                'gpa_normalized_4', ue.gpa_normalized::float,
                'graduation_year', EXTRACT(YEAR FROM COALESCE(ue.end_date, ue.expected_graduation_date))::int
            )
        )
        FROM public.user_educations ue
        JOIN public.majors m ON m.id = ue.major_id
        LEFT JOIN public.education_levels edl ON edl.id = ue.education_level_id
        LEFT JOIN public.institutions inst ON inst.id = ue.institution_id
        WHERE ue.user_id = u.id
    ), '[]'::jsonb) AS educations,
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'id', utm.major_id,
                'name', tm.name_en,
                'category', mc.name_en
            )
        )
        FROM public.user_target_majors utm
        JOIN public.majors tm ON tm.id = utm.major_id
        LEFT JOIN public.major_categories mc ON mc.id = tm.category_id
        WHERE utm.user_id = u.id
    ), '[]'::jsonb) AS fields_of_study
FROM public.users u
LEFT JOIN public.user_profiles p ON p.user_id = u.id
LEFT JOIN public.countries nat ON nat.id = p.nationality_id
LEFT JOIN public.education_levels el ON el.id = p.education_level_id
LEFT JOIN public.countries c_res ON c_res.id = p.country_of_residence_id
LEFT JOIN public.cities city ON city.id = p.current_city_id
WHERE u.id = $1::uuid;
"""


class UserProfileReader:
    """Read-only client for retrieving user profiles from the main database.

    Queries public user tables by user_id and converts the result
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
        try:
            rows: list[dict[str, Any]] = await client.query_raw(
                SELECT_USER_PROFILE_QUERY,
                user_uuid_str,
            )
        except Exception as exc:
            logger.error("Failed to query user profile for %s: %s", user_uuid_str, exc)
            return None

        if not rows:
            return None

        return UserProfileDTO(**rows[0])
