import datetime
import uuid

from google.cloud import storage

from src.storage.interface import StorageError


class GCSStorage:
    def __init__(
        self,
        bucket_name: str,
        signed_url_expiration_hours: int = 24,
        prefix: str = "generated/",
        service_account_file: str | None = None,
    ):
        if service_account_file:
            self._client = storage.Client.from_service_account_json(service_account_file)
        else:
            self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._expiration_hours = signed_url_expiration_hours
        self._prefix = prefix

    def upload(self, data: bytes, filename: str, content_type: str) -> str:
        blob_name = f"{self._prefix}{uuid.uuid4().hex}/{filename}"
        blob = self._bucket.blob(blob_name)
        try:
            blob.upload_from_string(data, content_type=content_type)
            url = blob.generate_signed_url(
                expiration=datetime.timedelta(hours=self._expiration_hours),
                method="GET",
            )
            return url
        except Exception as e:
            raise StorageError(f"Upload failed: {e}") from e

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(key)
        try:
            blob.delete()
        except Exception:
            pass

    def download(self, url_or_key: str) -> bytes:
        blob = self._bucket.blob(url_or_key)
        try:
            return blob.download_as_bytes()
        except Exception as e:
            raise StorageError(f"Download failed: {e}") from e
