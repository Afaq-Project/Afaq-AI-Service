import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.modules.matching.models import (
    EducationDTO,
    FieldOfStudyDTO,
    LanguageDTO,
    SkillDTO,
    UserProfileDTO,
)
from src.modules.matching.services.user_profile_reader import (
    SELECT_USER_PROFILE_QUERY,
    UserProfileReader,
)


class TestUserProfileDTO:
    def test_dto_with_all_fields_populated(self):
        uid = uuid4()
        data = {
            "user_id": uid,
            "email": "user@example.com",
            "first_name": "Sarah",
            "last_name": "Connor",
            "full_name": "Sarah Connor",
            "date_of_birth": date(1995, 5, 20),
            "nationality": "Palestine",
            "education_level": "Bachelor",
            "current_country": "Jordan",
            "current_city": "Amman",
            "phone": "+962790000000",
            "experience_level": "Mid-level",
            "has_financial_need": True,
            "career_goals": "AI Research Scientist",
            "profile_photo_url": "https://example.com/photo.jpg",
            "completion_pct": 90,
            "preferences": {"remote_only": True, "preferred_countries": ["DE", "UK"]},
            "is_draft": False,
            "skills": [
                {
                    "id": str(uuid4()),
                    "name": "Python",
                    "category": "Programming",
                    "proficiency": "expert",
                },
                {
                    "id": str(uuid4()),
                    "name": "PyTorch",
                    "category": "ML",
                    "proficiency": "intermediate",
                },
            ],
            "languages": [
                {"id": str(uuid4()), "name": "Arabic", "proficiency": "native"},
                {"id": str(uuid4()), "name": "English", "proficiency": "fluent"},
            ],
            "educations": [
                {
                    "id": str(uuid4()),
                    "degree": "Bachelor of Science",
                    "major": "Computer Science",
                    "institution": "University of Jordan",
                    "graduation_year": 2018,
                    "gpa_normalized_4": 3.85,
                },
                {
                    "id": str(uuid4()),
                    "degree": "Master of Science",
                    "major": "Artificial Intelligence",
                    "institution": "Technical University of Munich",
                    "graduation_year": 2021,
                    "gpa_normalized_4": 3.92,
                },
            ],
            "fields_of_study": [
                {"id": str(uuid4()), "name": "Computer Science", "category": "STEM"},
                {"id": str(uuid4()), "name": "Data Science", "category": "STEM"},
            ],
        }

        dto = UserProfileDTO(**data)

        assert dto.user_id == uid
        assert dto.email == "user@example.com"
        assert dto.nationality == "Palestine"
        assert dto.education_level == "Bachelor"
        assert dto.completion_pct == 90
        assert dto.is_draft is False
        assert len(dto.skills) == 2
        assert isinstance(dto.skills[0], SkillDTO)
        assert dto.skills[0].name == "Python"
        assert len(dto.languages) == 2
        assert isinstance(dto.languages[0], LanguageDTO)
        assert dto.languages[1].name == "English"
        assert len(dto.educations) == 2
        assert isinstance(dto.educations[0], EducationDTO)
        assert dto.educations[0].gpa_normalized_4 == 3.85
        assert dto.educations[1].gpa_normalized_4 == 3.92
        assert len(dto.fields_of_study) == 2
        assert isinstance(dto.fields_of_study[0], FieldOfStudyDTO)
        assert dto.fields_of_study[0].name == "Computer Science"

    def test_dto_with_null_and_empty_fields_preserves_none(self):
        uid = uuid4()
        data = {
            "user_id": uid,
            "email": None,
            "first_name": None,
            "last_name": None,
            "full_name": None,
            "date_of_birth": None,
            "nationality": None,
            "education_level": None,
            "current_country": None,
            "current_city": None,
            "phone": None,
            "experience_level": None,
            "has_financial_need": None,
            "career_goals": None,
            "profile_photo_url": None,
            "completion_pct": None,
            "preferences": None,
            "is_draft": None,
            "skills": None,
            "languages": None,
            "educations": None,
            "fields_of_study": None,
        }

        dto = UserProfileDTO(**data)

        assert dto.user_id == uid
        assert dto.nationality is None
        assert dto.education_level is None
        assert dto.experience_level is None
        assert dto.completion_pct is None
        assert dto.preferences is None
        assert dto.skills == []
        assert dto.languages == []
        assert dto.educations == []
        assert dto.fields_of_study == []

    def test_dto_parses_json_string_arrays(self):
        uid = uuid4()
        skills_json = json.dumps(
            [
                {
                    "name": "FastAPI",
                    "category": "Backend",
                    "proficiency": "advanced",
                }
            ]
        )
        languages_json = json.dumps([{"name": "French", "proficiency": "intermediate"}])
        educations_json = json.dumps(
            [{"degree": "Bachelor", "major": "EE", "gpa_normalized_4": 3.5}]
        )
        fields_json = json.dumps(
            [{"name": "Electrical Engineering", "category": "Engineering"}]
        )
        preferences_json = json.dumps({"relocation": True})

        data = {
            "user_id": uid,
            "skills": skills_json,
            "languages": languages_json,
            "educations": educations_json,
            "fields_of_study": fields_json,
            "preferences": preferences_json,
        }

        dto = UserProfileDTO(**data)

        assert len(dto.skills) == 1
        assert dto.skills[0].name == "FastAPI"
        assert len(dto.languages) == 1
        assert dto.languages[0].name == "French"
        assert len(dto.educations) == 1
        assert dto.educations[0].gpa_normalized_4 == 3.5
        assert len(dto.fields_of_study) == 1
        assert dto.fields_of_study[0].name == "Electrical Engineering"
        assert dto.preferences == {"relocation": True}

    def test_dto_handles_malformed_json_strings_gracefully(self):
        uid = uuid4()
        data = {
            "user_id": uid,
            "skills": "invalid-json",
            "languages": "{not a list}",
            "educations": "12345",
            "fields_of_study": "",
            "preferences": "invalid-json-dict",
        }

        dto = UserProfileDTO(**data)
        assert dto.skills == []
        assert dto.languages == []
        assert dto.educations == []
        assert dto.fields_of_study == []
        assert dto.preferences is None


