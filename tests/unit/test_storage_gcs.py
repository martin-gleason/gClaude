import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.storage.gcs import GCSStorage
from src.storage.interface import StorageError


@pytest.fixture
def mock_gcs_client():
    with patch("src.storage.gcs.storage.Client") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_bucket = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_blob = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.generate_signed_url.return_value = "https://storage.googleapis.com/signed-url"
        mock_blob.download_as_bytes.return_value = b"file-content"
        yield {
            "client_cls": mock_cls,
            "client": mock_client,
            "bucket": mock_bucket,
            "blob": mock_blob,
        }


@pytest.fixture
def gcs_storage(mock_gcs_client):
    return GCSStorage(bucket_name="test-bucket")


class TestGCSUpload:
    def test_upload_creates_blob_and_returns_signed_url(self, gcs_storage, mock_gcs_client):
        url = gcs_storage.upload(b"data", "report.xlsx", "application/octet-stream")
        mock_gcs_client["blob"].upload_from_string.assert_called_once_with(
            b"data", content_type="application/octet-stream"
        )
        mock_gcs_client["blob"].generate_signed_url.assert_called_once()
        assert url == "https://storage.googleapis.com/signed-url"

    def test_upload_uses_prefix(self, gcs_storage, mock_gcs_client):
        gcs_storage.upload(b"data", "report.xlsx", "application/octet-stream")
        blob_name = mock_gcs_client["bucket"].blob.call_args[0][0]
        assert blob_name.startswith("generated/")

    def test_upload_unique_blob_names(self, gcs_storage, mock_gcs_client):
        gcs_storage.upload(b"data1", "same.xlsx", "application/octet-stream")
        name1 = mock_gcs_client["bucket"].blob.call_args_list[0][0][0]
        gcs_storage.upload(b"data2", "same.xlsx", "application/octet-stream")
        name2 = mock_gcs_client["bucket"].blob.call_args_list[1][0][0]
        assert name1 != name2

    def test_upload_error_raises_storage_error(self, gcs_storage, mock_gcs_client):
        mock_gcs_client["blob"].upload_from_string.side_effect = Exception("GCS down")
        with pytest.raises(StorageError, match="Upload failed"):
            gcs_storage.upload(b"data", "test.xlsx", "application/octet-stream")


class TestGCSDownload:
    def test_download_reads_blob(self, gcs_storage, mock_gcs_client):
        result = gcs_storage.download("generated/abc/report.xlsx")
        assert result == b"file-content"
        mock_gcs_client["bucket"].blob.assert_called_with("generated/abc/report.xlsx")

    def test_download_error_raises_storage_error(self, gcs_storage, mock_gcs_client):
        mock_gcs_client["blob"].download_as_bytes.side_effect = Exception("Not found")
        with pytest.raises(StorageError, match="Download failed"):
            gcs_storage.download("generated/abc/report.xlsx")


class TestGCSDelete:
    def test_delete_calls_blob_delete(self, gcs_storage, mock_gcs_client):
        gcs_storage.delete("generated/abc/report.xlsx")
        mock_gcs_client["bucket"].blob.assert_called_with("generated/abc/report.xlsx")
        mock_gcs_client["blob"].delete.assert_called_once()

    def test_delete_missing_blob_no_error(self, gcs_storage, mock_gcs_client):
        from google.api_core.exceptions import NotFound
        mock_gcs_client["blob"].delete.side_effect = NotFound("Not found")
        gcs_storage.delete("generated/missing/file.xlsx")  # should not raise


class TestGCSConfig:
    def test_signed_url_expiration_configurable(self, mock_gcs_client):
        gcs = GCSStorage(bucket_name="test-bucket", signed_url_expiration_hours=48)
        gcs.upload(b"data", "test.xlsx", "application/octet-stream")
        call_kwargs = mock_gcs_client["blob"].generate_signed_url.call_args.kwargs
        assert call_kwargs["expiration"] == datetime.timedelta(hours=48)

    def test_default_credentials_when_no_service_account(self, mock_gcs_client):
        GCSStorage(bucket_name="test-bucket")
        mock_gcs_client["client_cls"].assert_called_once_with()
