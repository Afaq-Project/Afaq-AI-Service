# [OMA-W006-T008] Public facade for TemplateEngineService package

import logging
from typing import Any

from prisma.models import ScrapingTemplate

from src.modules.core.config.settings import Settings, get_settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.llm.base import StructuredGenerator
from src.modules.scraping.models import ExtractionResult

from .matcher import (
    CONTAINER_SELECTOR_KEYS,
    COVERAGE_THRESHOLD,
    MAX_TEXT_BOUND_CHARS,
    evaluate_gate_1_container,
    evaluate_gate_2_coverage,
    evaluate_gate_3_text_bounds,
    extract_first_value,
    extract_level_1_catalog,
    extract_level_2_detail,
    extract_selectors_map,
    extract_with_template,
    match_template_deterministic,
    unwrap_json,
)
from .metrics import FieldMetrics, update_field_metrics_in_db
from .micro_repair import (
    SOFT_DRIFT_THRESHOLD,
    MicroRepairResponse,
    detect_soft_drift,
    extract_dom_snippet,
    increment_minor_version,
    repair_field_with_llm,
    validate_synthesized_selector,
)

logger = logging.getLogger(__name__)


class TemplateEngineService:
    """Autonomous template engine managing layout matching, data extraction,

    telemetry fill rates, soft-drift detection, and targeted micro-repairs.
    """

    # Backward compatible class/static methods
    _unwrap_json = staticmethod(unwrap_json)
    _extract_selectors_map = staticmethod(extract_selectors_map)
    _evaluate_gate_1_container = staticmethod(evaluate_gate_1_container)
    _evaluate_gate_2_coverage = staticmethod(evaluate_gate_2_coverage)
    _evaluate_gate_3_text_bounds = staticmethod(evaluate_gate_3_text_bounds)
    _extract_first_value = staticmethod(extract_first_value)
    _extract_level_1_catalog = staticmethod(extract_level_1_catalog)
    _extract_level_2_detail = staticmethod(extract_level_2_detail)
    _extract_dom_snippet = staticmethod(extract_dom_snippet)
    _increment_minor_version = staticmethod(increment_minor_version)
    _validate_synthesized_selector = staticmethod(validate_synthesized_selector)

    def __init__(
        self,
        repository: ScrapingRepository | None = None,
        settings: Settings | None = None,
        llm_client: StructuredGenerator | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings or get_settings()
        self._llm_client = llm_client

    def match_template_deterministic(
        self, html: str, templates: list[ScrapingTemplate]
    ) -> ScrapingTemplate | None:
        return match_template_deterministic(html, templates)

    def extract_with_template(
        self, html: str, template: ScrapingTemplate
    ) -> ExtractionResult:
        return extract_with_template(html, template)

    async def update_field_metrics(
        self,
        source_id: str,
        template_id: str,
        field_results: dict[str, bool],
    ) -> None:
        await update_field_metrics_in_db(self._repository, template_id, field_results)

    def detect_soft_drift(
        self, metrics: list[FieldMetrics] | list[dict[str, Any]] | dict[str, Any]
    ) -> list[str]:
        return detect_soft_drift(metrics)

    async def micro_repair_field(
        self,
        html: str,
        template: ScrapingTemplate,
        degraded_field: str,
    ) -> ScrapingTemplate:
        return await repair_field_with_llm(
            html=html,
            template=template,
            degraded_field=degraded_field,
            repository=self._repository,
            llm_client=self._llm_client,
        )

    async def get_or_synthesize_template(
        self,
        source_id: str,
        level: int,
        html: str,
        layout_signature: str,
        schema_candidate: dict[str, Any] | None = None,
    ) -> ScrapingTemplate | None:
        """Load templates for source/level, match deterministically, or synthesize
        via LLM, validate, and persist. Returns None on failure.
        """
        templates = await self._repository.get_templates_for_source(source_id, level)
        matched = self.match_template_deterministic(html, templates)
        if matched is not None:
            return matched

        if schema_candidate is None and self._llm_client is not None:
            schema_candidate = await self._synthesize_schema(level, html)

        if not schema_candidate:
            return None

        from src.modules.security.services.schema_validator_service import (
            SchemaValidatorService,
        )

        validation = await SchemaValidatorService.validate_template_schema(
            schema_candidate, sample_html=html, raise_on_error=False
        )
        if not getattr(validation, "is_valid", False):
            return None
        try:
            return await self._repository.create_template(
                source_id=source_id,
                level=level,
                layout_signature=layout_signature,
                template_schema=schema_candidate,
                schema_type="CSS",
            )
        except Exception as exc:
            logger.warning("Template persistence failed: %s", exc)
            return None

    async def _synthesize_schema(self, level: int, html: str) -> dict[str, Any] | None:
        from pydantic import BaseModel, ConfigDict, Field

        from src.modules.scraping.services.discovery_service.prompts import (
            package_untrusted_prompt,
        )
        from src.modules.scraping.services.discovery_service.skeletonizer import (
            skeletonize_dom,
        )

        class L1Out(BaseModel):
            model_config = ConfigDict(extra="ignore")

            card_container_selector: str
            card_title_selector: str
            card_link_selector: str

        class L2Out(BaseModel):
            model_config = ConfigDict(extra="ignore")

            title_selector: str
            content_selector: str
            deadline_selector: str | None = None
            application_link_selector: str | None = None

        try:
            from src.modules.scraping.services.discovery_service.onboarding import (
                DiscoveryService,
            )

            skeleton = skeletonize_dom(html)
            prompt = package_untrusted_prompt(
                skeleton, user_instruction="Generate extraction selectors."
            )
            if level == 1:
                completion = await self._llm_client.generate(
                    system="Generate CSS selectors for catalog cards.",
                    prompt=prompt,
                    output_type=L1Out,
                )
                out = completion.output
                return {
                    "schema_name": "catalog_l1",
                    "selectors": {
                        "card_container": out.card_container_selector,
                        "card_title": out.card_title_selector,
                        "card_link": out.card_link_selector,
                    },
                }
            completion = await self._llm_client.generate(
                system="Generate CSS selectors for detail fields.",
                prompt=prompt,
                output_type=L2Out,
            )
            out = completion.output
            selectors = {
                "title": out.title_selector,
                "content": out.content_selector,
            }
            if out.deadline_selector:
                selectors["deadline_raw"] = out.deadline_selector
            if out.application_link_selector:
                selectors["application_link"] = out.application_link_selector
            return {"schema_name": "detail_l2", "selectors": selectors}
        except Exception as exc:
            logger.warning("Schema synthesis failed: %s", exc)
            return None


__all__ = [
    "TemplateEngineService",
    "FieldMetrics",
    "MicroRepairResponse",
    "COVERAGE_THRESHOLD",
    "MAX_TEXT_BOUND_CHARS",
    "SOFT_DRIFT_THRESHOLD",
    "CONTAINER_SELECTOR_KEYS",
]
