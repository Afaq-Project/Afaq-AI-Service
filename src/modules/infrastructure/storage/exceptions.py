class StorageError(Exception):
    """Base exception for all storage infrastructure operations."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error


class StorageConfigurationError(StorageError):
    """Raised when S3 storage configuration or credentials are missing or invalid."""


class StorageConnectionError(StorageError):
    """Raised when connecting or authenticating to S3 endpoint fails."""


class StorageUploadError(StorageError):
    """Raised when uploading an object to S3 fails."""


class StorageDownloadError(StorageError):
    """Raised when downloading an object from S3 fails."""


class StorageFileNotFoundError(StorageError):
    """Raised when the requested object is not found in the S3 bucket."""
