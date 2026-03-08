import uuid

from src.storage.interface import StorageError


class InMemoryStorage:
    """FileStorage implementation backed by a dict. For tests."""

    def __init__(self):
        self._store: dict[str, bytes] = {}

    def upload(self, data: bytes, filename: str, content_type: str) -> str:
        key = f"memory://{uuid.uuid4().hex}/{filename}"
        self._store[key] = data
        return key

    def download(self, url_or_key: str) -> bytes:
        if url_or_key not in self._store:
            raise StorageError(f"File not found: {url_or_key}")
        return self._store[url_or_key]

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
