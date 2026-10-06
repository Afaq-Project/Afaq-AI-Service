"""
Gemini Template Generator Service for Afaq GenericTemplateAdapter.

Generates candidate extraction templates from HTML samples using LLM providers (Gemini),
and enforces a strict 3-gate validation pipeline (Schema -> Runtime -> Quality)
before marking a candidate as ACCEPTED_FOR_REVIEW.

IMPORTANT: This module never mutates, overwrites, or activates active templates automatically.
"""

from __future__ import annotations

import json
import logging
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.scraping.templates.change_detector import (
    ChangeDetectionResult,
    PageFetchResult,
    TemplateChangeDetector,
    TemplateMetrics,
)
from src.modules.scraping.templates.llm_provider import (
    BaseLLMProvider,
    GeminiLLMProvider,
    LLMGenerationError,
    LLMTimeoutError,
)
from src.modules.scraping.templates.template_contract import (
    TemplateRuntimeValidator,
    TemplateSchemaValidator,
)

logger = logging.getLogger(__name__)


class CandidateStatus(StrEnum):
    """Lifecycle status for a generated candidate extraction template."""

    ACCEPTED_FOR_REVIEW = "ACCEPTED_FOR_REVIEW"
    REJECTED = "REJECTED"


class CandidateTemplateResult(BaseModel):
    """Encapsulates the full result and diagnostic evaluation of a candidate template."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    status: CandidateStatus
    valid: bool = False
    candidate_template: dict[str, Any] | None = None
    gate_failed: int | None = None  # 1 (Schema), 2 (Runtime), or 3 (Quality)
    rejection_reason: str | None = None
    quality_score: float = 0.0
    runtime_metrics: TemplateMetrics | None = None
    change_detection_result: ChangeDetectionResult | None = None
    comparison_with_current: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generation_metadata: dict[str, Any] = Field(default_factory=dict)


SYSTEM_PROMPT_TEMPLATE = """You are an expert web scraping and HTML structural analysis AI assistant.
Your task is to generate a declarative JSON extraction template for a scholarship website based on provided HTML samples.

