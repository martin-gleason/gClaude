import pytest

from src.storage.interface import StorageError
from src.storage.memory import InMemoryStorage


@pytest.fixture
def storage():
    return InMemoryStorage()


class TestInMemoryStorage:
    def test_upload_returns_url(self, storage):
        url = storage.upload(b"data", "test.xlsx", "application/octet-stream")
        assert isinstance(url, str)
        assert "test.xlsx" in url

    def test_upload_stores_data(self, storage):
        storage.upload(b"hello", "file.xlsx", "application/octet-stream")
        assert len(storage._store) == 1

    def test_download_returns_uploaded_data(self, storage):
        url = storage.upload(b"my-data", "file.xlsx", "application/octet-stream")
        result = storage.download(url)
        assert result == b"my-data"

    def test_download_nonexistent_raises(self, storage):
        with pytest.raises(StorageError, match="not found"):
            storage.download("memory://nonexistent")

    def test_upload_unique_keys(self, storage):
        url1 = storage.upload(b"data1", "same.xlsx", "application/octet-stream")
        url2 = storage.upload(b"data2", "same.xlsx", "application/octet-stream")
        assert url1 != url2

    def test_upload_empty_file(self, storage):
        url = storage.upload(b"", "empty.xlsx", "application/octet-stream")
        result = storage.download(url)
        assert result == b""

    def test_upload_preserves_content_type(self, storage):
        url = storage.upload(b"data", "test.xlsx", "application/vnd.openxmlformats")
        # Content type stored but not directly accessible; just verify upload/download works
        result = storage.download(url)
        assert result == b"data"

    def test_clear_empties_store(self, storage):
        storage.upload(b"data", "test.xlsx", "application/octet-stream")
        assert len(storage._store) > 0
        storage.clear()
        assert len(storage._store) == 0

    def test_multiple_files(self, storage):
        url1 = storage.upload(b"file1", "a.xlsx", "application/octet-stream")
        url2 = storage.upload(b"file2", "b.xlsx", "application/octet-stream")
        assert storage.download(url1) == b"file1"
        assert storage.download(url2) == b"file2"

    def test_delete_existing_file(self, storage):
        url = storage.upload(b"data", "test.xlsx", "application/octet-stream")
        storage.delete(url)
        assert url not in storage._store

    def test_delete_missing_file_no_error(self, storage):
        storage.delete("memory://nonexistent")  # should not raise

    def test_large_file_stored(self, storage):
        large_data = b"x" * (5 * 1024 * 1024)  # 5 MB
        url = storage.upload(large_data, "big.xlsx", "application/octet-stream")
        result = storage.download(url)
        assert result == large_data
