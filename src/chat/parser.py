from dataclasses import dataclass, field


@dataclass
class ChatAttachment:
    resource_name: str
    content_name: str
    content_type: str
    source: str


@dataclass
class ChatEvent:
    event_type: str
    sender_email: str
    sender_name: str
    question: str
    raw_text: str
    space_name: str
    space_type: str
    thread_name: str
    message_name: str
    attachments: list[ChatAttachment] = field(default_factory=list)


def parse_chat_event(payload: dict) -> ChatEvent:
    event_type = payload.get("type", "")

    user = payload.get("user", {})
    sender_email = user.get("email", "")
    sender_name = user.get("displayName", "")

    message = payload.get("message", {})
    if not sender_email:
        sender = message.get("sender", {})
        sender_email = sender.get("email", "")
        if not sender_name:
            sender_name = sender.get("displayName", "")

    space = payload.get("space", {})
    space_type = space.get("type", "")

    argument_text = message.get("argumentText", "")
    text = message.get("text", "")

    if space_type == "DM":
        question = text.strip()
    else:
        question = argument_text.strip()

    attachments = []
    for att in message.get("attachment", []):
        attachments.append(
            ChatAttachment(
                resource_name=att.get("name", ""),
                content_name=att.get("contentName", ""),
                content_type=att.get("contentType", ""),
                source=att.get("source", ""),
            )
        )

    return ChatEvent(
        event_type=event_type,
        sender_email=sender_email,
        sender_name=sender_name,
        question=question,
        raw_text=text,
        space_name=space.get("name", ""),
        space_type=space_type,
        thread_name=message.get("thread", {}).get("name", ""),
        message_name=message.get("name", ""),
        attachments=attachments,
    )
