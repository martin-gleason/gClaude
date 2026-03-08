from unittest.mock import MagicMock, patch

import pytest

from src.chat.attachments import (
    AttachmentDownloadError,
    ChatAttachmentDownloader,
    is_xlsx_attachment,
)


class TestChatAttachmentDownloader:
    @patch("src.chat.attachments.build")
    @patch("src.chat.attachments.ServiceAccountCredentials.from_service_account_file")
    def test_download_calls_media_download(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_media = mock_service.media.return_value
        mock_request = MagicMock()
        mock_media.download.return_value = mock_request
        mock_request.execute.return_value = b"file-bytes"

        downloader = ChatAttachmentDownloader(service_account_file="/path/to/key.json")
        result = downloader.download("spaces/AAA/messages/BBB/attachments/CCC")

        assert result == b"file-bytes"
        mock_media.download.assert_called_once_with(
            resourceName="spaces/AAA/messages/BBB/attachments/CCC"
        )

    @patch("src.chat.attachments.build")
    @patch("src.chat.attachments.ServiceAccountCredentials.from_service_account_file")
    def test_download_error_raises_attachment_error(self, mock_creds, mock_build):
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_media = mock_service.media.return_value
        mock_media.download.return_value.execute.side_effect = Exception("API error")

        downloader = ChatAttachmentDownloader(service_account_file="/path/to/key.json")
        with pytest.raises(AttachmentDownloadError, match="API error"):
            downloader.download("spaces/AAA/messages/BBB/attachments/CCC")

    @patch("src.chat.attachments.build")
    @patch("src.chat.attachments.google.auth.default")
    def test_default_credentials_used_when_no_file(self, mock_default, mock_build):
        mock_default.return_value = (MagicMock(), "project-id")
        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_media = mock_service.media.return_value
        mock_media.download.return_value.execute.return_value = b"data"

        downloader = ChatAttachmentDownloader()
        result = downloader.download("att/1")

        assert result == b"data"
        mock_default.assert_called_once()


class TestIsXlsxAttachment:
    def test_is_xlsx_by_mime_type(self):
        assert is_xlsx_attachment(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "report.xlsx",
        )

    def test_is_xlsx_by_extension(self):
        assert is_xlsx_attachment("application/octet-stream", "data.xlsx")

    def test_is_xlsx_case_insensitive(self):
        assert is_xlsx_attachment("application/octet-stream", "DATA.XLSX")

    def test_non_xlsx_rejected(self):
        assert not is_xlsx_attachment("application/pdf", "report.pdf")

    def test_no_extension_rejected(self):
        assert not is_xlsx_attachment("application/octet-stream", "datafile")
