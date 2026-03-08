from src.storage.interface import FileStorage, StorageError
from src.storage.memory import InMemoryStorage


class TestProtocol:
    def test_in_memory_implements_protocol(self):
        storage = InMemoryStorage()
        assert isinstance(storage, FileStorage)

    def test_protocol_requires_upload(self):
        assert hasattr(FileStorage, "upload")

    def test_protocol_requires_download(self):
        assert hasattr(FileStorage, "download")

    def test_protocol_requires_delete(self):
        assert hasattr(FileStorage, "delete")

    def test_storage_error_is_exception(self):
        assert issubclass(StorageError, Exception)
        err = StorageError("test error")
        assert str(err) == "test error"
