from typing import Literal

Locale = Literal["ar", "en"]

NO_DATA_MARKER = "INSUFFICIENT_DATA"

DISCLAIMERS: dict[str, str] = {
    "ar": "هذا التوجيه مقدم للمساعدة فقط ولا يضمن قبول طلبك أو أي نتيجة.",
    "en": "This guidance is for assistance only and does not guarantee acceptance or any outcome.",
}

DECLINE_WITH_SOURCE: dict[str, str] = {
    "ar": (
        "لا تتوفر لدينا معلومات موثوقة كافية للإجابة عن هذا السؤال بدقة. "
        "يرجى مراجعة المصدر الرسمي للفرصة: {url}"
    ),
    "en": (
        "We don't have reliable enough information to answer this accurately. "
        "Please check the official source of the opportunity: {url}"
    ),
}

DECLINE_WITHOUT_SOURCE: dict[str, str] = {
    "ar": (
        "لا تتوفر لدينا معلومات موثوقة كافية للإجابة عن هذا السؤال بدقة. "
        "يرجى التواصل مع الجهة المانحة مباشرة."
    ),
    "en": (
        "We don't have reliable enough information to answer this accurately. "
        "Please contact the provider directly."
    ),
}

BLOCKED_MESSAGE: dict[str, str] = {
    "ar": "لا يمكن معالجة هذه الرسالة. يرجى إعادة صياغة سؤالك حول الفرصة.",
    "en": "This message can't be processed. Please rephrase your question about the opportunity.",
}

ERROR_MESSAGES: dict[str, str] = {
    "ai_timeout": "استغرق المساعد وقتاً أطول من المتوقع. حاول مرة أخرى بعد قليل.",
    "ai_busy": "المساعد يستقبل طلبات كثيرة حالياً. حاول مرة أخرى بعد قليل.",
    "ai_unavailable": "المساعد غير متاح حالياً. حاول مرة أخرى لاحقاً.",
    "ai_refused": "تعذر معالجة هذا الطلب. حاول إعادة صياغته.",
    "ai_incomplete": "لم يكتمل رد المساعد. حاول مرة أخرى.",
    "ai_error": "حدث خطأ غير متوقع في المساعد. حاول مرة أخرى لاحقاً.",
    "opportunity_not_found": "الفرصة المطلوبة غير موجودة.",
}


def disclaimer_for(locale: str) -> str:
    return DISCLAIMERS.get(locale, DISCLAIMERS["ar"])


def decline_message(locale: str, source_url: str | None) -> str:
    if source_url:
        template = DECLINE_WITH_SOURCE.get(locale, DECLINE_WITH_SOURCE["ar"])
        return template.format(url=source_url)
    return DECLINE_WITHOUT_SOURCE.get(locale, DECLINE_WITHOUT_SOURCE["ar"])


def blocked_message(locale: str) -> str:
    return BLOCKED_MESSAGE.get(locale, BLOCKED_MESSAGE["ar"])
