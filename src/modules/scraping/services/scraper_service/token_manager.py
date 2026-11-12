# [OMA-W006-T009] TokenManager: Cancellation tokens registry for operations and sources

import asyncio
import logging

logger = logging.getLogger(__name__)


class TokenManager:
    """Registry managing asyncio.Event cancellation tokens for operations and sources."""

    _operation_tokens: dict[str, asyncio.Event] = {}
    _source_tokens: dict[str, asyncio.Event] = {}

    @classmethod
    def get_operation_token(cls, operation_id: str) -> asyncio.Event | None:
        return cls._operation_tokens.get(operation_id)

    @classmethod
    def create_operation_token(cls, operation_id: str) -> asyncio.Event:
        token = asyncio.Event()
        cls._operation_tokens[operation_id] = token
        return token

    @classmethod
    def is_operation_cancelled(cls, operation_id: str) -> bool:
        token = cls._operation_tokens.get(operation_id)
        return token is not None and token.is_set()

    @classmethod
    def cancel_operation(cls, operation_id: str) -> None:
        token = cls._operation_tokens.get(operation_id)
        if token:
            token.set()

    @classmethod
    def clear_operation_token(cls, operation_id: str) -> None:
        cls._operation_tokens.pop(operation_id, None)

    @classmethod
    def get_source_token(cls, source_id: str) -> asyncio.Event | None:
        return cls._source_tokens.get(source_id)

    @classmethod
    def create_source_token(cls, source_id: str) -> asyncio.Event:
        token = asyncio.Event()
        cls._source_tokens[source_id] = token
        return token

    @classmethod
    def is_source_cancelled(cls, source_id: str) -> bool:
        token = cls._source_tokens.get(source_id)
        return token is not None and token.is_set()

    @classmethod
    def cancel_source(cls, source_id: str) -> None:
        token = cls._source_tokens.get(source_id)
        if token:
            token.set()

    @classmethod
    def clear_source_token(cls, source_id: str) -> None:
        cls._source_tokens.pop(source_id, None)