Strict Rules:
1. Return ONLY valid JSON matching the ExtractionTemplateSchema v1.0. Do NOT include any markdown prose, explanation, or text outside the JSON object.
2. The JSON schema must strictly conform to:
   - "$schema_version": "1.0"
   - "source_name": string (alphanumeric, hyphens, or underscores)
   - "display_name": string (human readable name)
   - "base_url": string (starting with http:// or https://)
   - "detail_rules": object containing "fields", "section_rules" (optional), and "taxonomy_rules" (optional)
   - "listing_rules": object containing "card_selector" and "fields" (optional if only detail page provided)
3. For detail_rules fields:
   - Required fields: "title" (required=true), "application_url" (required=true if present as link).
   - Optional fields: "description", "eligibility_text", "funding_details", "deadline", "country", "organization", "degree_level", "benefits".
   - Field rule object format: {"selector": "CSS_SELECTOR", "extract": "text"|"html"|"href"|"src"|"attr:<attr>", "required": boolean}
4. Selectors must be robust and specific CSS selectors present in the provided HTML. Do NOT invent selectors that do not exist.
5. Do NOT hallucinate data, scholarships, or field values not found in the HTML.
6. If a reference current template is provided, use it as a structural guide, but fix any outdated or broken selectors.
"""


class GeminiTemplateGenerator:
    """
    Orchestrates candidate extraction template generation and 3-gate validation pipeline.
    """

    def __init__(
        self,
        llm_provider: BaseLLMProvider | None = None,
        change_detector: TemplateChangeDetector | None = None,
        min_detail_samples: int = 1,
        quality_score_threshold: float = 0.75,
    ) -> None:
        self.llm_provider = llm_provider or GeminiLLMProvider()
        self.change_detector = change_detector or TemplateChangeDetector(
            min_detail_samples=min_detail_samples,
            quality_score_threshold=quality_score_threshold,
        )
        self.min_detail_samples = min_detail_samples
        self.quality_score_threshold = quality_score_threshold

    def build_prompt(
        self,
        detail_fetches: list[PageFetchResult],
        listing_fetches: list[PageFetchResult] | None = None,
        current_template: dict[str, Any] | None = None,
        source_name: str = "generic_source",
        base_url: str = "",
        failed_fields: list[str] | None = None,
    ) -> tuple[str, str]:
        """Constructs system instruction and user prompt containing HTML samples and context."""
        listing_fetches = listing_fetches or []

        prompt_parts: list[str] = [
            f"Target Source Name: {source_name}",
            f"Target Base URL: {base_url}",
        ]

        if failed_fields:
            prompt_parts.append(
                f"Failed / Degraded Fields to Fix: {', '.join(failed_fields)}"
            )

        if current_template:
            prompt_parts.append("\n--- CURRENT TEMPLATE (FOR REFERENCE ONLY) ---")
            prompt_parts.append(json.dumps(current_template, indent=2))

        # Add Detail HTML samples (safely truncated if very large)
        for i, fetch in enumerate(detail_fetches, 1):
            html_content = fetch.html or ""
            # Truncate HTML body if > 15KB per sample to prevent prompt token overflow
            truncated_html = (
                html_content[:15000] if len(html_content) > 15000 else html_content
            )
            prompt_parts.append(f"\n--- DETAIL HTML SAMPLE #{i} ({fetch.url}) ---")
            prompt_parts.append(truncated_html)

        # Add Listing HTML samples if present
        for i, fetch in enumerate(listing_fetches, 1):
            html_content = fetch.html or ""
            truncated_html = (
                html_content[:15000] if len(html_content) > 15000 else html_content
            )
            prompt_parts.append(f"\n--- LISTING HTML SAMPLE #{i} ({fetch.url}) ---")
            prompt_parts.append(truncated_html)

        prompt_parts.append(
            "\nPlease analyze the HTML samples above and generate the candidate JSON template."
        )

        user_prompt = "\n".join(prompt_parts)
        return SYSTEM_PROMPT_TEMPLATE, user_prompt

    async def generate_candidate(
        self,
        detail_fetches: list[PageFetchResult],
        listing_fetches: list[PageFetchResult] | None = None,
        current_template: dict[str, Any] | None = None,
        source_name: str = "generic_source",
        base_url: str = "",
        baseline_score: float | None = None,
        failed_fields: list[str] | None = None,
    ) -> CandidateTemplateResult:
        """
        Executes LLM candidate generation and passes candidate through 3 validation gates:
        Gate 1: Static Schema Validation
        Gate 2: Runtime Execution Validation against real HTML samples
        Gate 3: Quality Evaluation & Comparison against current template / thresholds
        """
        detail_fetches = detail_fetches or []
        listing_fetches = listing_fetches or []

        # Step 0: Check HTML sample sufficiency
        valid_detail = [
            f for f in detail_fetches if f.success and f.html and f.html.strip()
        ]
        valid_listing = [
            f for f in listing_fetches if f.success and f.html and f.html.strip()
        ]

        if len(valid_detail) < self.min_detail_samples and not valid_listing:
            reason = (
                f"Insufficient HTML samples: detail samples ({len(valid_detail)}) "
                f"and listing samples ({len(valid_listing)}) below minimum required. Generation skipped."
            )
            logger.warning(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                rejection_reason=reason,
                errors=[reason],
            )

        # Step 1: Build prompt & call LLM provider
        system_inst, user_prompt = self.build_prompt(
            detail_fetches=valid_detail,
            listing_fetches=valid_listing,
            current_template=current_template,
            source_name=source_name,
            base_url=base_url,
            failed_fields=failed_fields,
        )

        try:
            llm_response = await self.llm_provider.generate(
                prompt=user_prompt, system_instruction=system_inst
            )
        except (LLMTimeoutError, LLMGenerationError, Exception) as exc:
            reason = f"LLM generation failed: {exc}"
            logger.error(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                rejection_reason=reason,
                errors=[reason],
            )

        # Step 2: Clean and parse JSON response
        candidate_dict: dict[str, Any]
        try:
            cleaned_text = llm_response.strip()
            if cleaned_text.startswith("```"):
                # Strip markdown fence if present
                cleaned_text = re.sub(r"^```(?:json)?\n", "", cleaned_text)
                cleaned_text = re.sub(r"\n```$", "", cleaned_text).strip()
            candidate_dict = json.loads(cleaned_text)
        except Exception as exc:
            reason = f"Gate 1 Failed: Malformed JSON returned by LLM: {exc}"
            logger.warning(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                gate_failed=1,
                rejection_reason=reason,
                errors=[reason],
                generation_metadata={"raw_llm_response": llm_response[:500]},
            )

        # Ensure source_name and base_url are fallback populated if missing
        if "source_name" not in candidate_dict or not candidate_dict["source_name"]:
            candidate_dict["source_name"] = source_name
        if "base_url" not in candidate_dict or not candidate_dict["base_url"]:
            candidate_dict["base_url"] = base_url

        # ---------------------------------------------------------------------
        # Gate 1: Static Schema Validation
        # ---------------------------------------------------------------------
        static_res = TemplateSchemaValidator.validate(candidate_dict)
        if not static_res.valid:
            error_msgs = [e.message for e in static_res.errors]
            reason = f"Gate 1 Failed: Static schema validation errors: {'; '.join(error_msgs)}"
            logger.warning(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                candidate_template=candidate_dict,
                gate_failed=1,
                rejection_reason=reason,
                errors=error_msgs,
                warnings=[w.message for w in static_res.warnings],
            )

        # ---------------------------------------------------------------------
        # Gate 2: Runtime Execution Validation
        # ---------------------------------------------------------------------
        runtime_errors: list[str] = []
        runtime_warnings: list[str] = []

        # Validate on Detail HTML samples
        for fetch in valid_detail:
            d_res = TemplateRuntimeValidator.validate_detail(
                candidate_dict, fetch.html or "", source_url=fetch.url or ""
            )
            if not d_res.valid:
                for err in d_res.errors:
                    runtime_errors.append(
                        f"Detail runtime error on {fetch.url}: {err.message}"
                    )
            for warn in d_res.warnings:
                runtime_warnings.append(
                    f"Detail runtime warning on {fetch.url}: {warn.message}"
                )

        # Validate on Listing HTML samples if listing_rules present in candidate
        if candidate_dict.get("listing_rules") and valid_listing:
            for fetch in valid_listing:
                l_res = TemplateRuntimeValidator.validate_listing(
                    candidate_dict, fetch.html or ""
                )
                if not l_res.valid:
                    for err in l_res.errors:
                        runtime_errors.append(
                            f"Listing runtime error on {fetch.url}: {err.message}"
                        )

        if runtime_errors:
            reason = f"Gate 2 Failed: Runtime execution validation failed: {'; '.join(runtime_errors)}"
            logger.warning(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                candidate_template=candidate_dict,
                gate_failed=2,
                rejection_reason=reason,
                errors=runtime_errors,
                warnings=runtime_warnings,
            )

        # ---------------------------------------------------------------------
        # Gate 3: Quality Evaluation & Comparison on Identical HTML Samples
        # ---------------------------------------------------------------------
        candidate_eval = self.change_detector.evaluate(
            template_input=candidate_dict,
            detail_fetches=valid_detail,
            listing_fetches=valid_listing,
            baseline_score=baseline_score,
        )

        comparison_meta: dict[str, Any] = {
            "candidate_quality_score": candidate_eval.quality_score,
            "candidate_status": candidate_eval.status.value,
        }

        # Evaluate Current Template on IDENTICAL HTML samples if provided
        current_eval: ChangeDetectionResult | None = None
        if current_template:
            current_eval = self.change_detector.evaluate(
                template_input=current_template,
                detail_fetches=valid_detail,
                listing_fetches=valid_listing,
            )
            comparison_meta["current_quality_score"] = current_eval.quality_score
            comparison_meta["current_status"] = current_eval.status.value
            comparison_meta["score_improvement"] = round(
                candidate_eval.quality_score - current_eval.quality_score, 4
            )

        # Check candidate quality score threshold
        if candidate_eval.quality_score < self.quality_score_threshold:
            reason = (
                f"Gate 3 Failed: Candidate quality score ({candidate_eval.quality_score:.2f}) "
                f"is below required threshold ({self.quality_score_threshold:.2f})."
            )
            logger.warning(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                candidate_template=candidate_dict,
                gate_failed=3,
                rejection_reason=reason,
                quality_score=candidate_eval.quality_score,
                runtime_metrics=candidate_eval.metrics,
                change_detection_result=candidate_eval,
                comparison_with_current=comparison_meta,
                errors=[reason] + candidate_eval.errors,
                warnings=candidate_eval.warnings,
            )

        # Check quality vs Current Template (candidate must be equal or better than current)
        if (
            current_eval
            and current_eval.valid
            and candidate_eval.quality_score < current_eval.quality_score
        ):
            reason = (
                f"Gate 3 Failed: Candidate quality score ({candidate_eval.quality_score:.2f}) "
                f"is lower than current active template quality score ({current_eval.quality_score:.2f})."
            )
            logger.warning(reason)
            return CandidateTemplateResult(
                source_name=source_name,
                status=CandidateStatus.REJECTED,
                valid=False,
                candidate_template=candidate_dict,
                gate_failed=3,
                rejection_reason=reason,
                quality_score=candidate_eval.quality_score,
                runtime_metrics=candidate_eval.metrics,
                change_detection_result=candidate_eval,
                comparison_with_current=comparison_meta,
                errors=[reason],
                warnings=candidate_eval.warnings,
            )

        # ---------------------------------------------------------------------
        # All 3 Gates Passed -> Candidate Ready for Human Review
        # ---------------------------------------------------------------------
        logger.info(
            "Candidate template for '%s' passed all 3 validation gates with quality score %.2f",
            source_name,
            candidate_eval.quality_score,
        )

        return CandidateTemplateResult(
            source_name=source_name,
            status=CandidateStatus.ACCEPTED_FOR_REVIEW,
            valid=True,
            candidate_template=candidate_dict,
            gate_failed=None,
            rejection_reason=None,
            quality_score=candidate_eval.quality_score,
            runtime_metrics=candidate_eval.metrics,
            change_detection_result=candidate_eval,
            comparison_with_current=comparison_meta,
            errors=[],
            warnings=candidate_eval.warnings,
        )
