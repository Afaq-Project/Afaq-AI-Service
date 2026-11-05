# [OMA-W001-T006] Unit tests for Security domain models, immutability, and exception hierarchy

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.modules.security.exceptions import (
    ERR_CIRCULAR_REDIRECT,
    ERR_CSS_SELECTOR_REDOS_TIMEOUT,
    ERR_FILE_SIZE_EXCEEDED,
    ERR_HOMOGRAPH_ATTACK,
    ERR_INVALID_PORT,
    ERR_INVALID_SCHEME,
    ERR_INVALID_URL_SYNTAX,
    ERR_MALICIOUS_FILE_TYPE,
    ERR_MAX_REDIRECTS_EXCEEDED,
    ERR_PATH_TRAVERSAL,
    ERR_RATE_LIMITED_COOLDOWN,
    ERR_SCHEMA_SHAPE_INVALID,
    ERR_SELECTOR_SYNTAX_INVALID,
    ERR_SSRF_ATTEMPT_BLOCKED,
    ERR_ZIP_BOMB_DETECTED,
    CircularRedirectError,
    CssSelectorReDosTimeoutError,
    FileSizeExceededError,
    HomographAttackError,
    InvalidUrlPortError,
    InvalidUrlSchemeError,
    InvalidUrlSyntaxError,
    MaliciousFileTypeError,
    MaxRedirectsExceededError,
    PathTraversalError,
    RateLimitedCooldownError,
    SchemaShapeInvalidError,
    SecurityValidationError,
    SelectorSyntaxInvalidError,
    SSRFAttemptBlockedError,
    ZipBombDetectedError,
)
from src.modules.security.models import (
    FileValidationResult,
    InspectUrlRequest,
    InspectUrlResponse,
    TemplateSchemaValidationResult,
    ValidatedUrl,
)


# [OMA-W001-T006] Test ValidatedUrl model creation, immutability, and rejection of extra fields
def test_validated_url_model_immutability():
    """Protects ARCH-007 and UC-01: ValidatedUrl value object must be frozen and reject extra attributes."""
    url_obj = ValidatedUrl(
        original_url="https://scholarships.example.edu/programs/2026",
        canonical_url="https://scholarships.example.edu/programs/2026",
        scheme="https",
        host="scholarships.example.edu",
        port=443,
        resolved_ip="93.184.216.34",
        is_https=True,
        redirect_hops=0,
        redirect_chain=[],
        dns_pinned_rule="--host-resolver-rules=MAP scholarships.example.edu 93.184.216.34",
    )

    assert url_obj.original_url == "https://scholarships.example.edu/programs/2026"
    assert url_obj.canonical_url == "https://scholarships.example.edu/programs/2026"
    assert url_obj.scheme == "https"
    assert url_obj.host == "scholarships.example.edu"
    assert url_obj.port == 443
    assert url_obj.resolved_ip == "93.184.216.34"
    assert url_obj.is_https is True
    assert url_obj.redirect_hops == 0
    assert url_obj.redirect_chain == []
    assert isinstance(url_obj.validated_at, datetime)

    # Immutability check: mutation attempt must raise ValidationError
    with pytest.raises(ValidationError):
        url_obj.host = "mutated.com"  # type: ignore[misc]

    # Extra fields forbidden check
    with pytest.raises(ValidationError):
        ValidatedUrl(
            original_url="https://example.com",
            canonical_url="https://example.com",
            scheme="https",
            host="example.com",
            port=443,
            resolved_ip="93.184.216.34",
            is_https=True,
            dns_pinned_rule="--host-resolver-rules=MAP example.com 93.184.216.34",
            unauthorized_extra_attribute="malicious",  # type: ignore[call-arg]
        )


# [OMA-W001-T006] Test ValidatedUrl scheme literal constraint
def test_validated_url_scheme_literal():
    """Protects RFC 3986 scheme invariants: only http and https are allowed in ValidatedUrl."""
    with pytest.raises(ValidationError):
        ValidatedUrl(
            original_url="ftp://example.com",
            canonical_url="ftp://example.com",
            scheme="ftp",  # type: ignore[arg-type]
            host="example.com",
            port=21,
            resolved_ip="93.184.216.34",
            is_https=False,
            dns_pinned_rule="--host-resolver-rules=MAP example.com 93.184.216.34",
        )


# [OMA-W001-T006] Test FileValidationResult model immutability and defaults
def test_file_validation_result_immutability():
    """Protects UC-03 & UC-06: FileValidationResult is frozen and rejects extra fields."""
    result = FileValidationResult(
        is_valid=True,
        source_url="https://example.edu/guidelines.pdf",
        mime_type="application/pdf",
        file_extension="pdf",
        file_size_bytes=1024,
        sha256_checksum="abc123def456",
        suggested_s3_key="documents/src_1/abc123def456_guidelines.pdf",
        magic_bytes_hex="255044462D",
    )

    assert result.is_valid is True
    assert result.mime_type == "application/pdf"
    assert result.error_code is None
    assert result.rejection_reason is None

    # Mutation attempt must raise ValidationError
    with pytest.raises(ValidationError):
        result.is_valid = False  # type: ignore[misc]

    # Extra fields forbidden check
    with pytest.raises(ValidationError):
        FileValidationResult(
            is_valid=False,
            extra_forbidden_key="tamper",  # type: ignore[call-arg]
        )


