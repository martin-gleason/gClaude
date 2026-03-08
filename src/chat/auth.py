from google.auth.transport import requests as google_requests
from google.oauth2 import id_token


class GoogleTokenError(Exception):
    pass


def verify_google_chat_token(token: str, project_number: str) -> dict:
    """Verify a Google Chat bearer token.

    Validates that the token was issued by chat@system.gserviceaccount.com
    for the given project number.
    """
    try:
        claims = id_token.verify_token(
            token,
            request=google_requests.Request(),
            audience=project_number,
        )
    except Exception as e:
        raise GoogleTokenError(f"Token verification failed: {e}") from e

    expected_issuer = "chat@system.gserviceaccount.com"
    issuer = claims.get("iss", "")
    if issuer != expected_issuer:
        raise GoogleTokenError(
            f"Invalid issuer: expected {expected_issuer}, got {issuer}"
        )

    return claims