class TestUserProfileReader:
    @pytest.fixture
    def mock_prisma_client(self):
        client = MagicMock()
        client.is_connected.return_value = True
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.query_raw = AsyncMock()
        return client

    async def test_get_profile_by_user_id_success(self, mock_prisma_client):
        uid = uuid4()
        mock_row = {
            "user_id": str(uid),
            "email": "test@example.com",
            "first_name": "Ali",
            "last_name": "Ahmad",
            "full_name": "Ali Ahmad",
            "date_of_birth": date(1998, 1, 15),
            "nationality": "Egypt",
            "education_level": "Master",
            "current_country": "Egypt",
            "current_city": "Cairo",
            "phone": "+201000000000",
            "experience_level": "Entry-level",
            "has_financial_need": False,
            "career_goals": "Software Engineer",
            "profile_photo_url": None,
            "completion_pct": 100,
            "preferences": {"interested_in": "Scholarships"},
            "is_draft": False,
            "skills": [{"name": "Python", "proficiency": "advanced"}],
            "languages": [{"name": "Arabic", "proficiency": "native"}],
            "educations": [
                {
                    "degree": "Bachelor",
                    "major": "Computer Engineering",
                    "gpa_normalized_4": 3.7,
                }
            ],
            "fields_of_study": [{"name": "Engineering", "category": "STEM"}],
        }
        mock_prisma_client.query_raw.return_value = [mock_row]

        reader = UserProfileReader(db=mock_prisma_client)
        profile = await reader.get_profile_by_user_id(uid)

        assert profile is not None
        assert str(profile.user_id) == str(uid)
        assert profile.email == "test@example.com"
        assert profile.nationality == "Egypt"
        assert profile.education_level == "Master"
        assert len(profile.skills) == 1
        assert profile.skills[0].name == "Python"
        assert len(profile.educations) == 1
        assert profile.educations[0].gpa_normalized_4 == 3.7

        mock_prisma_client.query_raw.assert_awaited_once_with(
            SELECT_USER_PROFILE_QUERY, str(uid)
        )

    async def test_get_profile_by_user_id_accepts_uuid_string(self, mock_prisma_client):
        uid = uuid4()
        mock_row = {
            "user_id": str(uid),
            "email": "test@example.com",
            "skills": [],
            "languages": [],
            "educations": [],
            "fields_of_study": [],
        }
        mock_prisma_client.query_raw.return_value = [mock_row]

        reader = UserProfileReader(db=mock_prisma_client)
        profile = await reader.get_profile_by_user_id(str(uid))

        assert profile is not None
        assert str(profile.user_id) == str(uid)
        mock_prisma_client.query_raw.assert_awaited_once_with(
            SELECT_USER_PROFILE_QUERY, str(uid)
        )

    async def test_get_profile_by_user_id_returns_none_when_not_found(
        self, mock_prisma_client
    ):
        uid = uuid4()
        mock_prisma_client.query_raw.return_value = []

        reader = UserProfileReader(db=mock_prisma_client)
        profile = await reader.get_profile_by_user_id(uid)

        assert profile is None
        mock_prisma_client.query_raw.assert_awaited_once_with(
            SELECT_USER_PROFILE_QUERY, str(uid)
        )

    async def test_get_profile_by_user_id_returns_none_for_invalid_uuid_string(
        self, mock_prisma_client
    ):
        reader = UserProfileReader(db=mock_prisma_client)
        profile = await reader.get_profile_by_user_id("not-a-valid-uuid")

        assert profile is None
        mock_prisma_client.query_raw.assert_not_awaited()

    async def test_read_only_query_behavior(self, mock_prisma_client):
        uid = uuid4()
        mock_prisma_client.query_raw.return_value = []

        reader = UserProfileReader(db=mock_prisma_client)
        await reader.get_profile_by_user_id(uid)

        mock_prisma_client.query_raw.assert_awaited_once()
        # Assert query is strictly SELECT from public.v_user_full_profile
        call_args = mock_prisma_client.query_raw.call_args[0]
        query_sql = call_args[0]
        assert "SELECT" in query_sql
        assert "FROM public.v_user_full_profile" in query_sql
        assert "WHERE user_id = $1::uuid" in query_sql
        assert "INSERT" not in query_sql
        assert "UPDATE" not in query_sql
        assert "DELETE" not in query_sql
        assert "DROP" not in query_sql

    async def test_missing_database_url_raises_error(self):
        reader = UserProfileReader(db=None, database_url="")
        with pytest.raises(
            ValueError, match="PROFILE_API_DATABASE_URL is not configured"
        ):
            await reader.get_client()

    async def test_close_calls_disconnect_on_owned_client(self, mock_prisma_client):
        reader = UserProfileReader(db=None)
        reader._db = mock_prisma_client
        reader._owns_db = True

        await reader.close()
        mock_prisma_client.disconnect.assert_awaited_once()
        assert reader._db is None