# [OMA-W001-T006] Test TemplateSchemaValidationResult model immutability and defaults
def test_template_schema_validation_result_immutability():
    """Protects UC-02 & UC-14: TemplateSchemaValidationResult is frozen and rejects extra fields."""
    result = TemplateSchemaValidationResult(
        is_valid=True,
        schema_name="grant_schema",
        selector_count=2,
        selectors_validated=["h1.grant-title", "a.btn-apply"],
        dry_run_latency_ms=12.5,
    )

    assert result.is_valid is True
    assert result.schema_name == "grant_schema"
    assert result.selector_count == 2
    assert result.selectors_validated == ["h1.grant-title", "a.btn-apply"]
    assert result.error_code is None
    assert result.rejection_reason is None
    assert result.failing_selector is None

    # Mutation attempt must raise ValidationError
    with pytest.raises(ValidationError):
        result.schema_name = "tampered"  # type: ignore[misc]

    # Extra fields forbidden check
    with pytest.raises(ValidationError):
        TemplateSchemaValidationResult(
            is_valid=True,
            schema_name="test",
            selector_count=1,
            unauthorized="extra",  # type: ignore[call-arg]
        )


# [OMA-W001-T006] Test InspectUrlRequest model validation and immutability
def test_inspect_url_request_model():
    """Protects API ingress models: InspectUrlRequest enforces frozen state and default flags."""
    req = InspectUrlRequest(url="https://example.edu/grant")
    assert req.url == "https://example.edu/grant"
    assert req.base_url is None
    assert req.allow_redirects is True

    # Mutation attempt
    with pytest.raises(ValidationError):
        req.url = "https://mutated.com"  # type: ignore[misc]

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        InspectUrlRequest(
            url="https://example.edu",
            rogue_field="unexpected",  # type: ignore[call-arg]
        )


# [OMA-W001-T006] Test InspectUrlResponse model validation and immutability
def test_inspect_url_response_model():
    """Protects API egress response envelope: InspectUrlResponse structure and immutability."""
    url_obj = ValidatedUrl(
        original_url="https://example.edu",
        canonical_url="https://example.edu",
        scheme="https",
        host="example.edu",
        port=443,
        resolved_ip="93.184.216.34",
        is_https=True,
        dns_pinned_rule="--host-resolver-rules=MAP example.edu 93.184.216.34",
    )
    res = InspectUrlResponse(data=url_obj)

    assert res.status == "success"
    assert res.message == "URL verified as safe."
    assert res.data == url_obj

    # Mutation attempt
    with pytest.raises(ValidationError):
        res.status = "tampered"  # type: ignore[misc]

    # Extra fields forbidden
    with pytest.raises(ValidationError):
        InspectUrlResponse(
            data=url_obj,
            extra_key="not_allowed",  # type: ignore[call-arg]
        )


# [OMA-W001-T006] Test SecurityValidationError base exception formatting and repr
def test_security_validation_error_base():
    """Protects exception hierarchy base: error_code, details, str, and repr."""
    exc = SecurityValidationError(
        message="Test security failure",
        error_code="ERR_CUSTOM_TEST",
        details={"key": "val"},
    )
    assert exc.message == "Test security failure"
    assert exc.error_code == "ERR_CUSTOM_TEST"
    assert exc.details == {"key": "val"}
    assert str(exc) == "Test security failure"
    assert (
        repr(exc)
        == "SecurityValidationError(error_code='ERR_CUSTOM_TEST', message='Test security failure')"
    )

    # Default values check
    default_exc = SecurityValidationError()
    assert default_exc.message == "Security validation error"
    assert default_exc.error_code == "ERR_SECURITY_VALIDATION"
    assert default_exc.details == {}


# [OMA-W001-T006] Test typed domain exceptions for specific error codes and attributes
def test_security_exception_subclasses():
    """Protects typed exception contract across the entire security error hierarchy."""
    exceptions_to_test = [
        (InvalidUrlSyntaxError, ERR_INVALID_URL_SYNTAX),
        (InvalidUrlSchemeError, ERR_INVALID_SCHEME),
        (InvalidUrlPortError, ERR_INVALID_PORT),
        (PathTraversalError, ERR_PATH_TRAVERSAL),
        (HomographAttackError, ERR_HOMOGRAPH_ATTACK),
        (SSRFAttemptBlockedError, ERR_SSRF_ATTEMPT_BLOCKED),
        (CircularRedirectError, ERR_CIRCULAR_REDIRECT),
        (MaxRedirectsExceededError, ERR_MAX_REDIRECTS_EXCEEDED),
        (MaliciousFileTypeError, ERR_MALICIOUS_FILE_TYPE),
        (FileSizeExceededError, ERR_FILE_SIZE_EXCEEDED),
        (ZipBombDetectedError, ERR_ZIP_BOMB_DETECTED),
        (SchemaShapeInvalidError, ERR_SCHEMA_SHAPE_INVALID),
        (SelectorSyntaxInvalidError, ERR_SELECTOR_SYNTAX_INVALID),
        (CssSelectorReDosTimeoutError, ERR_CSS_SELECTOR_REDOS_TIMEOUT),
    ]

    for exc_class, expected_code in exceptions_to_test:
        err = exc_class("Sample message", details={"ctx": 1})
        assert isinstance(err, SecurityValidationError)
        assert err.error_code == expected_code
        assert err.details == {"ctx": 1}
        assert "Sample message" in str(err)
        assert expected_code in repr(err)

    # Special case: RateLimitedCooldownError carries retry_after attribute
    rate_err = RateLimitedCooldownError(
        "Rate limit cooldown",
        error_code=ERR_RATE_LIMITED_COOLDOWN,
        details={"status": 429},
        retry_after=600.0,
    )
    assert rate_err.retry_after == 600.0
    assert rate_err.error_code == ERR_RATE_LIMITED_COOLDOWN
    assert rate_err.details == {"status": 429}
