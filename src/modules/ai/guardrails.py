from functools import lru_cache
from typing import Any

from wardhook.guardrails import InjectionDetector, PIIRedactor
from wardhook.guardrails.injection import SignalCategory

ARABIC_INJECTION_SIGNALS = (
    SignalCategory(
        name="instruction_override_ar",
        weight=0.6,
        description="Arabic attempts to discard prior instructions.",
        patterns=(
            r"(?:تجاهل|تجاهلي|انس|انسى|إنس|اترك|الغ|ألغ)\s+(?:كل\s+|جميع\s+)?(?:ال)?(?:تعليمات|أوامر|اوامر|قواعد|توجيهات|قيود)",
            r"(?:ال)?(?:تعليمات|أوامر|اوامر|قواعد)\s+(?:ال)?(?:سابقة|قديمة|اللي\s+فوق|أعلاه|اعلاه)\s+(?:لم\s+تعد|ما\s+عادت|ملغية|ملغاة)",
            r"تعليمات\s+جديدة\s*:",
        ),
    ),
    SignalCategory(
        name="role_hijack_ar",
        weight=0.55,
        description="Arabic attempts to reassign the assistant's role or rules.",
        patterns=(
            r"(?:تصرف|تصرفي|تظاهر|تخيل)\s+(?:ك|أنك|انك|بأنك|بانك)\s*\S*\s*(?:بدون|بلا|من\s+غير|دون)\s+(?:قيود|حدود|رقابة)",
            r"(?:أنت|انت)\s+(?:الآن|الان|هلق|هلأ)\s+(?:لست|مش|ما\s+عدت)\s+(?:مساعد|ملزم|مقيد)",
            r"من\s+(?:الآن|الان|هلق|هلأ)\s+(?:وصاعدا\s+|فصاعدا\s+)?(?:أنت|انت|ستكون|رح\s+تكون)\s+(?!مساعد)",
        ),
    ),
    SignalCategory(
        name="system_probe_ar",
        weight=0.5,
        description="Arabic attempts to extract the system prompt.",
        patterns=(
            r"(?:اعرض|اكشف|اطبع|أظهر|اظهر|أعطني|اعطني|ورجيني|وريني|انسخ)\s+(?:لي\s+)?(?:ال)?(?:تعليمات|برومبت|موجه|أوامر|اوامر)\s+(?:ال)?(?:نظام|سرية|مخفية|أصلية|اصلية|تبعك|الخاصة\s+بك)",
            r"(?:ما|شو)\s+(?:هي\s+)?(?:ال)?(?:تعليمات|برومبت)\s+(?:اللي\s+|التي\s+)?(?:أعطيت|اعطيت|انعطيت|عندك|تبعك)",
        ),
    ),
)


@lru_cache
def build_chat_guardrails() -> tuple[Any, ...]:
    return (
        InjectionDetector(extra_signals=ARABIC_INJECTION_SIGNALS),
        PIIRedactor(pack="default", on_stages=("input",), exclude=("PHONE",)),
    )
