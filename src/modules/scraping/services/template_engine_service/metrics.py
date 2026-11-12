# [OMA-W006-T008] Rolling fill-rate metrics for TemplateEngineService

import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)

from .matcher import unwrap_json

logger = logging.getLogger(__name__)


class FieldMetrics(BaseModel):
    """Metrics tracking rolling fill rate and baseline for a single template field."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    field_name: str
    fill_rate: float
    baseline_fill_rate: float = 1.0
    total_runs: int = 0
    successful_runs: int = 0

    @model_validator(mode="before")
    @classmethod
    def _coerce_field_names(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "field" in data and "field_name" not in data:
                data["field_name"] = data["field"]
            if "baseline" in data and "baseline_fill_rate" not in data:
                data["baseline_fill_rate"] = data["baseline"]
        return data


async def update_field_metrics_in_db(
    repository: ScrapingRepository | None,
    template_id: str,
    field_results: dict[str, bool],
) -> None:
    """Updates rolling fill-rate metrics in field_metrics table via repository."""
    if not repository:
        logger.debug("ScrapingRepository not provided; skipping DB metrics update.")
        return

    template = await repository.get_template_by_id(template_id)
    if not template:
        logger.warning("Template %s not found for metrics update", template_id)
        return

    current_metrics = unwrap_json(template.field_metrics)

    updated_metrics = dict(current_metrics)
    for field_name, success in field_results.items():
        field_stat = dict(updated_metrics.get(field_name, {}))
        total_runs = int(field_stat.get("total_runs", 0)) + 1
        successful_runs = int(field_stat.get("successful_runs", 0)) + (
            1 if success else 0
        )
        fill_rate = round(successful_runs / total_runs, 4)
        baseline = float(field_stat.get("baseline_fill_rate", 1.0))

        updated_metrics[field_name] = {
            "field_name": field_name,
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "fill_rate": fill_rate,
            "baseline_fill_rate": baseline,
        }

    await repository.update_field_metrics(template_id, updated_metrics)
