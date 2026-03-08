import google.auth
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.discovery import build

XLSX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}

CHAT_SCOPES = ["https://www.googleapis.com/auth/chat.bot"]


class AttachmentDownloadError(Exception):
    pass


def is_xlsx_attachment(content_type: str, content_name: str) -> bool:
    if content_type in XLSX_MIME_TYPES:
        return True
    return content_name.lower().endswith(".xlsx")


class ChatAttachmentDownloader:
    """Downloads attachments from Google Chat using the Chat API media.download endpoint."""

    def __init__(self, service_account_file: str | None = None):
        if service_account_file:
            credentials = ServiceAccountCredentials.from_service_account_file(
                service_account_file, scopes=CHAT_SCOPES
            )
        else:
            credentials, _ = google.auth.default(scopes=CHAT_SCOPES)
        self._service = build("chat", "v1", credentials=credentials)

    def download(self, resource_name: str) -> bytes:
        try:
            request = self._service.media().download(resourceName=resource_name)
            return request.execute()
        except Exception as e:
            raise AttachmentDownloadError(
                f"Failed to download attachment '{resource_name}': {e}"
            ) from e
