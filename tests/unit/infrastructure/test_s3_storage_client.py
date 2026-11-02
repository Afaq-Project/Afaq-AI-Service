from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from src.modules.core.config.settings import Settings
from src.modules.infrastructure.storage import (
    S3StorageClient,
    StorageConfigurationError,
    StorageConnectionError,
    StorageDownloadError,
    StorageFileNotFoundError,
    StorageUploadError,
)


@pytest.fixture
def mock_settings() -> Settings:
    return Settings(
        filebase_endpoint="https://s3.filebase.io",
        filebase_region="us-east-1",
        filebase_bucket="test-bucket",
        filebase_access_key="test-access-key",
        filebase_secret_key="test-secret-key",
    )


def test_s3_client_missing_credentials():
    settings = Settings(
        filebase_access_key="",
        filebase_secret_key="",
        aws_access_key_id="",
        aws_secret_access_key="",
    )
    with pytest.raises(
        StorageConfigurationError, match="credentials are not configured"
    ):
        S3StorageClient(settings=settings)


def test_s3_client_missing_bucket():
    settings = Settings(
        filebase_access_key="valid-key",
        filebase_secret_key="valid-secret",
        filebase_bucket="",
        s3_attachments_bucket="",
    )
    with pytest.raises(
        StorageConfigurationError, match="bucket name is not configured"
    ):
        S3StorageClient(settings=settings)


@pytest.mark.asyncio
async def test_s3_check_connection_success(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.head_bucket.return_value = {}

        client = S3StorageClient(settings=mock_settings)
        result = await client.check_connection()

        assert result is True
        mock_s3.head_bucket.assert_called_once_with(Bucket="test-bucket")


@pytest.mark.asyncio
async def test_s3_check_connection_failure(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.head_bucket.side_effect = ClientError(
            {"Error": {"Code": "403", "Message": "Forbidden"}}, "head_bucket"
        )

        client = S3StorageClient(settings=mock_settings)
        with pytest.raises(StorageConnectionError, match="access failed: 403"):
            await client.check_connection()


@pytest.mark.asyncio
async def test_s3_upload_file_bytes(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        client = S3StorageClient(settings=mock_settings)
        key = await client.upload_file(
            file_data=b"hello world",
            object_key="docs/test.txt",
            content_type="text/plain",
            metadata={"source": "unit-test"},
        )

        assert key == "docs/test.txt"
        assert mock_s3.upload_fileobj.call_count == 1
        args, kwargs = mock_s3.upload_fileobj.call_args
        assert kwargs["Bucket"] == "test-bucket"
        assert kwargs["Key"] == "docs/test.txt"
        assert kwargs["ExtraArgs"]["ContentType"] == "text/plain"
        assert kwargs["ExtraArgs"]["Metadata"]["source"] == "unit-test"


@pytest.mark.asyncio
async def test_s3_upload_file_error(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.upload_fileobj.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "InternalError"}}, "upload_fileobj"
        )

        client = S3StorageClient(settings=mock_settings)
        with pytest.raises(StorageUploadError, match="Failed to upload"):
            await client.upload_file(b"data", "docs/test.txt")


@pytest.mark.asyncio
async def test_s3_download_file_success(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        def mock_download(Bucket, Key, Fileobj):
            Fileobj.write(b"downloaded content")

        mock_s3.download_fileobj.side_effect = mock_download

        client = S3StorageClient(settings=mock_settings)
        content = await client.download_file("docs/test.txt")

        assert content == b"downloaded content"
        mock_s3.download_fileobj.assert_called_once()


@pytest.mark.asyncio
async def test_s3_download_file_not_found(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.download_fileobj.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "download_fileobj"
        )

        client = S3StorageClient(settings=mock_settings)
        with pytest.raises(StorageFileNotFoundError, match="not found in S3 bucket"):
            await client.download_file("missing.txt")


@pytest.mark.asyncio
async def test_s3_download_file_general_error(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.download_fileobj.side_effect = ClientError(
            {"Error": {"Code": "500", "Message": "Internal Server Error"}},
            "download_fileobj",
        )

        client = S3StorageClient(settings=mock_settings)
        with pytest.raises(StorageDownloadError, match="Failed to download"):
            await client.download_file("failing.txt")


@pytest.mark.asyncio
async def test_s3_check_file_exists(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        client = S3StorageClient(settings=mock_settings)

        # Case 1: Exists
        mock_s3.head_object.return_value = {"ContentLength": 100}
        assert await client.check_file_exists("existing.txt") is True

        # Case 2: Not found
        mock_s3.head_object.side_effect = ClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "head_object"
        )
        assert await client.check_file_exists("missing.txt") is False


@pytest.mark.asyncio
async def test_s3_delete_file(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3

        client = S3StorageClient(settings=mock_settings)
        assert await client.delete_file("to_delete.txt") is True
        mock_s3.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="to_delete.txt"
        )


@pytest.mark.asyncio
async def test_s3_generate_presigned_url(mock_settings: Settings):
    with patch("boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.generate_presigned_url.return_value = (
            "https://s3.filebase.io/presigned-url"
        )

        client = S3StorageClient(settings=mock_settings)
        url = await client.generate_presigned_url("doc.pdf", expires_in=1800)

        assert url == "https://s3.filebase.io/presigned-url"
        mock_s3.generate_presigned_url.assert_called_once_with(
            ClientMethod="get_object",
            Params={"Bucket": "test-bucket", "Key": "doc.pdf"},
            ExpiresIn=1800,
        )
