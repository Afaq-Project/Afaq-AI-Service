"""
Declarative Scraping Templates Module for Afaq.

Provides template specifications, schema validators, runtime validators,
change detection engine, LLM abstraction, and Gemini template generation pipeline.
"""

from .change_detector import (
    ChangeDetectionResult,
    ChangeDetectionStatus,
    PageFetchResult,
    TemplateChangeDetector,
    TemplateMetrics,
)
from .llm_provider import (
    BaseLLMProvider,
    GeminiLLMProvider,
    LLMGenerationError,
    LLMTimeoutError,
    MockLLMProvider,
)
from .template_contract import (
    ExtractionTemplateSchema,
    TemplateRuntimeValidator,
    TemplateSchemaValidator,
    TemplateValidationResult,
)
from .template_generator import (
    CandidateStatus,
    CandidateTemplateResult,
    GeminiTemplateGenerator,
)

__all__ = [
    "ExtractionTemplateSchema",
    "TemplateSchemaValidator",
    "TemplateRuntimeValidator",
    "TemplateValidationResult",
    "TemplateChangeDetector",
    "ChangeDetectionStatus",
    "ChangeDetectionResult",
    "TemplateMetrics",
    "PageFetchResult",
    "BaseLLMProvider",
    "GeminiLLMProvider",
    "MockLLMProvider",
    "LLMGenerationError",
    "LLMTimeoutError",
    "GeminiTemplateGenerator",
    "CandidateStatus",
    "CandidateTemplateResult",
]
