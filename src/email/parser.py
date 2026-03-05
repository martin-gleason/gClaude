import base64
from dataclasses import dataclass, field


@dataclass
class EmailAttachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass
class ParsedEmail:
    sender: str
    subject: str
    body: str
    message_id: str
    attachments: list[EmailAttachment] = field(default_factory=list)

    @property
    def question(self) -> str:
        if self.body.strip():
            return self.body.strip()
        if self.subject.strip():
            return self.subject.strip()
        return ""


XLSX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}


def parse_email_payload(payload: dict) -> ParsedEmail:
    sender = payload.get("sender", "")
    subject = payload.get("subject", "")
    body = payload.get("body", "")
    message_id = payload.get("message_id", "")
    raw_attachments = payload.get("attachments", [])

    attachments = decode_attachments(raw_attachments)

    return ParsedEmail(
        sender=sender,
        subject=subject,
        body=body,
        message_id=message_id,
        attachments=attachments,
    )


def decode_attachments(raw_attachments: list[dict]) -> list[EmailAttachment]:
    attachments = []
    for att in raw_attachments:
        filename = att.get("filename", "")
        mime_type = att.get("mime_type", "")

        if not _is_xlsx(filename, mime_type):
            continue

        data_b64 = att.get("data", "")
        try:
            data = base64.b64decode(data_b64)
        except Exception:
            continue

        attachments.append(
            EmailAttachment(filename=filename, mime_type=mime_type, data=data)
        )
    return attachments


def _is_xlsx(filename: str, mime_type: str) -> bool:
    if mime_type in XLSX_MIME_TYPES:
        return True
    return filename.lower().endswith(".xlsx")
