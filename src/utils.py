def sanitize_email(email: str) -> str:
    """Mask the local part of an email address, preserving domain for debugging."""
    if not email:
        return "<unknown>"
    if "@" not in email:
        return "<invalid>"
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked = "**"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"
