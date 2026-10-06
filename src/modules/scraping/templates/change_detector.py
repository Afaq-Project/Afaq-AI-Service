"""
Template Change Detection Engine for Afaq GenericTemplateAdapter.

Evaluates extraction template validity, network reliability, sample sufficiency,
structural DOM changes, and extraction quality metrics against HTML samples
and baseline scores.
"""

from __future__ import annotations

import json
import logging
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from src.modules.scraping.templates.template_contract import (
    TemplateSchemaValidator,
)

logger = logging.getLogger(__name__)


class ChangeDetectionStatus(str, Enum):
    """Classification outcomes for template evaluation."""

    VALID = "VALID"
    INVALID_TEMPLATE = "INVALID_TEMPLATE"
    NETWORK_ERROR = "NETWORK_ERROR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STRUCTURE_CHANGED = "STRUCTURE_CHANGED"
    EXTRACTION_DEGRADED = "EXTRACTION_DEGRADED"


class PageFetchResult(BaseModel):
    """Container for page retrieval outcome metadata."""

    model_config = ConfigDict(extra="forbid")

    url: str = ""
    success: bool = True
    status_code: int | None = 200
    error_type: str | None = (
        None  # e.g. "timeout", "http_403", "http_500", "network_error", "empty_body"
    )
    error_message: str | None = None
    html: str | None = None


class TemplateMetrics(BaseModel):
    """Calculated numeric extraction quality metrics."""

    model_config = ConfigDict(extra="forbid")

    required_field_success_rate: float = 0.0
    optional_field_coverage_rate: float = 0.0
    valid_url_format_rate: float = 1.0
    content_completeness_rate: float = 0.0
    overall_quality_score: float = 0.0
    baseline_degradation: float | None = (
        None  # Relative degradation drop ratio if baseline exists
    )


class ChangeDetectionResult(BaseModel):
    """Complete diagnostic result of template change detection evaluation."""

    model_config = ConfigDict(extra="forbid")

    source_name: str
    status: ChangeDetectionStatus
    valid: bool
    quality_score: float
    metrics: TemplateMetrics
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    detail_samples_evaluated: int = 0
    listing_samples_evaluated: int = 0
    sample_extracted_data: dict[str, Any] = Field(default_factory=dict)


