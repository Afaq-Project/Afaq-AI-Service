# [OMA-W005-T006] [OMA-W005-T007] [OMA-W006-T011] Unit tests for Scraping & Extraction pipeline models, validators, and exceptions

import pytest
from pydantic import ValidationError

from src.modules.scraping.exceptions import (
    ERR_ACCESS_CHALLENGE_BLOCKED,
    ERR_CSS_SELECTOR_REDOS_TIMEOUT,
    ERR_EXTRACTION_FAILED,
    ERR_IRRELEVANT_CONTENT_REJECTED,
    ERR_NOT_OPPORTUNITY_PORTAL,
    ERR_OPERATION_TIMEOUT,
    ERR_PAGINATION_LOOP_DETECTED,
    ERR_RATE_LIMITED_COOLDOWN,
    ERR_SOURCE_LOCKED,
    ERR_SOURCE_NOT_FOUND,
    ERR_TEMPLATE_NOT_FOUND,
    AccessChallengeBlockedError,
    CSSSelectorReDoSTimeoutError,
    ExtractionFailedError,
    IrrelevantContentRejectedError,
    NotOpportunityPortalError,
    OperationTimeoutError,
    PaginationLoopDetectedError,
    RateLimitedCooldownError,
    ScrapingError,
    ScrapingException,
    SourceLockedError,
    SourceNotFoundError,
    TemplateNotFoundError,
)
from src.modules.scraping.models import (
    ExtractionStatus,
    OperationStatus,
    OrderingStrategy,
    PageType,
    PaginationType,
    ScrapeRunRequest,
    SourceOnboardRequest,
    SourceStatus,
)
from src.modules.scraping.services.template_engine_service.metrics import (
    FieldMetrics,
)


# [OMA-W006-T011] Test ScrapeRunRequest model input validation and extra field rejection (forbids parameter injection)
def test_scrape_run_request_validation():
    """Protects UC-02 & UC-11: Validates ScrapeRunRequest accepts optional source_ids and forbids extra fields."""
    req_all = ScrapeRunRequest()
    assert req_all.source_ids is None

    req_filtered = ScrapeRunRequest(source_ids=["src_001", "src_002"])
    assert req_filtered.source_ids == ["src_001", "src_002"]

    with pytest.raises(ValidationError):
        ScrapeRunRequest(source_ids=["src_001"], extra_unexpected_arg="malicious")


# [OMA-W006-T011] Test SourceOnboardRequest extra field rejection (forbids parameter injection)
def test_source_onboard_request_validation():
    """Protects UC-02: Validates Stage 0 onboarding request validation and parameter tampering prevention."""
    onboard_req = SourceOnboardRequest(
        url="https://scholarships.example.edu",
        name="Example Scholarships Portal",
    )
    assert onboard_req.url == "https://scholarships.example.edu"
    assert onboard_req.name == "Example Scholarships Portal"

    # Forbid extra fields to prevent injection
    with pytest.raises(ValidationError):
        SourceOnboardRequest(
            url="https://scholarships.example.edu",
            malicious_param="bypass",
        )


# [OMA-W006-T011] Test custom model validator and field coercion transformation on FieldMetrics
def test_field_metrics_custom_validator_transformation():
    """Protects FR-013: Validates custom @model_validator coerces legacy 'field' and 'baseline' aliases."""
    # Direct canonical field names
    direct = FieldMetrics(
        field_name="deadline", fill_rate=0.85, baseline_fill_rate=0.90
    )
    assert direct.field_name == "deadline"
    assert direct.baseline_fill_rate == 0.90

    # Coerced legacy aliases via model validator
    coerced = FieldMetrics.model_validate(
        {"field": "scholarship_amount", "fill_rate": 0.70, "baseline": 0.95}
    )
    assert coerced.field_name == "scholarship_amount"
    assert coerced.baseline_fill_rate == 0.95


