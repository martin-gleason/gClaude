from unittest.mock import patch

import pytest

from src.chat.auth import GoogleTokenError, verify_google_chat_token


class TestVerifyGoogleChatToken:
    @patch("src.chat.auth.google_requests.Request")
    @patch("src.chat.auth.id_token.verify_token")
    def test_valid_token(self, mock_verify, mock_request):
        mock_verify.return_value = {
            "iss": "chat@system.gserviceaccount.com",
            "aud": "123456",
        }
        claims = verify_google_chat_token("valid-token", "123456")
        assert claims["iss"] == "chat@system.gserviceaccount.com"
        mock_verify.assert_called_once()

    @patch("src.chat.auth.google_requests.Request")
    @patch("src.chat.auth.id_token.verify_token")
    def test_invalid_token_raises(self, mock_verify, mock_request):
        mock_verify.side_effect = ValueError("Invalid token")
        with pytest.raises(GoogleTokenError, match="Token verification failed"):
            verify_google_chat_token("bad-token", "123456")

    @patch("src.chat.auth.google_requests.Request")
    @patch("src.chat.auth.id_token.verify_token")
    def test_wrong_issuer_raises(self, mock_verify, mock_request):
        mock_verify.return_value = {
            "iss": "wrong@issuer.com",
            "aud": "123456",
        }
        with pytest.raises(GoogleTokenError, match="Invalid issuer"):
            verify_google_chat_token("token", "123456")
