# [OMA-W004-T001] Streamlined SchemaValidatorService using cssselect2

import asyncio
import time
from typing import Any

import bs4
import cssselect2.parser
import soupsieve

from src.modules.security.exceptions import (
    ERR_CSS_SELECTOR_REDOS_TIMEOUT,
    ERR_SCHEMA_SHAPE_INVALID,
    ERR_SELECTOR_SYNTAX_INVALID,
    CssSelectorReDosTimeoutError,
    SchemaShapeInvalidError,
    SecurityValidationError,
    SelectorSyntaxInvalidError,
)
from src.modules.security.models import TemplateSchemaValidationResult

ALLOWED_ROOT_KEYS = {
    "schema_name",
    "name",
    "selectors",
    "fields",
    "version",
    "description",
    "target_url",
    "created_at",
}


# [OMA-W004-T001] Streamlined SchemaValidatorService using cssselect2
class SchemaValidatorService:
    """Validates AI-generated template schemas and defends against CSS selector

    catastrophic backtracking (ReDoS) using cssselect2 AST inspection.
    """

    @classmethod
    async def validate_template_schema(
        cls,
        schema_dict: dict[str, Any],
        sample_html: str | None = None,
        raise_on_error: bool = True,
    ) -> TemplateSchemaValidationResult:
        """Inspects template schema shape and verifies all CSS selectors for ReDoS

        complexity and execution timeout limits.
        """
        try:
            return await cls._execute_validation(schema_dict, sample_html)
        except SecurityValidationError as err:
            if raise_on_error:
                raise
            schema_name = (
                schema_dict.get("schema_name")
                or schema_dict.get("name")
                or "invalid_schema"
                if isinstance(schema_dict, dict)
                else "invalid_schema"
            )
            failing = getattr(err, "details", {}).get("selector")
            return TemplateSchemaValidationResult(
                is_valid=False,
                schema_name=str(schema_name),
                selector_count=0,
                selectors_validated=[],
                dry_run_latency_ms=0.0,
                error_code=err.error_code,
                rejection_reason=str(err),
                failing_selector=failing,
            )

    # [OMA-W004-T001] Schema dictionary shape and structure verification
    @classmethod
    def _validate_schema_structure(cls, schema_dict: Any) -> str:
        """Validates root schema dictionary type, forbidden keys, and schema name."""
        if not isinstance(schema_dict, dict):
            raise SchemaShapeInvalidError(
                "Template schema must be a dictionary",
                error_code=ERR_SCHEMA_SHAPE_INVALID,
            )

        extra_keys = set(schema_dict.keys()) - ALLOWED_ROOT_KEYS
        if extra_keys:
            raise SchemaShapeInvalidError(
                f"Extra forbidden field(s) in schema: {sorted(extra_keys)}",
                error_code=ERR_SCHEMA_SHAPE_INVALID,
            )

        schema_name = schema_dict.get("schema_name") or schema_dict.get("name")
        if (
            not schema_name
            or not isinstance(schema_name, str)
            or not schema_name.strip()
        ):
            raise SchemaShapeInvalidError(
                "Schema missing or invalid 'schema_name'",
                error_code=ERR_SCHEMA_SHAPE_INVALID,
            )
        return schema_name

    # [OMA-W004-T001] Extract selectors from 'selectors' block
    @classmethod
    def _extract_from_selectors_block(cls, sel_obj: Any, selectors: list[str]) -> None:
        """Extracts CSS selectors from dictionary or list under 'selectors' key."""
        if isinstance(sel_obj, dict):
            for k, v in sel_obj.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise SchemaShapeInvalidError(
                        "Selectors dictionary keys and values must be strings",
                        error_code=ERR_SCHEMA_SHAPE_INVALID,
                    )
                selectors.append(v)
        elif isinstance(sel_obj, list):
            for item in sel_obj:
                if not isinstance(item, str):
                    raise SchemaShapeInvalidError(
                        "Selectors list items must be strings",
                        error_code=ERR_SCHEMA_SHAPE_INVALID,
                    )
                selectors.append(item)
        else:
            raise SchemaShapeInvalidError(
                "'selectors' must be a dictionary or list",
                error_code=ERR_SCHEMA_SHAPE_INVALID,
            )

    # [OMA-W004-T001] Extract selectors from 'fields' block
    @classmethod
    def _extract_from_fields_block(cls, fields_obj: Any, selectors: list[str]) -> None:
        """Extracts CSS selectors from dictionary or list under 'fields' key."""
        if isinstance(fields_obj, dict):
            for k, v in fields_obj.items():
                if isinstance(v, str):
                    selectors.append(v)
                elif isinstance(v, dict):
                    sel = v.get("selector")
                    if isinstance(sel, str):
                        selectors.append(sel)
                    elif "selector" in v:
                        raise SchemaShapeInvalidError(
                            "Field selector must be a string",
                            error_code=ERR_SCHEMA_SHAPE_INVALID,
                        )
                    else:
                        raise SchemaShapeInvalidError(
                            f"Invalid field definition for '{k}'",
                            error_code=ERR_SCHEMA_SHAPE_INVALID,
                        )
                else:
                    raise SchemaShapeInvalidError(
                        f"Invalid field definition for '{k}'",
                        error_code=ERR_SCHEMA_SHAPE_INVALID,
                    )
        elif isinstance(fields_obj, list):
            for item in fields_obj:
                if isinstance(item, str):
                    selectors.append(item)
                elif isinstance(item, dict):
                    sel = item.get("selector")
                    if isinstance(sel, str):
                        selectors.append(sel)
                    else:
                        raise SchemaShapeInvalidError(
                            "Field definition missing 'selector' string",
                            error_code=ERR_SCHEMA_SHAPE_INVALID,
                        )
                else:
                    raise SchemaShapeInvalidError(
                        "Invalid item in 'fields' list",
                        error_code=ERR_SCHEMA_SHAPE_INVALID,
                    )
        else:
            raise SchemaShapeInvalidError(
                "'fields' must be a dictionary or list",
                error_code=ERR_SCHEMA_SHAPE_INVALID,
            )

    # [OMA-W004-T001] Selector list extractor and minimum count enforcer
    @classmethod
    def _extract_selector_list(cls, schema_dict: dict[str, Any]) -> list[str]:
        """Collects all selector strings across schema and enforces minimum 2 selectors."""
        selectors: list[str] = []
        if "selectors" in schema_dict:
            cls._extract_from_selectors_block(schema_dict["selectors"], selectors)
        if "fields" in schema_dict:
            cls._extract_from_fields_block(schema_dict["fields"], selectors)

        if len(selectors) < 2:
            raise SchemaShapeInvalidError(
                f"Template schema must contain at least 2 selectors/fields, found {len(selectors)}",
                error_code=ERR_SCHEMA_SHAPE_INVALID,
            )
        return selectors

    # [OMA-W004-T001] Streamlined AST linting and compilation using cssselect2 and soupsieve
    @classmethod
    def _lint_and_compile_selectors(cls, selectors: list[str]) -> list[tuple[str, Any]]:
        """Lints CSS complexity via cssselect2 AST and compiles selectors."""
        compiled_selectors = []
        for sel in selectors:
            cls._lint_selector_complexity(sel)
            try:
                compiled = soupsieve.compile(sel)
                compiled_selectors.append((sel, compiled))
            except Exception as e:
                raise SelectorSyntaxInvalidError(
                    f"Invalid CSS selector syntax '{sel}': {e}",
                    error_code=ERR_SELECTOR_SYNTAX_INVALID,
                    details={"selector": sel},
                ) from e
        return compiled_selectors

    # [OMA-W004-T001] Streamlined selector AST complexity inspector
    @classmethod
    def _lint_selector_complexity(cls, sel: str) -> None:
        """Inspects CSS selector length, :has() nesting depth, and combinator limits using cssselect2 AST."""
        if len(sel) > 300:
            raise SelectorSyntaxInvalidError(
                f"CSS selector exceeds maximum length of 300 characters ({len(sel)}): {sel[:50]}...",
                error_code=ERR_SELECTOR_SYNTAX_INVALID,
                details={"selector": sel},
            )

        try:
            ast_nodes = list(cssselect2.parser.parse(sel))
        except Exception as e:
            raise SelectorSyntaxInvalidError(
                f"Invalid CSS selector syntax '{sel}': {e}",
                error_code=ERR_SELECTOR_SYNTAX_INVALID,
                details={"selector": sel},
            ) from e

        has_depth = max(
            (cls._calculate_has_depth(node) for node in ast_nodes), default=0
        )
        if has_depth > 1:
            raise CssSelectorReDosTimeoutError(
                f"Nested :has() depth ({has_depth}) exceeds allowed limit of 1: {sel}",
                error_code=ERR_CSS_SELECTOR_REDOS_TIMEOUT,
                details={"selector": sel, "has_depth": has_depth},
            )

        combinator_count = sum(cls._count_combinators(node) for node in ast_nodes)
        if combinator_count > 5:
            raise CssSelectorReDosTimeoutError(
                f"CSS combinator count ({combinator_count}) exceeds allowed limit of 5: {sel}",
                error_code=ERR_CSS_SELECTOR_REDOS_TIMEOUT,
                details={"selector": sel, "combinator_count": combinator_count},
            )

    # [OMA-W004-T001] Recursive :has() depth calculator on cssselect2 AST or selector string
    @classmethod
    def _calculate_has_depth(cls, target: Any) -> int:
        """Calculates the maximum nesting depth of :has() pseudo-classes in AST or selector string."""
        if isinstance(target, str):
            try:
                ast_nodes = list(cssselect2.parser.parse(target))
                return max(
                    (cls._calculate_has_depth(node) for node in ast_nodes), default=0
                )
            except Exception:
                return 0

        if isinstance(target, cssselect2.parser.RelationalSelector):
            sub_depth = max(
                (
                    cls._calculate_has_depth(sub)
                    for sub in getattr(target, "selector_list", [])
                ),
                default=0,
            )
            return 1 + sub_depth

        max_d = 0
        if hasattr(target, "__dict__"):
            for v in target.__dict__.values():
                if isinstance(v, (list, tuple)):
                    for item in v:
                        max_d = max(max_d, cls._calculate_has_depth(item))
                elif hasattr(v, "__dict__"):
                    max_d = max(max_d, cls._calculate_has_depth(v))
        return max_d

    # [OMA-W004-T001] Structural combinator counter on cssselect2 AST or selector string
    @classmethod
    def _count_combinators(cls, target: Any) -> int:
        """Counts structural combinators (>, +, ~, :has, :not) in AST or selector string."""
        if isinstance(target, str):
            try:
                ast_nodes = list(cssselect2.parser.parse(target))
                return sum(cls._count_combinators(node) for node in ast_nodes)
            except Exception:
                return 0

        cnt = 0
        if isinstance(
            target,
            (cssselect2.parser.CombinedSelector, cssselect2.parser.RelativeSelector),
        ) and target.combinator in (">", "+", "~"):
            cnt += 1
        elif isinstance(
            target,
            (cssselect2.parser.RelationalSelector, cssselect2.parser.NegationSelector),
        ):
            cnt += 1

        if hasattr(target, "__dict__"):
            for v in target.__dict__.values():
                if isinstance(v, (list, tuple)):
                    for item in v:
                        cnt += cls._count_combinators(item)
                elif hasattr(v, "__dict__"):
                    cnt += cls._count_combinators(v)
        return cnt

    # [OMA-W004-T001] Dry-run execution with 200ms timeout guard
    @classmethod
    async def _execute_dry_run_match(
        cls, compiled: Any, sel: str, soup: bs4.BeautifulSoup
    ) -> float:
        """Executes a single compiled selector against HTML soup with timeout protection."""
        start_time = time.perf_counter()
        try:
            await asyncio.wait_for(
                asyncio.to_thread(compiled.select, soup),
                timeout=0.200,
            )
        except TimeoutError as te:
            raise CssSelectorReDosTimeoutError(
                f"CSS selector execution timed out (>200ms): {sel}",
                error_code=ERR_CSS_SELECTOR_REDOS_TIMEOUT,
                details={"selector": sel},
            ) from te

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if elapsed_ms > 200.0:
            raise CssSelectorReDosTimeoutError(
                f"CSS selector latency ({elapsed_ms:.1f}ms) exceeded 200ms threshold: {sel}",
                error_code=ERR_CSS_SELECTOR_REDOS_TIMEOUT,
                details={"selector": sel, "latency_ms": elapsed_ms},
            )
        return elapsed_ms

    # [OMA-W004-T001] Multi-selector dry-run orchestrator
    @classmethod
    async def _execute_dry_run(
        cls, compiled_selectors: list[tuple[str, Any]], sample_html: str | None
    ) -> float:
        """Executes dry-run matches across all compiled selectors if sample HTML provided."""
        if not sample_html:
            return 0.0

        soup = bs4.BeautifulSoup(sample_html, "html.parser")
        total_latency_ms = 0.0
        for sel, compiled in compiled_selectors:
            elapsed_ms = await cls._execute_dry_run_match(compiled, sel, soup)
            total_latency_ms += elapsed_ms
        return total_latency_ms

    # [OMA-W004-T001] Main validation method refactored (Cognitive Complexity <= 15)
    @classmethod
    async def _execute_validation(
        cls,
        schema_dict: dict[str, Any],
        sample_html: str | None = None,
    ) -> TemplateSchemaValidationResult:
        """Performs Pydantic shape checking, static selector linting, and dry-run evaluation."""
        schema_name = cls._validate_schema_structure(schema_dict)
        selectors = cls._extract_selector_list(schema_dict)
        compiled_selectors = cls._lint_and_compile_selectors(selectors)
        total_latency_ms = await cls._execute_dry_run(compiled_selectors, sample_html)

        return TemplateSchemaValidationResult(
            is_valid=True,
            schema_name=schema_name,
            selector_count=len(selectors),
            selectors_validated=selectors,
            dry_run_latency_ms=round(total_latency_ms, 2),
        )


# [OMA-W004-T001] Backward-compatible alias
SchemaValidator = SchemaValidatorService
