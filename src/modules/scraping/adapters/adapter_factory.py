import logging
from typing import Any

from src.modules.infrastructure.http.base_http_client import BaseHttpClient

from .almin7_adapter import Almin7Adapter
from .base_adapter import BaseAdapter
from .generic_template_adapter import GenericTemplateAdapter
from .grabscholarship_adapter import GrabScholarshipAdapter
from .scholars4dev_adapter import Scholars4DevAdapter
from .wordpress_api_adapter import WordPressApiAdapter

logger = logging.getLogger(__name__)


class AdapterFactory:
    """مصنع يقوم بتسجيل المحولات وإنشاء النسخة المناسبة لكل مصدر."""

    _registry: dict[str, type[BaseAdapter]] = {
        "almin7": Almin7Adapter,
        "grabscholarship": GrabScholarshipAdapter,
        "grabscholarships": GrabScholarshipAdapter,
        "scholars4dev": Scholars4DevAdapter,
        "wordpress_api": WordPressApiAdapter,
        "wp_api": WordPressApiAdapter,
        "wordpress": WordPressApiAdapter,
        "generic_template": GenericTemplateAdapter,
        "template": GenericTemplateAdapter,
    }

    @classmethod
    def register(cls, source_name: str, adapter_cls: type[BaseAdapter]) -> None:
        """يسجل محولاً جديداً برابط اسمه."""
        cls._registry[source_name.lower().strip()] = adapter_cls
        logger.info(
            "Registered adapter for source '%s': %s", source_name, adapter_cls.__name__
        )

    @classmethod
    def get_adapter(
        cls,
        source_name: str,
        source_config: dict[str, Any] | None = None,
        http_client: BaseHttpClient | None = None,
        allow_fallback: bool = True,
    ) -> BaseAdapter:
        """يرجع كائن المحول المناسب بناءً على اسم المصدر أو طريقته."""
        config = source_config or {}
        name_key = source_name.lower().strip() if source_name else ""
        method_key = str(config.get("method", "")).lower().strip()

        # 1. Direct name match
        adapter_cls = cls._registry.get(name_key)

        # 2. Check by method (e.g. method="wordpress_api", method="html", method="generic_template")
        if adapter_cls is None and method_key:
            adapter_cls = cls._registry.get(method_key)

        # 3. Check for keywords in name, method, or presence of template config
        if adapter_cls is None:
            if "almin7" in name_key:
                adapter_cls = Almin7Adapter
            elif "grabscholarship" in name_key:
                adapter_cls = GrabScholarshipAdapter
            elif "scholars4dev" in name_key:
                adapter_cls = Scholars4DevAdapter
            elif (
                "template" in name_key
                or "template" in method_key
                or config.get("template") is not None
            ):
                adapter_cls = GenericTemplateAdapter
            elif (
                "wordpress" in name_key or "wp" in name_key or "wordpress" in method_key
            ):
                adapter_cls = WordPressApiAdapter

        # 4. Fallback or Raise
        if adapter_cls is None:
            if not allow_fallback and method_key and method_key not in cls._registry:
                raise ValueError(
                    f"Unsupported adapter source or method: '{source_name}' (method: '{method_key}')"
                )
            logger.warning(
                "No specialized adapter found for '%s' (method: '%s'). Falling back to WordPressApiAdapter.",
                source_name,
                method_key,
            )
            adapter_cls = WordPressApiAdapter

        if adapter_cls is GenericTemplateAdapter:
            template = config.get("template")
            if not template:
                raise ValueError(
                    f"GenericTemplateAdapter requires a 'template' dictionary or file path in source_config for source '{source_name}'."
                )
            return GenericTemplateAdapter(
                template=template,
                source_config=config,
                http_client=http_client,
            )

        return adapter_cls(source_config=config, http_client=http_client)

    @classmethod
    def list_supported_sources(cls) -> list[str]:
        """يرجع قائمة بأسماء المصادر المدعومة."""
        return sorted(cls._registry.keys())
