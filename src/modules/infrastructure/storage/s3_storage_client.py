import asyncio
import io
import logging
from typing import Any, BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError

from src.modules.core.config.settings import Settings, get_settings

from .exceptions import (
    StorageConfigurationError,
    StorageConnectionError,
    StorageDownloadError,
    StorageError,
    StorageFileNotFoundError,
    StorageUploadError,
)

logger = logging.getLogger(__name__)


class S3StorageClient:
    """Asynchronous wrapper for S3-compatible object storage (Filebase / AWS S3).

    Wraps synchronous boto3 operations in asyncio.to_thread to maintain non-blocking
    asynchronous execution across FastAPI workers.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._endpoint_url = self._settings.s3_endpoint
        self._bucket_name = self._settings.s3_bucket
        self._access_key = self._settings.s3_access_key
        self._secret_key = self._settings.s3_secret_key
        self._region = self._settings.s3_region

        if not self._access_key or not self._secret_key:
            raise StorageConfigurationError(
                "S3 storage credentials are not configured. Check FILEBASE_ACCESS_KEY / AWS_ACCESS_KEY_ID in .env."
            )
        if not self._bucket_name:
            raise StorageConfigurationError(
                "S3 bucket name is not configured. Check FILEBASE_BUCKET in .env."
            )

        self._boto_config = Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=10,
            read_timeout=30,
        )

        self._client = boto3.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            config=self._boto_config,
        )

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

    async def check_connection(self) -> bool:
        """Verifies connection and access to the target S3 bucket."""

        def _check() -> bool:
            try:
                self._client.head_bucket(Bucket=self._bucket_name)
                return True
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                logger.error(
                    f"S3 connection check failed with ClientError: {error_code} - {e}"
                )
                raise StorageConnectionError(
                    f"S3 bucket '{self._bucket_name}' access failed: {error_code}", e
                ) from e
            except EndpointConnectionError as e:
                logger.error(
                    f"Unable to connect to S3 endpoint '{self._endpoint_url}': {e}"
                )
                raise StorageConnectionError(
                    f"S3 endpoint connection failed: {self._endpoint_url}", e
                ) from e
            except Exception as e:
                logger.error(f"Unexpected error during S3 connection check: {e}")
                raise StorageConnectionError(
                    f"Unexpected S3 connection failure: {e}", e
                ) from e

        return await asyncio.to_thread(_check)

    async def upload_file(
        self,
        file_data: bytes | BinaryIO,
        object_key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        """Uploads binary file data or stream to the configured S3 bucket.

        Args:
            file_data: File payload as bytes or file-like stream.
            object_key: Target object key path in the bucket.
            content_type: MIME type of the uploaded file.
            metadata: Optional user metadata key-value dictionary.

        Returns:
            The uploaded object key on success.
        """

        def _upload() -> str:
            try:
                extra_args: dict[str, Any] = {"ContentType": content_type}
                if metadata:
                    extra_args["Metadata"] = metadata

                if isinstance(file_data, bytes):
                    body = io.BytesIO(file_data)
                else:
                    body = file_data

                self._client.upload_fileobj(
                    Fileobj=body,
                    Bucket=self._bucket_name,
                    Key=object_key,
                    ExtraArgs=extra_args,
                )
                logger.info(
                    f"Successfully uploaded object '{object_key}' to S3 bucket '{self._bucket_name}'."
                )
                return object_key
            except ClientError as e:
                logger.error(f"Failed to upload object '{object_key}' to S3: {e}")
                raise StorageUploadError(
                    f"Failed to upload '{object_key}' to S3", e
                ) from e
            except Exception as e:
                logger.error(f"Unexpected error uploading '{object_key}' to S3: {e}")
                raise StorageUploadError(
                    f"Unexpected upload failure for '{object_key}': {e}", e
                ) from e

        return await asyncio.to_thread(_upload)

    async def download_file(self, object_key: str) -> bytes:
        """Downloads an object from the S3 bucket into memory as bytes."""

        def _download() -> bytes:
            try:
                buffer = io.BytesIO()
                self._client.download_fileobj(
                    Bucket=self._bucket_name,
                    Key=object_key,
                    Fileobj=buffer,
                )
                buffer.seek(0)
                return buffer.read()
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                if error_code in ("404", "NoSuchKey"):
                    raise StorageFileNotFoundError(
                        f"Object '{object_key}' not found in S3 bucket.", e
                    ) from e
                logger.error(f"Failed to download object '{object_key}' from S3: {e}")
                raise StorageDownloadError(
                    f"Failed to download '{object_key}' from S3", e
                ) from e
            except Exception as e:
                logger.error(
                    f"Unexpected error downloading '{object_key}' from S3: {e}"
                )
                raise StorageDownloadError(
                    f"Unexpected download failure for '{object_key}': {e}", e
                ) from e

        return await asyncio.to_thread(_download)

    async def check_file_exists(self, object_key: str) -> bool:
        """Checks whether an object exists in the S3 bucket."""

        def _exists() -> bool:
            try:
                self._client.head_object(Bucket=self._bucket_name, Key=object_key)
                return True
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "Unknown")
                if error_code in ("404", "NoSuchKey"):
                    return False
                logger.error(f"Error checking object existence '{object_key}': {e}")
                return False
            except Exception:
                return False

        return await asyncio.to_thread(_exists)

    async def delete_file(self, object_key: str) -> bool:
        """Deletes an object from the S3 bucket."""

        def _delete() -> bool:
            try:
                self._client.delete_object(Bucket=self._bucket_name, Key=object_key)
                logger.info(
                    f"Deleted object '{object_key}' from S3 bucket '{self._bucket_name}'."
                )
                return True
            except ClientError as e:
                logger.error(f"Failed to delete object '{object_key}' from S3: {e}")
                return False

        return await asyncio.to_thread(_delete)

    async def generate_presigned_url(
        self, object_key: str, expires_in: int = 3600
    ) -> str:
        """Generates a presigned GET URL for an object."""

        def _presign() -> str:
            try:
                url = self._client.generate_presigned_url(
                    ClientMethod="get_object",
                    Params={"Bucket": self._bucket_name, "Key": object_key},
                    ExpiresIn=expires_in,
                )
                return str(url)
            except ClientError as e:
                logger.error(
                    f"Failed to generate presigned URL for '{object_key}': {e}"
                )
                raise StorageError(
                    f"Failed to generate presigned URL for '{object_key}'", e
                ) from e

        return await asyncio.to_thread(_presign)