# [OMA-W006-T011] Test domain state machine integrity and status values across scraping lifecycle
def test_scraping_enums_and_status_states():
    """Protects domain state machine integrity: Validates status and mechanics enums."""
    assert OperationStatus.RUNNING == "running"
    assert OperationStatus.TIMED_OUT == "timed_out"
    assert OperationStatus.ABORTED == "aborted"
    assert OperationStatus.PARTIALLY_ABORTED == "partially_aborted"
    assert OperationStatus.COMPLETED == "completed"
    assert OperationStatus.FAILED == "failed"

    assert SourceStatus.ACTIVE == "active"
    assert SourceStatus.COOLDOWN == "cooldown"
    assert SourceStatus.ABORTED == "aborted"

    assert ExtractionStatus.PENDING_DETAIL_CRAWL == "pending_detail_crawl"
    assert ExtractionStatus.DETAILS_EXTRACTED == "details_extracted"
    assert ExtractionStatus.FAILED_PERMANENTLY == "failed_permanently"

    assert PageType.CATALOG == "catalog"
    assert PageType.DETAIL == "detail"

    assert PaginationType.NEXT_BUTTON == "next_button"
    assert PaginationType.URL_PARAM == "url_param"

    assert OrderingStrategy.CHRONOLOGICAL_DESCENDING == "chronological_descending"


# [OMA-W005-T007] Test ScrapingException base class properties and representation
def test_scraping_exception_base():
    """Protects domain invariant: All scraping exceptions possess standard message, code, and details."""
    exc = ScrapingException(
        message="Test failure",
        code="ERR_CUSTOM_TEST",
        details={"key": "val"},
    )
    assert exc.message == "Test failure"
    assert exc.code == "ERR_CUSTOM_TEST"
    assert exc.error_code == "ERR_CUSTOM_TEST"
    assert exc.details == {"key": "val"}
    assert str(exc) == "Test failure"
    assert "ScrapingException" in repr(exc)
    assert "ERR_CUSTOM_TEST" in repr(exc)

    # ScrapingError is alias for ScrapingException
    assert ScrapingError is ScrapingException


# [OMA-W005-T007] Test ScrapingException subclasses and specialized parameters
@pytest.mark.parametrize(
    ("exc_cls", "expected_code"),
    [
        (NotOpportunityPortalError, ERR_NOT_OPPORTUNITY_PORTAL),
        (AccessChallengeBlockedError, ERR_ACCESS_CHALLENGE_BLOCKED),
        (RateLimitedCooldownError, ERR_RATE_LIMITED_COOLDOWN),
        (OperationTimeoutError, ERR_OPERATION_TIMEOUT),
        (CSSSelectorReDoSTimeoutError, ERR_CSS_SELECTOR_REDOS_TIMEOUT),
        (TemplateNotFoundError, ERR_TEMPLATE_NOT_FOUND),
        (ExtractionFailedError, ERR_EXTRACTION_FAILED),
        (SourceNotFoundError, ERR_SOURCE_NOT_FOUND),
        (SourceLockedError, ERR_SOURCE_LOCKED),
        (IrrelevantContentRejectedError, ERR_IRRELEVANT_CONTENT_REJECTED),
        (PaginationLoopDetectedError, ERR_PAGINATION_LOOP_DETECTED),
    ],
)
def test_scraping_exception_hierarchy(exc_cls, expected_code):
    """Protects domain invariant: All specialized exceptions inherit from ScrapingException and use assigned codes."""
    instance = exc_cls()
    assert isinstance(instance, ScrapingException)
    assert instance.code == expected_code
    assert instance.error_code == expected_code


# [OMA-W005-T007] Test specialized attributes on specific scraping exceptions
def test_specialized_exception_attributes():
    """Protects UC-13, UC-14, UC-10: Specialized exceptions capture typed recovery telemetry."""
    # RateLimitedCooldownError captures cool_down_seconds
    rate_err = RateLimitedCooldownError(
        message="Too many requests",
        cool_down_seconds=600.0,
        details={"status_code": 429},
    )
    assert rate_err.cool_down_seconds == 600.0
    assert rate_err.details["cool_down_seconds"] == 600.0
    assert rate_err.details["status_code"] == 429

    # OperationTimeoutError captures timeout_sec
    timeout_err = OperationTimeoutError(
        message="Hard timeout ceiling breached",
        timeout_sec=1200,
    )
    assert timeout_err.timeout_sec == 1200
    assert timeout_err.details["timeout_sec"] == 1200

    # CSSSelectorReDoSTimeoutError captures failing_selector
    redos_err = CSSSelectorReDoSTimeoutError(
        message="Selector execution timed out",
        failing_selector="div > * + * ~ *",
    )
    assert redos_err.failing_selector == "div > * + * ~ *"
    assert redos_err.details["failing_selector"] == "div > * + * ~ *"
