# [OMA-W005-T036] Offline statistical n-gram language classification service using py3langid

import logging
import math
import re
from dataclasses import dataclass
from typing import Any

import py3langid

logger = logging.getLogger(__name__)

# [OMA-W005-T036] Minimum classification confidence threshold (FR-020)
DEFAULT_CONFIDENCE_THRESHOLD: float = 0.50
# [OMA-W005-T036] ISO 639-1 code for undetermined or low-confidence text
UNDETERMINED_LANGUAGE: str = "und"
# [OMA-W005-T036] Top candidates pool size for softmax normalization
DEFAULT_TOP_K_CANDIDATES: int = 5


# [OMA-W005-T036] Result of opportunity language classification
@dataclass(frozen=True)
class OpportunityLanguageResult:
    """Outcome of statistical language analysis on opportunity title and description."""

    title_language: str
    title_confidence: float
    body_language: str
    body_confidence: float
    overall_language: str
    overall_confidence: float
    is_low_confidence: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "title_language": self.title_language,
            "title_confidence": self.title_confidence,
            "body_language": self.body_language,
            "body_confidence": self.body_confidence,
            "overall_language": self.overall_language,
            "overall_confidence": self.overall_confidence,
            "is_low_confidence": self.is_low_confidence,
        }


# [OMA-W005-T036] Fast offline statistical language classifier service
class LanguageClassifierService:
    """Sub-millisecond offline statistical n-gram language classifier using py3langid.

    Enforces:
      - Normalized confidence score in [0.0, 1.0] via softmax over top-k log probabilities.
      - Permissive 0.50 confidence threshold (FR-020): text with confidence < 0.50 is tagged as 'und'.
      - Independent title and body classification methods.
      - Zero remote network dependencies and sub-millisecond execution.
    """

    def __init__(
        self,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        top_k: int = DEFAULT_TOP_K_CANDIDATES,
    ) -> None:
        self._confidence_threshold = confidence_threshold
        self._top_k = max(2, top_k)

    @property
    def confidence_threshold(self) -> float:
        """Configured confidence ceiling threshold."""
        return self._confidence_threshold

    # [OMA-W005-T036] Helper to sanitize input and strip markup
    @staticmethod
    def _clean_text(text: str | None) -> str:
        """Strips HTML tags and normalizes excessive whitespace."""
        if not text:
            return ""
        # Strip potential HTML tags
        cleaned = re.sub(r"<[^>]+>", " ", text)
        # Normalize whitespace
        return re.sub(r"\s+", " ", cleaned).strip()

    # [OMA-W005-T036] Classify isolated text returning ISO 639-1 code and confidence
    def classify_text(
        self,
        text: str | None,
        enforce_threshold: bool = True,
    ) -> tuple[str, float]:
        """Classifies text returning a tuple of (iso_639_1_lang, confidence).

        If confidence is strictly below confidence_threshold (< 0.50), returns ('und', confidence).
        """
        cleaned = self._clean_text(text)
        if not cleaned or not any(c.isalpha() for c in cleaned):
            return UNDETERMINED_LANGUAGE, 0.0

        try:
            ranked = py3langid.rank(cleaned)[: self._top_k]
        except Exception as exc:
            logger.warning("py3langid rank failed on text sample: %s", exc)
            return UNDETERMINED_LANGUAGE, 0.0

        if not ranked:
            return UNDETERMINED_LANGUAGE, 0.0

        top_lang, top_score = ranked[0]
        if len(ranked) == 1:
            confidence = 1.0
        else:
            # Softmax normalization over top candidates relative to top log probability
            denominator = sum(math.exp(score - top_score) for _, score in ranked)
            confidence = 1.0 / denominator if denominator > 0 else 0.0

        confidence = round(max(0.0, min(1.0, float(confidence))), 4)

        # Ignore special or non-linguistic ISO codes
        if top_lang in ("zxx", "und", "mis", "mul"):
            return UNDETERMINED_LANGUAGE, confidence

        if enforce_threshold and confidence < self._confidence_threshold:
            return UNDETERMINED_LANGUAGE, confidence

        return top_lang, confidence

    # [OMA-W005-T036] Classify opportunity title and description independently
    def classify_opportunity(
        self,
        title: str | None,
        description: str | None,
    ) -> OpportunityLanguageResult:
        """Independently classifies title and body text and derives overall opportunity language."""
        title_lang, title_conf = self.classify_text(title, enforce_threshold=True)
        body_lang, body_conf = self.classify_text(description, enforce_threshold=True)

        # Resolve overall language: prefer body text if decisive; fallback to title; or combine
        if (
            body_lang != UNDETERMINED_LANGUAGE
            and body_conf >= self._confidence_threshold
        ):
            overall_lang = body_lang
            overall_conf = body_conf
        elif (
            title_lang != UNDETERMINED_LANGUAGE
            and title_conf >= self._confidence_threshold
        ):
            overall_lang = title_lang
            overall_conf = title_conf
        else:
            # Combined classification when individual components are ambiguous or short
            combined_text = f"{title or ''}\n{description or ''}".strip()
            comb_lang, comb_conf = self.classify_text(
                combined_text, enforce_threshold=True
            )
            overall_lang = comb_lang
            overall_conf = comb_conf

        is_low_confidence = bool(overall_conf < self._confidence_threshold)

        return OpportunityLanguageResult(
            title_language=title_lang,
            title_confidence=title_conf,
            body_language=body_lang,
            body_confidence=body_conf,
            overall_language=overall_lang,
            overall_confidence=overall_conf,
            is_low_confidence=is_low_confidence,
        )
