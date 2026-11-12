# [OMA-W006-T007] Public facade for DiscoveryService package

from .onboarding import DiscoveryService
from .prompts import (
    DETAIL_TEMPLATE_SYSTEM_PROMPT,
    DISCOVERY_SYSTEM_PROMPT,
    escape_untrusted_content,
    package_untrusted_prompt,
)
from .relevance_gate import (
    DetailTemplateDiscoveryOutput,
    PlatformDiscoveryOutput,
)
from .skeletonizer import (
    NOISE_TAGS,
    PRESERVED_ATTRIBUTES,
    skeletonize_dom,
)

__all__ = [
    "DiscoveryService",
    "PlatformDiscoveryOutput",
    "DetailTemplateDiscoveryOutput",
    "DISCOVERY_SYSTEM_PROMPT",
    "DETAIL_TEMPLATE_SYSTEM_PROMPT",
    "NOISE_TAGS",
    "PRESERVED_ATTRIBUTES",
    "skeletonize_dom",
    "escape_untrusted_content",
    "package_untrusted_prompt",
]
