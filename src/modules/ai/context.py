import json
from datetime import datetime
from typing import Any

from .models import UserProfile

NOT_PROVIDED = "not provided"


def _display(value: Any) -> str:
    if value is None or value == "" or value == [] or value == {}:
        return NOT_PROVIDED
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, list | tuple):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).strip()


def build_opportunity_context(opportunity: Any) -> str:
    fields = [
        ("Title", opportunity.title),
        ("Organization", opportunity.organization),
        ("Type", opportunity.opportunity_type),
        ("Country", opportunity.country),
        ("Location", opportunity.location),
        ("Remote", opportunity.is_remote),
        ("Funding", opportunity.funding_type),
        ("Deadline", opportunity.deadline),
        ("Study levels", opportunity.study_levels),
        ("Fields of study", opportunity.fields_of_study),
        ("Eligibility", opportunity.eligibility),
        ("Application URL", opportunity.application_url),
        ("Source URL", opportunity.source_url),
    ]
    lines = [f"{label}: {_display(value)}" for label, value in fields]
    description = (opportunity.description or "").strip()
    lines.append(f"Description:\n{description or NOT_PROVIDED}")
    return "\n".join(lines)


def build_profile_context(profile: UserProfile | None) -> str:
    if profile is None:
        return "No profile was provided."

    data = profile.model_dump(exclude_none=True)
    languages = data.pop("languages", [])
    lines = [
        f"{key.replace('_', ' ').capitalize()}: {_display(value)}"
        for key, value in data.items()
        if value not in ([], "")
    ]
    if languages:
        rendered = ", ".join(
            f"{lang['name']} ({lang['level']})" if lang.get("level") else lang["name"]
            for lang in languages
        )
        lines.append(f"Languages: {rendered}")

    return "\n".join(lines) if lines else "No profile was provided."