class TemplateChangeDetector:
    """
    Evaluates whether an extraction template is still valid against a website's
    current HTML structure or if site changes / quality degradation occurred.
    """

    def __init__(
        self,
        min_detail_samples: int = 1,
        min_listing_samples: int = 0,
        quality_score_threshold: float = 0.75,
        optional_coverage_threshold: float = 0.50,
        degradation_threshold: float = 0.20,
    ) -> None:
        self.min_detail_samples = min_detail_samples
        self.min_listing_samples = min_listing_samples
        self.quality_score_threshold = quality_score_threshold
        self.optional_coverage_threshold = optional_coverage_threshold
        self.degradation_threshold = degradation_threshold

    def evaluate(
        self,
        template_input: dict[str, Any] | str | Path,
        detail_fetches: list[PageFetchResult] | None = None,
        listing_fetches: list[PageFetchResult] | None = None,
        baseline_score: float | None = None,
    ) -> ChangeDetectionResult:
        """
        Evaluates a template against page fetch results using an unambiguous priority decision order:
        1. INVALID_TEMPLATE: If static schema validation fails.
        2. NETWORK_ERROR: If page fetches failed due to timeouts, HTTP errors, or network blocks.
        3. INSUFFICIENT_DATA: If valid HTML sample count < configured minimum required.
        4. STRUCTURE_CHANGED: If DOM selectors for required fields fail to extract valid data.
        5. EXTRACTION_DEGRADED: If optional field coverage, overall score, or baseline drop triggers.
        6. VALID: If all checks pass.
        """
        detail_fetches = detail_fetches or []
        listing_fetches = listing_fetches or []

        # Extract raw dict for source_name
        template_dict: dict[str, Any] = {}
        if isinstance(template_input, (str, Path)):
            raw_path = Path(template_input)
            if raw_path.is_file():
                try:
                    with open(raw_path, encoding="utf-8") as f:
                        template_dict = json.load(f)
                except Exception:
                    pass
            else:
                try:
                    template_dict = json.loads(str(template_input))
                except Exception:
                    pass
        elif isinstance(template_input, dict):
            template_dict = template_input

        source_name = template_dict.get("source_name") or "unknown_source"

        # ---------------------------------------------------------------------
        # Step 1: Static Schema Validation Check
        # ---------------------------------------------------------------------
        static_res = TemplateSchemaValidator.validate(template_input)
        if not static_res.valid:
            error_msgs = [e.message for e in static_res.errors]
            return ChangeDetectionResult(
                source_name=source_name,
                status=ChangeDetectionStatus.INVALID_TEMPLATE,
                valid=False,
                quality_score=0.0,
                metrics=TemplateMetrics(),
                errors=[f"Static schema validation failed: {m}" for m in error_msgs],
                warnings=[w.message for w in static_res.warnings],
            )

        # ---------------------------------------------------------------------
        # Step 2: Separate Network Retrieval Check
        # ---------------------------------------------------------------------
        all_fetches = detail_fetches + listing_fetches
        network_errors: list[str] = []
        for fetch in all_fetches:
            if (
                not fetch.success
                or fetch.error_type
                or (fetch.html is None or not fetch.html.strip())
            ):
                err_desc = (
                    fetch.error_message
                    or fetch.error_type
                    or f"HTTP {fetch.status_code}"
                )
                network_errors.append(
                    f"Fetch failed for {fetch.url or 'sample'}: {err_desc}"
                )

        if (
            network_errors
            and len(network_errors) == len(all_fetches)
            and len(all_fetches) > 0
        ):
            return ChangeDetectionResult(
                source_name=source_name,
                status=ChangeDetectionStatus.NETWORK_ERROR,
                valid=False,
                quality_score=0.0,
                metrics=TemplateMetrics(),
                errors=network_errors,
                warnings=[
                    "All attempts to retrieve page samples encountered network or HTTP errors."
                ],
            )

        # ---------------------------------------------------------------------
        # Step 3: Sample Size Sufficiency Check
        # ---------------------------------------------------------------------
        valid_detail_fetches = [
            f for f in detail_fetches if f.success and f.html and f.html.strip()
        ]
        valid_listing_fetches = [
            f for f in listing_fetches if f.success and f.html and f.html.strip()
        ]

        requires_detail = bool(template_dict.get("detail_rules"))
        requires_listing = bool(template_dict.get("listing_rules"))

        insufficient_reasons: list[str] = []
        if requires_detail and len(valid_detail_fetches) < self.min_detail_samples:
            insufficient_reasons.append(
                f"Detail samples ({len(valid_detail_fetches)}) below required minimum ({self.min_detail_samples})."
            )

        if requires_listing and len(valid_listing_fetches) < self.min_listing_samples:
            insufficient_reasons.append(
                f"Listing samples ({len(valid_listing_fetches)}) below required minimum ({self.min_listing_samples})."
            )

        if insufficient_reasons:
            return ChangeDetectionResult(
                source_name=source_name,
                status=ChangeDetectionStatus.INSUFFICIENT_DATA,
                valid=False,
                quality_score=0.0,
                metrics=TemplateMetrics(),
                errors=insufficient_reasons,
                warnings=network_errors,
                detail_samples_evaluated=len(valid_detail_fetches),
                listing_samples_evaluated=len(valid_listing_fetches),
            )

        # ---------------------------------------------------------------------
        # Step 4: Execute Extractions and Measure Quality Metrics
        # ---------------------------------------------------------------------
        from src.modules.scraping.adapters.generic_template_adapter import (
            GenericTemplateAdapter,
        )

        adapter = GenericTemplateAdapter(template=template_dict)

        detail_field_rules = template_dict.get("detail_rules", {}).get("fields", {})
        required_fields = [
            fn for fn, r in detail_field_rules.items() if r.get("required", False)
        ]
        optional_fields = [
            fn for fn, r in detail_field_rules.items() if not r.get("required", False)
        ]

        total_req_evaluations = 0
        successful_req_extractions = 0

        total_opt_evaluations = 0
        successful_opt_extractions = 0

        extracted_urls: list[str] = []
        extracted_text_values: list[str] = []

        detection_errors: list[str] = []
        detection_warnings: list[str] = []

        last_extracted_data: dict[str, Any] = {}

        # Process Detail Pages
        for fetch in valid_detail_fetches:
            html = fetch.html or ""
            source_url = fetch.url or "https://example.com"
            try:
                extracted = adapter.extract_from_detail_html(
                    html, source_url=source_url
                )
                last_extracted_data = extracted

                # Check required fields
                for req_fn in required_fields:
                    total_req_evaluations += 1
                    val = extracted.get(req_fn)
                    if val is not None and (not isinstance(val, str) or val.strip()):
                        successful_req_extractions += 1
                    else:
                        detection_errors.append(
                            f"Required detail field '{req_fn}' extracted empty or None on {source_url}."
                        )

                # Check optional fields
                for opt_fn in optional_fields:
                    total_opt_evaluations += 1
                    val = extracted.get(opt_fn)
                    if val is not None and (not isinstance(val, str) or val.strip()):
                        successful_opt_extractions += 1
                    else:
                        detection_warnings.append(
                            f"Optional detail field '{opt_fn}' missing on {source_url}."
                        )

                # Collect URL format checks
                for url_key in ("application_url", "source_url"):
                    u_val = extracted.get(url_key)
                    if u_val and isinstance(u_val, str):
                        extracted_urls.append(u_val)

                # Collect text completeness checks
                for txt_key in (
                    "title",
                    "description",
                    "eligibility_text",
                    "funding_details",
                ):
                    t_val = extracted.get(txt_key)
                    if t_val and isinstance(t_val, str):
                        extracted_text_values.append(t_val)

            except Exception as exc:
                if required_fields:
                    for _ in required_fields:
                        total_req_evaluations += 1
                else:
                    total_req_evaluations += 1
                detection_errors.append(
                    f"Adapter error on detail page {source_url}: {exc}"
                )

        # Process Listing Pages if present
        listing_field_rules = template_dict.get("listing_rules", {}).get("fields", {})
        for fetch in valid_listing_fetches:
            html = fetch.html or ""
            try:
                items = adapter.extract_items_from_listing_html(html)
                if not items:
                    detection_errors.append(
                        f"Listing card_selector matched 0 items on {fetch.url or 'listing'}."
                    )
                for item in items:
                    for l_fn, l_rule in listing_field_rules.items():
                        is_req = l_rule.get("required", False)
                        l_val = item.get(l_fn)
                        if is_req:
                            total_req_evaluations += 1
                            if l_val is not None and (
                                not isinstance(l_val, str) or l_val.strip()
                            ):
                                successful_req_extractions += 1
                            else:
                                detection_errors.append(
                                    f"Required listing field '{l_fn}' empty."
                                )
                        else:
                            total_opt_evaluations += 1
                            if l_val is not None and (
                                not isinstance(l_val, str) or l_val.strip()
                            ):
                                successful_opt_extractions += 1
            except Exception as exc:
                detection_errors.append(f"Adapter error on listing page: {exc}")

        # ---------------------------------------------------------------------
        # Step 5: Calculate Explicit Quality Metrics
        # ---------------------------------------------------------------------
        req_rate = (
            successful_req_extractions / total_req_evaluations
            if total_req_evaluations > 0
            else 0.0 if (detection_errors and required_fields) else 1.0
        )
        opt_rate = (
            successful_opt_extractions / total_opt_evaluations
            if total_opt_evaluations > 0
            else 1.0
        )

        valid_urls_count = 0
        for u in extracted_urls:
            parsed = urlparse(u)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                valid_urls_count += 1
        url_rate = valid_urls_count / len(extracted_urls) if extracted_urls else 1.0

        complete_text_count = sum(
            1 for t in extracted_text_values if len(t.strip()) >= 10
        )
        completeness_rate = (
            complete_text_count / len(extracted_text_values)
            if extracted_text_values
            else 1.0
        )

        overall_score = (
            (0.40 * req_rate)
            + (0.30 * opt_rate)
            + (0.20 * url_rate)
            + (0.10 * completeness_rate)
        )

        # Baseline degradation ratio
        baseline_drop_ratio: float | None = None
        if (
            baseline_score is not None
            and isinstance(baseline_score, (int, float))
            and baseline_score > 0
        ):
            if overall_score < baseline_score:
                baseline_drop_ratio = (baseline_score - overall_score) / baseline_score

        metrics = TemplateMetrics(
            required_field_success_rate=round(req_rate, 4),
            optional_field_coverage_rate=round(opt_rate, 4),
            valid_url_format_rate=round(url_rate, 4),
            content_completeness_rate=round(completeness_rate, 4),
            overall_quality_score=round(overall_score, 4),
            baseline_degradation=(
                round(baseline_drop_ratio, 4)
                if baseline_drop_ratio is not None
                else None
            ),
        )

        # ---------------------------------------------------------------------
        # Step 6: Outcome Classification Decision Order
        # ---------------------------------------------------------------------
        # Rule 4: If any required field fails (req_rate < 1.0 or extraction errors) -> STRUCTURE_CHANGED
        if req_rate < 1.0 or (detection_errors and required_fields):
            return ChangeDetectionResult(
                source_name=source_name,
                status=ChangeDetectionStatus.STRUCTURE_CHANGED,
                valid=False,
                quality_score=round(overall_score, 4),
                metrics=metrics,
                errors=detection_errors,
                warnings=detection_warnings,
                detail_samples_evaluated=len(valid_detail_fetches),
                listing_samples_evaluated=len(valid_listing_fetches),
                sample_extracted_data=last_extracted_data,
            )

        # Rule 5: Check degradation conditions -> EXTRACTION_DEGRADED
        is_degraded = False
        degradation_reasons: list[str] = []

        if overall_score < self.quality_score_threshold:
            is_degraded = True
            degradation_reasons.append(
                f"Overall quality score ({overall_score:.2f}) fell below threshold ({self.quality_score_threshold})."
            )

        if opt_rate < self.optional_coverage_threshold:
            is_degraded = True
            degradation_reasons.append(
                f"Optional field coverage ({opt_rate:.2f}) fell below threshold ({self.optional_coverage_threshold})."
            )

        if (
            baseline_drop_ratio is not None
            and baseline_drop_ratio > self.degradation_threshold
        ):
            is_degraded = True
            degradation_reasons.append(
                f"Relative baseline degradation ({baseline_drop_ratio:.2%}) exceeded threshold ({self.degradation_threshold:.2%})."
            )

        if is_degraded:
            return ChangeDetectionResult(
                source_name=source_name,
                status=ChangeDetectionStatus.EXTRACTION_DEGRADED,
                valid=False,
                quality_score=round(overall_score, 4),
                metrics=metrics,
                errors=degradation_reasons + detection_errors,
                warnings=detection_warnings,
                detail_samples_evaluated=len(valid_detail_fetches),
                listing_samples_evaluated=len(valid_listing_fetches),
                sample_extracted_data=last_extracted_data,
            )

        # Rule 6: All checks passed -> VALID
        return ChangeDetectionResult(
            source_name=source_name,
            status=ChangeDetectionStatus.VALID,
            valid=True,
            quality_score=round(overall_score, 4),
            metrics=metrics,
            errors=[],
            warnings=detection_warnings,
            detail_samples_evaluated=len(valid_detail_fetches),
            listing_samples_evaluated=len(valid_listing_fetches),
            sample_extracted_data=last_extracted_data,
        )
