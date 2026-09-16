from uuid import uuid4

from src.modules.matching.models import (
    EducationDTO,
    FieldOfStudyDTO,
    LanguageDTO,
    SkillDTO,
    UserProfileDTO,
)


def create_dummy_profile() -> UserProfileDTO:
    return UserProfileDTO(
        user_id=uuid4(),
        email="dummy@example.com",
        first_name="Test",
        last_name="User",
        full_name="Test User",
        nationality="Palestine",
        education_level="Bachelor",
        current_country="Palestine",
        current_city="Gaza",
        experience_level="Intermediate",
        has_financial_need=True,
        career_goals="Data Science and AI",
        completion_pct=90,
        preferences={"interests": ["Data Science", "Artificial Intelligence"]},
        is_draft=False,
        skills=[
            SkillDTO(
                id=uuid4(),
                name="Python",
                category="Programming",
                proficiency="Advanced",
            ),
            SkillDTO(
                id=uuid4(),
                name="SQL",
                category="Database",
                proficiency="Intermediate",
            ),
            SkillDTO(
                id=uuid4(),
                name="Power BI",
                category="Data Analysis",
                proficiency="Intermediate",
            ),
        ],
        languages=[
            LanguageDTO(
                id=uuid4(),
                name="Arabic",
                proficiency="Native",
            ),
            LanguageDTO(
                id=uuid4(),
                name="English",
                proficiency="Upper Intermediate",
            ),
        ],
        educations=[
            EducationDTO(
                id=uuid4(),
                degree="Bachelor",
                major="Data Science",
                institution="Test University",
                graduation_year=2027,
                gpa_normalized_4=3.5,
            )
        ],
        fields_of_study=[
            FieldOfStudyDTO(
                id=uuid4(),
                name="Computer Science",
                category="Technology",
            ),
            FieldOfStudyDTO(
                id=uuid4(),
                name="Data Science",
                category="Technology",
            ),
        ],
    )


def test_dummy_profile():
    profile = create_dummy_profile()

    assert profile.nationality == "Palestine"
    assert profile.education_level == "Bachelor"
    assert profile.experience_level == "Intermediate"
    assert profile.completion_pct == 90

    assert len(profile.skills) == 3
    assert len(profile.languages) == 2
    assert len(profile.educations) == 1
    assert len(profile.fields_of_study) == 2

    assert profile.skills[0].name == "Python"
    assert profile.educations[0].degree == "Bachelor"
    assert profile.educations[0].gpa_normalized_4 == 3.5
