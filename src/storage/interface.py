from typing import Protocol, runtime_checkable


class StorageError(Exception):
    pass


@runtime_checkable
class FileStorage(Protocol):
    def upload(self, data: bytes, filename: str, content_type: str) -> str:
        """Upload file, return public URL (signed or otherwise)."""
        ...

    def download(self, url_or_key: str) -> bytes:
        """Download file by URL or key."""
        ...

    def delete(self, key: str) -> None:
        """Delete file by key. No error if missing."""
        ...
