from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from src.modules.ai.constants import Locale
from src.modules.ai.models import EssayType, UserProfile

ChatText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
EssayText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=100, max_length=20000)
]


class ChatMessageRequest(BaseModel):

    user_id: UUID
    opportunity_id: UUID
    application_id: UUID | None = None
    message: ChatText
    locale: Locale = "ar"
    profile: UserProfile | None = None


class EssayReviewRequest(BaseModel):

    user_id: UUID
    essay_type: EssayType
    essay_text: EssayText
    opportunity_id: UUID | None = None
    locale: Locale = "ar"
