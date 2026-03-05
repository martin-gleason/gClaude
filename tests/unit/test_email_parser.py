import base64

from src.email.parser import (
    EmailAttachment,
    ParsedEmail,
    decode_attachments,
    parse_email_payload,
)

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class TestParseEmailPayload:
    def test_parses_basic_fields(self):
        payload = {
            "sender": "shannon@gmail.com",
            "subject": "VLOOKUP help",
            "body": "How do I use VLOOKUP?",
            "message_id": "msg-123",
            "attachments": [],
        }
        result = parse_email_payload(payload)
        assert result.sender == "shannon@gmail.com"
        assert result.subject == "VLOOKUP help"
        assert result.body == "How do I use VLOOKUP?"
        assert result.message_id == "msg-123"
        assert result.attachments == []

    def test_missing_fields_default_to_empty(self):
        result = parse_email_payload({})
        assert result.sender == ""
        assert result.subject == ""
        assert result.body == ""
        assert result.message_id == ""
        assert result.attachments == []

    def test_parses_xlsx_attachment(self):
        xlsx_data = base64.b64encode(b"fake-xlsx").decode()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "test body",
            "message_id": "msg-1",
            "attachments": [
                {
                    "filename": "data.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": xlsx_data,
                }
            ],
        }
        result = parse_email_payload(payload)
        assert len(result.attachments) == 1
        assert result.attachments[0].filename == "data.xlsx"
        assert result.attachments[0].data == b"fake-xlsx"

    def test_filters_non_xlsx_attachments(self):
        pdf_data = base64.b64encode(b"pdf-content").decode()
        xlsx_data = base64.b64encode(b"xlsx-content").decode()
        payload = {
            "sender": "user@example.com",
            "subject": "test",
            "body": "body",
            "message_id": "msg-1",
            "attachments": [
                {"filename": "doc.pdf", "mime_type": "application/pdf", "data": pdf_data},
                {
                    "filename": "data.xlsx",
                    "mime_type": XLSX_MIME,
                    "data": xlsx_data,
                },
            ],
        }
        result = parse_email_payload(payload)
        assert len(result.attachments) == 1
        assert result.attachments[0].filename == "data.xlsx"


class TestDecodeAttachments:
    def test_decodes_base64_xlsx(self):
        raw = [
            {
                "filename": "test.xlsx",
                "mime_type": XLSX_MIME,
                "data": base64.b64encode(b"hello").decode(),
            }
        ]
        result = decode_attachments(raw)
        assert len(result) == 1
        assert result[0].data == b"hello"

    def test_filters_non_xlsx_by_mime(self):
        raw = [
            {
                "filename": "image.png",
                "mime_type": "image/png",
                "data": base64.b64encode(b"img").decode(),
            }
        ]
        result = decode_attachments(raw)
        assert result == []

    def test_accepts_xlsx_by_extension(self):
        raw = [
            {
                "filename": "report.xlsx",
                "mime_type": "application/octet-stream",
                "data": base64.b64encode(b"data").decode(),
            }
        ]
        result = decode_attachments(raw)
        assert len(result) == 1

    def test_accepts_old_excel_mime(self):
        raw = [
            {
                "filename": "old.xls",
                "mime_type": "application/vnd.ms-excel",
                "data": base64.b64encode(b"old-data").decode(),
            }
        ]
        result = decode_attachments(raw)
        assert len(result) == 1

    def test_skips_invalid_base64(self):
        raw = [
            {
                "filename": "bad.xlsx",
                "mime_type": XLSX_MIME,
                "data": "not-valid-base64!!!",
            }
        ]
        result = decode_attachments(raw)
        assert result == []

    def test_empty_list(self):
        assert decode_attachments([]) == []


class TestParsedEmailQuestion:
    def test_question_returns_body(self):
        email = ParsedEmail(
            sender="x", subject="subj", body="my question", message_id="1"
        )
        assert email.question == "my question"

    def test_question_falls_back_to_subject(self):
        email = ParsedEmail(sender="x", subject="my subject", body="", message_id="1")
        assert email.question == "my subject"

    def test_question_strips_whitespace(self):
        email = ParsedEmail(
            sender="x", subject="sub", body="  question  ", message_id="1"
        )
        assert email.question == "question"

    def test_question_empty_when_both_empty(self):
        email = ParsedEmail(sender="x", subject="", body="", message_id="1")
        assert email.question == ""

    def test_question_body_whitespace_falls_back(self):
        email = ParsedEmail(
            sender="x", subject="fallback", body="   ", message_id="1"
        )
        assert email.question == "fallback"


class TestEmailAttachment:
    def test_dataclass_fields(self):
        att = EmailAttachment(filename="test.xlsx", mime_type="application/test", data=b"data")
        assert att.filename == "test.xlsx"
        assert att.mime_type == "application/test"
        assert att.data == b"data"
