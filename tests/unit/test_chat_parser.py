from src.chat.parser import parse_chat_event

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


class TestParseChatEvent:
    def test_parses_message_event(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com", "displayName": "Test User"},
            "message": {
                "name": "spaces/AAA/messages/BBB",
                "text": "@ExcelBot How do I use VLOOKUP?",
                "argumentText": "How do I use VLOOKUP?",
                "sender": {"email": "user@example.com", "displayName": "Test User"},
                "thread": {"name": "spaces/AAA/threads/CCC"},
            },
            "space": {"name": "spaces/AAA", "type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert event.event_type == "MESSAGE"
        assert event.sender_email == "user@example.com"
        assert event.sender_name == "Test User"
        assert event.question == "How do I use VLOOKUP?"
        assert event.raw_text == "@ExcelBot How do I use VLOOKUP?"
        assert event.space_name == "spaces/AAA"
        assert event.space_type == "ROOM"
        assert event.thread_name == "spaces/AAA/threads/CCC"
        assert event.message_name == "spaces/AAA/messages/BBB"

    def test_parses_added_to_space_event(self):
        payload = {
            "type": "ADDED_TO_SPACE",
            "user": {"email": "admin@example.com", "displayName": "Admin"},
            "space": {"name": "spaces/XYZ", "type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert event.event_type == "ADDED_TO_SPACE"
        assert event.sender_email == "admin@example.com"
        assert event.question == ""

    def test_dm_uses_text_not_argument_text(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com", "displayName": "User"},
            "message": {
                "text": "What is a pivot table?",
                "argumentText": "",
            },
            "space": {"name": "spaces/DM1", "type": "DM"},
        }
        event = parse_chat_event(payload)
        assert event.question == "What is a pivot table?"
        assert event.space_type == "DM"

    def test_empty_payload_returns_defaults(self):
        event = parse_chat_event({})
        assert event.event_type == ""
        assert event.sender_email == ""
        assert event.sender_name == ""
        assert event.question == ""
        assert event.raw_text == ""
        assert event.space_name == ""
        assert event.space_type == ""
        assert event.thread_name == ""
        assert event.message_name == ""

    def test_argument_text_stripped(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com"},
            "message": {
                "text": "@ExcelBot  How do I use VLOOKUP?  ",
                "argumentText": "  How do I use VLOOKUP?  ",
            },
            "space": {"type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert event.question == "How do I use VLOOKUP?"


class TestParseChatEventAttachments:
    def test_message_with_attachment(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com"},
            "message": {
                "text": "Analyze this",
                "argumentText": "Analyze this",
                "attachment": [
                    {
                        "name": "spaces/AAA/messages/BBB/attachments/CCC",
                        "contentName": "report.xlsx",
                        "contentType": XLSX_MIME,
                        "source": "UPLOADED_CONTENT",
                    }
                ],
            },
            "space": {"type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert len(event.attachments) == 1
        att = event.attachments[0]
        assert att.resource_name == "spaces/AAA/messages/BBB/attachments/CCC"
        assert att.content_name == "report.xlsx"
        assert att.content_type == XLSX_MIME
        assert att.source == "UPLOADED_CONTENT"

    def test_message_without_attachment(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com"},
            "message": {"text": "Hello", "argumentText": "Hello"},
            "space": {"type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert event.attachments == []

    def test_multiple_attachments(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com"},
            "message": {
                "text": "Analyze",
                "argumentText": "Analyze",
                "attachment": [
                    {
                        "name": "att/1",
                        "contentName": "file1.xlsx",
                        "contentType": XLSX_MIME,
                        "source": "UPLOADED_CONTENT",
                    },
                    {
                        "name": "att/2",
                        "contentName": "file2.xlsx",
                        "contentType": XLSX_MIME,
                        "source": "UPLOADED_CONTENT",
                    },
                ],
            },
            "space": {"type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert len(event.attachments) == 2

    def test_drive_attachment_parsed(self):
        payload = {
            "type": "MESSAGE",
            "user": {"email": "user@example.com"},
            "message": {
                "text": "Check this",
                "argumentText": "Check this",
                "attachment": [
                    {
                        "name": "att/drive",
                        "contentName": "shared.xlsx",
                        "contentType": XLSX_MIME,
                        "source": "DRIVE_FILE",
                    }
                ],
            },
            "space": {"type": "ROOM"},
        }
        event = parse_chat_event(payload)
        assert len(event.attachments) == 1
        assert event.attachments[0].source == "DRIVE_FILE"

    def test_empty_payload_still_has_empty_attachments(self):
        event = parse_chat_event({})
        assert event.attachments == []
